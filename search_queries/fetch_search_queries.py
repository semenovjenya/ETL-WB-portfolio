"""Выгрузка поисковых запросов WB по разделу search-report."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

import requests

from config import Config
from database import SearchQueriesDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class RequestPolicy:
    request_interval_sec: float
    requests_per_minute: int
    retry_count: int
    retry_delay: int
    retry_delay_429: int


class RateLimitExceeded(RuntimeError):
    """WB API rate limit was reached before the request could be completed."""


def resolve_snapshot_hour(snapshot_hour: Optional[datetime]) -> datetime:
    if snapshot_hour is None:
        snapshot_hour = datetime.now(MOSCOW_TZ)
    elif snapshot_hour.tzinfo is None:
        snapshot_hour = snapshot_hour.replace(tzinfo=MOSCOW_TZ)
    return snapshot_hour.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


def chunked(values: list[Any], size: int) -> Iterable[list[Any]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def metric_value(metric: Any, key: str) -> Any:
    if isinstance(metric, dict):
        return metric.get(key)
    return None


class SearchQueriesFetcher:
    """Клиент WB search-report с сохранением в JSON и PostgreSQL."""

    def __init__(self):
        Config.validate()
        self.db = SearchQueriesDatabase()
        self.session = requests.Session()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
        self._last_request_times: list[float] = []

    def _get_headers(self) -> dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        return {"Authorization": token, "Content-Type": "application/json"}

    def _request_policy(self, method_name: str) -> RequestPolicy:
        if method_name == "search_texts":
            return RequestPolicy(
                request_interval_sec=Config.SEARCH_TEXTS_REQUEST_INTERVAL_SEC,
                requests_per_minute=Config.SEARCH_TEXTS_REQUESTS_PER_MINUTE,
                retry_count=Config.SEARCH_TEXTS_RETRY_COUNT,
                retry_delay=Config.SEARCH_TEXTS_RETRY_DELAY,
                retry_delay_429=Config.SEARCH_TEXTS_RETRY_DELAY_429,
            )
        if method_name == "orders":
            return RequestPolicy(
                request_interval_sec=Config.ORDERS_REQUEST_INTERVAL_SEC,
                requests_per_minute=Config.ORDERS_REQUESTS_PER_MINUTE,
                retry_count=Config.ORDERS_RETRY_COUNT,
                retry_delay=Config.ORDERS_RETRY_DELAY,
                retry_delay_429=Config.ORDERS_RETRY_DELAY_429,
            )
        return RequestPolicy(
            request_interval_sec=Config.REQUEST_INTERVAL_SEC,
            requests_per_minute=Config.REQUESTS_PER_MINUTE,
            retry_count=Config.RETRY_COUNT,
            retry_delay=Config.RETRY_DELAY,
            retry_delay_429=Config.RETRY_DELAY_429,
        )

    def _wait_rate_limit(self, method_name: str) -> None:
        policy = self._request_policy(method_name)
        now = time.monotonic()
        interval = policy.request_interval_sec
        per_minute = policy.requests_per_minute
        if len(self._last_request_times) >= per_minute:
            wait_sliding = 60.0 - (now - self._last_request_times[0])
            if wait_sliding > 0:
                time.sleep(wait_sliding)
                now = time.monotonic()
        if self._last_request_times:
            wait_interval = interval - (now - self._last_request_times[-1])
            if wait_interval > 0:
                time.sleep(wait_interval)
                now = time.monotonic()
        self._last_request_times = (self._last_request_times + [now])[-per_minute:]

    @staticmethod
    def _request_context(
        *,
        endpoint: str,
        batch_index: int,
        offset_value: int | None,
        nm_id: int | None,
        top_order_by: str | None,
    ) -> str:
        parts = [f"endpoint={endpoint}", f"batch={batch_index}"]
        if offset_value is not None:
            parts.append(f"offset={offset_value}")
        if nm_id is not None:
            parts.append(f"nm_id={nm_id}")
        if top_order_by is not None:
            parts.append(f"top_order_by={top_order_by}")
        return ", ".join(parts)

    @staticmethod
    def _is_retryable_request_exception(exc: requests.exceptions.RequestException) -> bool:
        if isinstance(
            exc,
            (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.SSLError,
            ),
        ):
            return True
        if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
            return exc.response.status_code >= 500
        return False

    @staticmethod
    def _sleep_with_jitter(wait_seconds: float) -> float:
        jitter = random.uniform(0, max(Config.RETRY_JITTER_SEC, 0))
        actual_wait = wait_seconds + jitter
        time.sleep(actual_wait)
        return actual_wait

    def _periods(self, snapshot_hour: datetime) -> dict[str, date]:
        current_end = snapshot_hour.date() - timedelta(days=1)
        current_start = current_end - timedelta(days=Config.SEARCH_PERIOD_DAYS - 1)
        past_end = current_start - timedelta(days=1)
        past_start = past_end - timedelta(days=Config.SEARCH_PERIOD_DAYS - 1)
        return {
            "current_start": current_start,
            "current_end": current_end,
            "past_start": past_start,
            "past_end": past_end,
        }

    def _request_key(self, method_name: str, endpoint: str, payload: dict[str, Any]) -> str:
        basis = {"method_name": method_name, "endpoint": endpoint, "payload": payload}
        raw = json.dumps(basis, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _save_json(
        self,
        *,
        method_name: str,
        snapshot_hour: datetime,
        batch_index: int,
        request_key: str,
        payload: dict[str, Any],
        response: dict[str, Any],
        suffix: str = "",
    ) -> None:
        ts = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d_%H-%M-%S")
        safe_suffix = f"_{suffix}" if suffix else ""
        filename = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"search_{method_name}_{snapshot_hour.strftime('%Y-%m-%d_%H')}_b{batch_index}{safe_suffix}_{ts}.json",
        )
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "request_key": request_key,
                    "snapshot_hour": snapshot_hour.isoformat(),
                    "method_name": method_name,
                    "payload": payload,
                    "response": response,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )

    def _post_json(
        self,
        *,
        method_name: str,
        endpoint: str,
        payload: dict[str, Any],
        snapshot_hour: datetime,
        batch_index: int,
        offset_value: int | None = None,
        nm_id: int | None = None,
        top_order_by: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        url = f"{Config.WB_API_BASE_URL}{endpoint}"
        request_key = self._request_key(method_name, endpoint, payload)
        response_data: dict[str, Any] | None = None
        policy = self._request_policy(method_name)
        context = self._request_context(
            endpoint=endpoint,
            batch_index=batch_index,
            offset_value=offset_value,
            nm_id=nm_id,
            top_order_by=top_order_by,
        )
        for attempt in range(policy.retry_count):
            try:
                self._wait_rate_limit(method_name)
                resp = self.session.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                    timeout=Config.REQUEST_TIMEOUT,
                )
                if resp.status_code == 429:
                    if Config.STOP_ON_429:
                        raise RateLimitExceeded(f"{method_name}: 429 Too Many Requests ({context})")
                    wait = max(policy.retry_delay_429, (attempt + 1) * policy.retry_delay * 2)
                    actual_wait = self._sleep_with_jitter(wait)
                    logger.warning(
                        "%s: 429 Too Many Requests (%s), попытка %s/%s, ожидание %.1f сек...",
                        method_name,
                        context,
                        attempt + 1,
                        policy.retry_count,
                        actual_wait,
                    )
                    if attempt == policy.retry_count - 1:
                        raise RateLimitExceeded(f"{method_name}: 429 Too Many Requests ({context})")
                    continue
                resp.raise_for_status()
                response_data = resp.json()
                periods = self._periods(snapshot_hour)
                self.db.upsert_api_requests(
                    [
                        {
                            "request_key": request_key,
                            "snapshot_hour": snapshot_hour,
                            "method_name": method_name,
                            "endpoint": endpoint,
                            "batch_index": batch_index,
                            "offset_value": offset_value,
                            "limit_value": payload.get("limit"),
                            "current_period_start": periods["current_start"],
                            "current_period_end": periods["current_end"],
                            "past_period_start": periods["past_start"] if "pastPeriod" in payload else None,
                            "past_period_end": periods["past_end"] if "pastPeriod" in payload else None,
                            "nm_id": nm_id,
                            "top_order_by": top_order_by,
                            "position_cluster": payload.get("positionCluster"),
                            "include_substituted_skus": payload.get("includeSubstitutedSKUs"),
                            "include_search_texts": payload.get("includeSearchTexts"),
                            "request_payload": payload,
                            "response_payload": response_data,
                        }
                    ]
                )
                suffix = f"o{offset_value}" if offset_value is not None else f"nm{nm_id}" if nm_id else ""
                self._save_json(
                    method_name=method_name,
                    snapshot_hour=snapshot_hour,
                    batch_index=batch_index,
                    request_key=request_key,
                    payload=payload,
                    response=response_data,
                    suffix=suffix,
                )
                return request_key, response_data
            except requests.exceptions.RequestException as exc:
                retryable = self._is_retryable_request_exception(exc)
                if attempt == policy.retry_count - 1 or not retryable:
                    logger.warning(
                        "%s: попытка %s/%s не удалась без дальнейших ретраев (%s): %s",
                        method_name,
                        attempt + 1,
                        policy.retry_count,
                        context,
                        exc,
                    )
                    raise
                wait = max(policy.retry_delay_429, (attempt + 1) * policy.retry_delay * 2)
                actual_wait = self._sleep_with_jitter(wait)
                logger.warning(
                    "%s: transient ошибка (%s), попытка %s/%s, ожидание %.1f сек... %s",
                    method_name,
                    context,
                    attempt + 1,
                    policy.retry_count,
                    actual_wait,
                    exc,
                )
        return request_key, response_data or {}

    def _base_period_payload(self, periods: dict[str, date]) -> dict[str, Any]:
        payload = {
            "currentPeriod": {
                "start": periods["current_start"].isoformat(),
                "end": periods["current_end"].isoformat(),
            },
            "pastPeriod": {
                "start": periods["past_start"].isoformat(),
                "end": periods["past_end"].isoformat(),
            },
        }
        return payload

    @staticmethod
    def _group_row(
        *,
        request_key: str,
        snapshot_hour: datetime,
        periods: dict[str, date],
        batch_index: int,
        offset_value: int,
        row_index: int,
        group: dict[str, Any],
        currency: Optional[str],
    ) -> dict[str, Any]:
        metrics = group.get("metrics") or {}
        return {
            "request_key": request_key,
            "snapshot_hour": snapshot_hour,
            "current_period_start": periods["current_start"],
            "current_period_end": periods["current_end"],
            "past_period_start": periods["past_start"],
            "past_period_end": periods["past_end"],
            "batch_index": batch_index,
            "offset_value": offset_value,
            "row_index": row_index,
            "subject_id": group.get("subjectId"),
            "subject_name": group.get("subjectName"),
            "brand_name": group.get("brandName"),
            "tag_id": group.get("tagId"),
            "tag_name": group.get("tagName"),
            "metric_avg_position_current": metric_value(metrics.get("avgPosition"), "current"),
            "metric_avg_position_dynamics": metric_value(metrics.get("avgPosition"), "dynamics"),
            "metric_open_card_current": metric_value(metrics.get("openCard"), "current"),
            "metric_open_card_dynamics": metric_value(metrics.get("openCard"), "dynamics"),
            "metric_add_to_cart_current": metric_value(metrics.get("addToCart"), "current"),
            "metric_add_to_cart_dynamics": metric_value(metrics.get("addToCart"), "dynamics"),
            "metric_open_to_cart_current": metric_value(metrics.get("openToCart"), "current"),
            "metric_open_to_cart_dynamics": metric_value(metrics.get("openToCart"), "dynamics"),
            "metric_orders_current": metric_value(metrics.get("orders"), "current"),
            "metric_orders_dynamics": metric_value(metrics.get("orders"), "dynamics"),
            "metric_cart_to_order_current": metric_value(metrics.get("cartToOrder"), "current"),
            "metric_cart_to_order_dynamics": metric_value(metrics.get("cartToOrder"), "dynamics"),
            "metric_visibility_current": metric_value(metrics.get("visibility"), "current"),
            "metric_visibility_dynamics": metric_value(metrics.get("visibility"), "dynamics"),
            "currency": currency,
            "api_response": group,
        }

    @staticmethod
    def _detail_row(
        *,
        request_key: str,
        snapshot_hour: datetime,
        periods: dict[str, date],
        batch_index: int,
        offset_value: int,
        item: dict[str, Any],
        currency: Optional[str],
    ) -> dict[str, Any]:
        return {
            "request_key": request_key,
            "snapshot_hour": snapshot_hour,
            "current_period_start": periods["current_start"],
            "current_period_end": periods["current_end"],
            "past_period_start": periods["past_start"],
            "past_period_end": periods["past_end"],
            "batch_index": batch_index,
            "offset_value": offset_value,
            "nm_id": item.get("nmId"),
            "name": item.get("name"),
            "vendor_code": item.get("vendorCode"),
            "subject_name": item.get("subjectName"),
            "brand_name": item.get("brandName"),
            "main_photo": item.get("mainPhoto"),
            "is_advertised": item.get("isAdvertised"),
            "is_substituted_sku": item.get("isSubstitutedSKU"),
            "is_card_rated": item.get("isCardRated"),
            "rating": item.get("rating"),
            "feedback_rating": item.get("feedbackRating"),
            "min_price": (item.get("price") or {}).get("minPrice"),
            "max_price": (item.get("price") or {}).get("maxPrice"),
            "avg_position_current": metric_value(item.get("avgPosition"), "current"),
            "avg_position_dynamics": metric_value(item.get("avgPosition"), "dynamics"),
            "open_card_current": metric_value(item.get("openCard"), "current"),
            "open_card_dynamics": metric_value(item.get("openCard"), "dynamics"),
            "add_to_cart_current": metric_value(item.get("addToCart"), "current"),
            "add_to_cart_dynamics": metric_value(item.get("addToCart"), "dynamics"),
            "open_to_cart_current": metric_value(item.get("openToCart"), "current"),
            "open_to_cart_dynamics": metric_value(item.get("openToCart"), "dynamics"),
            "orders_current": metric_value(item.get("orders"), "current"),
            "orders_dynamics": metric_value(item.get("orders"), "dynamics"),
            "cart_to_order_current": metric_value(item.get("cartToOrder"), "current"),
            "cart_to_order_dynamics": metric_value(item.get("cartToOrder"), "dynamics"),
            "visibility_current": metric_value(item.get("visibility"), "current"),
            "visibility_dynamics": metric_value(item.get("visibility"), "dynamics"),
            "currency": currency,
            "api_response": item,
        }

    @staticmethod
    def _search_text_row(
        *,
        request_key: str,
        snapshot_hour: datetime,
        periods: dict[str, date],
        batch_index: int,
        top_order_by: str,
        item: dict[str, Any],
        currency: Optional[str],
    ) -> dict[str, Any]:
        return {
            "request_key": request_key,
            "snapshot_hour": snapshot_hour,
            "current_period_start": periods["current_start"],
            "current_period_end": periods["current_end"],
            "past_period_start": periods["past_start"],
            "past_period_end": periods["past_end"],
            "batch_index": batch_index,
            "top_order_by": top_order_by,
            "nm_id": item.get("nmId"),
            "text": item.get("text"),
            "subject_name": item.get("subjectName"),
            "brand_name": item.get("brandName"),
            "vendor_code": item.get("vendorCode"),
            "product_name": item.get("name"),
            "is_card_rated": item.get("isCardRated"),
            "rating": item.get("rating"),
            "feedback_rating": item.get("feedbackRating"),
            "min_price": (item.get("price") or {}).get("minPrice"),
            "max_price": (item.get("price") or {}).get("maxPrice"),
            "frequency_current": metric_value(item.get("frequency"), "current"),
            "frequency_dynamics": metric_value(item.get("frequency"), "dynamics"),
            "week_frequency": item.get("weekFrequency"),
            "median_position_current": metric_value(item.get("medianPosition"), "current"),
            "median_position_dynamics": metric_value(item.get("medianPosition"), "dynamics"),
            "avg_position_current": metric_value(item.get("avgPosition"), "current"),
            "avg_position_dynamics": metric_value(item.get("avgPosition"), "dynamics"),
            "open_card_current": metric_value(item.get("openCard"), "current"),
            "open_card_dynamics": metric_value(item.get("openCard"), "dynamics"),
            "open_card_percentile": metric_value(item.get("openCard"), "percentile"),
            "add_to_cart_current": metric_value(item.get("addToCart"), "current"),
            "add_to_cart_dynamics": metric_value(item.get("addToCart"), "dynamics"),
            "add_to_cart_percentile": metric_value(item.get("addToCart"), "percentile"),
            "open_to_cart_current": metric_value(item.get("openToCart"), "current"),
            "open_to_cart_dynamics": metric_value(item.get("openToCart"), "dynamics"),
            "open_to_cart_percentile": metric_value(item.get("openToCart"), "percentile"),
            "orders_current": metric_value(item.get("orders"), "current"),
            "orders_dynamics": metric_value(item.get("orders"), "dynamics"),
            "orders_percentile": metric_value(item.get("orders"), "percentile"),
            "cart_to_order_current": metric_value(item.get("cartToOrder"), "current"),
            "cart_to_order_dynamics": metric_value(item.get("cartToOrder"), "dynamics"),
            "cart_to_order_percentile": metric_value(item.get("cartToOrder"), "percentile"),
            "visibility_current": metric_value(item.get("visibility"), "current"),
            "visibility_dynamics": metric_value(item.get("visibility"), "dynamics"),
            "currency": currency,
            "api_response": item,
        }

    def _fetch_report(
        self,
        snapshot_hour: datetime,
        periods: dict[str, date],
        batch_index: int,
        nm_ids: list[int],
    ) -> tuple[int, list[int]]:
        total_groups = 0
        subject_ids: set[int] = set()
        offset_value = 0
        while True:
            payload = self._base_period_payload(periods)
            payload.update(
                {
                    "nmIds": nm_ids,
                    "positionCluster": Config.POSITION_CLUSTER,
                    "orderBy": {"field": Config.ORDER_BY_FIELD, "mode": Config.ORDER_BY_MODE},
                    "includeSubstitutedSKUs": Config.INCLUDE_SUBSTITUTED_SKUS,
                    "includeSearchTexts": Config.INCLUDE_SEARCH_TEXTS,
                    "limit": Config.REPORT_LIMIT,
                    "offset": offset_value,
                }
            )
            request_key, response = self._post_json(
                method_name="report",
                endpoint=Config.REPORT_ENDPOINT,
                payload=payload,
                snapshot_hour=snapshot_hour,
                batch_index=batch_index,
                offset_value=offset_value,
            )
            data = response.get("data") or {}
            groups = data.get("groups") or []
            currency = data.get("currency")
            if offset_value == 0:
                common_info = data.get("commonInfo") or {}
                position_info = data.get("positionInfo") or {}
                visibility_info = data.get("visibilityInfo") or {}
                self.db.upsert_report_overview(
                    [
                        {
                            "request_key": request_key,
                            "snapshot_hour": snapshot_hour,
                            "current_period_start": periods["current_start"],
                            "current_period_end": periods["current_end"],
                            "past_period_start": periods["past_start"],
                            "past_period_end": periods["past_end"],
                            "batch_index": batch_index,
                            "offset_value": offset_value,
                            "total_products": common_info.get("totalProducts"),
                            "supplier_rating_current": metric_value(common_info.get("supplierRating"), "current"),
                            "supplier_rating_dynamics": metric_value(common_info.get("supplierRating"), "dynamics"),
                            "advertised_products_current": metric_value(common_info.get("advertisedProducts"), "current"),
                            "advertised_products_dynamics": metric_value(common_info.get("advertisedProducts"), "dynamics"),
                            "position_average_current": metric_value(position_info.get("average"), "current"),
                            "position_average_dynamics": metric_value(position_info.get("average"), "dynamics"),
                            "position_median_current": metric_value(position_info.get("median"), "current"),
                            "position_median_dynamics": metric_value(position_info.get("median"), "dynamics"),
                            "cluster_first_hundred_current": metric_value((position_info.get("clusters") or {}).get("firstHundred"), "current"),
                            "cluster_first_hundred_dynamics": metric_value((position_info.get("clusters") or {}).get("firstHundred"), "dynamics"),
                            "cluster_second_hundred_current": metric_value((position_info.get("clusters") or {}).get("secondHundred"), "current"),
                            "cluster_second_hundred_dynamics": metric_value((position_info.get("clusters") or {}).get("secondHundred"), "dynamics"),
                            "cluster_below_current": metric_value((position_info.get("clusters") or {}).get("below"), "current"),
                            "cluster_below_dynamics": metric_value((position_info.get("clusters") or {}).get("below"), "dynamics"),
                            "visibility_current": metric_value(visibility_info.get("visibility"), "current"),
                            "visibility_dynamics": metric_value(visibility_info.get("visibility"), "dynamics"),
                            "open_card_current": metric_value(visibility_info.get("openCard"), "current"),
                            "open_card_dynamics": metric_value(visibility_info.get("openCard"), "dynamics"),
                            "currency": currency,
                            "api_response": data,
                        }
                    ]
                )
            self.db.upsert_report_groups(
                [
                    self._group_row(
                        request_key=request_key,
                        snapshot_hour=snapshot_hour,
                        periods=periods,
                        batch_index=batch_index,
                        offset_value=offset_value,
                        row_index=offset_value + row_no,
                        group=group,
                        currency=currency,
                    )
                    for row_no, group in enumerate(groups)
                ]
            )
            total_groups += len(groups)
            for group in groups:
                subject_id = group.get("subjectId")
                if subject_id is not None:
                    subject_ids.add(int(subject_id))
            if len(groups) < Config.REPORT_LIMIT:
                break
            offset_value += Config.REPORT_LIMIT
        return total_groups, sorted(subject_ids)

    def _fetch_details(self, snapshot_hour: datetime, periods: dict[str, date], batch_index: int, nm_ids: list[int]) -> tuple[int, list[int]]:
        total_products = 0
        subject_ids: set[int] = set()
        offset_value = 0
        while True:
            payload = self._base_period_payload(periods)
            payload.update(
                {
                    "nmIds": nm_ids,
                    "orderBy": {"field": Config.ORDER_BY_FIELD, "mode": Config.ORDER_BY_MODE},
                    "positionCluster": Config.POSITION_CLUSTER,
                    "includeSubstitutedSKUs": Config.INCLUDE_SUBSTITUTED_SKUS,
                    "includeSearchTexts": Config.INCLUDE_SEARCH_TEXTS,
                    "limit": Config.DETAILS_LIMIT,
                    "offset": offset_value,
                }
            )
            request_key, response = self._post_json(
                method_name="details",
                endpoint=Config.DETAILS_ENDPOINT,
                payload=payload,
                snapshot_hour=snapshot_hour,
                batch_index=batch_index,
                offset_value=offset_value,
            )
            data = response.get("data") or {}
            products = data.get("products") or []
            currency = data.get("currency")
            rows = []
            for item in products:
                row = self._detail_row(
                    request_key=request_key,
                    snapshot_hour=snapshot_hour,
                    periods=periods,
                    batch_index=batch_index,
                    offset_value=offset_value,
                    item=item,
                    currency=currency,
                )
                rows.append(row)
            self.db.upsert_details(rows)
            total_products += len(rows)
            for item in products:
                value = item.get("subjectId")
                if value is not None:
                    subject_ids.add(int(value))
            if len(products) < Config.DETAILS_LIMIT:
                break
            offset_value += Config.DETAILS_LIMIT
        return total_products, sorted(subject_ids)

    def _fetch_groups(
        self,
        snapshot_hour: datetime,
        periods: dict[str, date],
        batch_index: int,
        nm_ids: list[int],
        subject_ids: list[int],
    ) -> int:
        total_groups = 0
        offset_value = 0
        while True:
            payload = self._base_period_payload(periods)
            payload.update(
                {
                    "nmIds": nm_ids,
                    "orderBy": {"field": Config.ORDER_BY_FIELD, "mode": Config.ORDER_BY_MODE},
                    "positionCluster": Config.POSITION_CLUSTER,
                    "includeSubstitutedSKUs": Config.INCLUDE_SUBSTITUTED_SKUS,
                    "includeSearchTexts": Config.INCLUDE_SEARCH_TEXTS,
                    "limit": Config.GROUPS_LIMIT,
                    "offset": offset_value,
                }
            )
            if subject_ids:
                payload["subjectIds"] = subject_ids
            request_key, response = self._post_json(
                method_name="groups",
                endpoint=Config.GROUPS_ENDPOINT,
                payload=payload,
                snapshot_hour=snapshot_hour,
                batch_index=batch_index,
                offset_value=offset_value,
            )
            data = response.get("data") or {}
            groups = data.get("groups") or []
            currency = data.get("currency")
            self.db.upsert_groups(
                [
                    self._group_row(
                        request_key=request_key,
                        snapshot_hour=snapshot_hour,
                        periods=periods,
                        batch_index=batch_index,
                        offset_value=offset_value,
                        row_index=offset_value + row_no,
                        group=group,
                        currency=currency,
                    )
                    for row_no, group in enumerate(groups)
                ]
            )
            total_groups += len(groups)
            if len(groups) < Config.GROUPS_LIMIT:
                break
            offset_value += Config.GROUPS_LIMIT
        return total_groups

    def _fetch_search_texts(
        self,
        snapshot_hour: datetime,
        periods: dict[str, date],
        batch_index: int,
        nm_ids: list[int],
        top_order_by_values: Optional[Iterable[str]] = None,
    ) -> tuple[int, dict[int, set[str]]]:
        total_rows = 0
        texts_by_nm: dict[int, set[str]] = {}
        for top_order_by in top_order_by_values or Config.TOP_ORDER_BY_VALUES:
            payload = self._base_period_payload(periods)
            payload.update(
                {
                    "nmIds": nm_ids,
                    "topOrderBy": top_order_by,
                    "includeSubstitutedSKUs": Config.INCLUDE_SUBSTITUTED_SKUS,
                    "includeSearchTexts": Config.INCLUDE_SEARCH_TEXTS,
                    "orderBy": {"field": Config.ORDER_BY_FIELD, "mode": Config.ORDER_BY_MODE},
                    "limit": Config.SEARCH_TEXTS_LIMIT,
                }
            )
            request_key, response = self._post_json(
                method_name="search_texts",
                endpoint=Config.SEARCH_TEXTS_ENDPOINT,
                payload=payload,
                snapshot_hour=snapshot_hour,
                batch_index=batch_index,
                top_order_by=top_order_by,
            )
            data = response.get("data") or {}
            items = data.get("items") or []
            currency = data.get("currency")
            rows = []
            for item in items:
                row = self._search_text_row(
                    request_key=request_key,
                    snapshot_hour=snapshot_hour,
                    periods=periods,
                    batch_index=batch_index,
                    top_order_by=top_order_by,
                    item=item,
                    currency=currency,
                )
                rows.append(row)
                nm_id = row.get("nm_id")
                text = row.get("text")
                if nm_id and text:
                    texts_by_nm.setdefault(int(nm_id), set()).add(str(text))
            self.db.upsert_search_texts(rows)
            total_rows += len(rows)
        return total_rows, texts_by_nm

    def _fetch_orders_for_nm(
        self,
        snapshot_hour: datetime,
        periods: dict[str, date],
        batch_index: int,
        nm_id: int,
        search_texts: list[str],
    ) -> tuple[int, int]:
        total_total_rows = 0
        total_text_rows = 0
        for text_chunk in chunked(search_texts, Config.ORDERS_TEXTS_CHUNK_SIZE):
            payload = {
                "period": {
                    "start": periods["current_start"].isoformat(),
                    "end": periods["current_end"].isoformat(),
                },
                "nmId": nm_id,
                "searchTexts": text_chunk,
            }
            request_key, response = self._post_json(
                method_name="orders",
                endpoint=Config.ORDERS_ENDPOINT,
                payload=payload,
                snapshot_hour=snapshot_hour,
                batch_index=batch_index,
                nm_id=nm_id,
            )
            data = response.get("data") or {}
            total_rows = []
            for item in data.get("total") or []:
                total_rows.append(
                    {
                        "snapshot_hour": snapshot_hour,
                        "current_period_start": periods["current_start"],
                        "current_period_end": periods["current_end"],
                        "nm_id": nm_id,
                        "dt": item.get("dt"),
                        "avg_position": item.get("avgPosition"),
                        "orders_count": item.get("orders"),
                        "api_response": item,
                    }
                )
            text_rows = []
            for item in data.get("items") or []:
                for date_item in item.get("dateItems") or []:
                    text_rows.append(
                        {
                            "request_key": request_key,
                            "snapshot_hour": snapshot_hour,
                            "current_period_start": periods["current_start"],
                            "current_period_end": periods["current_end"],
                            "nm_id": nm_id,
                            "text": item.get("text"),
                            "frequency": item.get("frequency"),
                            "dt": date_item.get("dt"),
                            "avg_position": date_item.get("avgPosition"),
                            "orders_count": date_item.get("orders"),
                            "api_response": {"text": item.get("text"), "date_item": date_item},
                        }
                    )
            self.db.upsert_orders_totals(total_rows)
            self.db.upsert_orders_text_daily(text_rows)
            total_total_rows += len(total_rows)
            total_text_rows += len(text_rows)
        return total_total_rows, total_text_rows

    def _connect_db(self) -> None:
        self.db.connect()
        self.db.create_tables()

    def _get_active_nm_ids(self) -> list[int]:
        return self.db.get_active_nm_ids(
            days=Config.ACTIVE_NM_LOOKBACK_DAYS,
            limit=Config.MAX_ACTIVE_NM_IDS,
        )

    def _log_periods(self, periods: dict[str, date]) -> None:
        logger.info(
            "search_queries: текущий период %s - %s, период сравнения %s - %s",
            periods["current_start"],
            periods["current_end"],
            periods["past_start"],
            periods["past_end"],
        )

    def prepare(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        periods = self._periods(snapshot_hour)
        self._log_periods(periods)

        self._connect_db()
        try:
            active_nm_ids = self._get_active_nm_ids()
            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "active_nm_ids": len(active_nm_ids),
                "current_period_start": periods["current_start"].isoformat(),
                "current_period_end": periods["current_end"].isoformat(),
                "past_period_start": periods["past_start"].isoformat(),
                "past_period_end": periods["past_end"].isoformat(),
            }
        finally:
            self.db.close()

    def run_report_stage(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        periods = self._periods(snapshot_hour)
        self._log_periods(periods)

        self._connect_db()
        try:
            active_nm_ids = self._get_active_nm_ids()
            if not active_nm_ids:
                logger.warning("Нет активных nm_id для этапа report")
                return {"snapshot_hour": snapshot_hour.isoformat(), "active_nm_ids": 0, "report_groups": 0}

            total_report_groups = 0
            all_subject_ids: set[int] = set()
            for batch_index, nm_batch in enumerate(chunked(active_nm_ids, Config.NM_IDS_BATCH_SIZE), start=1):
                logger.info("report: обработка батча %s, nm_ids=%s", batch_index, len(nm_batch))
                try:
                    report_groups_count, report_subject_ids = self._fetch_report(
                        snapshot_hour,
                        periods,
                        batch_index,
                        nm_batch,
                    )
                except RateLimitExceeded as exc:
                    logger.warning("report: лимит WB, остановка этапа с сохранением прогресса: %s", exc)
                    return {
                        "snapshot_hour": snapshot_hour.isoformat(),
                        "active_nm_ids": len(active_nm_ids),
                        "report_groups": total_report_groups,
                        "subject_ids": len(all_subject_ids),
                        "rate_limited": True,
                        "next_batch_index": batch_index,
                    }
                total_report_groups += report_groups_count
                all_subject_ids.update(report_subject_ids)

            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "active_nm_ids": len(active_nm_ids),
                "report_groups": total_report_groups,
                "subject_ids": len(all_subject_ids),
            }
        finally:
            self.db.close()

    def run_details_stage(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        periods = self._periods(snapshot_hour)
        self._log_periods(periods)

        self._connect_db()
        try:
            active_nm_ids = self._get_active_nm_ids()
            if not active_nm_ids:
                logger.warning("Нет активных nm_id для этапа details")
                return {"snapshot_hour": snapshot_hour.isoformat(), "active_nm_ids": 0, "details": 0}

            total_details = 0
            all_subject_ids: set[int] = set()
            for batch_index, nm_batch in enumerate(chunked(active_nm_ids, Config.NM_IDS_BATCH_SIZE), start=1):
                logger.info("details: обработка батча %s, nm_ids=%s", batch_index, len(nm_batch))
                try:
                    details_count, subject_ids = self._fetch_details(snapshot_hour, periods, batch_index, nm_batch)
                except RateLimitExceeded as exc:
                    logger.warning("details: лимит WB, остановка этапа с сохранением прогресса: %s", exc)
                    return {
                        "snapshot_hour": snapshot_hour.isoformat(),
                        "active_nm_ids": len(active_nm_ids),
                        "details": total_details,
                        "subject_ids": len(all_subject_ids),
                        "rate_limited": True,
                        "next_batch_index": batch_index,
                    }
                total_details += details_count
                all_subject_ids.update(subject_ids)

            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "active_nm_ids": len(active_nm_ids),
                "details": total_details,
                "subject_ids": len(all_subject_ids),
            }
        finally:
            self.db.close()

    def run_groups_stage(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        periods = self._periods(snapshot_hour)
        self._log_periods(periods)

        self._connect_db()
        try:
            active_nm_ids = self._get_active_nm_ids()
            if not active_nm_ids:
                logger.warning("Нет активных nm_id для этапа groups")
                return {"snapshot_hour": snapshot_hour.isoformat(), "active_nm_ids": 0, "groups": 0}

            subject_ids = self.db.get_report_subject_ids(
                snapshot_hour=snapshot_hour,
                current_period_start=periods["current_start"],
                current_period_end=periods["current_end"],
            )
            total_groups = 0
            for batch_index, nm_batch in enumerate(chunked(active_nm_ids, Config.NM_IDS_BATCH_SIZE), start=1):
                logger.info(
                    "groups: обработка батча %s, nm_ids=%s, subject_ids=%s",
                    batch_index,
                    len(nm_batch),
                    len(subject_ids),
                )
                try:
                    total_groups += self._fetch_groups(snapshot_hour, periods, batch_index, nm_batch, subject_ids)
                except RateLimitExceeded as exc:
                    logger.warning("groups: лимит WB, остановка этапа с сохранением прогресса: %s", exc)
                    return {
                        "snapshot_hour": snapshot_hour.isoformat(),
                        "active_nm_ids": len(active_nm_ids),
                        "groups": total_groups,
                        "subject_ids": len(subject_ids),
                        "rate_limited": True,
                        "next_batch_index": batch_index,
                    }

            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "active_nm_ids": len(active_nm_ids),
                "groups": total_groups,
                "subject_ids": len(subject_ids),
            }
        finally:
            self.db.close()

    def run_search_texts_stage(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        periods = self._periods(snapshot_hour)
        self._log_periods(periods)

        self._connect_db()
        try:
            active_nm_ids = self._get_active_nm_ids()
            if not active_nm_ids:
                logger.warning("Нет активных nm_id для этапа search_texts")
                return {"snapshot_hour": snapshot_hour.isoformat(), "active_nm_ids": 0, "search_texts": 0}

            total_rows = 0
            texts_by_nm: dict[int, set[str]] = {}
            for batch_index, nm_batch in enumerate(chunked(active_nm_ids, Config.SEARCH_TEXTS_NM_IDS_BATCH_SIZE), start=1):
                logger.info("search_texts: обработка батча %s, nm_ids=%s", batch_index, len(nm_batch))
                try:
                    search_text_count, batch_texts = self._fetch_search_texts(snapshot_hour, periods, batch_index, nm_batch)
                except RateLimitExceeded as exc:
                    logger.warning("search_texts: лимит WB, остановка этапа с сохранением прогресса: %s", exc)
                    return {
                        "snapshot_hour": snapshot_hour.isoformat(),
                        "active_nm_ids": len(active_nm_ids),
                        "search_texts": total_rows,
                        "nm_with_texts": len(texts_by_nm),
                        "unique_texts": sum(len(texts) for texts in texts_by_nm.values()),
                        "rate_limited": True,
                        "next_batch_index": batch_index,
                    }
                total_rows += search_text_count
                for nm_id, texts in batch_texts.items():
                    texts_by_nm.setdefault(nm_id, set()).update(texts)

            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "active_nm_ids": len(active_nm_ids),
                "search_texts": total_rows,
                "nm_with_texts": len(texts_by_nm),
                "unique_texts": sum(len(texts) for texts in texts_by_nm.values()),
            }
        finally:
            self.db.close()

    def run_order_search_texts_stage(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        periods = self._periods(snapshot_hour)
        self._log_periods(periods)

        self._connect_db()
        try:
            active_nm_ids = self._get_active_nm_ids()
            if not active_nm_ids:
                logger.warning("Нет активных nm_id для этапа order_search_texts")
                return {"snapshot_hour": snapshot_hour.isoformat(), "active_nm_ids": 0, "order_search_texts": 0}

            total_rows = 0
            texts_by_nm: dict[int, set[str]] = {}
            top_order_by_values = Config.ORDER_SEARCH_TEXT_TOP_ORDER_BY_VALUES
            completed_nm_ids = self.db.get_search_text_nm_ids_for_top_order_by(
                snapshot_hour=snapshot_hour,
                current_period_start=periods["current_start"],
                current_period_end=periods["current_end"],
                top_order_by_values=top_order_by_values,
            )
            requested_batches = 0
            skipped_nm_ids = 0
            for batch_index, nm_batch in enumerate(chunked(active_nm_ids, Config.SEARCH_TEXTS_NM_IDS_BATCH_SIZE), start=1):
                pending_nm_batch = [nm_id for nm_id in nm_batch if nm_id not in completed_nm_ids]
                skipped_nm_ids += len(nm_batch) - len(pending_nm_batch)
                if not pending_nm_batch:
                    logger.info("order_search_texts: батч %s уже загружен, nm_ids=%s", batch_index, len(nm_batch))
                    continue
                if Config.ORDER_SEARCH_TEXTS_MAX_BATCHES_PER_RUN > 0 and requested_batches >= Config.ORDER_SEARCH_TEXTS_MAX_BATCHES_PER_RUN:
                    break
                logger.info(
                    "order_search_texts: обработка батча %s, nm_ids=%s, top_order_by=%s",
                    batch_index,
                    len(pending_nm_batch),
                    ",".join(top_order_by_values),
                )
                try:
                    search_text_count, batch_texts = self._fetch_search_texts(
                        snapshot_hour,
                        periods,
                        batch_index,
                        pending_nm_batch,
                        top_order_by_values=top_order_by_values,
                    )
                except RateLimitExceeded as exc:
                    logger.warning("order_search_texts: лимит WB, остановка этапа с сохранением прогресса: %s", exc)
                    return {
                        "snapshot_hour": snapshot_hour.isoformat(),
                        "active_nm_ids": len(active_nm_ids),
                        "order_search_texts": total_rows,
                        "nm_with_texts": len(texts_by_nm),
                        "unique_texts": sum(len(texts) for texts in texts_by_nm.values()),
                        "top_order_by_values": top_order_by_values,
                        "rate_limited": True,
                        "next_batch_index": batch_index,
                        "requested_batches": requested_batches,
                        "skipped_nm_ids": skipped_nm_ids,
                    }
                requested_batches += 1
                total_rows += search_text_count
                for nm_id, texts in batch_texts.items():
                    texts_by_nm.setdefault(nm_id, set()).update(texts)

            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "active_nm_ids": len(active_nm_ids),
                "order_search_texts": total_rows,
                "nm_with_texts": len(texts_by_nm),
                "unique_texts": sum(len(texts) for texts in texts_by_nm.values()),
                "top_order_by_values": top_order_by_values,
                "requested_batches": requested_batches,
                "skipped_nm_ids": skipped_nm_ids,
            }
        finally:
            self.db.close()

    def run_orders_stage(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        periods = self._periods(snapshot_hour)
        self._log_periods(periods)

        self._connect_db()
        try:
            texts_by_nm = self.db.get_search_texts_for_orders(
                snapshot_hour=snapshot_hour,
                current_period_start=periods["current_start"],
                current_period_end=periods["current_end"],
            )
            if not texts_by_nm:
                logger.warning("Нет поисковых текстов для этапа orders")
                return {
                    "snapshot_hour": snapshot_hour.isoformat(),
                    "nm_with_texts": 0,
                    "orders_total_daily": 0,
                    "orders_text_daily": 0,
                }

            completed_texts_by_nm = self.db.get_completed_order_texts(
                snapshot_hour=snapshot_hour,
                current_period_start=periods["current_start"],
                current_period_end=periods["current_end"],
            )
            total_total_rows = 0
            total_text_rows = 0
            skipped_texts = 0
            skipped_nm_ids = 0
            requested_nm_ids = 0
            for batch_index, nm_id in enumerate(sorted(texts_by_nm), start=1):
                all_search_texts = sorted(set(texts_by_nm[nm_id]))
                completed_texts = completed_texts_by_nm.get(nm_id, set())
                search_texts = [text for text in all_search_texts if text not in completed_texts]
                skipped_texts += len(all_search_texts) - len(search_texts)
                if not search_texts:
                    skipped_nm_ids += 1
                    logger.info("orders: nm_id=%s уже загружен, search_texts=%s", nm_id, len(all_search_texts))
                    continue
                if Config.ORDERS_MAX_NM_PER_RUN > 0 and requested_nm_ids >= Config.ORDERS_MAX_NM_PER_RUN:
                    logger.info("orders: достигнут лимит nm_id за запуск: %s", Config.ORDERS_MAX_NM_PER_RUN)
                    break
                logger.info(
                    "orders: nm_id=%s, search_texts=%s, skipped_existing=%s",
                    nm_id,
                    len(search_texts),
                    len(all_search_texts) - len(search_texts),
                )
                try:
                    totals_count, text_count = self._fetch_orders_for_nm(
                        snapshot_hour=snapshot_hour,
                        periods=periods,
                        batch_index=batch_index,
                        nm_id=nm_id,
                        search_texts=search_texts,
                    )
                except RateLimitExceeded as exc:
                    logger.warning("orders: лимит WB, остановка этапа с сохранением прогресса: %s", exc)
                    return {
                        "snapshot_hour": snapshot_hour.isoformat(),
                        "nm_with_texts": len(texts_by_nm),
                        "orders_total_daily": total_total_rows,
                        "orders_text_daily": total_text_rows,
                        "skipped_nm_ids": skipped_nm_ids,
                        "skipped_order_texts": skipped_texts,
                        "requested_nm_ids": requested_nm_ids,
                        "rate_limited": True,
                        "next_nm_id": nm_id,
                    }
                requested_nm_ids += 1
                total_total_rows += totals_count
                total_text_rows += text_count

            return {
                "snapshot_hour": snapshot_hour.isoformat(),
                "nm_with_texts": len(texts_by_nm),
                "orders_total_daily": total_total_rows,
                "orders_text_daily": total_text_rows,
                "skipped_nm_ids": skipped_nm_ids,
                "skipped_order_texts": skipped_texts,
                "requested_nm_ids": requested_nm_ids,
            }
        finally:
            self.db.close()

    def validate_snapshot(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        self._connect_db()
        try:
            counts = self.db.get_snapshot_counts(snapshot_hour=snapshot_hour)
            counts["snapshot_hour"] = snapshot_hour.isoformat()
            return counts
        finally:
            self.db.close()

    def run(self, snapshot_hour: Optional[datetime] = None) -> dict[str, Any]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        prepared = self.prepare(snapshot_hour=snapshot_hour)
        if prepared.get("active_nm_ids", 0) == 0:
            return {"snapshot_hour": snapshot_hour.isoformat(), "active_nm_ids": 0}

        stats = {"snapshot_hour": snapshot_hour.isoformat(), "active_nm_ids": prepared["active_nm_ids"]}
        for method_name in (
            "run_order_search_texts_stage",
            "run_orders_stage",
            "run_report_stage",
            "run_details_stage",
            "run_groups_stage",
            "run_search_texts_stage",
        ):
            stats.update(getattr(self, method_name)(snapshot_hour=snapshot_hour))

        logger.info("Выгрузка поисковых запросов завершена: %s", stats)
        return stats


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Выгрузка поисковых запросов WB search-report")
    parser.add_argument(
        "--snapshot-hour",
        type=str,
        default=None,
        help="ISO timestamp для фиксированного часа среза, например 2026-03-20T12:00:00+03:00",
    )
    args = parser.parse_args()

    snapshot_hour = datetime.fromisoformat(args.snapshot_hour) if args.snapshot_hour else None
    result = SearchQueriesFetcher().run(snapshot_hour=snapshot_hour)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
