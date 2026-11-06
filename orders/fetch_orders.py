"""Скрипт для получения заказов WB из API supplier/orders."""
import json
import logging
import os
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo
import requests
from config import Config
from database import OrdersDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

ORDERS_PAGE_LIMIT = 80000  # лимит API за один запрос
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


class OrdersFetcher:
    """Выгрузка заказов WB (API supplier/orders)."""

    def __init__(self):
        Config.validate()
        self.db = OrdersDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def save_progress(self, last_change_date_from: str) -> None:
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
                    {"last_change_date_from": last_change_date_from, "updated_at": datetime.now().isoformat()},
                    f, ensure_ascii=False, indent=2,
                )
        except IOError as e:
            logger.error(f"Ошибка сохранения progress.json: {e}")

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        return {"Authorization": token, "Content-Type": "application/json"}

    def fetch_page(self, date_from: str, retry_count: int = None) -> Optional[List[Dict[str, Any]]]:
        """Один запрос: заказы начиная с dateFrom. До 80000 строк."""
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = Config.WB_API_BASE_URL
        headers = self._get_headers()
        params = {"dateFrom": date_from, "flag": 0}

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
                logger.info(f"Получено строк заказов: {len(data)} (dateFrom={date_from})")
                return data
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{retry_count} не удалась: {e}")
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки исчерпаны: {e}")
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def save_to_json(self, items: List[Dict[str, Any]], date_from: str, page: int, snapshot_hour: datetime) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_date = date_from.replace(":", "-").replace(" ", "_")[:19]
        filename = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"orders_{safe_date}_h{snapshot_hour.strftime('%Y-%m-%d_%H')}_p{page}_{ts}.json",
        )
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                {"date_from": date_from, "page": page, "total_items": len(items), "timestamp": ts, "data": items},
                f, ensure_ascii=False, indent=2,
            )
        logger.info(f"Сохранён JSON: {filename} ({len(items)} записей)")
        return filename

    def run(self, full_snapshot: bool = False, snapshot_hour: Optional[datetime] = None) -> None:
        logger.info("Начало выгрузки заказов supplier/orders")

        try:
            self.db.connect()
            self.db.create_tables()
        except Exception as e:
            logger.error(f"Подключение к БД: {e}")
            raise

        clear_tables = getattr(self, "_clear_before_run", False)
        if clear_tables:
            self.db.truncate_orders_and_progress()
            if os.path.exists(Config.PROGRESS_FILE):
                try:
                    os.remove(Config.PROGRESS_FILE)
                    logger.info(f"Удалён файл прогресса: {Config.PROGRESS_FILE}")
                except OSError as e:
                    logger.warning(f"Не удалось удалить progress.json: {e}")

        try:
            default_start_dt = datetime.combine(
                date.today() - timedelta(days=Config.ORDERS_INITIAL_DAYS),
                datetime.min.time(),
            )
            if full_snapshot or clear_tables:
                date_from = format_wb_datetime(default_start_dt)
                logger.info(f"Полный снимок: выгрузка за последние {Config.ORDERS_INITIAL_DAYS} дней (dateFrom={date_from}). API возвращает до {ORDERS_PAGE_LIMIT} строк за запрос; при большем объёме будут дополнительные страницы.")
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
                    logger.info(f"Первая выгрузка: за последние {Config.ORDERS_INITIAL_DAYS} дней, dateFrom={date_from}")
                else:
                    logger.info(f"Ежедневная выгрузка: продолжение с dateFrom={date_from}")

            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            logger.info(f"Срез заказов: date={snapshot_date}, hour={snapshot_hour.isoformat()}")
            total_items = 0
            page = 0

            while True:
                page += 1
                chunk = self.fetch_page(date_from)
                if chunk is None:
                    logger.error("Ошибка запроса, остановка")
                    break
                if not chunk:
                    logger.info("Пустой ответ — все заказы выгружены")
                    break

                self.save_to_json(chunk, date_from, page, snapshot_hour)
                count = self.db.upsert_orders(chunk, snapshot_date, snapshot_hour)
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
                    "Overlap cursor supplier/orders: lastChangeDate=%s, saved dateFrom=%s",
                    next_date_str,
                    date_from,
                )
                self.save_progress(date_from)

                logger.info(f"Страница {page}: обработано {len(chunk)} строк, всего за запуск {total_items}")

                if len(chunk) < ORDERS_PAGE_LIMIT:
                    logger.info("Получено меньше 80000 строк — конец выгрузки")
                    break

                logger.info(f"Пауза {Config.REQUEST_INTERVAL} сек перед следующим запросом...")
                time.sleep(Config.REQUEST_INTERVAL)

            logger.info(f"Выгрузка заказов завершена. Всего записей: {total_items}")
        finally:
            self.db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Выгрузка заказов WB (supplier/orders)")
    parser.add_argument("--full", action="store_true", help="Полный снимок за последние N дней (см. ORDERS_INITIAL_DAYS)")
    parser.add_argument("--clear", action="store_true", help="Очистить таблицы и прогресс, затем выгрузить заново за 90 дней")
    args = parser.parse_args()
    fetcher = OrdersFetcher()
    if args.clear:
        fetcher._clear_before_run = True
        fetcher.run(full_snapshot=True)
    else:
        fetcher.run(full_snapshot=args.full)


if __name__ == "__main__":
    main()
