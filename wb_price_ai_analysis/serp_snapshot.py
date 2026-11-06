"""Canonical WB SERP snapshots and host-worker orchestration."""
from __future__ import annotations

import importlib
import argparse
import logging
import os
import re
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from statistics import median
from typing import Any, Callable, Dict, Iterable, List, Optional

from config import Config
from database import WBPriceAIAnalysisDatabase
from prepare_active_skus import collapse_source_rows

logger = logging.getLogger(__name__)

SPACE_RE = re.compile(r"\s+")
SERP_NAMESPACE = uuid.UUID("8fc6c634-5a31-4e35-98e8-580715186ca3")
QUERY_STOPWORDS = {
    "без", "для", "его", "ее", "её", "или", "как", "кожа", "кожи",
    "лицо", "лица", "мл", "на", "над", "под", "при", "средство",
    "тело", "тела", "товар", "это",
}


def normalize_query(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "").strip().lower())


def is_own_brand_query(value: Any, brands: Iterable[Any]) -> bool:
    query = normalize_query(value)
    for brand in brands:
        normalized_brand = normalize_query(brand)
        if normalized_brand and re.search(
            rf"(?<!\w){re.escape(normalized_brand)}(?!\w)",
            query,
        ):
            return True
    return False


def _meaningful_query_stems(value: Any) -> set[str]:
    tokens = re.findall(r"[a-zа-яё0-9]+", normalize_query(value))
    result: set[str] = set()
    for token in tokens:
        if token in QUERY_STOPWORDS or token.isdigit() or len(token) < 4:
            continue
        result.add(token[:6] if len(token) >= 7 else token[:4])
    return result


def is_query_relevant(value: Any, reference_texts: Iterable[Any]) -> bool:
    query_stems = _meaningful_query_stems(value)
    if not query_stems:
        return False
    reference_stems: set[str] = set()
    for text in reference_texts:
        reference_stems.update(_meaningful_query_stems(text))
    return bool(query_stems & reference_stems)


def deterministic_batch_id(tenant_id: str, observed_at: str) -> str:
    return str(uuid.uuid5(SERP_NAMESPACE, f"{tenant_id}:{observed_at}"))


def deterministic_run_id(batch_id: str, source_nm_id: int, query_normalized: str) -> str:
    return str(uuid.uuid5(uuid.UUID(batch_id), f"{int(source_nm_id)}:{query_normalized}"))


def _iso_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def prepare_serp_skus(
    observed_at: str,
    tenant_id: Optional[str] = None,
    source_nm_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    Config.validate_db()
    observed_iso = _iso_datetime(observed_at)
    batch_key = f"{tenant_id or os.getenv('TENANT_ID') or 'legacy-default'}:{observed_iso}"
    batch_id = deterministic_batch_id(tenant_id or os.getenv("TENANT_ID") or "legacy-default", observed_iso)
    run_date = datetime.fromisoformat(observed_iso).date()
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        payloads = collapse_source_rows(
            db.get_latest_source_rows(),
            run_date=run_date,
            require_price=False,
        )
    finally:
        db.close()
    allowed_nm_ids = {int(value) for value in source_nm_ids or []}
    if allowed_nm_ids:
        payloads = [payload for payload in payloads if int(payload["source_nm_id"]) in allowed_nm_ids]
    for payload in payloads:
        payload.update(
            {
                "batch_id": batch_id,
                "batch_key": batch_key,
                "observed_at": observed_iso,
                "region_dest": Config.WB_SERP_DEST,
                "currency": Config.WB_SERP_CURRENCY,
                "locale": Config.WB_SERP_LOCALE,
                "device": Config.WB_SERP_DEVICE,
                "requested_max_positions": Config.WB_SERP_MAX_POSITIONS,
            }
        )
    return payloads


def choose_queries(
    real_queries: Iterable[Dict[str, Any]],
    seo_keywords: Iterable[Any],
    *,
    limit: int = 5,
    excluded_brands: Iterable[Any] = (),
    excluded_queries: Iterable[Any] = (),
    relevance_texts: Iterable[Any] = (),
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    excluded = {normalize_query(value) for value in excluded_queries if normalize_query(value)}
    relevance_reference = [value for value in relevance_texts if value]
    for row in real_queries:
        normalized = normalize_query(row.get("query"))
        if (
            not normalized
            or normalized in seen
            or normalized in excluded
            or is_own_brand_query(normalized, excluded_brands)
            or (relevance_reference and not is_query_relevant(normalized, relevance_reference))
        ):
            continue
        orders = float(row.get("orders_7d") or 0)
        frequency = float(row.get("frequency") or 0)
        selected.append(
            {
                "query": str(row.get("query") or normalized).strip(),
                "query_normalized": normalized,
                "query_source": "orders" if orders > 0 else "frequency",
                "query_orders_7d": orders,
                "query_frequency": frequency,
            }
        )
        seen.add(normalized)
        if len(selected) >= limit:
            break
    seo_source = "seo" if selected else "seo_fallback_stale"
    for keyword in seo_keywords:
        if len(selected) >= limit:
            break
        normalized = normalize_query(keyword)
        if (
            not normalized
            or normalized in seen
            or normalized in excluded
            or is_own_brand_query(normalized, excluded_brands)
            or (relevance_reference and not is_query_relevant(normalized, relevance_reference))
        ):
            continue
        selected.append(
            {
                "query": str(keyword).strip(),
                "query_normalized": normalized,
                "query_source": seo_source,
                "query_orders_7d": 0.0,
                "query_frequency": 0.0,
            }
        )
        seen.add(normalized)
        if len(selected) >= limit:
            break
    for index, row in enumerate(selected, start=1):
        row["query_rank"] = index
    return selected


def local_seo_fallback(payload: Dict[str, Any]) -> List[str]:
    """Build deterministic phrases when the external SEO generator is unavailable."""
    title = str(payload.get("source_title") or "").strip()
    subject = str(payload.get("source_subject_name") or "").strip()
    return [
        value
        for value in (
            title,
            subject,
        )
        if value
    ]


def select_queries_per_sku(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(payload)
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        frozen = db.get_serp_query_set(int(payload["source_nm_id"]))
        if frozen:
            query_specs = list(frozen["query_specs"])
            result["query_specs"] = query_specs
            result["query_count"] = len(query_specs)
            result["real_query_count"] = sum(
                1 for row in query_specs if row.get("query_source") in {"orders", "frequency"}
            )
            result["seo_query_count"] = len(query_specs) - result["real_query_count"]
            result["query_set_mode"] = "frozen"
            result["query_set_frozen_at"] = frozen.get("created_at")
            result["query_set_source_batch_id"] = frozen.get("frozen_from_batch_id")
            return result
        real_queries = db.get_recent_real_queries(
            int(payload["source_nm_id"]),
            Config.WB_SERP_QUERY_MAX_AGE_DAYS,
        )
        cached_seo_keywords = db.get_latest_successful_seo_keywords(
            int(payload["source_nm_id"])
        )
    finally:
        db.close()

    selection_kwargs = {
        "limit": Config.WB_SERP_MAX_QUERIES_PER_SKU,
        "excluded_brands": [payload.get("source_brand"), *Config.WB_SERP_OWN_BRAND_ALIASES],
        "excluded_queries": [
            payload.get("source_nm_id"),
            payload.get("source_vendor_code"),
            payload.get("source_supplier_article"),
            *(payload.get("source_barcodes_json") or []),
        ],
        "relevance_texts": [payload.get("source_title"), payload.get("source_subject_name")],
    }
    real_selection = choose_queries(real_queries, [], **selection_kwargs)
    seo_keywords: List[str] = list(cached_seo_keywords)
    if len(real_selection) < Config.WB_SERP_MAX_QUERIES_PER_SKU and not seo_keywords:
        try:
            from generate_seo_keywords import run_one as generate_seo_keywords

            generated = generate_seo_keywords(dict(payload))
            if generated.get("seo_status") == "success":
                seo_keywords = list(generated.get("keywords_json") or [])
        except Exception as exc:
            logger.warning("SEO fallback failed for nm_id=%s: %s", payload.get("source_nm_id"), exc)
    query_specs = choose_queries(
        real_queries,
        [*seo_keywords, *local_seo_fallback(payload)],
        **selection_kwargs,
    )
    if not query_specs:
        result["query_specs"] = []
        result["query_count"] = 0
        result["real_query_count"] = 0
        result["seo_query_count"] = 0
        result["query_set_mode"] = "missing"
        return result

    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        stored = db.create_serp_query_set(
            int(payload["source_nm_id"]),
            query_specs,
            frozen_from_batch_id=payload.get("batch_id"),
            frozen_from_observed_at=payload.get("observed_at"),
        )
        query_specs = list(stored["query_specs"])
    finally:
        db.close()
    result["query_specs"] = query_specs
    result["query_count"] = len(query_specs)
    result["real_query_count"] = sum(1 for row in query_specs if row["query_source"] in {"orders", "frequency"})
    result["seo_query_count"] = len(query_specs) - result["real_query_count"]
    result["query_set_mode"] = "created"
    result["query_set_frozen_at"] = stored.get("created_at")
    result["query_set_source_batch_id"] = stored.get("frozen_from_batch_id")
    return result


def enqueue_and_wait_serp_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not payload.get("query_specs"):
        return {
            "batch_id": payload.get("batch_id"),
            "source_nm_id": payload.get("source_nm_id"),
            "status": "failed",
            "error": "No real or SEO queries available",
            "planned_runs": 0,
            "completed_runs": 0,
        }
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        job = db.enqueue_serp_job(payload)
        if job["status"] == "completed":
            return _downstream_payload(
                payload,
                job.get("result_json") or {"status": "completed"},
            )
        deadline = time.monotonic() + Config.WB_SERP_JOB_TIMEOUT_SEC
        while time.monotonic() < deadline:
            current = db.get_serp_job(payload["batch_id"], int(payload["source_nm_id"]))
            if current and current["status"] == "completed":
                return _downstream_payload(
                    payload,
                    current.get("result_json") or {"status": "completed"},
                )
            if current and current["status"] == "failed":
                return current.get("result_json") or {
                    "batch_id": payload["batch_id"],
                    "source_nm_id": payload["source_nm_id"],
                    "status": "failed",
                    "error": current.get("last_error"),
                }
            time.sleep(max(Config.WB_PRICE_AI_HOST_RUNNER_POLL_INTERVAL_SEC, 1.0))
        return {
            "batch_id": payload["batch_id"],
            "source_nm_id": payload["source_nm_id"],
            "status": "timeout",
            "error": f"SERP host job timed out after {Config.WB_SERP_JOB_TIMEOUT_SEC}s",
        }
    finally:
        db.close()


def _downstream_payload(payload: Dict[str, Any], worker_result: Dict[str, Any]) -> Dict[str, Any]:
    """Merge browser result with source data required by deterministic analysis stages."""
    query_specs = list(payload.get("query_specs") or [])
    status = str(worker_result.get("status") or "failed")
    result = {
        **payload,
        **worker_result,
        # The canonical business price comes from the seller prices report.
        # Browser observations are carried in explicit source_price_site_* fields.
        "source_price_regular": payload.get("source_price_regular"),
        "source_price_promo": payload.get("source_price_promo"),
        "source_price_site_display": payload.get("source_price_site_display"),
        "source_price_site_wallet": payload.get("source_price_site_wallet"),
        "source_price_site_effective": payload.get("source_price_site_effective"),
        "source_platform_discount_percent": payload.get("source_platform_discount_percent"),
        "source_wallet_discount_percent": payload.get("source_wallet_discount_percent"),
        "source_report_to_site_discount_percent": payload.get("source_report_to_site_discount_percent"),
        "keywords_json": [row.get("query") for row in query_specs if row.get("query")],
        "keyword_count": len(query_specs),
        "seo_status": "success",
        "seo_error": None,
        "seo_model": "frozen_serp_query_set",
        "raw_status": "success" if status in {"completed", "partial"} else "failed",
        "raw_error": worker_result.get("error"),
        "raw_rows_written": int(worker_result.get("compatibility_rows_written") or 0),
    }
    return result


def _float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


def _discount_percent(regular: Optional[float], effective: Optional[float]) -> Optional[float]:
    if regular is None or effective is None or regular <= 0:
        return None
    return round((regular - effective) * 100.0 / regular, 4)


def _source_site_price_context(
    report_price: Optional[float],
    display_prices: Iterable[float],
    wallet_prices: Iterable[float],
    effective_prices: Iterable[float],
) -> Dict[str, Optional[float]]:
    display_values = [float(value) for value in display_prices]
    wallet_values = [float(value) for value in wallet_prices]
    effective_values = [float(value) for value in effective_prices]
    site_display = float(median(display_values)) if display_values else None
    site_wallet = float(median(wallet_values)) if wallet_values else None
    site_effective = float(median(effective_values)) if effective_values else (site_wallet or site_display)
    return {
        "source_price_site_display": site_display,
        "source_price_site_wallet": site_wallet,
        "source_price_site_effective": site_effective,
        "source_platform_discount_percent": _discount_percent(report_price, site_display),
        "source_wallet_discount_percent": _discount_percent(site_display, site_wallet),
        "source_report_to_site_discount_percent": _discount_percent(report_price, site_effective),
    }


def _build_serp_item(
    occurrence: Dict[str, Any],
    *,
    run_id: str,
    source_nm_id: int,
    detail_product: Optional[Dict[str, Any]],
    wb_module: Any,
) -> Dict[str, Any]:
    detail_regular, detail_display = wb_module.WBCompetitorFetcher._extract_detail_prices(detail_product)
    regular = _float(occurrence.get("competitor_price_regular_search")) or _float(detail_regular)
    display = _float(occurrence.get("competitor_price_promo_search")) or _float(detail_display)
    wallet = _float(occurrence.get("competitor_price_wallet_search"))
    effective = wallet or display or regular
    basis = "wallet" if wallet is not None else "display" if display is not None else "regular" if regular is not None else None
    result_nm_id = int(occurrence["competitor_nm_id"])
    return {
        "run_id": run_id,
        "result_nm_id": result_nm_id,
        "is_source": result_nm_id == int(source_nm_id),
        "catalog_page": int(occurrence.get("catalog_page") or 1),
        "position_on_page": int(occurrence.get("catalog_position_on_page") or 1),
        "position_absolute": int(occurrence["catalog_position_absolute"]),
        "position_organic": occurrence.get("catalog_position_organic"),
        "placement_type": occurrence.get("placement_type") or "unknown",
        "placement_detection": occurrence.get("placement_detection"),
        "brand": (detail_product or {}).get("brand") or occurrence.get("competitor_brand"),
        "subject_name": (detail_product or {}).get("entity") or occurrence.get("competitor_subject_name"),
        "title": (detail_product or {}).get("name") or occurrence.get("competitor_title"),
        "product_url": wb_module.build_product_url(result_nm_id),
        "image_url": occurrence.get("competitor_main_photo_url"),
        "price_regular": regular,
        "price_display": display,
        "price_wallet": wallet,
        "price_effective": effective,
        "price_basis": basis,
        "discount_percent": _discount_percent(regular, effective),
        "promo_label": occurrence.get("competitor_promo_label"),
        "rating": _float((detail_product or {}).get("reviewRating") or occurrence.get("competitor_rating")),
        "feedbacks": int((detail_product or {}).get("feedbacks") or occurrence.get("competitor_feedbacks") or 0),
        "raw_payload": occurrence.get("search_payload_json") or {},
    }


def _build_run_row(
    payload: Dict[str, Any],
    spec: Dict[str, Any],
    metadata: Dict[str, Any],
    items: List[Dict[str, Any]],
    *,
    parser_status: str,
    parser_error: Optional[str] = None,
) -> Dict[str, Any]:
    run_id = deterministic_run_id(payload["batch_id"], int(payload["source_nm_id"]), spec["query_normalized"])
    return {
        "run_id": run_id,
        "batch_id": payload["batch_id"],
        "batch_key": payload["batch_key"],
        "observed_at": payload["observed_at"],
        "source_snapshot_date": payload.get("source_snapshot_date"),
        "source_nm_id": int(payload["source_nm_id"]),
        "source_title": payload.get("source_title"),
        "source_price_regular": payload.get("source_price_regular"),
        "source_price_display": payload.get("source_price_promo"),
        "query": spec["query"],
        "query_normalized": spec["query_normalized"],
        "query_source": spec["query_source"],
        "query_rank": int(spec["query_rank"]),
        "query_orders_7d": float(spec.get("query_orders_7d") or 0),
        "query_frequency": float(spec.get("query_frequency") or 0),
        "region_dest": payload.get("region_dest") or Config.WB_SERP_DEST,
        "currency": payload.get("currency") or Config.WB_SERP_CURRENCY,
        "locale": payload.get("locale") or Config.WB_SERP_LOCALE,
        "device": payload.get("device") or Config.WB_SERP_DEVICE,
        "browser_profile": Config.WB_PRICE_AI_COMPETITOR_BROWSER_PROFILE_DIR,
        "requested_max_positions": int(payload.get("requested_max_positions") or Config.WB_SERP_MAX_POSITIONS),
        "pages_scanned": int(metadata.get("pages_scanned") or 0),
        "max_position_scanned": int(metadata.get("max_position_scanned") or 0),
        "organic_positions_scanned": int(metadata.get("organic_positions_scanned") or 0),
        "source_found_any": bool(metadata.get("source_found_any")),
        "source_found_organic": bool(metadata.get("source_found_organic")),
        "source_found_sponsored": bool(metadata.get("source_found_sponsored")),
        "source_position_absolute": metadata.get("source_position_absolute"),
        "source_position_organic": metadata.get("source_position_organic"),
        "source_position_organic_absolute": metadata.get("source_position_organic_absolute"),
        "source_position_sponsored": metadata.get("source_position_sponsored"),
        "complete_until_source": bool(metadata.get("complete_until_source")),
        "hit_position_limit": bool(metadata.get("hit_position_limit")),
        "result_count": len(items),
        "sponsored_count": sum(item["placement_type"] == "sponsored" for item in items),
        "organic_count": sum(item["placement_type"] == "organic" for item in items),
        "unknown_placement_count": sum(item["placement_type"] == "unknown" for item in items),
        "parser_status": parser_status,
        "parser_error": parser_error,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def _compatibility_rows(
    payload: Dict[str, Any],
    spec: Dict[str, Any],
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    organic_source_items = [
        item
        for item in items
        if item.get("is_source") and item.get("placement_type") == "organic"
    ]
    if not organic_source_items:
        return []
    source_item = min(organic_source_items, key=lambda item: int(item["position_absolute"]))
    source_position = int(source_item["position_absolute"])
    # Compare the public prices a buyer sees in the same SERP observation.
    # The supplier price snapshot is only a fallback because promotions and
    # wallet prices can make it differ materially from the search card.
    source_price = _float(source_item.get("price_effective")) or _float(payload.get("source_price_promo"))
    if source_price is None:
        return []
    segment = float(os.getenv("WB_COMPETITOR_PRICE_SEGMENT_PCT", "35")) / 100.0
    lower, upper = source_price * (1 - segment), source_price * (1 + segment)
    best_by_nm: Dict[int, Dict[str, Any]] = {}
    for item in items:
        if item["is_source"] or int(item["position_absolute"]) >= source_position:
            continue
        nm_id = int(item["result_nm_id"])
        current = best_by_nm.get(nm_id)
        if current is None or int(item["position_absolute"]) < int(current["position_absolute"]):
            best_by_nm[nm_id] = item
    rows = []
    for item in best_by_nm.values():
        effective = _float(item.get("price_effective"))
        if effective is None:
            continue
        delta = round(effective - source_price, 2)
        rows.append(
            {
                "run_date": datetime.fromisoformat(payload["observed_at"]).date().isoformat(),
                "source_snapshot_date": payload.get("source_snapshot_date"),
                "source_nm_id": int(payload["source_nm_id"]),
                "source_barcode": (payload.get("source_barcodes_json") or [None])[0],
                "source_brand": payload.get("source_brand"),
                "source_subject_name": payload.get("source_subject_name"),
                "source_title": payload.get("source_title"),
                "source_product_url": payload.get("source_product_url"),
                "source_price_regular": source_item.get("price_regular") or payload.get("source_price_regular"),
                "source_price_promo": source_price,
                "source_price_segment_min": round(lower, 2),
                "source_price_segment_max": round(upper, 2),
                "source_colors_json": [],
                "keyword": spec["query"],
                "keyword_order": int(spec["query_rank"]),
                "catalog_page": item["catalog_page"],
                "catalog_position_on_page": item["position_on_page"],
                "catalog_position_absolute": item["position_absolute"],
                "competitor_nm_id": item["result_nm_id"],
                "competitor_brand": item.get("brand"),
                "competitor_supplier_name": None,
                "competitor_supplier_id": None,
                "competitor_subject_name": item.get("subject_name") or payload.get("source_subject_name"),
                "competitor_title": item.get("title"),
                "competitor_description_short": item.get("title"),
                "competitor_colors_json": [],
                "competitor_main_photo_url": item.get("image_url"),
                "competitor_product_url": item.get("product_url"),
                "competitor_price_regular": item.get("price_regular"),
                "competitor_price_promo": effective,
                "competitor_discount_percent": item.get("discount_percent"),
                "competitor_rating": item.get("rating"),
                "competitor_feedbacks": item.get("feedbacks"),
                "photo_ai_is_competitor": None,
                "photo_ai_confidence": None,
                "photo_ai_reason": None,
                "photo_ai_model": None,
                "photo_ai_raw_json": None,
                "price_delta_abs": delta,
                "price_delta_percent": round(delta * 100.0 / source_price, 2),
                "within_price_segment": lower <= effective <= upper,
                "same_subject": normalize_query(item.get("subject_name")) == normalize_query(payload.get("source_subject_name")),
                "same_color": None,
                "search_payload_json": item.get("raw_payload") or {},
                "detail_payload_json": None,
                "parser_status": "raw_serp",
                "parser_error": None,
                "competitor_status": "success",
                "competitor_error": None,
                "task_attempt": 1,
            }
        )
    return rows


def rebuild_serp_analysis_batch(
    batch_id: str,
    source_nm_ids: Optional[List[int]] = None,
    *,
    projection_only: bool = False,
) -> Dict[str, Any]:
    """Rebuild competitor analysis from stored SERP rows without opening WB again."""
    Config.validate_db()
    allowed_nm_ids = {int(value) for value in source_nm_ids or []}
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    downstream_payloads: List[Dict[str, Any]] = []
    try:
        db.create_tables()
        jobs = db.get_completed_serp_jobs(batch_id)
        if allowed_nm_ids:
            jobs = [job for job in jobs if int(job["source_nm_id"]) in allowed_nm_ids]
        if not jobs:
            raise RuntimeError(f"SERP batch {batch_id} has no completed source jobs")

        source_rows = collapse_source_rows(
            db.get_latest_source_rows(),
            run_date=date.today(),
            require_price=False,
        )
        latest_sources = {int(row["source_nm_id"]): row for row in source_rows}
        for job in jobs:
            payload = dict(job.get("payload_json") or {})
            source_nm_id = int(job["source_nm_id"])
            latest_source = latest_sources.get(source_nm_id) or {}
            for key, value in latest_source.items():
                if key.startswith("source_") and value is not None:
                    payload[key] = value
            payload["batch_id"] = str(batch_id)
            payload["source_nm_id"] = source_nm_id
            payload["run_date"] = datetime.fromisoformat(payload["observed_at"]).date().isoformat()

            runs = db.get_serp_projection_runs(batch_id, source_nm_id)
            public_effective_prices = [
                float(item["price_effective"])
                for run in runs
                for item in run["items"]
                if item.get("is_source")
                and item.get("placement_type") == "organic"
                and item.get("price_effective") is not None
            ]
            public_wallet_prices = [
                float(item["price_wallet"])
                for run in runs
                for item in run["items"]
                if item.get("is_source")
                and item.get("placement_type") == "organic"
                and item.get("price_wallet") is not None
            ]
            # Older snapshots wrote the same value into display and wallet.
            # Treat such display values as ambiguous instead of inventing a
            # non-wallet price that was not actually observed.
            public_display_prices = [
                float(item["price_display"])
                for run in runs
                for item in run["items"]
                if item.get("is_source")
                and item.get("placement_type") == "organic"
                and item.get("price_display") is not None
                and (
                    item.get("price_wallet") is None
                    or float(item["price_display"]) != float(item["price_wallet"])
                )
            ]
            stored_result = dict(job.get("result_json") or {})
            if stored_result.get("source_site_price_observed_on") == "product_detail":
                if stored_result.get("source_price_site_display") is not None:
                    public_display_prices = [float(stored_result["source_price_site_display"])]
                if stored_result.get("source_price_site_wallet") is not None:
                    public_wallet_prices = [float(stored_result["source_price_site_wallet"])]
                if stored_result.get("source_price_site_effective") is not None:
                    public_effective_prices = [float(stored_result["source_price_site_effective"])]
            payload.update(
                _source_site_price_context(
                    _float(payload.get("source_price_promo")),
                    public_display_prices,
                    public_wallet_prices,
                    public_effective_prices,
                )
            )
            compatibility_rows: List[Dict[str, Any]] = []
            for run in runs:
                if run["parser_status"] not in {"success", "partial"}:
                    continue
                compatibility_rows.extend(
                    _compatibility_rows(payload, run["spec"], run["items"])
                )
            db.delete_raw_competitors(payload["run_date"], source_nm_id)
            written = db.upsert_raw_competitor_rows(compatibility_rows)
            worker_result = {
                **stored_result,
                "status": "completed",
                "compatibility_rows_written": written,
            }
            downstream_payloads.append(_downstream_payload(payload, worker_result))
    finally:
        db.close()

    analyses: List[Dict[str, Any]] = []
    if not projection_only:
        from normalize_candidate_attributes_per_sku import run_one as normalize_one
        from apply_hard_filters_per_sku import run_one as filter_one
        from finalize_price_ai_row import run_one as finalize_one

        for payload in downstream_payloads:
            normalized = normalize_one(payload)
            filtered = filter_one(normalized)
            analyses.append(finalize_one(filtered))

    return {
        "batch_id": str(batch_id),
        "source_jobs_rebuilt": len(downstream_payloads),
        "raw_rows_written": sum(int(row.get("raw_rows_written") or 0) for row in downstream_payloads),
        "analysis_rows_rebuilt": len(analyses),
        "source_results": analyses if not projection_only else downstream_payloads,
    }


def run_serp_direct(
    payload: Dict[str, Any],
    heartbeat: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    from fetch_raw_competitors_per_sku import _configure_wb_sku_import

    _configure_wb_sku_import()
    wb_module = importlib.import_module("fetch_wb_competitors")
    wb_config = importlib.import_module("config").Config
    wb_config.WB_BROWSER_PROFILE_DIR = Config.WB_PRICE_AI_COMPETITOR_BROWSER_PROFILE_DIR
    wb_config.WB_BROWSER_HEADLESS = Config.WB_PRICE_AI_COMPETITOR_HEADLESS
    fetcher = wb_module.WBCompetitorFetcher(
        limit_per_sku=10**6,
        page_limit=Config.WB_SERP_MAX_PAGES,
        dry_run=True,
        photo_ai_filter_enabled=False,
    )
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    completed = 0
    compatibility_rows: List[Dict[str, Any]] = []
    statuses: List[str] = []
    public_effective_prices: List[float] = []
    public_display_prices: List[float] = []
    public_wallet_prices: List[float] = []
    try:
        db.create_tables()
        for spec in payload.get("query_specs") or []:
            if heartbeat:
                heartbeat()
            run_id = deterministic_run_id(payload["batch_id"], int(payload["source_nm_id"]), spec["query_normalized"])
            try:
                occurrences = fetcher._scan_keyword(
                    spec["query"],
                    source_nm_id=int(payload["source_nm_id"]),
                    max_positions=int(payload.get("requested_max_positions") or Config.WB_SERP_MAX_POSITIONS),
                )
                metadata = dict(fetcher._last_serp_scan_metadata)
                detail_lookup = fetcher._fetch_detail_lookup(
                    sorted({int(row["competitor_nm_id"]) for row in occurrences})
                )
                items = [
                    _build_serp_item(
                        row,
                        run_id=run_id,
                        source_nm_id=int(payload["source_nm_id"]),
                        detail_product=detail_lookup.get(int(row["competitor_nm_id"])),
                        wb_module=wb_module,
                    )
                    for row in occurrences
                ]
                if metadata.get("source_found_organic"):
                    status = "success"
                elif metadata.get("source_found_any"):
                    status = "partial"
                else:
                    status = "source_not_found"
                run = _build_run_row(payload, spec, metadata, items, parser_status=status)
                db.upsert_serp_run(run)
                db.replace_serp_items(run_id, items)
                public_effective_prices.extend(
                    float(item["price_effective"])
                    for item in items
                    if item.get("is_source")
                    and item.get("placement_type") == "organic"
                    and item.get("price_effective") is not None
                )
                public_display_prices.extend(
                    float(item["price_display"])
                    for item in items
                    if item.get("is_source")
                    and item.get("placement_type") == "organic"
                    and item.get("price_display") is not None
                    and (
                        item.get("price_wallet") is None
                        or float(item["price_display"]) != float(item["price_wallet"])
                    )
                )
                public_wallet_prices.extend(
                    float(item["price_wallet"])
                    for item in items
                    if item.get("is_source")
                    and item.get("placement_type") == "organic"
                    and item.get("price_wallet") is not None
                )
                compatibility_rows.extend(_compatibility_rows(payload, spec, items))
                statuses.append(status)
                if status in {"success", "source_not_found"}:
                    completed += 1
            except Exception as exc:
                logger.exception(
                    "SERP query failed: source_nm_id=%s query=%r",
                    payload.get("source_nm_id"),
                    spec.get("query"),
                )
                metadata = dict(getattr(fetcher, "_last_serp_scan_metadata", {}) or {})
                run = _build_run_row(payload, spec, metadata, [], parser_status="failed", parser_error=str(exc))
                db.upsert_serp_run(run)
                db.replace_serp_items(run_id, [])
                statuses.append("failed")
        detail_prices = fetcher._fetch_source_detail_page_prices(int(payload["source_nm_id"]))
        if detail_prices.get("display") is not None:
            public_display_prices.append(float(detail_prices["display"]))
        if detail_prices.get("wallet") is not None:
            public_wallet_prices.append(float(detail_prices["wallet"]))
        if detail_prices.get("wallet") is not None:
            public_effective_prices.append(float(detail_prices["wallet"]))
        elif detail_prices.get("display") is not None:
            public_effective_prices.append(float(detail_prices["display"]))
        run_date = datetime.fromisoformat(payload["observed_at"]).date()
        db.delete_raw_competitors(run_date, int(payload["source_nm_id"]))
        compatibility_written = db.upsert_raw_competitor_rows(compatibility_rows)
        planned = len(payload.get("query_specs") or [])
        return {
            "batch_id": payload["batch_id"],
            "source_nm_id": int(payload["source_nm_id"]),
            "status": "completed" if completed == planned else "partial",
            "planned_runs": planned,
            "completed_runs": completed,
            "run_statuses": statuses,
            "compatibility_rows_written": compatibility_written,
            "source_site_price_observed_on": "product_detail" if detail_prices else "serp",
            "source_site_price_evidence": detail_prices.get("evidence") or {},
            **_source_site_price_context(
                _float(payload.get("source_price_promo")),
                public_display_prices,
                public_wallet_prices,
                public_effective_prices,
            ),
        }
    finally:
        fetcher.close()
        db.close()


def validate_serp_batch(batch_id: str) -> Dict[str, Any]:
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        summary = db.get_serp_batch_summary(batch_id)
    finally:
        db.close()
    if summary["planned_runs"] <= 0:
        raise RuntimeError(f"SERP batch {batch_id} contains no planned query runs")
    if summary["completion_ratio"] < Config.WB_SERP_MIN_COMPLETION_RATIO:
        raise RuntimeError(
            f"SERP batch completion {summary['completion_ratio']:.1%} is below "
            f"{Config.WB_SERP_MIN_COMPLETION_RATIO:.1%}: {summary}"
        )
    summary["status"] = "success"
    return summary


def run_canary(source_nm_id: int, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    observed_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
    payloads = prepare_serp_skus(
        observed_at,
        tenant_id=tenant_id or os.getenv("TENANT_ID"),
        source_nm_ids=[int(source_nm_id)],
    )
    if not payloads:
        raise RuntimeError(f"Active source SKU {source_nm_id} was not found")
    selected = select_queries_per_sku(payloads[0])
    if not selected.get("query_specs"):
        raise RuntimeError(f"No SERP queries available for source SKU {source_nm_id}")
    return run_serp_direct(selected)


def main() -> None:
    parser = argparse.ArgumentParser(description="WB canonical SERP snapshot utilities")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--canary-nm-id", type=int)
    mode.add_argument("--rebuild-batch-id")
    parser.add_argument("--projection-only", action="store_true")
    args = parser.parse_args()
    if args.rebuild_batch_id:
        result = rebuild_serp_analysis_batch(
            args.rebuild_batch_id,
            projection_only=args.projection_only,
        )
    else:
        result = run_canary(args.canary_nm_id)
    logger.info("SERP canary result: %s", result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()
