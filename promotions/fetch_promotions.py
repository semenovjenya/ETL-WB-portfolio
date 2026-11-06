"""Скрипт для получения календаря акций WB из API calendar/promotions."""
import json
import logging
import os
import time
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Any
import requests
from zoneinfo import ZoneInfo
from config import Config
from database import PromotionsDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def resolve_snapshot_hour(snapshot_hour: Optional[datetime]) -> datetime:
    if snapshot_hour is None:
        snapshot_hour = datetime.now(MOSCOW_TZ)
    elif snapshot_hour.tzinfo is None:
        snapshot_hour = snapshot_hour.replace(tzinfo=MOSCOW_TZ)
    return snapshot_hour.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


class PromotionsFetcher:
    """Выгрузка календаря акций WB (API calendar/promotions)."""

    def __init__(self):
        Config.validate()
        self.db = PromotionsDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        return {"Authorization": token, "Content-Type": "application/json"}

    def _format_dt_iso(self, dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def fetch_page(
        self,
        start_date_time: str,
        end_date_time: str,
        offset: int = 0,
        limit: int = None,
        all_promo: bool = None,
        retry_count: int = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Один запрос: список акций за период. limit 1..1000."""
        if limit is None:
            limit = Config.PAGE_LIMIT
        if all_promo is None:
            all_promo = Config.ALL_PROMO
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = Config.WB_API_BASE_URL
        headers = self._get_headers()
        params = {
            "startDateTime": start_date_time,
            "endDateTime": end_date_time,
            "allPromo": "true" if all_promo else "false",
            "limit": limit,
            "offset": offset,
        }

        for attempt in range(retry_count):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=60)
                if resp.status_code == 429:
                    wait = (attempt + 1) * Config.RETRY_DELAY * 2
                    logger.warning(f"429 Too Many Requests, ожидание {wait} сек...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                promotions = (data.get("data") or {}).get("promotions") or []
                if not isinstance(promotions, list):
                    promotions = []
                logger.info(f"Получено акций: {len(promotions)} (offset={offset})")
                return promotions
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
        start_dt: str,
        end_dt: str,
        offset: int,
    ) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"promotions_{start_dt[:10]}_{end_dt[:10]}_offset{offset}_{ts}.json",
        )
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "startDateTime": start_dt,
                    "endDateTime": end_dt,
                    "offset": offset,
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
        logger.info("Начало выгрузки календаря акций calendar/promotions")

        try:
            self.db.connect()
            self.db.create_tables()
        except Exception as e:
            logger.error(f"Подключение к БД: {e}")
            raise

        clear_tables = getattr(self, "_clear_before_run", False)
        if clear_tables:
            self.db.truncate_promotions_and_progress()
            if os.path.exists(Config.PROGRESS_FILE):
                try:
                    os.remove(Config.PROGRESS_FILE)
                    logger.info(f"Удалён файл прогресса: {Config.PROGRESS_FILE}")
                except OSError as e:
                    logger.warning(f"Не удалось удалить progress.json: {e}")

        now = datetime.now(timezone.utc)
        start_dt = now
        end_dt = now + timedelta(days=Config.PROMOTIONS_DAYS_AHEAD)
        start_str = self._format_dt_iso(start_dt)
        end_str = self._format_dt_iso(end_dt)
        logger.info(f"Период: {start_str} — {end_str}")

        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        snapshot_date = snapshot_hour.date()
        total_items = 0
        offset = 0
        all_promotions: List[Dict[str, Any]] = []

        try:
            while True:
                chunk = self.fetch_page(start_str, end_str, offset=offset)
                if chunk is None:
                    raise RuntimeError(
                        "Не удалось получить календарь акций "
                        f"за период {start_str} - {end_str} (offset={offset})"
                    )
                if not chunk:
                    break
                all_promotions.extend(chunk)
                self.save_to_json(chunk, start_str, end_str, offset)
                offset += len(chunk)
                if len(chunk) < Config.PAGE_LIMIT:
                    break
                time.sleep(Config.REQUEST_INTERVAL)

            if not all_promotions:
                raise RuntimeError(
                    "Выгрузка календаря акций завершилась без записей. "
                    "Проверьте WB API token/endpoint и наличие доступных акций."
                )

            count = self.db.upsert_promotions(all_promotions, snapshot_date, snapshot_hour)
            total_items = count
            self.db.save_progress(end_dt)
            try:
                with open(Config.PROGRESS_FILE, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "startDateTime": start_str,
                            "endDateTime": end_str,
                            "updated_at": datetime.now().isoformat(),
                        },
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
            except IOError as e:
                logger.error(f"Ошибка сохранения progress.json: {e}")

            logger.info(f"Выгрузка календаря акций завершена. Всего записей: {total_items}")
        finally:
            self.db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Выгрузка календаря акций WB (calendar/promotions)")
    parser.add_argument("--full", action="store_true", help="Полный снимок за период PROMOTIONS_DAYS_AHEAD")
    parser.add_argument("--clear", action="store_true", help="Очистить таблицы и прогресс, затем выгрузить заново")
    args = parser.parse_args()
    fetcher = PromotionsFetcher()
    if args.clear:
        fetcher._clear_before_run = True
        fetcher.run(full_snapshot=True)
    else:
        fetcher.run(full_snapshot=args.full)


if __name__ == "__main__":
    main()
