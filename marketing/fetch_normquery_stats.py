"""Выгрузка статистики по поисковым кластерам (normquery stats v0 и v1) в таблицы маркетинга."""
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
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


class NormqueryStatsFetcher:
    """POST normquery/stats (v0) и normquery/stats (v1) — заполнение wb_marketing_normquery_stats и wb_marketing_normquery_stats_daily."""

    REQUEST_TIMEOUT = (10, 30)

    def __init__(self):
        Config.validate()
        self.db = MarketingDatabase()
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
        return Path(Config.NORMQUERY_STATS_PROGRESS_FILE)

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
        period_from: date,
        period_to: date,
        completed_substages: list[str],
    ) -> None:
        payload = {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_hour.date().isoformat(),
            "stage": stage,
            "cursor": cursor,
            "batch_size": batch_size,
            "total_items": total_items,
            "period_from": period_from.isoformat(),
            "period_to": period_to.isoformat(),
            "completed_substages": completed_substages,
            "last_rate_limit": self.last_rate_limit,
        }
        save_progress_state(self._progress_path(), payload)

    def _clear_progress(self) -> None:
        clear_progress_state(self._progress_path())

    def _post(self, url: str, body: Dict[str, Any], interval: float = 6.0) -> Optional[Any]:
        for attempt in range(Config.RETRY_COUNT):
            try:
                response = requests.post(
                    url,
                    headers=self._get_headers(),
                    json=body,
                    timeout=self.REQUEST_TIMEOUT,
                )
                if response.status_code == 429:
                    wait = self._retry_wait_for_429(response, attempt)
                    logger.warning("429 Too Many Requests для WB POST %s, ожидание %.1f сек", url, wait)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                time.sleep(interval)
                return response.json()
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{Config.RETRY_COUNT}: {e}")
                self.last_rate_limit = None
                if attempt == Config.RETRY_COUNT - 1:
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def _resolve_period(
        self,
        *,
        period_from: Optional[date],
        period_to: Optional[date],
        days: int,
        snapshot_hour: datetime,
    ) -> tuple[date, date]:
        if period_to is None:
            period_to = snapshot_hour.date()
        if period_from is None:
            period_from = period_to - timedelta(days=min(days, 31))
        if period_from > period_to:
            period_from, period_to = period_to, period_from
        return period_from, period_to

    def _load_pairs(self, snapshot_hour: datetime) -> list[tuple[int, int]]:
        return self.db.get_campaign_nm_pairs(snapshot_date=snapshot_hour.date())

    def fetch_v0_batches(
        self,
        period_from: Optional[date] = None,
        period_to: Optional[date] = None,
        days: int = 7,
        snapshot_hour: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        period_from, period_to = self._resolve_period(
            period_from=period_from,
            period_to=period_to,
            days=days,
            snapshot_hour=snapshot_hour,
        )
        self.db.connect()
        try:
            self.db.create_tables()
            pairs = self._load_pairs(snapshot_hour)
            if not pairs:
                return {
                    "snapshot_hour": snapshot_hour.isoformat(),
                    "period_from": period_from.isoformat(),
                    "period_to": period_to.isoformat(),
                    "campaign_nm_pairs": 0,
                    "normquery_stats": 0,
                }

            state = self._load_progress(snapshot_hour)
            batch_size = int(state.get("batch_size") or 100)
            next_cursor = int(state.get("cursor") or 0)
            rows_count = 0

            for start in range(next_cursor, len(pairs), batch_size):
                chunk = pairs[start : start + batch_size]
                items = [{"advert_id": advert_id, "nm_id": nm_id} for advert_id, nm_id in chunk]
                body = {"from": period_from.isoformat(), "to": period_to.isoformat(), "items": items}
                response = self._post(Config.NORMQUERY_STATS_URL, body, interval=Config.REQUEST_INTERVAL_STATS)
                if response is None:
                    raise RuntimeError(f"Не удалось получить normquery stats v0 batch start={start}")
                stats_rows = []
                if isinstance(response, dict):
                    for block in response.get("stats") or []:
                        advert_id = block.get("advert_id")
                        nm_id = block.get("nm_id")
                        if advert_id is None or nm_id is None:
                            continue
                        for stat in block.get("stats") or []:
                            norm_query = stat.get("norm_query")
                            if norm_query is None:
                                continue
                            stats_rows.append({
                                "advert_id": advert_id,
                                "nm_id": nm_id,
                                "norm_query": str(norm_query),
                                "views": stat.get("views", 0),
                                "clicks": stat.get("clicks", 0),
                                "ctr": stat.get("ctr"),
                                "cpc": stat.get("cpc"),
                                "cpm": stat.get("cpm"),
                                "orders": stat.get("orders", 0),
                                "atbs": stat.get("atbs", 0),
                                "avg_pos": stat.get("avg_pos"),
                            })
                if stats_rows:
                    rows_count += self.db.upsert_normquery_stats(stats_rows, period_from, period_to)
                self._save_progress(
                    snapshot_hour,
                    stage="fetch_v0_batches",
                    cursor=start + batch_size,
                    batch_size=batch_size,
                    total_items=len(pairs),
                    period_from=period_from,
                    period_to=period_to,
                    completed_substages=["fetch_v0_batches"],
                )

            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "period_from": period_from.isoformat(),
                "period_to": period_to.isoformat(),
                "campaign_nm_pairs": len(pairs),
                "normquery_stats": rows_count,
            }
        finally:
            self.db.close()

    def fetch_v1_batches(
        self,
        period_from: Optional[date] = None,
        period_to: Optional[date] = None,
        days: int = 7,
        snapshot_hour: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        period_from, period_to = self._resolve_period(
            period_from=period_from,
            period_to=period_to,
            days=days,
            snapshot_hour=snapshot_hour,
        )
        self.db.connect()
        try:
            self.db.create_tables()
            pairs = self._load_pairs(snapshot_hour)
            if not pairs:
                return {
                    "snapshot_hour": snapshot_hour.isoformat(),
                    "period_from": period_from.isoformat(),
                    "period_to": period_to.isoformat(),
                    "campaign_nm_pairs": 0,
                    "normquery_stats_daily": 0,
                }

            state = self._load_progress(snapshot_hour)
            batch_size = int(state.get("batch_size") or 100)
            next_cursor = int(state.get("cursor") or 0)
            rows_count = 0

            for start in range(next_cursor, len(pairs), batch_size):
                chunk = pairs[start : start + batch_size]
                items = [{"advertId": advert_id, "nmId": nm_id} for advert_id, nm_id in chunk]
                body = {"from": period_from.isoformat(), "to": period_to.isoformat(), "items": items}
                response = self._post(Config.NORMQUERY_STATS_V1_URL, body, interval=Config.REQUEST_INTERVAL_STATS)
                if response is None:
                    raise RuntimeError(f"Не удалось получить normquery stats v1 batch start={start}")
                stats_daily_rows = []
                if isinstance(response, dict):
                    for item in response.get("items") or []:
                        advert_id = item.get("advertId") or item.get("advert_id")
                        nm_id = item.get("nmId") or item.get("nm_id")
                        if advert_id is None or nm_id is None:
                            continue
                        for daily in item.get("dailyStats") or []:
                            stat_date = daily.get("date")
                            if not isinstance(stat_date, str):
                                continue
                            stat = daily.get("stat") or {}
                            stats_daily_rows.append({
                                "stat_date": stat_date[:10],
                                "advert_id": advert_id,
                                "nm_id": nm_id,
                                "norm_query": str(stat.get("normQuery") or stat.get("norm_query") or ""),
                                "views": stat.get("views", 0),
                                "clicks": stat.get("clicks", 0),
                                "ctr": stat.get("ctr"),
                                "cpc": stat.get("cpc"),
                                "cpm": stat.get("cpm"),
                                "orders": stat.get("orders", 0),
                                "shks": stat.get("shks", 0),
                                "atbs": stat.get("atbs", 0),
                                "avg_pos": stat.get("avgPos") or stat.get("avg_pos"),
                                "spend": stat.get("spend"),
                            })
                if stats_daily_rows:
                    rows_count += self.db.upsert_normquery_stats_daily(stats_daily_rows)
                self._save_progress(
                    snapshot_hour,
                    stage="fetch_v1_batches",
                    cursor=start + batch_size,
                    batch_size=batch_size,
                    total_items=len(pairs),
                    period_from=period_from,
                    period_to=period_to,
                    completed_substages=["fetch_v0_batches", "fetch_v1_batches"],
                )

            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "period_from": period_from.isoformat(),
                "period_to": period_to.isoformat(),
                "campaign_nm_pairs": len(pairs),
                "normquery_stats_daily": rows_count,
            }
        finally:
            self.db.close()

    def finalize(
        self,
        period_from: Optional[date] = None,
        period_to: Optional[date] = None,
        days: int = 7,
        snapshot_hour: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        period_from, period_to = self._resolve_period(
            period_from=period_from,
            period_to=period_to,
            days=days,
            snapshot_hour=snapshot_hour,
        )
        state = self._load_progress(snapshot_hour)
        completed_substages = set(state.get("completed_substages") or [])
        cursor = int(state.get("cursor") or 0)
        total_items = int(state.get("total_items") or 0)
        if total_items and (cursor < total_items or "fetch_v1_batches" not in completed_substages):
            raise RuntimeError(
                f"marketing normquery stats not fully processed: cursor={cursor}, total={total_items}, completed={sorted(completed_substages)}"
            )
        self._clear_progress()
        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "period_from": period_from.isoformat(),
            "period_to": period_to.isoformat(),
            "completed": True,
        }

    def run(
        self,
        period_from: Optional[date] = None,
        period_to: Optional[date] = None,
        days: int = 7,
        snapshot_hour: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Выгрузка статистики по кластерам за период."""
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        v0_result = self.fetch_v0_batches(
            period_from=period_from,
            period_to=period_to,
            days=days,
            snapshot_hour=snapshot_hour,
        )
        v1_result = self.fetch_v1_batches(
            period_from=period_from,
            period_to=period_to,
            days=days,
            snapshot_hour=snapshot_hour,
        )
        finalize_result = self.finalize(
            period_from=period_from,
            period_to=period_to,
            days=days,
            snapshot_hour=snapshot_hour,
        )
        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "period_from": (period_from.isoformat() if period_from else v0_result.get("period_from")),
            "period_to": (period_to.isoformat() if period_to else v0_result.get("period_to")),
            "campaign_nm_pairs": v0_result.get("campaign_nm_pairs", 0),
            "normquery_stats": v0_result.get("normquery_stats", 0),
            "normquery_stats_daily": v1_result.get("normquery_stats_daily", 0),
            "completed": finalize_result.get("completed", False),
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Выгрузка статистики по поисковым кластерам (normquery stats v0/v1)")
    parser.add_argument("--from", dest="from_date", metavar="DATE", help="Начало периода (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", metavar="DATE", help="Конец периода (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Период в днях от сегодня (если не заданы --from/--to)")
    args = parser.parse_args()
    period_from = date.fromisoformat(args.from_date) if args.from_date else None
    period_to = date.fromisoformat(args.to_date) if args.to_date else None
    fetcher = NormqueryStatsFetcher()
    fetcher.run(period_from=period_from, period_to=period_to, days=args.days)


if __name__ == "__main__":
    main()
