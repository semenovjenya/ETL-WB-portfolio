"""Выгрузка подробностей календарных акций WB — API GET /api/v1/calendar/promotions/details."""
import json
import logging
import os
import time
from datetime import date, datetime
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

# До 100 ID за запрос (документация output/markdown/promotion)
DETAILS_BATCH_SIZE = 100


def resolve_snapshot_hour(snapshot_hour: Optional[datetime]) -> datetime:
    if snapshot_hour is None:
        snapshot_hour = datetime.now(MOSCOW_TZ)
    elif snapshot_hour.tzinfo is None:
        snapshot_hour = snapshot_hour.replace(tzinfo=MOSCOW_TZ)
    return snapshot_hour.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


class PromotionsDetailsFetcher:
    """Выгрузка подробностей акций (GET /api/v1/calendar/promotions/details)."""

    def __init__(self):
        Config.validate()
        self.db = PromotionsDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        return {"Authorization": token, "Content-Type": "application/json"}

    def fetch_details_batch(
        self,
        promotion_ids: List[int],
        retry_count: int = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Один запрос: подробности по до 100 promotionIDs."""
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = Config.WB_API_DETAILS_URL
        headers = self._get_headers()
        # promotionIDs=1&promotionIDs=2&...
        params = [("promotionIDs", pid) for pid in promotion_ids]

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
                logger.info(f"Получено подробностей акций: {len(promotions)} (батч из {len(promotion_ids)} id)")
                return promotions
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{retry_count} не удалась: {e}")
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки исчерпаны: {e}")
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def save_to_json(self, items: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime) -> str:
        """Сохранить снимок details в JSON."""
        filename = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"promotions_details_{snapshot_date.isoformat()}_{snapshot_hour.strftime('%H-%M-%S')}.json",
        )
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "snapshot_date": snapshot_date.isoformat(),
                    "snapshot_hour": snapshot_hour.isoformat(),
                    "promotions": items,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info(f"Сохранён JSON: {filename} ({len(items)} записей)")
        return filename

    def run(
        self,
        snapshot_date: Optional[date] = None,
        snapshot_hour: Optional[datetime] = None,
    ) -> None:
        """
        Выгрузка подробностей по всем акциям за срез.
        Берёт список promotion_id из wb_calendar_promotions за конкретную snapshot_date.
        Запрашивает details батчами по 100 ID.
        """
        logger.info("Начало выгрузки подробностей календарных акций (details)")

        try:
            self.db.connect()
            self.db.create_tables()
        except Exception as e:
            logger.error(f"Подключение к БД: {e}")
            raise

        if snapshot_hour is not None:
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)

        if snapshot_date is None:
            snapshot_date = self.db.get_latest_snapshot_date()
        if snapshot_date is None:
            logger.warning(
                "Нет дневного среза акций за выбранную дату. Сначала выполните fetch_promotions."
            )
            self.db.close()
            return

        if snapshot_hour is None:
            snapshot_hour = resolve_snapshot_hour(datetime.combine(snapshot_date, datetime.min.time(), tzinfo=MOSCOW_TZ))
        else:
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
        promotion_ids = self.db.get_promotion_ids(snapshot_date=snapshot_date)
        if not promotion_ids:
            logger.warning(
                "Нет акций за выбранный срез. Сначала выполните fetch_promotions."
            )
            self.db.close()
            return

        logger.info(
            "Акций для выгрузки details: %s (snapshot_date=%s)",
            len(promotion_ids),
            snapshot_date,
        )

        all_details = []
        try:
            for i in range(0, len(promotion_ids), DETAILS_BATCH_SIZE):
                batch = promotion_ids[i : i + DETAILS_BATCH_SIZE]
                details = self.fetch_details_batch(batch)
                if details is None:
                    continue
                all_details.extend(details)
                time.sleep(Config.REQUEST_INTERVAL)

            if all_details:
                self.save_to_json(all_details, snapshot_date, snapshot_hour)
                normalized = [self.db.normalize_row_details(d) for d in all_details]
                normalized = [r for r in normalized if r.get("promotion_id") is not None]
                if normalized:
                    self.db.upsert_promotion_details(normalized, snapshot_date, snapshot_hour)

            logger.info(
                f"Выгрузка подробностей акций завершена. Всего записей: {len(all_details)}"
            )
        finally:
            self.db.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Выгрузка подробностей календарных акций WB (calendar/promotions/details)"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Дата среза YYYY-MM-DD (по умолчанию — последний срез в БД)",
    )
    parser.add_argument(
        "--snapshot-hour",
        type=str,
        default=None,
        help="Точный snapshot_hour YYYY-MM-DDTHH:MM:SS[+TZ]",
    )
    args = parser.parse_args()
    snapshot_date = None
    snapshot_hour = None
    if args.date:
        try:
            snapshot_date = date.fromisoformat(args.date)
        except ValueError:
            raise SystemExit(f"Неверный формат даты: {args.date}")
    if args.snapshot_hour:
        try:
            snapshot_hour = datetime.fromisoformat(args.snapshot_hour)
        except ValueError:
            raise SystemExit(f"Неверный формат snapshot_hour: {args.snapshot_hour}")

    fetcher = PromotionsDetailsFetcher()
    fetcher.run(snapshot_date=snapshot_date, snapshot_hour=snapshot_hour)


if __name__ == "__main__":
    main()
