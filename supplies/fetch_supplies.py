"""Скрипт для получения поставок WB из API supplies (orders-fbw)."""
import json
import logging
import os
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo
import requests
from config import Config
from database import SuppliesDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

SUPPLIES_PAGE_LIMIT = 1000  # лимит API за один запрос (max 1000)


def resolve_snapshot_hour(snapshot_hour: Optional[datetime]) -> datetime:
    if snapshot_hour is None:
        snapshot_hour = datetime.now(MOSCOW_TZ)
    elif snapshot_hour.tzinfo is None:
        snapshot_hour = snapshot_hour.replace(tzinfo=MOSCOW_TZ)
    return snapshot_hour.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


class SuppliesFetcher:
    """Выгрузка поставок WB (API POST/GET supplies)."""

    def __init__(self):
        Config.validate()
        self.db = SuppliesDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def save_progress(self, last_create_date: str) -> None:
        try:
            if not self.db.conn:
                self.db.connect()
            dt = self.db.parse_datetime(last_create_date)
            if dt:
                self.db.save_progress(dt)
        except Exception as e:
            logger.error(f"Ошибка сохранения прогресса в БД: {e}")
            raise
        try:
            with open(Config.PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"last_create_date": last_create_date, "updated_at": datetime.now().isoformat()},
                    f, ensure_ascii=False, indent=2,
                )
        except IOError as e:
            logger.error(f"Ошибка сохранения progress.json: {e}")

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        return {"Authorization": token, "Content-Type": "application/json"}

    def fetch_list(self, date_from: date, date_till: date, offset: int = 0, retry_count: int = None) -> Optional[List[Dict[str, Any]]]:
        """POST /api/v1/supplies — список поставок с фильтром по датам и пагинацией."""
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = Config.WB_API_BASE_URL
        headers = self._get_headers()
        payload = {
            "limit": SUPPLIES_PAGE_LIMIT,
            "offset": offset,
            "dates": [{"from": date_from.isoformat(), "till": date_till.isoformat(), "type": "createDate"}],
        }

        for attempt in range(retry_count):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
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
                logger.info(f"Получено поставок: {len(data)} (offset={offset})")
                return data
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{retry_count} не удалась: {e}")
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки исчерпаны: {e}")
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def fetch_detail(self, supply_id: int, retry_count: int = None) -> Optional[Dict[str, Any]]:
        """GET /api/v1/supplies/{ID} — детали поставки."""
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = f"{Config.WB_API_BASE_URL.rstrip('/')}/{supply_id}"
        headers = self._get_headers()
        for attempt in range(retry_count):
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                if resp.status_code == 404:
                    return None
                if resp.status_code == 429:
                    time.sleep((attempt + 1) * Config.RETRY_DELAY * 2)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                logger.warning(f"GET supply {supply_id} попытка {attempt + 1}/{retry_count}: {e}")
                if attempt == retry_count - 1:
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def fetch_goods(self, supply_id: int, retry_count: int = None) -> Optional[List[Dict[str, Any]]]:
        """GET /api/v1/supplies/{ID}/goods — товары в поставке."""
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = f"{Config.WB_API_BASE_URL.rstrip('/')}/{supply_id}/goods"
        headers = self._get_headers()
        for attempt in range(retry_count):
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                if resp.status_code == 404:
                    return []
                if resp.status_code == 429:
                    time.sleep((attempt + 1) * Config.RETRY_DELAY * 2)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, list) else []
            except requests.exceptions.RequestException as e:
                logger.warning(f"GET goods {supply_id} попытка {attempt + 1}/{retry_count}: {e}")
                if attempt == retry_count - 1:
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def save_to_json(self, items: List[Dict[str, Any]], date_from: str, date_till: str, offset: int) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"supplies_{date_from}_{date_till}_offset{offset}_{ts}.json",
        )
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                {"date_from": date_from, "date_till": date_till, "offset": offset, "total_items": len(items), "timestamp": ts, "data": items},
                f, ensure_ascii=False, indent=2,
            )
        logger.info(f"Сохранён JSON: {filename} ({len(items)} записей)")
        return filename

    def run(self, full_snapshot: bool = False, snapshot_hour: Optional[datetime] = None) -> None:
        logger.info("Начало выгрузки поставок (supplies)")

        try:
            self.db.connect()
            self.db.create_tables()
        except Exception as e:
            logger.error(f"Подключение к БД: {e}")
            raise

        clear_tables = getattr(self, "_clear_before_run", False)
        if clear_tables:
            self.db.truncate_supplies_and_progress()
            if os.path.exists(Config.PROGRESS_FILE):
                try:
                    os.remove(Config.PROGRESS_FILE)
                    logger.info(f"Удалён файл прогресса: {Config.PROGRESS_FILE}")
                except OSError as e:
                    logger.warning(f"Не удалось удалить progress.json: {e}")

        try:
            if full_snapshot or clear_tables:
                date_till = date.today()
                date_from = date_till - timedelta(days=Config.SUPPLIES_INITIAL_DAYS)
                logger.info(f"Полный снимок: выгрузка за последние {Config.SUPPLIES_INITIAL_DAYS} дней ({date_from} — {date_till})")
            else:
                last_dt = self.db.get_last_create_date_from()
                if last_dt and os.path.exists(Config.PROGRESS_FILE):
                    try:
                        with open(Config.PROGRESS_FILE, "r", encoding="utf-8") as f:
                            last_create = json.load(f).get("last_create_date")
                            if last_create:
                                last_dt = self.db.parse_datetime(last_create) or last_dt
                    except Exception:
                        pass
                if last_dt:
                    date_from = last_dt.date()
                    date_till = date.today()
                    logger.info(f"Инкремент: с {date_from} по {date_till}")
                else:
                    date_till = date.today()
                    date_from = date_till - timedelta(days=Config.SUPPLIES_INITIAL_DAYS)
                    logger.info(f"Первая выгрузка: за последние {Config.SUPPLIES_INITIAL_DAYS} дней")

            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            total_supplies = 0
            offset = 0

            while True:
                chunk = self.fetch_list(date_from, date_till, offset)
                if chunk is None:
                    logger.error("Ошибка запроса списка поставок, остановка")
                    break
                if not chunk:
                    logger.info("Пустой ответ — все поставки за период выгружены")
                    break

                self.save_to_json(chunk, date_from.isoformat(), date_till.isoformat(), offset)
                count = self.db.upsert_supplies_batch(chunk, snapshot_date, snapshot_hour)
                total_supplies += count

                # Детали и товары по желанию (лимит 30 req/мин)
                if Config.FETCH_DETAILS or Config.FETCH_GOODS:
                    for item in chunk:
                        sid = item.get("supplyID") or item.get("supply_id")
                        if sid is None:
                            continue
                        time.sleep(Config.REQUEST_INTERVAL)
                        if Config.FETCH_DETAILS:
                            detail = self.fetch_detail(sid)
                            if detail:
                                detail = dict(detail)
                                detail["supplyID"] = sid
                                self.db.upsert_supply(detail, snapshot_date, snapshot_hour)
                                time.sleep(Config.REQUEST_INTERVAL)
                        if Config.FETCH_GOODS:
                            goods = self.fetch_goods(sid)
                            if goods is not None and goods:
                                self.db.upsert_goods(sid, goods, snapshot_date, snapshot_hour)

                # Прогресс: последняя createDate в чанке
                last_create = None
                for item in chunk:
                    cd = item.get("createDate") or item.get("create_date")
                    if cd:
                        last_create = cd
                if last_create:
                    self.save_progress(last_create)

                offset += len(chunk)
                logger.info(f"Оффсет {offset}: обработано {len(chunk)} поставок, всего за запуск {total_supplies}")

                if len(chunk) < SUPPLIES_PAGE_LIMIT:
                    logger.info("Получено меньше 1000 — конец выгрузки за период")
                    break

                logger.info(f"Пауза {Config.REQUEST_INTERVAL} сек перед следующим запросом...")
                time.sleep(Config.REQUEST_INTERVAL)

            logger.info(f"Выгрузка поставок завершена. Всего записей: {total_supplies}")
        finally:
            self.db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Выгрузка поставок WB (supplies)")
    parser.add_argument("--full", action="store_true", help="Полный снимок за последние N дней (SUPPLIES_INITIAL_DAYS)")
    parser.add_argument("--clear", action="store_true", help="Очистить таблицы и прогресс, затем выгрузить заново")
    args = parser.parse_args()
    fetcher = SuppliesFetcher()
    if args.clear:
        fetcher._clear_before_run = True
        fetcher.run(full_snapshot=True)
    else:
        fetcher.run(full_snapshot=args.full)


if __name__ == "__main__":
    main()
