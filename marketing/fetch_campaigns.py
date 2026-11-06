"""Скрипт для получения маркетинговых кампаний WB (рекламные кампании поиска + медиакампании)."""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo
import requests
from config import Config
from database import MarketingDatabase
from progress_state import clear_progress_state, load_progress_state, save_progress_state
from wb_api_support import (
    TOKEN_MODE_BASE,
    extract_rate_limit_snapshot,
    resolve_wb_token_mode,
)

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


class CampaignsFetcher:
    """Выгрузка активных и неактивных маркетинговых кампаний продавца (Продвижение WB)."""

    REQUEST_TIMEOUT = (10, 30)
    ALWAYS_INCLUDE_STATUSES = {9, 11}
    RECENT_FINISHED_STATUS = 7
    RECENT_FINISHED_LOOKBACK_DAYS = 31

    def __init__(self):
        Config.validate()
        self.db = MarketingDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
        self.token_mode = resolve_wb_token_mode(Config.WB_API_TOKEN, Config.WB_API_TOKEN_MODE)
        self.retry_delay_429 = (
            float(Config.BASE_TOKEN_RETRY_DELAY_429)
            if self.token_mode == TOKEN_MODE_BASE
            else float(Config.RETRY_DELAY_429)
        )
        self.last_rate_limit: dict[str, Any] | None = None

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        headers = {"Authorization": token, "Content-Type": "application/json"}
        client_secret = (Config.WB_API_CLIENT_SECRET or "").strip()
        if client_secret:
            headers["X-Client-Secret"] = client_secret
        return headers

    def _retry_wait_for_429(self, resp: requests.Response, attempt: int) -> float:
        snapshot = extract_rate_limit_snapshot(resp.headers)
        self.last_rate_limit = {
            "retry": snapshot.retry,
            "reset": snapshot.reset,
            "remaining": snapshot.remaining,
            "limit": snapshot.limit,
            "retry_after": snapshot.retry_after,
        }
        if snapshot.wait_hint is not None:
            return snapshot.wait_hint
        return max(self.retry_delay_429, (attempt + 1) * Config.RETRY_DELAY * 2)

    @staticmethod
    def _progress_path() -> Path:
        return Path(Config.CAMPAIGNS_PROGRESS_FILE)

    def _load_progress(self, snapshot_hour: datetime) -> dict[str, Any]:
        payload = load_progress_state(self._progress_path())
        if payload.get("snapshot_hour") != snapshot_hour.isoformat():
            return {}
        return payload

    def _save_progress(
        self,
        snapshot_hour: datetime,
        *,
        stage: str,
        cursor: int,
        batch_size: int,
        total_items: int,
        campaign_ids: list[int],
        completed_substages: list[str],
    ) -> None:
        payload = {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_hour.date().isoformat(),
            "stage": stage,
            "cursor": cursor,
            "batch_size": batch_size,
            "total_items": total_items,
            "campaign_ids": campaign_ids,
            "completed_substages": completed_substages,
            "last_rate_limit": self.last_rate_limit,
        }
        save_progress_state(self._progress_path(), payload)

    def _clear_progress(self) -> None:
        clear_progress_state(self._progress_path())

    @staticmethod
    def _coerce_status(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _cutoff_date(cls, snapshot_date: date) -> date:
        return snapshot_date - timedelta(days=cls.RECENT_FINISHED_LOOKBACK_DAYS)

    @staticmethod
    def _parse_dt_value(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return MarketingDatabase().parse_datetime(value)

    @classmethod
    def _should_keep_promotion_item(
        cls,
        *,
        status_value: Any,
        change_time_value: Any,
        snapshot_date: date,
    ) -> bool:
        status = cls._coerce_status(status_value)
        if status in cls.ALWAYS_INCLUDE_STATUSES:
            return True
        if status != cls.RECENT_FINISHED_STATUS:
            return False
        parsed_change_time = cls._parse_dt_value(change_time_value)
        if parsed_change_time is None:
            return False
        return parsed_change_time.date() >= cls._cutoff_date(snapshot_date)

    @classmethod
    def _should_keep_normalized_campaign(
        cls,
        normalized_row: dict[str, Any],
        snapshot_date: date,
    ) -> bool:
        status = cls._coerce_status(normalized_row.get("status"))
        if status in cls.ALWAYS_INCLUDE_STATUSES:
            return True
        if status != cls.RECENT_FINISHED_STATUS:
            return False
        deleted_at = normalized_row.get("deleted_at")
        updated_at = normalized_row.get("updated_at")
        started_at = normalized_row.get("started_at")
        effective_end = deleted_at or updated_at or started_at
        if effective_end is None:
            return False
        if isinstance(effective_end, datetime):
            effective_date = effective_end.date()
        else:
            effective_date = cls._parse_dt_value(effective_end)
            effective_date = effective_date.date() if effective_date else None
        if effective_date is None:
            return False
        return effective_date >= cls._cutoff_date(snapshot_date)

    def _request(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        interval: float = 0.2,
    ) -> Optional[Any]:
        """Выполнить GET-запрос с повторами и паузой."""
        headers = self._get_headers()
        for attempt in range(Config.RETRY_COUNT):
            try:
                resp = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.REQUEST_TIMEOUT,
                )
                if resp.status_code == 429:
                    rate_limit = extract_rate_limit_snapshot(resp.headers)
                    wait = self._retry_wait_for_429(resp, attempt)
                    logger.warning(
                        "429 Too Many Requests, ожидание %.1f сек... "
                        "(mode=%s, retry=%s, reset=%s, remaining=%s, limit=%s, retry_after=%s)",
                        wait,
                        self.token_mode,
                        rate_limit.retry,
                        rate_limit.reset,
                        rate_limit.remaining,
                        rate_limit.limit,
                        rate_limit.retry_after,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                time.sleep(interval)
                if not resp.content:
                    logger.warning(
                        "Пустой ответ WB GET %s params=%s attempt=%s/%s",
                        url,
                        params,
                        attempt + 1,
                        Config.RETRY_COUNT,
                    )
                    return None
                return resp.json()
            except ValueError as e:
                logger.warning(
                    "Невалидный JSON WB GET %s params=%s attempt=%s/%s: %s",
                    url,
                    params,
                    attempt + 1,
                    Config.RETRY_COUNT,
                    e,
                )
                return None
            except requests.exceptions.RequestException as e:
                logger.warning(
                    "Попытка %s/%s не удалась для WB GET %s params=%s: %s",
                    attempt + 1,
                    Config.RETRY_COUNT,
                    url,
                    params,
                    e,
                )
                self.last_rate_limit = None
                if attempt == Config.RETRY_COUNT - 1:
                    logger.error(f"Все попытки исчерпаны: {e}")
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def fetch_promotion_count(self, snapshot_date: Optional[date] = None) -> Dict[str, Any]:
        """GET /adv/v1/promotion/count — собрать только актуальные ID рекламных кампаний поиска."""
        if snapshot_date is None:
            snapshot_date = datetime.now(MOSCOW_TZ).date()
        data = self._request(
            Config.PROMOTION_COUNT_URL,
            interval=Config.REQUEST_INTERVAL_PROMOTION,
        )
        if not data or not isinstance(data, dict):
            return {"campaign_ids": [], "raw_items": 0, "kept_items": 0}
        ids = []
        raw_items = 0
        kept_by_status: dict[int | None, int] = {}
        adverts = data.get("adverts") or []
        for group in adverts:
            status_value = group.get("status")
            for item in group.get("advert_list") or []:
                raw_items += 1
                aid = item.get("advertId") or item.get("advert_id")
                if aid is None:
                    continue
                if not self._should_keep_promotion_item(
                    status_value=status_value,
                    change_time_value=item.get("changeTime") or item.get("change_time"),
                    snapshot_date=snapshot_date,
                ):
                    continue
                status_key = self._coerce_status(status_value)
                kept_by_status[status_key] = kept_by_status.get(status_key, 0) + 1
                ids.append(int(aid))
        deduped_ids = list(dict.fromkeys(ids))
        logger.info(
            "Получено ID рекламных кампаний (promotion): raw=%s, kept=%s, unique=%s, kept_by_status=%s",
            raw_items,
            len(ids),
            len(deduped_ids),
            kept_by_status,
        )
        return {
            "campaign_ids": deduped_ids,
            "raw_items": raw_items,
            "kept_items": len(ids),
            "unique_items": len(deduped_ids),
            "kept_by_status": kept_by_status,
        }

    def fetch_promotion_details(self, ids: List[int]) -> List[Dict[str, Any]]:
        """GET /api/advert/v2/adverts?ids=... батчами по 50."""
        all_adverts = []
        batch_size = 50
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            ids_param = ",".join(str(x) for x in batch)
            data = self._request(
                Config.ADVERTS_V2_URL,
                params={"ids": ids_param},
                interval=Config.REQUEST_INTERVAL_PROMOTION,
            )
            if not data or not isinstance(data, dict):
                continue
            adverts = data.get("adverts") or []
            all_adverts.extend(adverts)
            logger.info(f"Получено деталей рекламных кампаний: {len(adverts)} (батч {i // batch_size + 1})")
        return all_adverts

    def fetch_media_adverts(self) -> List[Dict[str, Any]]:
        """GET /adv/v1/adverts с пагинацией limit/offset."""
        all_items = []
        offset = 0
        limit = Config.MEDIA_PAGE_LIMIT
        while True:
            data = self._request(
                Config.MEDIA_ADVERTS_URL,
                params={"limit": limit, "offset": offset},
                interval=Config.REQUEST_INTERVAL_MEDIA,
            )
            if data is None:
                break
            if isinstance(data, list):
                chunk = data
            elif isinstance(data, dict) and "adverts" in data:
                chunk = data.get("adverts") or []
            else:
                chunk = []
            if not chunk:
                break
            all_items.extend(chunk)
            logger.info(f"Получено медиакампаний: {len(chunk)} (offset={offset}, всего {len(all_items)})")
            if len(chunk) < limit:
                break
            offset += limit
        return all_items

    def save_to_json(
        self,
        data: Any,
        prefix: str,
        snapshot_hour: datetime,
    ) -> str:
        """Сохранить снимок в JSON."""
        ts = f"{snapshot_hour.strftime('%Y-%m-%d_%H')}_{int(time.time())}"
        filename = os.path.join(Config.JSON_OUTPUT_DIR, f"{prefix}_{ts}.json")
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        count = len(data) if isinstance(data, list) else 0
        logger.info(f"Сохранён JSON: {filename} ({count} записей)")
        return filename

    def _normalize_campaign_batch(
        self,
        promotion_details: list[dict[str, Any]],
        snapshot_date: date,
        snapshot_hour: datetime,
    ) -> tuple[int, int]:
        if not promotion_details:
            return 0, 0

        normalized_all = [self.db.normalize_row_promotion(item) for item in promotion_details]
        filtered_normalized = []
        kept_ids = set()
        for normalized_row in normalized_all:
            if not normalized_row:
                continue
            if not self._should_keep_normalized_campaign(normalized_row, snapshot_date):
                continue
            filtered_normalized.append(normalized_row)
            kept_ids.add(int(normalized_row["external_id"]))

        if not filtered_normalized:
            logger.info("Батч promotion details полностью отфильтрован как неактуальный")
            return 0, 0

        filtered_details = [
            item
            for item in promotion_details
            if (item.get("id") or item.get("advertId")) in kept_ids
        ]
        self.save_to_json(
            {"snapshot_date": snapshot_date.isoformat(), "campaigns": filtered_details},
            "promotion_campaigns",
            snapshot_hour,
        )
        promotion_count = self.db.upsert_campaigns(filtered_normalized, snapshot_date, snapshot_hour, "promotion")

        campaign_nms_rows = []
        for camp in filtered_details:
            advert_id = camp.get("id") or camp.get("advertId")
            if advert_id is None:
                continue
            for nm in camp.get("nm_settings") or []:
                nm_id = nm.get("nm_id") or nm.get("nmId")
                if nm_id is None:
                    continue
                subject = nm.get("subject") or {}
                bids = nm.get("bids_kopecks") or nm.get("bidsKopecks") or {}
                campaign_nms_rows.append({
                    "advert_id": advert_id,
                    "nm_id": nm_id,
                    "subject_id": subject.get("id") if isinstance(subject, dict) else None,
                    "subject_name": subject.get("name") if isinstance(subject, dict) else None,
                    "bid_search_kopecks": bids.get("search", 0) or 0,
                    "bid_recommendations_kopecks": bids.get("recommendations", 0) or 0,
                })
        campaign_nms_count = 0
        if campaign_nms_rows:
            campaign_nms_count = self.db.upsert_campaign_nms(campaign_nms_rows, snapshot_date, snapshot_hour)
        return promotion_count, campaign_nms_count

    def fetch_ids(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        logger.info("Начало fetch_ids для маркетинговых кампаний")
        self.db.connect()
        try:
            self.db.create_tables()
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            fetch_result = self.fetch_promotion_count(snapshot_hour.date())
            promotion_ids = [int(value) for value in fetch_result.get("campaign_ids") or []]
            self._save_progress(
                snapshot_hour,
                stage="fetch_ids",
                cursor=0,
                batch_size=50,
                total_items=len(promotion_ids),
                campaign_ids=promotion_ids,
                completed_substages=["fetch_ids"],
            )
            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "snapshot_date": snapshot_hour.date().isoformat(),
                "campaign_ids": len(promotion_ids),
                "raw_campaign_ids": int(fetch_result.get("raw_items") or 0),
                "batch_size": 50,
            }
        finally:
            self.db.close()

    def fetch_details_batches(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        logger.info("Начало fetch_details_batches для маркетинговых кампаний")
        self.db.connect()
        try:
            self.db.create_tables()
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            state = self._load_progress(snapshot_hour)
            campaign_ids = [int(value) for value in state.get("campaign_ids") or []]
            if not campaign_ids:
                fetch_result = self.fetch_promotion_count(snapshot_date)
                campaign_ids = [int(value) for value in fetch_result.get("campaign_ids") or []]
            batch_size = int(state.get("batch_size") or 50)
            next_batch_index = int(state.get("cursor") or 0)
            total_items = int(state.get("total_items") or len(campaign_ids))
            completed_substages = list(state.get("completed_substages") or [])
            promotion_count = 0
            campaign_nms_count = 0

            for batch_index in range(next_batch_index, len(campaign_ids), batch_size):
                batch = campaign_ids[batch_index : batch_index + batch_size]
                if not batch:
                    break
                ids_param = ",".join(str(x) for x in batch)
                data = self._request(
                    Config.ADVERTS_V2_URL,
                    params={"ids": ids_param},
                    interval=Config.REQUEST_INTERVAL_PROMOTION,
                )
                if not data or not isinstance(data, dict):
                    raise RuntimeError(f"Не удалось получить batch adverts_v2 для ids={ids_param}")
                adverts = data.get("adverts") or []
                batch_promotion_count, batch_nms_count = self._normalize_campaign_batch(
                    adverts,
                    snapshot_date,
                    snapshot_hour,
                )
                promotion_count += batch_promotion_count
                campaign_nms_count += batch_nms_count
                completed_substages = ["fetch_ids", "fetch_details_batches"]
                self._save_progress(
                    snapshot_hour,
                    stage="fetch_details_batches",
                    cursor=batch_index + batch_size,
                    batch_size=batch_size,
                    total_items=total_items,
                    campaign_ids=campaign_ids,
                    completed_substages=completed_substages,
                )

            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "campaign_ids": len(campaign_ids),
                "promotion_campaigns": promotion_count,
                "campaign_nms": campaign_nms_count,
                "batch_size": batch_size,
            }
        finally:
            self.db.close()

    def finalize(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        state = self._load_progress(snapshot_hour)
        campaign_ids = [int(value) for value in state.get("campaign_ids") or []]
        total_items = int(state.get("total_items") or len(campaign_ids))
        cursor = int(state.get("cursor") or 0)
        if campaign_ids and cursor < total_items:
            raise RuntimeError(
                f"marketing campaigns not fully processed: cursor={cursor}, total_items={total_items}"
            )
        self._clear_progress()
        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_hour.date().isoformat(),
            "campaign_ids": len(campaign_ids),
            "completed": True,
        }

    def run(
        self,
        full_snapshot: bool = False,
        snapshot_hour: Optional[datetime] = None,
        include_media: bool = False,
    ) -> dict[str, Any]:
        """
        Полная выгрузка маркетинговых кампаний на текущую дату.
        full_snapshot: зарезервировано по аналогии с Остатками (на логику не влияет).
        """
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        ids_result = self.fetch_ids(snapshot_hour=snapshot_hour)
        details_result = self.fetch_details_batches(snapshot_hour=snapshot_hour)
        finalize_result = self.finalize(snapshot_hour=snapshot_hour)
        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_hour.date().isoformat(),
            "promotion_campaigns": details_result.get("promotion_campaigns", 0),
            "campaign_nms": details_result.get("campaign_nms", 0),
            "media_campaigns": 0,
            "include_media": include_media,
            "campaign_ids": ids_result.get("campaign_ids", 0),
            "completed": finalize_result.get("completed", False),
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Выгрузка активных и неактивных маркетинговых кампаний WB (Продвижение)"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Полный снимок (флаг по аналогии с Остатками)",
    )
    parser.add_argument(
        "--include-media",
        action="store_true",
        help="Дополнительно выгружать медиакампании",
    )
    args = parser.parse_args()
    fetcher = CampaignsFetcher()
    fetcher.run(full_snapshot=args.full, include_media=args.include_media)


if __name__ == "__main__":
    main()
