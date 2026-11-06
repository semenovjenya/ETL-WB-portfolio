"""Скрипт для получения остатков на складах WB из API supplier/stocks."""
import json
import logging
import os
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo
import requests
from config import Config
from database import StocksDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
CURSOR_OVERLAP_SECONDS = 2


def resolve_snapshot_hour(snapshot_hour: Optional[datetime]) -> datetime:
    if snapshot_hour is None:
        snapshot_hour = datetime.now(MOSCOW_TZ)
    elif snapshot_hour.tzinfo is None:
        snapshot_hour = snapshot_hour.replace(tzinfo=MOSCOW_TZ)
    return snapshot_hour.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


def format_wb_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def compute_overlap_date_from(
    cursor_dt: datetime,
    minimum_dt: datetime,
    overlap_seconds: int = CURSOR_OVERLAP_SECONDS,
) -> datetime:
    return max(cursor_dt - timedelta(seconds=overlap_seconds), minimum_dt)


class StocksFetcher:
    """Выгрузка остатков товаров на складах WB (API supplier/stocks)."""

    def __init__(self):
        Config.validate()
        self.db = StocksDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def load_progress(self) -> Optional[str]:
        """Возвращает dateFrom для следующего запроса (из БД или progress.json)."""
        try:
            self.db.connect()
            dt = self.db.get_last_change_date_from()
            if dt:
                # API принимает дату в формате RFC3339
                s = dt.strftime("%Y-%m-%dT%H:%M:%S")
                logger.info(f"Прогресс загружен из БД: dateFrom={s}")
                return s
        except Exception as e:
            logger.warning(f"Не удалось загрузить прогресс из БД: {e}")
        finally:
            if self.db.conn:
                self.db.close()

        if os.path.exists(Config.PROGRESS_FILE):
            try:
                with open(Config.PROGRESS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                date_from = data.get("last_change_date_from")
                if date_from:
                    logger.info(f"Прогресс загружен из файла: {date_from}")
                    return date_from
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Ошибка чтения progress.json: {e}")

        logger.info("Прогресс не найден, используется начальная дата")
        return None

    def save_progress(self, last_change_date_from: str) -> None:
        """Сохранить прогресс (dateFrom для следующей страницы) в БД и файл."""
        try:
            if not self.db.conn:
                self.db.connect()
            dt = self.db.parse_datetime(last_change_date_from)
            if dt:
                self.db.save_progress(dt)
        except Exception as e:
            logger.error(f"Ошибка сохранения прогресса в БД: {e}")
            raise

        try:
            with open(Config.PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "last_change_date_from": last_change_date_from,
                        "updated_at": datetime.now().isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except IOError as e:
            logger.error(f"Ошибка сохранения progress.json: {e}")

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        return {"Authorization": token, "Content-Type": "application/json"}

    def fetch_page(self, date_from: str, retry_count: int = None) -> Optional[List[Dict[str, Any]]]:
        """Один запрос к API: остатки начиная с dateFrom. До 60000 строк."""
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = Config.WB_API_BASE_URL
        headers = self._get_headers()
        params = {"dateFrom": date_from}

        for attempt in range(retry_count):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=120)
                if resp.status_code == 429:
                    wait = (attempt + 1) * Config.RETRY_DELAY * 2
                    logger.warning(f"429 Too Many Requests, ожидание {wait} сек...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    logger.warning(f"Ожидался массив, получен: {type(data)}")
                    return []
                logger.info(f"Получено строк остатков: {len(data)} (dateFrom={date_from})")
                return data
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{retry_count} не удалась: {e}")
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки исчерпаны: {e}")
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def save_to_json(
        self,
        items: List[Dict[str, Any]],
        date_from: str,
        page: int,
        snapshot_hour: datetime,
    ) -> str:
        """Сохранить одну страницу в JSON."""
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_date = date_from.replace(":", "-").replace(" ", "_")[:19]
        filename = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"stocks_{safe_date}_h{snapshot_hour.strftime('%Y-%m-%d_%H')}_p{page}_{ts}.json",
        )
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "date_from": date_from,
                    "page": page,
                    "total_items": len(items),
                    "timestamp": ts,
                    "data": items,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info(f"Сохранён JSON: {filename} ({len(items)} записей)")
        return filename

    def run(self, full_snapshot: bool = False, snapshot_hour: Optional[datetime] = None) -> None:
        """
        Полная выгрузка остатков с пагинацией.
        full_snapshot: если True, начать с STOCKS_DATE_FROM_DEFAULT (игнорировать прогресс).
        """
        logger.info("Начало выгрузки остатков supplier/stocks")

        try:
            self.db.connect()
            self.db.create_tables()
        except Exception as e:
            logger.error(f"Подключение к БД: {e}")
            raise

        try:
            default_start_dt = self.db.parse_datetime(Config.STOCKS_DATE_FROM_DEFAULT)
            if default_start_dt is None:
                raise ValueError("Не удалось распарсить STOCKS_DATE_FROM_DEFAULT")
            if full_snapshot:
                date_from = format_wb_datetime(default_start_dt)
                logger.info(f"Полный снимок с dateFrom={date_from}")
            else:
                dt = self.db.get_last_change_date_from()
                date_from = format_wb_datetime(dt) if dt else None
                if not date_from and os.path.exists(Config.PROGRESS_FILE):
                    try:
                        with open(Config.PROGRESS_FILE, "r", encoding="utf-8") as f:
                            date_from = json.load(f).get("last_change_date_from")
                    except Exception:
                        pass
                if not date_from:
                    date_from = format_wb_datetime(default_start_dt)
                logger.info(f"Продолжение с dateFrom={date_from}")

            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            logger.info(f"Срез остатков: date={snapshot_date}, hour={snapshot_hour.isoformat()}")
            total_items = 0
            page = 0

            while True:
                page += 1
                chunk = self.fetch_page(date_from)
                if chunk is None:
                    logger.error("Ошибка запроса, остановка")
                    break
                if not chunk:
                    logger.info("Пустой ответ — все остатки выгружены")
                    break

                self.save_to_json(chunk, date_from, page, snapshot_hour)
                count = self.db.upsert_stocks(chunk, snapshot_date, snapshot_hour)
                total_items += count

                last_row = chunk[-1]
                next_date = last_row.get("lastChangeDate") or last_row.get("last_change_date")
                if not next_date:
                    logger.warning("В ответе нет lastChangeDate, остановка")
                    break
                next_date_str = next_date if isinstance(next_date, str) else str(next_date)
                cursor_dt = self.db.parse_datetime(next_date_str)
                if cursor_dt is None:
                    logger.warning("Не удалось распарсить lastChangeDate=%s, остановка", next_date_str)
                    break
                overlapped_dt = compute_overlap_date_from(cursor_dt, default_start_dt)
                date_from = format_wb_datetime(overlapped_dt)
                logger.info(
                    "Overlap cursor supplier/stocks: lastChangeDate=%s, saved dateFrom=%s",
                    next_date_str,
                    date_from,
                )
                self.save_progress(date_from)

                logger.info(f"Страница {page}: обработано {len(chunk)} строк, всего за запуск {total_items}")

                if len(chunk) < 60000:
                    logger.info("Получено меньше 60000 строк — конец выгрузки")
                    break

                logger.info(f"Пауза {Config.REQUEST_INTERVAL} сек перед следующим запросом...")
                time.sleep(Config.REQUEST_INTERVAL)

            logger.info(f"Выгрузка остатков завершена. Всего записей: {total_items}")
        finally:
            self.db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Выгрузка остатков на складах WB (supplier/stocks)")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Полный снимок с начальной даты (игнорировать прогресс)",
    )
    args = parser.parse_args()
    fetcher = StocksFetcher()
    fetcher.run(full_snapshot=args.full)


if __name__ == "__main__":
    main()
