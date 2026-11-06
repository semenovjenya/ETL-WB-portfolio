"""Выгрузка детализации календарных акций WB до SKU (номенклатуры) — API calendar/promotions/nomenclatures."""
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


def resolve_snapshot_hour(snapshot_hour: Optional[datetime]) -> datetime:
    if snapshot_hour is None:
        snapshot_hour = datetime.now(MOSCOW_TZ)
    elif snapshot_hour.tzinfo is None:
        snapshot_hour = snapshot_hour.replace(tzinfo=MOSCOW_TZ)
    return snapshot_hour.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


class PromotionsNomenclaturesFetcher:
    """Выгрузка номенклатур (SKU) по календарным акциям WB (GET /api/v1/calendar/promotions/nomenclatures)."""

    def __init__(self):
        Config.validate()
        self.db = PromotionsDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        return {"Authorization": token, "Content-Type": "application/json"}

    def fetch_page(
        self,
        promotion_id: int,
        in_action: bool,
        offset: int = 0,
        limit: int = None,
        retry_count: int = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Один запрос: номенклатуры по акции. limit 1..1000 (API)."""
        if limit is None:
            limit = Config.PAGE_LIMIT
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = Config.WB_API_NOMENCLATURES_URL
        headers = self._get_headers()
        params = {
            "promotionID": promotion_id,
            "inAction": "true" if in_action else "false",
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
                # 422 = метод неприменим для этой акции (например, автоакция — см. доку nomenclatures)
                if resp.status_code == 422:
                    logger.info(
                        f"Промо {promotion_id} inAction={in_action}: 422 (метод не применим, напр. автоакция), пропуск"
                    )
                    return []
                resp.raise_for_status()
                data = resp.json()
                nomenclatures = (data.get("data") or {}).get("nomenclatures") or []
                if not isinstance(nomenclatures, list):
                    nomenclatures = []
                return nomenclatures
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{retry_count} не удалась: {e}")
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки исчерпаны: {e}")
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def fetch_all_nomenclatures_for_promotion(
        self, promotion_id: int, in_action: bool
    ) -> List[Dict[str, Any]]:
        """Все номенклатуры по одной акции и флагу inAction (с пагинацией)."""
        all_items = []
        offset = 0
        while True:
            chunk = self.fetch_page(promotion_id, in_action, offset=offset)
            if chunk is None:
                break
            if not chunk:
                break
            all_items.extend(chunk)
            if len(chunk) < Config.PAGE_LIMIT:
                break
            offset += len(chunk)
            time.sleep(Config.REQUEST_INTERVAL)
        return all_items

    def save_to_json(
        self,
        promotion_id: int,
        in_action: bool,
        items: List[Dict[str, Any]],
        snapshot_date: date,
        snapshot_hour: datetime,
    ) -> str:
        """Сохранить снимок номенклатур по акции в JSON."""
        suffix = "in_action" if in_action else "not_in_action"
        filename = os.path.join(
            Config.JSON_OUTPUT_DIR,
            (
                f"promotions_nomenclatures_p{promotion_id}_{suffix}_"
                f"{snapshot_date.isoformat()}_{snapshot_hour.strftime('%H-%M-%S')}.json"
            ),
        )
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "promotion_id": promotion_id,
                    "in_action": in_action,
                    "snapshot_date": snapshot_date.isoformat(),
                    "snapshot_hour": snapshot_hour.isoformat(),
                    "total_items": len(items),
                    "data": items,
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
        Выгрузка номенклатур (SKU) по всем акциям за срез.
        Берёт список promotion_id из wb_calendar_promotions за конкретную snapshot_date.
        По каждой акции запрашивает номенклатуры с inAction=true и inAction=false.
        """
        logger.info("Начало выгрузки номенклатур по календарным акциям (детализация до SKU)")

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
            "Акций для выгрузки номенклатур: %s (snapshot_date=%s)",
            len(promotion_ids),
            snapshot_date,
        )

        total_rows = 0
        try:
            for promotion_id in promotion_ids:
                for in_action in (True, False):
                    items = self.fetch_all_nomenclatures_for_promotion(
                        promotion_id, in_action
                    )
                    if items:
                        self.save_to_json(
                            promotion_id,
                            in_action,
                            items,
                            snapshot_date,
                            snapshot_hour,
                        )
                        normalized = [
                            self.db.normalize_row_nomenclature(
                                n, promotion_id, in_action
                            )
                            for n in items
                        ]
                        normalized = [r for r in normalized if r.get("nm_id") is not None]
                        if normalized:
                            cnt = self.db.upsert_promotion_nomenclatures(
                                normalized, snapshot_date, snapshot_hour
                            )
                            total_rows += cnt
                    time.sleep(Config.REQUEST_INTERVAL)

            logger.info(
                f"Выгрузка номенклатур по акциям завершена. Всего записей (SKU): {total_rows}"
            )
        finally:
            self.db.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Выгрузка номенклатур (SKU) по календарным акциям WB (calendar/promotions/nomenclatures)"
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

    fetcher = PromotionsNomenclaturesFetcher()
    fetcher.run(snapshot_date=snapshot_date, snapshot_hour=snapshot_hour)


if __name__ == "__main__":
    main()
