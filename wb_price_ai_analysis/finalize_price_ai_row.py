"""Finalize one per-SKU mart row."""
import logging
import os
from datetime import datetime
from statistics import mean, median
from typing import Any, Dict, List, Optional

from competitor_pipeline import safe_mean, vision_grade_priority
from config import Config
from database import WBPriceAIAnalysisDatabase, dump_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def calculate_discount_percent(regular: Optional[float], promo: Optional[float]) -> Optional[float]:
    if regular is None or promo is None or regular <= 0:
        return None
    return round(((regular - promo) / regular) * 100, 2)


def _price_distance_for_selection(row: Dict[str, Any]) -> float:
    competitor_price = row.get("competitor_price_promo")
    filter_mode = row.get("filter_mode")
    if filter_mode == "market_fallback" and competitor_price is not None:
        market_price_median = row.get("market_price_median")
        if market_price_median is not None:
            return abs(float(competitor_price) - float(market_price_median))
    if competitor_price is not None and row.get("source_price_promo") is not None and filter_mode == "expanded_outlier":
        market_price_median = row.get("market_price_median")
        if market_price_median is not None:
            return abs(float(competitor_price) - float(market_price_median))
    return abs(row.get("price_delta_percent") or 10**9)


def _strict_price_distance_for_selection(row: Dict[str, Any]) -> float:
    return abs(row.get("price_delta_percent") or 10**9)


def _extract_market_context(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    structural_rows = [
        row for row in rows
        if (row.get("hard_filter_flags_json") or {}).get("structural_compatible")
        and row.get("competitor_price_promo") is not None
    ]
    return {
        "competitor_selection_mode": "structural_market" if structural_rows else None,
        "used_outlier_expanded_segment": any(row.get("filter_mode") == "expanded_outlier" and row.get("passed_hard_filters") for row in rows),
        "used_market_fallback": any(row.get("filter_mode") == "market_fallback" and row.get("passed_hard_filters") for row in rows),
        "is_price_outlier": next(
            (bool(row.get("is_price_outlier")) for row in rows if row.get("is_price_outlier") is not None),
            False,
        ),
        "market_candidate_count": len({int(row["competitor_nm_id"]) for row in structural_rows}),
        "market_price_min": next(
            ((row.get("hard_filter_flags_json") or {}).get("market_price_min") for row in rows if (row.get("hard_filter_flags_json") or {}).get("market_price_min") is not None),
            None,
        ),
        "market_price_p25": next(
            ((row.get("hard_filter_flags_json") or {}).get("market_price_p25") for row in rows if (row.get("hard_filter_flags_json") or {}).get("market_price_p25") is not None),
            None,
        ),
        "market_price_median": next(
            (row.get("market_price_median") for row in rows if row.get("market_price_median") is not None),
            None,
        ),
        "market_price_p75": next(
            ((row.get("hard_filter_flags_json") or {}).get("market_price_p75") for row in rows if (row.get("hard_filter_flags_json") or {}).get("market_price_p75") is not None),
            None,
        ),
        "market_price_max": next(
            ((row.get("hard_filter_flags_json") or {}).get("market_price_max") for row in rows if (row.get("hard_filter_flags_json") or {}).get("market_price_max") is not None),
            None,
        ),
        "source_to_market_price_ratio": next(
            (row.get("source_to_market_price_ratio") for row in rows if row.get("source_to_market_price_ratio") is not None),
            None,
        ),
    }


def select_top_unique_competitors(
    rows: List[Dict[str, Any]],
    limit: int,
    *,
    mode: str = "selected",
) -> List[Dict[str, Any]]:
    best_rows: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        competitor_nm_id = int(row["competitor_nm_id"])
        current = best_rows.get(competitor_nm_id)
        if current is None:
            best_rows[competitor_nm_id] = row
            continue
        price_distance_fn = _strict_price_distance_for_selection if mode == "strict" else _price_distance_for_selection
        candidate_key = (
            row.get("keyword_order") or 10**9,
            row.get("catalog_position_absolute") or 10**9,
            price_distance_fn(row),
            -(row.get("competitor_rating") or 0),
            -(row.get("competitor_feedbacks") or 0),
            vision_grade_priority(row.get("vision_grade") if row.get("vision_status") == "success" else None),
        )
        current_key = (
            current.get("keyword_order") or 10**9,
            current.get("catalog_position_absolute") or 10**9,
            price_distance_fn(current),
            -(current.get("competitor_rating") or 0),
            -(current.get("competitor_feedbacks") or 0),
            vision_grade_priority(current.get("vision_grade") if current.get("vision_status") == "success" else None),
        )
        if candidate_key < current_key:
            best_rows[competitor_nm_id] = row
    ordered = sorted(
        best_rows.values(),
        key=lambda item: (
            item.get("keyword_order") or 10**9,
            item.get("catalog_position_absolute") or 10**9,
            (_strict_price_distance_for_selection(item) if mode == "strict" else _price_distance_for_selection(item)),
            -(item.get("competitor_rating") or 0),
            -(item.get("competitor_feedbacks") or 0),
            vision_grade_priority(item.get("vision_grade") if item.get("vision_status") == "success" else None),
            item["competitor_nm_id"],
        ),
    )
    return ordered[:limit]


def _is_relevance_accepted(row: Dict[str, Any], threshold: float) -> bool:
    if row.get("llm_status") == "success":
        if row.get("relevance_verdict") is True:
            return True
        score = row.get("relevance_score")
        return score is not None and float(score) >= threshold
    return False


def build_candidate_pool(rows: List[Dict[str, Any]], threshold: float) -> Dict[str, List[Dict[str, Any]]]:
    hard_filtered = [row for row in rows if row.get("passed_hard_filters")]
    accepted = [row for row in hard_filtered if _is_relevance_accepted(row, threshold)]
    fallback_rows = [
        row for row in hard_filtered
        if row.get("llm_status") not in {"success"}
    ]
    pool = accepted or hard_filtered
    return {
        "hard_filtered": hard_filtered,
        "accepted": accepted,
        "fallback_rows": fallback_rows,
        "pool": pool,
    }


def build_strict_candidate_pool(rows: List[Dict[str, Any]], threshold: float) -> Dict[str, List[Dict[str, Any]]]:
    strict_rows = [
        row for row in rows
        if (row.get("hard_filter_flags_json") or {}).get("structural_compatible")
        and bool(row.get("within_price_segment"))
    ]
    accepted = [row for row in strict_rows if _is_relevance_accepted(row, threshold)]
    fallback_rows = [
        row for row in strict_rows
        if row.get("llm_status") not in {"success"}
    ]
    pool = accepted or strict_rows
    return {
        "hard_filtered": strict_rows,
        "accepted": accepted,
        "fallback_rows": fallback_rows,
        "pool": pool,
    }


def _build_summary_prefix(
    *,
    rows: List[Dict[str, Any]],
    selected: List[Dict[str, Any]],
    hard_filtered: List[Dict[str, Any]],
    accepted: List[Dict[str, Any]],
    fallback_rows: List[Dict[str, Any]],
    source_price_promo: Optional[float],
    prefix: str,
) -> Dict[str, Any]:
    promo_prices = [float(row["competitor_price_promo"]) for row in selected if row.get("competitor_price_promo") is not None]
    cheaper_count = 0
    pricier_count = 0
    if source_price_promo is not None:
        for row in selected:
            promo_price = row.get("competitor_price_promo")
            if promo_price is None:
                continue
            if promo_price < source_price_promo:
                cheaper_count += 1
            elif promo_price > source_price_promo:
                pricier_count += 1
    relevance_scores = [
        float(row["relevance_score"])
        for row in selected
        if row.get("relevance_score") is not None
    ]
    return {
        f"{prefix}competitor_count": len(selected),
        f"{prefix}competitor_cheaper_count": cheaper_count,
        f"{prefix}competitor_pricier_count": pricier_count,
        f"{prefix}competitor_price_min": min(promo_prices) if promo_prices else None,
        f"{prefix}competitor_price_max": max(promo_prices) if promo_prices else None,
        f"{prefix}competitor_price_avg": round(mean(promo_prices), 2) if promo_prices else None,
        f"{prefix}competitor_price_median": round(median(promo_prices), 2) if promo_prices else None,
        f"{prefix}llm_kept_count": len({int(row["competitor_nm_id"]) for row in accepted}),
        f"{prefix}relevance_avg_score": safe_mean(relevance_scores),
        f"{prefix}used_llm_fallback": bool(selected and not accepted and fallback_rows),
        f"{prefix}hard_filter_pass_count": len({int(row["competitor_nm_id"]) for row in hard_filtered}),
        f"{prefix}pool_size": len(rows),
    }


def summarize_competitors(
    rows: List[Dict[str, Any]],
    source_price_promo: Optional[float],
    limit: int,
    threshold: float,
) -> Dict[str, Any]:
    candidate_pool = build_candidate_pool(rows, threshold)
    hard_filtered = candidate_pool["hard_filtered"]
    accepted = candidate_pool["accepted"]
    fallback_rows = candidate_pool["fallback_rows"]
    pool = candidate_pool["pool"]
    selected = select_top_unique_competitors(pool, limit, mode="selected")
    market_context = _extract_market_context(rows)
    vision_scores = [
        float(row["vision_score"])
        for row in selected
        if row.get("vision_status") == "success" and row.get("vision_score") is not None
    ]
    vision_checked_ids = {
        int(row["competitor_nm_id"])
        for row in rows
        if row.get("vision_status") == "success"
    }
    vision_absolute_ids = {
        int(row["competitor_nm_id"])
        for row in selected
        if row.get("vision_status") == "success" and row.get("vision_grade") == "absolute_analog"
    }
    vision_close_ids = {
        int(row["competitor_nm_id"])
        for row in selected
        if row.get("vision_status") == "success" and row.get("vision_grade") == "close_analog"
    }
    vision_similar_ids = {
        int(row["competitor_nm_id"])
        for row in selected
        if row.get("vision_status") == "success" and row.get("vision_grade") == "similar_market_item"
    }
    vision_not_analog_ids = {
        int(row["competitor_nm_id"])
        for row in selected
        if row.get("vision_status") == "success" and row.get("vision_grade") == "not_analog"
    }
    summary = _build_summary_prefix(
        rows=rows,
        selected=selected,
        hard_filtered=hard_filtered,
        accepted=accepted,
        fallback_rows=fallback_rows,
        source_price_promo=source_price_promo,
        prefix="",
    )
    summary.update({
        "llm_checked_count": len({int(row["competitor_nm_id"]) for row in rows if row.get("llm_status") == "success"}),
        "vision_checked_count": len(vision_checked_ids),
        "vision_absolute_count": len(vision_absolute_ids),
        "vision_close_count": len(vision_close_ids),
        "vision_similar_count": len(vision_similar_ids),
        "vision_not_analog_count": len(vision_not_analog_ids),
        "vision_avg_score": safe_mean(vision_scores),
        "vision_prompt_version": next(
            (row.get("vision_prompt_version") for row in selected if row.get("vision_prompt_version")),
            None,
        ),
        "used_llm_fallback": bool(selected and not accepted and fallback_rows),
        "competitor_selection_mode": market_context["competitor_selection_mode"],
        "used_outlier_expanded_segment": market_context["used_outlier_expanded_segment"],
        "used_market_fallback": market_context["used_market_fallback"],
        "is_price_outlier": market_context["is_price_outlier"],
        "market_candidate_count": market_context["market_candidate_count"],
        "market_price_min": market_context["market_price_min"],
        "market_price_p25": market_context["market_price_p25"],
        "market_price_median": market_context["market_price_median"],
        "market_price_p75": market_context["market_price_p75"],
        "market_price_max": market_context["market_price_max"],
        "source_to_market_price_ratio": market_context["source_to_market_price_ratio"],
        "best_competitor_position": min(
            (row.get("catalog_position_absolute") for row in selected if row.get("catalog_position_absolute") is not None),
            default=None,
        ),
        "competitors_json": selected,
    })
    return summary


def summarize_strict_competitors(
    rows: List[Dict[str, Any]],
    source_price_promo: Optional[float],
    limit: int,
    threshold: float,
) -> Dict[str, Any]:
    candidate_pool = build_strict_candidate_pool(rows, threshold)
    selected = select_top_unique_competitors(candidate_pool["pool"], limit, mode="strict")
    return _build_summary_prefix(
        rows=rows,
        selected=selected,
        hard_filtered=candidate_pool["hard_filtered"],
        accepted=candidate_pool["accepted"],
        fallback_rows=candidate_pool["fallback_rows"],
        source_price_promo=source_price_promo,
        prefix="strict_",
    )


def build_analysis_status(seo_status: str, competitor_status: str) -> str:
    if seo_status == "success" and competitor_status == "success":
        return "success"
    if seo_status.startswith("skipped") or competitor_status.startswith("skipped"):
        return "partial"
    return "partial"


def run_one(payload: Dict[str, Any]) -> Dict[str, Any]:
    Config.validate_db()
    os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        source_nm_id = int(payload["source_nm_id"])
        run_date = datetime.fromisoformat(f"{payload['run_date']}T00:00:00").date()
        final_candidates = db.get_final_candidates(run_date, source_nm_id) if payload.get("filter_status") == "success" else []
        summary = summarize_competitors(
            final_candidates,
            payload.get("source_price_promo"),
            Config.WB_PRICE_AI_COMPETITOR_LIMIT,
            Config.WB_PRICE_AI_RELEVANCE_THRESHOLD,
        )
        strict_summary = summarize_strict_competitors(
            final_candidates,
            payload.get("source_price_promo"),
            Config.WB_PRICE_AI_COMPETITOR_LIMIT,
            Config.WB_PRICE_AI_RELEVANCE_THRESHOLD,
        )
        competitor_status = "success" if payload.get("filter_status") == "success" and payload.get("raw_status") == "success" else "failed"
        if payload.get("raw_status", "").startswith("skipped") or payload.get("filter_status", "").startswith("skipped"):
            competitor_status = "partial"
        analysis_status = build_analysis_status(payload.get("seo_status") or "failed", competitor_status)
        if (
            summary["used_llm_fallback"]
            or payload.get("llm_status") not in {"success", None}
            or payload.get("vision_status") in {"failed", "partial"}
        ):
            analysis_status = "partial"
        if summary["used_outlier_expanded_segment"] or summary["used_market_fallback"]:
            analysis_status = "partial"
        row = {
            "run_date": payload["run_date"],
            "source_snapshot_date": payload.get("source_snapshot_date"),
            "source_nm_id": source_nm_id,
            "source_vendor_code": payload.get("source_vendor_code"),
            "source_supplier_article": payload.get("source_supplier_article"),
            "source_brand": payload.get("source_brand"),
            "source_subject_name": payload.get("source_subject_name"),
            "source_title": payload.get("source_title"),
            "source_description": payload.get("source_description"),
            "source_product_url": payload.get("source_product_url"),
            "source_main_photo_url": payload.get("source_main_photo_url"),
            "source_barcodes_json": payload.get("source_barcodes_json") or [],
            "variant_count": len(payload.get("source_barcodes_json") or []),
            "source_total_quantity": int(payload.get("source_total_quantity") or 0),
            "source_total_quantity_full": int(payload.get("source_total_quantity_full") or 0),
            "source_warehouse_names_json": payload.get("source_warehouse_names_json") or [],
            "source_warehouse_count": len(payload.get("source_warehouse_names_json") or []),
            "source_price_regular": payload.get("source_price_regular"),
            "source_price_promo": payload.get("source_price_promo"),
            "source_price_site_display": payload.get("source_price_site_display"),
            "source_price_site_wallet": payload.get("source_price_site_wallet"),
            "source_price_site_effective": payload.get("source_price_site_effective"),
            "source_platform_discount_percent": payload.get("source_platform_discount_percent"),
            "source_wallet_discount_percent": payload.get("source_wallet_discount_percent"),
            "source_report_to_site_discount_percent": payload.get("source_report_to_site_discount_percent"),
            "source_discount_percent": calculate_discount_percent(payload.get("source_price_regular"), payload.get("source_price_promo")),
            "seo_keywords_json": payload.get("keywords_json") or [],
            "seo_keyword_count": int(payload.get("keyword_count") or 0),
            "seo_model": payload.get("seo_model"),
            "seo_status": payload.get("seo_status") or "failed",
            "seo_error": payload.get("seo_error"),
            "competitor_status": competitor_status,
            "competitor_error": payload.get("vision_error") or payload.get("llm_error") or payload.get("filter_error") or payload.get("raw_error"),
            "competitor_count": summary["competitor_count"],
            "competitor_cheaper_count": summary["competitor_cheaper_count"],
            "competitor_pricier_count": summary["competitor_pricier_count"],
            "competitor_price_min": summary["competitor_price_min"],
            "competitor_price_max": summary["competitor_price_max"],
            "competitor_price_avg": summary["competitor_price_avg"],
            "competitor_price_median": summary["competitor_price_median"],
            "strict_competitor_count": strict_summary["strict_competitor_count"],
            "strict_competitor_cheaper_count": strict_summary["strict_competitor_cheaper_count"],
            "strict_competitor_pricier_count": strict_summary["strict_competitor_pricier_count"],
            "strict_competitor_price_min": strict_summary["strict_competitor_price_min"],
            "strict_competitor_price_max": strict_summary["strict_competitor_price_max"],
            "strict_competitor_price_avg": strict_summary["strict_competitor_price_avg"],
            "strict_competitor_price_median": strict_summary["strict_competitor_price_median"],
            "best_competitor_position": summary["best_competitor_position"],
            "hard_filter_pass_count": summary["hard_filter_pass_count"],
            "llm_checked_count": summary["llm_checked_count"],
            "llm_kept_count": summary["llm_kept_count"],
            "relevance_avg_score": summary["relevance_avg_score"],
            "relevance_threshold": Config.WB_PRICE_AI_RELEVANCE_THRESHOLD,
            "vision_checked_count": summary["vision_checked_count"],
            "vision_absolute_count": summary["vision_absolute_count"],
            "vision_close_count": summary["vision_close_count"],
            "vision_similar_count": summary["vision_similar_count"],
            "vision_not_analog_count": summary["vision_not_analog_count"],
            "vision_avg_score": summary["vision_avg_score"],
            "vision_prompt_version": summary["vision_prompt_version"],
            "pipeline_version": Config.WB_PRICE_AI_PIPELINE_VERSION,
            "competitor_selection_mode": summary["competitor_selection_mode"],
            "used_outlier_expanded_segment": summary["used_outlier_expanded_segment"],
            "used_market_fallback": summary["used_market_fallback"],
            "is_price_outlier": summary["is_price_outlier"],
            "market_candidate_count": summary["market_candidate_count"],
            "market_price_min": summary["market_price_min"],
            "market_price_p25": summary["market_price_p25"],
            "market_price_median": summary["market_price_median"],
            "market_price_p75": summary["market_price_p75"],
            "market_price_max": summary["market_price_max"],
            "source_to_market_price_ratio": summary["source_to_market_price_ratio"],
            "competitors_json": summary["competitors_json"],
            "analysis_status": analysis_status,
        }
        db.upsert_analysis_row(row)
        path = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"price_ai_row_{payload['run_date']}_{source_nm_id}.json",
        )
        dump_json(path, row)
        return row
    finally:
        db.close()
