"""Выгрузка статистики и финансов маркетинга WB: upd, payments, balance, budget, fullstats."""
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


class MarketingStatsFetcher:
    """Затраты (upd), баланс, бюджет кампаний, полная статистика по кампаниям (fullstats)."""

    REQUEST_TIMEOUT = (10, 30)
    FULLSTATS_REQUEST_TIMEOUT = (10, 120)

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
        return Path(Config.STATS_PROGRESS_FILE)

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

    def _get(
        self,
        url: str,
        params: Optional[Dict] = None,
        interval: float = 0.2,
        timeout: Optional[tuple[float, float]] = None,
    ) -> Optional[Any]:
        for attempt in range(Config.RETRY_COUNT):
            try:
                r = requests.get(
                    url,
                    headers=self._get_headers(),
                    params=params,
                    timeout=timeout or self.REQUEST_TIMEOUT,
                )
                if r.status_code == 429:
                    rate_limit = extract_rate_limit_snapshot(r.headers)
                    wait = self._retry_wait_for_429(r, attempt)
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
                    if wait > Config.MAX_RATE_LIMIT_WAIT_SECONDS:
                        self.last_rate_limit = {
                            **(self.last_rate_limit or {}),
                            "deferred": True,
                            "token_mode": self.token_mode,
                        }
                        logger.warning(
                            "WB GET отложен: retry %.1f сек превышает лимит ожидания %.1f сек",
                            wait,
                            Config.MAX_RATE_LIMIT_WAIT_SECONDS,
                        )
                        return None
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                time.sleep(interval)
                if not r.content:
                    logger.warning(
                        "Пустой ответ WB GET %s params=%s attempt=%s/%s",
                        url,
                        params,
                        attempt + 1,
                        Config.RETRY_COUNT,
                    )
                    return None
                return r.json()
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
                    "Попытка %s/%s для WB GET %s params=%s: %s",
                    attempt + 1,
                    Config.RETRY_COUNT,
                    url,
                    params,
                    e,
                )
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
                    rate_limit = extract_rate_limit_snapshot(r.headers)
                    wait = self._retry_wait_for_429(r, attempt)
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
                r.raise_for_status()
                time.sleep(interval)
                if not r.content:
                    logger.warning(
                        "Пустой ответ WB POST %s body_keys=%s attempt=%s/%s",
                        url,
                        sorted(body.keys()),
                        attempt + 1,
                        Config.RETRY_COUNT,
                    )
                    return None
                return r.json()
            except ValueError as e:
                logger.warning(
                    "Невалидный JSON WB POST %s body_keys=%s attempt=%s/%s: %s",
                    url,
                    sorted(body.keys()),
                    attempt + 1,
                    Config.RETRY_COUNT,
                    e,
                )
                return None
            except requests.exceptions.RequestException as e:
                logger.warning(
                    "Попытка %s/%s для WB POST %s body_keys=%s: %s",
                    attempt + 1,
                    Config.RETRY_COUNT,
                    url,
                    sorted(body.keys()),
                    e,
                )
                self.last_rate_limit = None
                if attempt == Config.RETRY_COUNT - 1:
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def _get_promotion_campaign_ids(self) -> List[int]:
        """Fallback: ID рекламных кампаний поиска из API."""
        data = self._get(Config.PROMOTION_COUNT_URL, interval=Config.REQUEST_INTERVAL_PROMOTION)
        if not data or not isinstance(data, dict):
            return []
        ids = []
        for group in (data.get("adverts") or []):
            for item in (group.get("advert_list") or []):
                aid = item.get("advertId") or item.get("advert_id")
                if aid is not None:
                    ids.append(int(aid))
        return ids

    def fetch_upd(self, period_from: date, period_to: date) -> List[Dict[str, Any]]:
        """GET /adv/v1/upd — фактические затраты за период (макс. 31 день)."""
        data = self._get(
            Config.UPD_URL,
            params={"from": period_from.isoformat(), "to": period_to.isoformat()},
            interval=Config.REQUEST_INTERVAL_UPD,
        )
        if not isinstance(data, list):
            return []
        rows = []
        for r in data:
            upd_time = r.get("updTime")
            if isinstance(upd_time, str) and "T" in upd_time:
                try:
                    from datetime import datetime
                    upd_time = datetime.fromisoformat(upd_time.replace("Z", "+00:00"))
                except Exception:
                    pass
            rows.append({
                "advert_id": r.get("advertId"),
                "camp_name": r.get("campName"),
                "upd_sum": r.get("updSum", 0),
                "upd_time": upd_time,
                "advert_type": r.get("advertType"),
                "payment_type": r.get("paymentType"),
                "advert_status": r.get("advertStatus"),
            })
        return [x for x in rows if x.get("advert_id") is not None]

    def fetch_payments(self, period_from: date, period_to: date) -> List[Dict[str, Any]]:
        """GET /adv/v1/payments — история пополнений за период."""
        data = self._get(
            Config.PAYMENTS_URL,
            params={"from": period_from.isoformat(), "to": period_to.isoformat()},
            interval=Config.REQUEST_INTERVAL_PAYMENTS,
        )
        if not isinstance(data, list):
            return []
        rows = []
        for r in data:
            upd_time = r.get("date") or r.get("updTime")
            if isinstance(upd_time, str) and "T" in upd_time:
                try:
                    upd_time = datetime.fromisoformat(upd_time.replace("Z", "+00:00"))
                except Exception:
                    pass
            rows.append({
                "upd_num": r.get("id") or r.get("updNum"),
                "advert_id": r.get("advertId"),
                "camp_name": r.get("campName") or r.get("cardStatus"),
                "upd_sum": r.get("sum", 0),
                "upd_time": upd_time,
                "advert_type": r.get("type") or r.get("advertType"),
                "payment_type": r.get("paymentType"),
                "advert_status": r.get("statusId") or r.get("advertStatus"),
            })
        return [x for x in rows if x.get("upd_num") is not None]

    def fetch_balance(self) -> Optional[Dict[str, Any]]:
        """GET /adv/v1/balance."""
        return self._get(Config.BALANCE_URL, interval=Config.REQUEST_INTERVAL_BALANCE)

    def fetch_budget(self, advert_id: int) -> Optional[Dict[str, Any]]:
        """GET /adv/v1/budget?id=..."""
        return self._get(
            Config.BUDGET_URL,
            params={"id": advert_id},
            interval=Config.REQUEST_INTERVAL_BUDGET,
        )

    def fetch_fullstats(self, ids: List[int], begin: date, end: date) -> Optional[List[Dict[str, Any]]]:
        """GET /adv/v3/fullstats — макс. 50 id, макс. 31 день."""
        if not ids or len(ids) > 50:
            return None
        return self._get(
            Config.FULLSTATS_URL,
            params={
                "ids": ",".join(str(x) for x in ids),
                "beginDate": begin.isoformat(),
                "endDate": end.isoformat(),
            },
            interval=Config.REQUEST_INTERVAL_FULLSTATS,
            timeout=self.FULLSTATS_REQUEST_TIMEOUT,
        )

    def _resolve_promotion_campaign_ids(self, snapshot_date: date) -> List[int]:
        ids = self.db.get_campaign_ids(snapshot_date=snapshot_date, campaign_type="promotion")
        if ids:
            return ids
        return self._get_promotion_campaign_ids()

    def _resolve_fullstats_campaign_ids(
        self,
        *,
        period_from: date,
        period_to: date,
    ) -> List[int]:
        """Union current API campaigns with every locally known period member."""

        known_ids = self.db.get_campaign_ids_for_period(
            period_from=period_from,
            period_to=period_to,
            campaign_type="promotion",
        )
        current_ids = self._get_promotion_campaign_ids()
        return sorted({int(value) for value in [*known_ids, *current_ids]})

    def validate_snapshot(self, snapshot_hour: Optional[datetime] = None) -> Dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        self.db.connect()
        try:
            counts = self.db.get_snapshot_counts(snapshot_hour=snapshot_hour)
            counts["snapshot_hour"] = snapshot_hour.isoformat()
            return counts
        finally:
            self.db.close()

    def _period_bounds(self, snapshot_hour: datetime, days_back: int) -> tuple[date, date]:
        snapshot_date = snapshot_hour.date()
        period_to = snapshot_date
        bounded_days = max(1, min(int(days_back), 31))
        period_from = period_to - timedelta(days=bounded_days - 1)
        return period_from, period_to

    def _load_campaign_ids_for_stage(self, snapshot_hour: datetime) -> list[int]:
        state = self._load_progress(snapshot_hour)
        campaign_ids = [int(value) for value in state.get("campaign_ids") or []]
        if campaign_ids:
            return campaign_ids
        return self._resolve_promotion_campaign_ids(snapshot_hour.date())

    def fetch_balance_stage(self, snapshot_hour: Optional[datetime] = None) -> Dict[str, Any]:
        self.db.connect()
        try:
            self.db.create_tables()
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            campaign_ids = self._load_campaign_ids_for_stage(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            bal = self.fetch_balance()
            if bal and isinstance(bal, dict):
                self.db.upsert_balance(
                    float(bal.get("balance") or 0),
                    float(bal.get("net") or 0),
                    float(bal.get("bonus") or 0),
                    snapshot_date,
                    snapshot_hour,
                )
            self._save_progress(
                snapshot_hour,
                stage="fetch_balance",
                cursor=0,
                batch_size=1,
                total_items=len(campaign_ids),
                campaign_ids=campaign_ids,
                completed_substages=["fetch_balance"],
            )
            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "campaign_ids": len(campaign_ids),
                "balance_loaded": bool(bal),
            }
        finally:
            self.db.close()

    def fetch_upd_stage(self, days_back: int = 31, snapshot_hour: Optional[datetime] = None) -> Dict[str, Any]:
        self.db.connect()
        try:
            self.db.create_tables()
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            campaign_ids = self._load_campaign_ids_for_stage(snapshot_hour)
            period_from, period_to = self._period_bounds(snapshot_hour, days_back)
            upd_rows = self.fetch_upd(period_from, period_to)
            upd_rows_count = 0
            if upd_rows:
                upd_rows_count = self.db.upsert_upd(upd_rows, period_from, period_to)
            state = self._load_progress(snapshot_hour)
            completed_substages = list(state.get("completed_substages") or [])
            if "fetch_balance" not in completed_substages:
                completed_substages.append("fetch_balance")
            completed_substages.append("fetch_upd")
            self._save_progress(
                snapshot_hour,
                stage="fetch_upd",
                cursor=0,
                batch_size=1,
                total_items=len(campaign_ids),
                campaign_ids=campaign_ids,
                completed_substages=completed_substages,
            )
            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "period_from": period_from.isoformat(),
                "period_to": period_to.isoformat(),
                "upd_rows": upd_rows_count,
            }
        finally:
            self.db.close()

    def fetch_payments_stage(self, days_back: int = 31, snapshot_hour: Optional[datetime] = None) -> Dict[str, Any]:
        self.db.connect()
        try:
            self.db.create_tables()
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            campaign_ids = self._load_campaign_ids_for_stage(snapshot_hour)
            period_from, period_to = self._period_bounds(snapshot_hour, days_back)
            payments_rows = self.fetch_payments(period_from, period_to)
            payments_rows_count = 0
            if payments_rows:
                payments_rows_count = self.db.upsert_payments(payments_rows, period_from, period_to)
            state = self._load_progress(snapshot_hour)
            completed_substages = list(state.get("completed_substages") or [])
            for item in ("fetch_balance", "fetch_upd"):
                if item not in completed_substages:
                    completed_substages.append(item)
            completed_substages.append("fetch_payments")
            self._save_progress(
                snapshot_hour,
                stage="fetch_payments",
                cursor=0,
                batch_size=1,
                total_items=len(campaign_ids),
                campaign_ids=campaign_ids,
                completed_substages=completed_substages,
            )
            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "period_from": period_from.isoformat(),
                "period_to": period_to.isoformat(),
                "payments_rows": payments_rows_count,
            }
        finally:
            self.db.close()

    def fetch_budget_batches(self, snapshot_hour: Optional[datetime] = None) -> Dict[str, Any]:
        self.db.connect()
        try:
            self.db.create_tables()
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            state = self._load_progress(snapshot_hour)
            campaign_ids = [int(value) for value in state.get("campaign_ids") or []] or self._resolve_promotion_campaign_ids(snapshot_date)
            next_index = int(state.get("cursor") or 0)
            completed_substages = list(state.get("completed_substages") or [])
            for item in ("fetch_balance", "fetch_upd", "fetch_payments"):
                if item not in completed_substages:
                    completed_substages.append(item)
            budget_rows_count = 0
            for index in range(next_index, len(campaign_ids)):
                aid = campaign_ids[index]
                budget = self.fetch_budget(aid)
                if budget and isinstance(budget, dict):
                    budget_rows_count += self.db.upsert_budget(
                        [{
                            "advert_id": aid,
                            "cash": float(budget.get("cash") or 0),
                            "netting": float(budget.get("netting") or 0),
                            "total": float(budget.get("total") or 0),
                        }],
                        snapshot_date,
                        snapshot_hour,
                    )
                self._save_progress(
                    snapshot_hour,
                    stage="fetch_budget_batches",
                    cursor=index + 1,
                    batch_size=1,
                    total_items=len(campaign_ids),
                    campaign_ids=campaign_ids,
                    completed_substages=completed_substages,
                )
            completed_substages.append("fetch_budget_batches")
            self._save_progress(
                snapshot_hour,
                stage="fetch_budget_batches",
                cursor=len(campaign_ids),
                batch_size=1,
                total_items=len(campaign_ids),
                campaign_ids=campaign_ids,
                completed_substages=completed_substages,
            )
            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "campaign_ids": len(campaign_ids),
                "budget_rows": budget_rows_count,
            }
        finally:
            self.db.close()

    def fetch_fullstats_batches(self, days_back: int = 31, snapshot_hour: Optional[datetime] = None) -> Dict[str, Any]:
        self.db.connect()
        try:
            self.db.create_tables()
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            period_from, period_to = self._period_bounds(snapshot_hour, days_back)
            state = self._load_progress(snapshot_hour)
            state_campaign_ids = [
                int(value) for value in state.get("campaign_ids") or []
            ]
            if state.get("stage") == "fetch_fullstats_batches" and state_campaign_ids:
                # Resume the exact frozen list; re-sorting a changed list could
                # skip or duplicate batches after a crash.
                campaign_ids = state_campaign_ids
                next_cursor = int(state.get("cursor") or 0)
            else:
                campaign_ids = sorted(
                    {
                        *state_campaign_ids,
                        *self._resolve_fullstats_campaign_ids(
                            period_from=period_from,
                            period_to=period_to,
                        ),
                    }
                )
                # The shared progress cursor belongs to the preceding budget
                # stage. A new fullstats stage must always start from batch 0.
                next_cursor = 0
            batch_size = 50
            completed_substages = list(state.get("completed_substages") or [])
            for item in ("fetch_balance", "fetch_upd", "fetch_payments", "fetch_budget_batches"):
                if item not in completed_substages:
                    completed_substages.append(item)
            campaign_daily_count = 0
            campaign_daily_nms_count = 0
            for cursor in range(next_cursor, len(campaign_ids), batch_size):
                batch = campaign_ids[cursor : cursor + batch_size]
                data = self.fetch_fullstats(batch, period_from, period_to)
                if not isinstance(data, list):
                    self._save_progress(
                        snapshot_hour,
                        stage="fetch_fullstats_batches",
                        cursor=cursor,
                        batch_size=batch_size,
                        total_items=len(campaign_ids),
                        campaign_ids=campaign_ids,
                        completed_substages=completed_substages,
                    )
                    raise RuntimeError(f"Не удалось получить fullstats batch cursor={cursor}")
                all_daily = []
                all_daily_nms = []
                for camp in data:
                    advert_id = camp.get("advertId")
                    if advert_id is None:
                        continue
                    for day_block in (camp.get("days") or []):
                        d = day_block.get("date")
                        if isinstance(d, str):
                            stat_date = d[:10]
                        else:
                            continue
                        all_daily.append({
                            "stat_date": stat_date,
                            "advert_id": advert_id,
                            "views": day_block.get("views", 0),
                            "clicks": day_block.get("clicks", 0),
                            "ctr": day_block.get("ctr"),
                            "cpc": day_block.get("cpc"),
                            "orders": day_block.get("orders", 0),
                            "shks": day_block.get("shks", 0),
                            "sum_spend": day_block.get("sum", 0),
                            # WB fullstats attribution. Missing must remain
                            # NULL; only an explicit source zero proves zero
                            # attributed order revenue.
                            "sum_price": day_block.get("sum_price"),
                            "atbs": day_block.get("atbs", 0),
                            "canceled": day_block.get("canceled", 0),
                            "cr": day_block.get("cr"),
                        })
                        nm_agg = {}
                        for app in (day_block.get("apps") or []):
                            for nm in (app.get("nms") or []):
                                nm_id = nm.get("nmId") or nm.get("nm_id")
                                if nm_id is None:
                                    continue
                                key = (stat_date, advert_id, nm_id)
                                if key not in nm_agg:
                                    nm_agg[key] = {
                                        "stat_date": stat_date,
                                        "advert_id": advert_id,
                                        "nm_id": nm_id,
                                        "nm_name": nm.get("name"),
                                        "views": 0,
                                        "clicks": 0,
                                        "orders": 0,
                                        "shks": 0,
                                        "sum_spend": 0,
                                        "sum_price": 0.0,
                                        "_sum_price_complete": True,
                                        "atbs": 0,
                                        "canceled": 0,
                                    }
                                nm_agg[key]["views"] += int(nm.get("views") or 0)
                                nm_agg[key]["clicks"] += int(nm.get("clicks") or 0)
                                nm_agg[key]["orders"] += int(nm.get("orders") or 0)
                                nm_agg[key]["shks"] += int(nm.get("shks") or 0)
                                nm_agg[key]["sum_spend"] += float(nm.get("sum") or 0)
                                if nm.get("sum_price") is None:
                                    nm_agg[key]["_sum_price_complete"] = False
                                elif nm_agg[key]["_sum_price_complete"]:
                                    nm_agg[key]["sum_price"] += float(nm["sum_price"])
                                nm_agg[key]["atbs"] += int(nm.get("atbs") or 0)
                                nm_agg[key]["canceled"] += int(nm.get("canceled") or 0)
                        for row in nm_agg.values():
                            if not row.pop("_sum_price_complete"):
                                row["sum_price"] = None
                            all_daily_nms.append(row)
                if all_daily:
                    campaign_daily_count += self.db.upsert_campaign_stats_daily(all_daily)
                if all_daily_nms:
                    for row in all_daily_nms:
                        row["ctr"] = (float(row["clicks"]) / float(row["views"]) * 100) if row.get("views") else None
                        row["cpc"] = (float(row["sum_spend"]) / float(row["clicks"])) if row.get("clicks") else None
                        row["cr"] = (float(row["orders"]) / float(row["clicks"]) * 100) if row.get("clicks") else None
                    campaign_daily_nms_count += self.db.upsert_campaign_stats_daily_nms(all_daily_nms)
                self._save_progress(
                    snapshot_hour,
                    stage="fetch_fullstats_batches",
                    cursor=cursor + batch_size,
                    batch_size=batch_size,
                    total_items=len(campaign_ids),
                    campaign_ids=campaign_ids,
                    completed_substages=completed_substages,
                )
            completed_substages.append("fetch_fullstats_batches")
            self._save_progress(
                snapshot_hour,
                stage="fetch_fullstats_batches",
                cursor=len(campaign_ids),
                batch_size=batch_size,
                total_items=len(campaign_ids),
                campaign_ids=campaign_ids,
                completed_substages=completed_substages,
            )
            watermark_to = min(period_to, snapshot_date - timedelta(days=1))
            if campaign_ids and period_from <= watermark_to:
                self.db.mark_campaign_stats_daily_watermarks(
                    period_from=period_from,
                    period_to=watermark_to,
                    source_run_id=snapshot_hour.isoformat(),
                )
            else:
                logger.warning(
                    "fullstats watermark not written: campaign id set is empty"
                )
            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "snapshot_date": snapshot_date.isoformat(),
                "campaign_ids": len(campaign_ids),
                "campaign_stats_daily": campaign_daily_count,
                "campaign_stats_daily_nms": campaign_daily_nms_count,
            }
        finally:
            self.db.close()

    def finalize(self, snapshot_hour: Optional[datetime] = None) -> Dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        state = self._load_progress(snapshot_hour)
        campaign_ids = [int(value) for value in state.get("campaign_ids") or []]
        total_items = int(state.get("total_items") or len(campaign_ids))
        cursor = int(state.get("cursor") or 0)
        completed_substages = set(state.get("completed_substages") or [])
        required = {
            "fetch_balance",
            "fetch_upd",
            "fetch_payments",
            "fetch_budget_batches",
            "fetch_fullstats_batches",
        }
        if cursor < total_items or not required.issubset(completed_substages):
            raise RuntimeError(
                f"marketing stats not fully processed: cursor={cursor}, total={total_items}, completed={sorted(completed_substages)}"
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
        days_back: int = 31,
        fetch_balance_budget: bool = True,
        fetch_upd_flag: bool = True,
        fetch_fullstats_flag: bool = True,
        fetch_payments_flag: bool = True,
        snapshot_hour: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Выгрузка: баланс и бюджет (снимок), upd за последние days_back дней, fullstats по дням.
        """
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        balance_result = (
            self.fetch_balance_stage(snapshot_hour=snapshot_hour)
            if fetch_balance_budget
            else {"balance_loaded": False}
        )
        upd_result = (
            self.fetch_upd_stage(days_back=days_back, snapshot_hour=snapshot_hour)
            if fetch_upd_flag
            else {"upd_rows": 0}
        )
        payments_result = (
            self.fetch_payments_stage(days_back=days_back, snapshot_hour=snapshot_hour)
            if fetch_payments_flag
            else {"payments_rows": 0}
        )
        budget_result = (
            self.fetch_budget_batches(snapshot_hour=snapshot_hour)
            if fetch_balance_budget
            else {"budget_rows": 0, "campaign_ids": 0}
        )
        fullstats_result = (
            self.fetch_fullstats_batches(days_back=days_back, snapshot_hour=snapshot_hour)
            if fetch_fullstats_flag
            else {"campaign_stats_daily": 0, "campaign_stats_daily_nms": 0}
        )
        finalize_result = self.finalize(snapshot_hour=snapshot_hour)
        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_hour.date().isoformat(),
            "campaign_ids": budget_result.get("campaign_ids", 0),
            "balance_loaded": balance_result.get("balance_loaded", False),
            "budget_rows": budget_result.get("budget_rows", 0),
            "upd_rows": upd_result.get("upd_rows", 0),
            "payments_rows": payments_result.get("payments_rows", 0),
            "campaign_stats_daily": fullstats_result.get("campaign_stats_daily", 0),
            "campaign_stats_daily_nms": fullstats_result.get("campaign_stats_daily_nms", 0),
            "completed": finalize_result.get("completed", False),
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Выгрузка статистики и финансов маркетинга WB")
    parser.add_argument("--days", type=int, default=31, help="Период для upd/fullstats (дней, макс. 31)")
    parser.add_argument("--no-balance", action="store_true", help="Не выгружать баланс и бюджет")
    parser.add_argument("--no-upd", action="store_true", help="Не выгружать upd")
    parser.add_argument("--no-payments", action="store_true", help="Не выгружать payments")
    parser.add_argument("--no-fullstats", action="store_true", help="Не выгружать fullstats")
    args = parser.parse_args()
    fetcher = MarketingStatsFetcher()
    fetcher.run(
        days_back=args.days,
        fetch_balance_budget=not args.no_balance,
        fetch_upd_flag=not args.no_upd,
        fetch_payments_flag=not args.no_payments,
        fetch_fullstats_flag=not args.no_fullstats,
    )


if __name__ == "__main__":
    main()
