"""Fetch raw competitors for one SKU and store raw rows."""
from __future__ import annotations

import importlib
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from config import Config
from database import WBPriceAIAnalysisDatabase, dump_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _configure_wb_sku_import(
    module_dir: str = "WB_sku_ai_analysis",
    purge_modules: Iterable[str] = ("database", "config"),
) -> None:
    module_path = PROJECT_ROOT / module_dir
    module_path_str = str(module_path)
    sys.path = [module_path_str, *[path for path in sys.path if path != module_path_str]]
    module_prefix = module_path_str + os.sep
    for module_name in purge_modules:
        module = sys.modules.get(module_name)
        module_file = getattr(module, "__file__", "") if module else ""
        if module_file and not os.path.abspath(str(module_file)).startswith(module_prefix):
            sys.modules.pop(module_name, None)
    importlib.invalidate_caches()


def is_supported_runtime() -> bool:
    return not Path("/.dockerenv").exists()


def _build_source_row(payload: Dict[str, Any]) -> Dict[str, Any]:
    barcodes = payload.get("source_barcodes_json") or []
    return {
        "snapshot_date": payload.get("source_snapshot_date"),
        "nm_id": payload.get("source_nm_id"),
        "barcode": barcodes[0] if barcodes else None,
        "brand": payload.get("source_brand"),
        "subject_name": payload.get("source_subject_name"),
        "title": payload.get("source_title"),
        "description": payload.get("source_description"),
        "product_url": payload.get("source_product_url"),
        "main_photo_url": payload.get("source_main_photo_url"),
        "characteristics_json": payload.get("source_characteristics_json"),
        "sizes_json": payload.get("source_sizes_json"),
        "tags_json": payload.get("source_tags_json"),
        "wb_link_price_regular": payload.get("source_price_regular"),
        "wb_link_price_promo": payload.get("source_price_promo"),
    }


def _raw_status(stats: Dict[str, Any], has_rows: bool) -> str:
    if has_rows:
        return "success"
    if stats.get("raw_keywords_total") and stats.get("raw_keywords_failed_other") == stats.get("raw_keywords_total"):
        return "failed"
    return "success"


def _build_initial_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(payload)
    result.update(
        {
            "raw_status": "failed",
            "raw_error": None,
            "raw_rows_written": 0,
            "raw_unique_competitors": 0,
            "raw_stats": {},
        }
    )
    return result


def _build_raw_rows_for_source(
    *,
    payload: Dict[str, Any],
    fetcher: Any,
    wb_module: Any,
    own_nm_ids: Set[int],
    run_date: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_row = _build_source_row(payload)
    source_nm_id = int(payload["source_nm_id"])
    source_price_regular, source_price_promo = wb_module.pick_source_prices(source_row)
    if source_price_promo is None:
        return [], {"skipped_missing_price": 1}
    source_colors = wb_module.extract_source_colors(source_row)
    lower_bound, upper_bound = wb_module.calculate_price_window(
        source_price_promo,
        wb_module.Config.WB_COMPETITOR_PRICE_SEGMENT_PCT,
    )
    raw_occurrences: List[Dict[str, Any]] = []
    stats = {
        "raw_keywords_total": len(payload.get("keywords_json") or []),
        "raw_keywords_failed_other": 0,
        "raw_search_hits": 0,
        "raw_filtered_own_sku": 0,
        "raw_filtered_missing_price": 0,
        "raw_filtered_missing_subject": 0,
        "raw_skipped_missing_price": 0,
        "raw_source_found_keywords": 0,
        "raw_source_not_found_keywords": 0,
    }

    for keyword_order, keyword in enumerate(payload.get("keywords_json") or [], start=1):
        try:
            hits = fetcher._search_keyword(keyword, stop_nm_id=source_nm_id)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning(
                "Raw competitor keyword failed: source_nm_id=%s keyword=%r error=%s",
                source_nm_id,
                keyword,
                exc,
            )
            stats["raw_keywords_failed_other"] += 1
            continue
        stop_metadata = getattr(fetcher, "_last_search_stop_metadata", {}) or {}
        if stop_metadata.get("stop_nm_id") == source_nm_id and stop_metadata.get("found"):
            stats["raw_source_found_keywords"] += 1
        else:
            stats["raw_source_not_found_keywords"] += 1
        for hit in hits:
            competitor_nm_id = int(hit["competitor_nm_id"])
            if competitor_nm_id in own_nm_ids:
                stats["raw_filtered_own_sku"] += 1
                continue
            raw_occurrences.append(
                {
                    **hit,
                    "run_date": run_date.isoformat(),
                    "source_snapshot_date": payload.get("source_snapshot_date"),
                    "source_nm_id": source_nm_id,
                    "source_barcode": source_row.get("barcode"),
                    "source_brand": payload.get("source_brand"),
                    "source_subject_name": payload.get("source_subject_name"),
                    "source_title": payload.get("source_title"),
                    "source_product_url": payload.get("source_product_url"),
                    "source_price_regular": payload.get("source_price_regular"),
                    "source_price_promo": payload.get("source_price_promo"),
                    "source_price_segment_min": wb_module.decimal_to_float(lower_bound),
                    "source_price_segment_max": wb_module.decimal_to_float(upper_bound),
                    "source_colors_json": list(source_colors),
                    "keyword": keyword,
                    "keyword_order": keyword_order,
                }
            )
    if not raw_occurrences:
        return [], stats

    stats["raw_search_hits"] = len(raw_occurrences)
    detail_lookup = fetcher._fetch_detail_lookup(sorted({int(item["competitor_nm_id"]) for item in raw_occurrences}))  # type: ignore[attr-defined]
    rows: List[Dict[str, Any]] = []

    for item in raw_occurrences:
        competitor_nm_id = int(item["competitor_nm_id"])
        detail_product = detail_lookup.get(competitor_nm_id)
        detail_regular, detail_promo = fetcher._extract_detail_prices(detail_product)  # type: ignore[attr-defined]
        competitor_price_regular = detail_regular or item.get("competitor_price_regular_search")
        competitor_price_promo = detail_promo or item.get("competitor_price_promo_search")
        competitor_subject_name = (detail_product or {}).get("entity") or item.get("competitor_subject_name")
        if competitor_subject_name in (None, ""):
            stats["raw_filtered_missing_subject"] += 1
            continue
        if competitor_price_promo is None:
            stats["raw_filtered_missing_price"] += 1
            continue
        competitor_title = (detail_product or {}).get("name") or item.get("competitor_title")
        competitor_colors = wb_module.extract_detail_colors(detail_product)
        competitor_brand = (detail_product or {}).get("brand") or item.get("competitor_brand")
        competitor_rating = (
            wb_module._to_decimal((detail_product or {}).get("reviewRating"))  # type: ignore[attr-defined]
            or wb_module._to_decimal((detail_product or {}).get("rating"))  # type: ignore[attr-defined]
            or item.get("competitor_rating")
        )
        competitor_feedbacks = int((detail_product or {}).get("feedbacks") or item.get("competitor_feedbacks") or 0)
        discount_percent = wb_module.calculate_discount_percent(competitor_price_regular, competitor_price_promo)
        price_delta_abs = wb_module._quantize(competitor_price_promo - source_price_promo)  # type: ignore[attr-defined]
        price_delta_percent = wb_module._quantize((price_delta_abs / source_price_promo) * wb_module.Decimal("100"))  # type: ignore[attr-defined]
        same_subject = wb_module.normalize_text(competitor_subject_name) == wb_module.normalize_text(payload.get("source_subject_name"))
        same_color = None
        if source_colors and competitor_colors:
            same_color = wb_module.match_color_sets(source_colors, competitor_colors)
        within_price_segment = lower_bound <= competitor_price_promo <= upper_bound
        rows.append(
            {
                "run_date": item["run_date"],
                "source_snapshot_date": item.get("source_snapshot_date"),
                "source_nm_id": item["source_nm_id"],
                "source_barcode": item.get("source_barcode"),
                "source_brand": item.get("source_brand"),
                "source_subject_name": item.get("source_subject_name"),
                "source_title": item.get("source_title"),
                "source_product_url": item.get("source_product_url"),
                "source_price_regular": item.get("source_price_regular"),
                "source_price_promo": item.get("source_price_promo"),
                "source_price_segment_min": item.get("source_price_segment_min"),
                "source_price_segment_max": item.get("source_price_segment_max"),
                "source_colors_json": item.get("source_colors_json") or [],
                "keyword": item["keyword"],
                "keyword_order": item["keyword_order"],
                "catalog_page": item.get("catalog_page"),
                "catalog_position_on_page": item.get("catalog_position_on_page"),
                "catalog_position_absolute": item.get("catalog_position_absolute"),
                "competitor_nm_id": competitor_nm_id,
                "competitor_brand": competitor_brand,
                "competitor_supplier_name": (detail_product or {}).get("supplier"),
                "competitor_supplier_id": (detail_product or {}).get("supplierId"),
                "competitor_subject_name": competitor_subject_name,
                "competitor_title": competitor_title,
                "competitor_description_short": wb_module.build_short_description(
                    competitor_title,
                    competitor_brand,
                    competitor_subject_name,
                ),
                "competitor_colors_json": competitor_colors,
                "competitor_main_photo_url": item.get("competitor_main_photo_url"),
                "competitor_product_url": wb_module.build_product_url(competitor_nm_id),
                "competitor_price_regular": wb_module.decimal_to_float(competitor_price_regular),
                "competitor_price_promo": wb_module.decimal_to_float(competitor_price_promo),
                "competitor_discount_percent": wb_module.decimal_to_float(discount_percent),
                "competitor_rating": wb_module.decimal_to_float(competitor_rating),
                "competitor_feedbacks": competitor_feedbacks,
                "photo_ai_is_competitor": None,
                "photo_ai_confidence": None,
                "photo_ai_reason": None,
                "photo_ai_model": None,
                "photo_ai_raw_json": None,
                "price_delta_abs": wb_module.decimal_to_float(price_delta_abs),
                "price_delta_percent": wb_module.decimal_to_float(price_delta_percent),
                "within_price_segment": within_price_segment,
                "same_subject": same_subject,
                "same_color": same_color,
                "search_payload_json": item.get("search_payload_json"),
                "detail_payload_json": detail_product,
                "parser_status": "raw",
                "parser_error": None,
                "competitor_status": "success",
                "competitor_error": None,
                "task_attempt": 1,
            }
        )
    return rows, stats


def _run_direct(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = _build_initial_result(payload)
    if payload.get("seo_status") != "success":
        result["raw_status"] = "skipped_missing_keywords"
        return result

    Config.validate_db()
    _configure_wb_sku_import()
    wb_module = importlib.import_module("fetch_wb_competitors")
    wb_config = importlib.import_module("config").Config
    wb_config.WB_BROWSER_PROFILE_DIR = Config.WB_PRICE_AI_COMPETITOR_BROWSER_PROFILE_DIR
    wb_config.WB_BROWSER_HEADLESS = Config.WB_PRICE_AI_COMPETITOR_HEADLESS
    wb_config.WB_COMPETITOR_PHOTO_AI_ENABLED = False
    fetcher = wb_module.WBCompetitorFetcher(
        limit_per_sku=10**6,
        page_limit=Config.WB_PRICE_AI_COMPETITOR_PAGE_LIMIT,
        dry_run=True,
        photo_ai_filter_enabled=False,
    )
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        own_nm_ids = set(db.get_latest_active_nm_ids())
        rows, stats = _build_raw_rows_for_source(
            payload=payload,
            fetcher=fetcher,
            wb_module=wb_module,
            own_nm_ids=own_nm_ids,
            run_date=date.fromisoformat(str(payload["run_date"])),
        )
        db.delete_raw_competitors(payload["run_date"], int(payload["source_nm_id"]))
        written_rows = db.upsert_raw_competitor_rows(rows)
        result["raw_status"] = _raw_status(stats, bool(rows))
        result["raw_error"] = None
        result["raw_rows_written"] = written_rows
        result["raw_unique_competitors"] = len({int(row["competitor_nm_id"]) for row in rows})
        result["raw_stats"] = stats
        path = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"competitors_raw_{payload['run_date']}_{payload['source_nm_id']}.json",
        )
        dump_json(
            path,
            {
                "generated_at": datetime.now().isoformat(),
                "source_nm_id": payload["source_nm_id"],
                "rows_written": written_rows,
                "stats": stats,
                "data": rows,
            },
        )
        return result
    except Exception as exc:
        result["raw_status"] = "failed"
        result["raw_error"] = str(exc)
        return result
    finally:
        fetcher.close()
        db.close()


def _poll_host_runner_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = _build_initial_result(payload)
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        db.enqueue_competitor_job(payload)
        poll_interval = max(Config.WB_PRICE_AI_HOST_RUNNER_POLL_INTERVAL_SEC, 1.0)
        deadline = time.monotonic() + max(Config.WB_PRICE_AI_HOST_RUNNER_TIMEOUT_SEC, poll_interval)
        while time.monotonic() < deadline:
            current_job = db.get_competitor_job(payload["run_date"], int(payload["source_nm_id"]))
            if not current_job:
                time.sleep(poll_interval)
                continue
            status = current_job["status"]
            if status == "completed":
                job_result = current_job.get("result_json") or {}
                if isinstance(job_result, dict):
                    merged = dict(result)
                    merged.update(job_result)
                    return merged
                result["raw_status"] = "failed"
                result["raw_error"] = "Host runner completed without valid result payload"
                return result
            if status == "failed":
                job_result = current_job.get("result_json") or {}
                if isinstance(job_result, dict):
                    merged = dict(result)
                    merged.update(job_result)
                    merged["raw_status"] = merged.get("raw_status") or "failed"
                    merged["raw_error"] = merged.get("raw_error") or current_job.get("last_error")
                    return merged
                result["raw_status"] = "failed"
                result["raw_error"] = current_job.get("last_error") or "Host runner job failed"
                return result
            time.sleep(poll_interval)
        result["raw_status"] = "failed"
        result["raw_error"] = (
            f"Host runner timeout after {int(Config.WB_PRICE_AI_HOST_RUNNER_TIMEOUT_SEC)} sec "
            f"for source_nm_id={payload['source_nm_id']}"
        )
        return result
    finally:
        db.close()


def run_one(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("seo_status") != "success":
        result = _build_initial_result(payload)
        result["raw_status"] = "skipped_missing_keywords"
        return result
    if is_supported_runtime():
        Config.validate_host_browser_runtime()
        return _run_direct(payload)
    if Config.WB_PRICE_AI_HOST_RUNNER_ENABLED:
        logger.info(
            "Raw competitor stage queued for host runner: source_nm_id=%s run_date=%s",
            payload.get("source_nm_id"),
            payload.get("run_date"),
        )
        return _poll_host_runner_job(payload)
    result = _build_initial_result(payload)
    result["raw_status"] = "failed"
    result["raw_error"] = "Host runner disabled and Docker runtime is unsupported for raw competitor stage"
    return result
