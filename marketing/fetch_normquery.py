"""Выгрузка поисковых кластеров, ставок и минус-фраз (аналитика маркетинга WB, не по подписке)."""
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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


class NormqueryFetcher:
    """Кластеры (list), ставки (get-bids), минус-фразы (get-minus) по рекламным кампаниям."""

    REQUEST_TIMEOUT = (10, 30)

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
        return Path(Config.NORMQUERY_PROGRESS_FILE)

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
        pairs: list[tuple[int, int]],
        completed_substages: list[str],
    ) -> None:
        payload = {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_hour.date().isoformat(),
            "stage": stage,
            "cursor": cursor,
            "batch_size": batch_size,
            "total_items": total_items,
            "pairs": [{"advert_id": advert_id, "nm_id": nm_id} for advert_id, nm_id in pairs],
            "completed_substages": completed_substages,
            "last_rate_limit": self.last_rate_limit,
        }
        save_progress_state(self._progress_path(), payload)

    def _clear_progress(self) -> None:
        clear_progress_state(self._progress_path())

    def _pairs_from_state(self, payload: dict[str, Any]) -> list[tuple[int, int]]:
        pairs = []
        for item in payload.get("pairs") or []:
            advert_id = item.get("advert_id")
            nm_id = item.get("nm_id")
            if advert_id is None or nm_id is None:
                continue
            pairs.append((int(advert_id), int(nm_id)))
        return pairs

    def _get(self, url: str, params: Optional[Dict] = None, interval: float = 0.2) -> Optional[Any]:
        for attempt in range(Config.RETRY_COUNT):
            try:
                r = requests.get(
                    url,
                    headers=self._get_headers(),
                    params=params,
                    timeout=self.REQUEST_TIMEOUT,
                )
                if r.status_code == 429:
                    wait = self._retry_wait_for_429(r, attempt)
                    logger.warning("429 Too Many Requests для WB GET %s, ожидание %.1f сек", url, wait)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                time.sleep(interval)
                return r.json()
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{Config.RETRY_COUNT}: {e}")
                self.last_rate_limit = None
                if attempt == Config.RETRY_COUNT - 1:
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def _post(self, url: str, body: Dict[str, Any], interval: float = 0.2) -> Optional[Any]:
        for attempt in range(Config.RETRY_COUNT):
            try:
                r = requests.post(
                    url,
                    headers=self._get_headers(),
                    json=body,
                    timeout=self.REQUEST_TIMEOUT,
                )
                if r.status_code == 429:
                    wait = self._retry_wait_for_429(r, attempt)
                    logger.warning("429 Too Many Requests для WB POST %s, ожидание %.1f сек", url, wait)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                time.sleep(interval)
                return r.json()
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{Config.RETRY_COUNT}: {e}")
                self.last_rate_limit = None
                if attempt == Config.RETRY_COUNT - 1:
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def _get_campaign_nm_pairs_from_api(self) -> List[Tuple[int, int]]:
        """Fallback: пары (advert_id, nm_id) из рекламных кампаний через API."""
        data = self._get(Config.PROMOTION_COUNT_URL, interval=Config.REQUEST_INTERVAL_PROMOTION)
        if not data or not isinstance(data, dict):
            return []
        ids = []
        for group in (data.get("adverts") or []):
            for item in (group.get("advert_list") or []):
                aid = item.get("advertId") or item.get("advert_id")
                if aid is not None:
                    ids.append(int(aid))
        if not ids:
            return []
        pairs = []
        batch_size = 50
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            resp = self._get(
                Config.ADVERTS_V2_URL,
                params={"ids": ",".join(str(x) for x in batch)},
                interval=Config.REQUEST_INTERVAL_PROMOTION,
            )
            if not resp or not isinstance(resp, dict):
                continue
            for camp in (resp.get("adverts") or []):
                advert_id = camp.get("id") or camp.get("advertId")
                if not advert_id:
                    continue
                for nm in (camp.get("nm_settings") or []):
                    nm_id = nm.get("nm_id") or nm.get("nmId")
                    if nm_id is not None:
                        pairs.append((int(advert_id), int(nm_id)))
        logger.info(f"Собрано пар (advert_id, nm_id): {len(pairs)}")
        return pairs

    def prepare_pairs(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        logger.info("Подготовка пар кампания-номенклатура для normquery")
        self.db.connect()
        try:
            self.db.create_tables()
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            pairs = self.db.get_campaign_nm_pairs(snapshot_date=snapshot_date)
            pair_source = "campaign_nms"
            if not pairs:
                pairs = self._get_campaign_nm_pairs_from_api()
                pair_source = "api_fallback"
            self._save_progress(
                snapshot_hour,
                stage="prepare_pairs",
                cursor=0,
                batch_size=100,
                total_items=len(pairs),
                pairs=pairs,
                completed_substages=["prepare_pairs"],
            )
            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "pair_source": pair_source,
                "campaign_nm_pairs": len(pairs),
                "batch_size": 100,
            }
        finally:
            self.db.close()

    def fetch_batches(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        logger.info("Выгрузка batch-ов normquery")
        self.db.connect()
        try:
            self.db.create_tables()
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            state = self._load_progress(snapshot_hour)
            pairs = self._pairs_from_state(state)
            if not pairs:
                pairs = self.db.get_campaign_nm_pairs(snapshot_date=snapshot_date) or self._get_campaign_nm_pairs_from_api()
            if not pairs:
                return {
                    "snapshot_hour": snapshot_hour.isoformat(),
                    "snapshot_date": snapshot_date.isoformat(),
                    "campaign_nm_pairs": 0,
                    "clusters": 0,
                    "bids": 0,
                    "minus": 0,
                }

            batch_size = int(state.get("batch_size") or 100)
            next_cursor = int(state.get("cursor") or 0)
            interval = Config.REQUEST_INTERVAL_NORMQUERY
            completed_substages = list(state.get("completed_substages") or [])
            cluster_count = 0
            bids_count = 0
            minus_count = 0

            for start in range(next_cursor, len(pairs), batch_size):
                chunk = pairs[start : start + batch_size]
                items_v1 = [{"advertId": advert_id, "nmId": nm_id} for advert_id, nm_id in chunk]
                items_v0 = [{"advert_id": advert_id, "nm_id": nm_id} for advert_id, nm_id in chunk]

                list_resp = self._post(
                    Config.NORMQUERY_LIST_URL,
                    {"items": items_v1},
                    interval=interval,
                )
                if list_resp is None:
                    raise RuntimeError(f"Не удалось получить normquery/list batch start={start}")
                cluster_rows = []
                if isinstance(list_resp, dict):
                    for item in (list_resp.get("items") or []):
                        advert_id = item.get("advertId") or item.get("advert_id")
                        nm_id = item.get("nmId") or item.get("nm_id")
                        if advert_id is None or nm_id is None:
                            continue
                        norm_queries = item.get("normQueries") or {}
                        for query in (norm_queries.get("active") or []):
                            if query:
                                cluster_rows.append({
                                    "advert_id": advert_id,
                                    "nm_id": nm_id,
                                    "is_active": True,
                                    "norm_query": str(query).strip(),
                                })
                        for query in (norm_queries.get("excluded") or []):
                            if query:
                                cluster_rows.append({
                                    "advert_id": advert_id,
                                    "nm_id": nm_id,
                                    "is_active": False,
                                    "norm_query": str(query).strip(),
                                })

                bids_resp = self._post(
                    Config.NORMQUERY_GET_BIDS_URL,
                    {"items": items_v0},
                    interval=interval,
                )
                if bids_resp is None:
                    raise RuntimeError(f"Не удалось получить normquery/get-bids batch start={start}")
                bid_rows = []
                if isinstance(bids_resp, dict):
                    for item in (bids_resp.get("bids") or []):
                        advert_id = item.get("advert_id") or item.get("advertId")
                        nm_id = item.get("nm_id") or item.get("nmId")
                        norm_query = item.get("norm_query") or item.get("normQuery")
                        bid = item.get("bid")
                        if advert_id is None or nm_id is None or norm_query is None or bid is None:
                            continue
                        bid_rows.append({
                            "advert_id": advert_id,
                            "nm_id": nm_id,
                            "norm_query": str(norm_query),
                            "bid": int(bid),
                        })

                minus_resp = self._post(
                    Config.NORMQUERY_GET_MINUS_URL,
                    {"items": items_v0},
                    interval=interval,
                )
                if minus_resp is None:
                    raise RuntimeError(f"Не удалось получить normquery/get-minus batch start={start}")
                minus_rows = []
                if isinstance(minus_resp, dict):
                    for item in (minus_resp.get("items") or []):
                        advert_id = item.get("advert_id") or item.get("advertId")
                        nm_id = item.get("nm_id") or item.get("nmId")
                        for query in (item.get("norm_queries") or []):
                            if query and advert_id is not None and nm_id is not None:
                                minus_rows.append({
                                    "advert_id": advert_id,
                                    "nm_id": nm_id,
                                    "norm_query": str(query).strip(),
                                })

                if cluster_rows:
                    cluster_count += self.db.upsert_normquery_clusters(cluster_rows, snapshot_date, snapshot_hour)
                if bid_rows:
                    bids_count += self.db.upsert_normquery_bids(bid_rows, snapshot_date, snapshot_hour)
                if minus_rows:
                    minus_count += self.db.upsert_normquery_minus(minus_rows, snapshot_date, snapshot_hour)

                completed_substages = ["prepare_pairs", "fetch_batches"]
                self._save_progress(
                    snapshot_hour,
                    stage="fetch_batches",
                    cursor=start + batch_size,
                    batch_size=batch_size,
                    total_items=len(pairs),
                    pairs=pairs,
                    completed_substages=completed_substages,
                )

            out = os.path.join(Config.JSON_OUTPUT_DIR, f"normquery_{snapshot_date.isoformat()}.json")
            with open(out, "w", encoding="utf-8") as file:
                json.dump(
                    {"clusters": cluster_count, "bids": bids_count, "minus": minus_count},
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "campaign_nm_pairs": len(pairs),
                "clusters": cluster_count,
                "bids": bids_count,
                "minus": minus_count,
            }
        finally:
            self.db.close()

    def finalize(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        state = self._load_progress(snapshot_hour)
        pairs = self._pairs_from_state(state)
        total_items = int(state.get("total_items") or len(pairs))
        cursor = int(state.get("cursor") or 0)
        completed_substages = set(state.get("completed_substages") or [])
        if pairs and (cursor < total_items or "fetch_batches" not in completed_substages):
            raise RuntimeError(
                f"marketing normquery not fully processed: cursor={cursor}, total_items={total_items}"
            )
        self._clear_progress()
        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_hour.date().isoformat(),
            "campaign_nm_pairs": len(pairs),
            "completed": True,
        }

    def run(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        """Выгрузка кластеров, ставок и минус-фраз на текущую дату."""
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        prepare_result = self.prepare_pairs(snapshot_hour=snapshot_hour)
        fetch_result = self.fetch_batches(snapshot_hour=snapshot_hour)
        finalize_result = self.finalize(snapshot_hour=snapshot_hour)
        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_hour.date().isoformat(),
            "campaign_nm_pairs": prepare_result.get("campaign_nm_pairs", 0),
            "clusters": fetch_result.get("clusters", 0),
            "bids": fetch_result.get("bids", 0),
            "minus": fetch_result.get("minus", 0),
            "completed": finalize_result.get("completed", False),
        }


def main():
    fetcher = NormqueryFetcher()
    fetcher.run()


if __name__ == "__main__":
    main()
