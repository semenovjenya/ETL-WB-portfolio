"""Apply hard filters for one SKU over normalized competitor attributes."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from competitor_pipeline import apply_hard_filter, safe_percentile
from config import Config
from database import WBPriceAIAnalysisDatabase, dump_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _initial_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(payload)
    result.update(
        {
            "filter_status": "failed",
            "filter_error": None,
            "filter_rows_written": 0,
            "hard_filter_pass_count": 0,
        }
    )
    return result


def _merge_raw_and_features(raw_rows: List[Dict[str, Any]], feature_rows: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    features_by_key = {
        (row["keyword"], int(row["competitor_nm_id"])): row
        for row in feature_rows
    }
    merged: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for raw_row in raw_rows:
        key = (raw_row["keyword"], int(raw_row["competitor_nm_id"]))
        feature_row = features_by_key.get(key)
        if feature_row is None:
            continue
        merged.append((raw_row, feature_row))
    return merged


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _selection_sort_key(
    row: Dict[str, Any],
    *,
    mode: str,
    market_price_median: Optional[float],
    source_price_promo: Optional[float],
) -> Tuple[Any, ...]:
    competitor_price = _safe_float(row.get("competitor_price_promo"))
    if mode == "market_fallback":
        anchor = market_price_median if market_price_median is not None else source_price_promo
        price_distance = abs(competitor_price - anchor) if competitor_price is not None and anchor is not None else 10**9
    else:
        price_distance = abs(_safe_float(row.get("price_delta_percent")) or 10**9)
    return (
        row.get("keyword_order") or 10**9,
        row.get("catalog_position_absolute") or 10**9,
        price_distance,
        -(row.get("competitor_rating") or 0),
        -(row.get("competitor_feedbacks") or 0),
        int(row["competitor_nm_id"]),
    )


def _select_top_unique_ids(
    rows: List[Dict[str, Any]],
    *,
    limit: int,
    mode: str,
    market_price_median: Optional[float],
    source_price_promo: Optional[float],
) -> set[int]:
    best_rows: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        competitor_nm_id = int(row["competitor_nm_id"])
        current = best_rows.get(competitor_nm_id)
        candidate_key = _selection_sort_key(
            row,
            mode=mode,
            market_price_median=market_price_median,
            source_price_promo=source_price_promo,
        )
        if current is None:
            best_rows[competitor_nm_id] = row
            continue
        current_key = _selection_sort_key(
            current,
            mode=mode,
            market_price_median=market_price_median,
            source_price_promo=source_price_promo,
        )
        if candidate_key < current_key:
            best_rows[competitor_nm_id] = row

    ordered = sorted(
        best_rows.values(),
        key=lambda row: _selection_sort_key(
            row,
            mode=mode,
            market_price_median=market_price_median,
            source_price_promo=source_price_promo,
        ),
    )
    return {int(row["competitor_nm_id"]) for row in ordered[:limit]}


def _build_market_stats(rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    prices = sorted(
        {
            _safe_float(row.get("competitor_price_promo"))
            for row in rows
            if _safe_float(row.get("competitor_price_promo")) is not None
        }
    )
    return {
        "market_candidate_count": len(prices),
        "market_price_min": round(min(prices), 2) if prices else None,
        "market_price_p25": safe_percentile(prices, 25),
        "market_price_median": safe_percentile(prices, 50),
        "market_price_p75": safe_percentile(prices, 75),
        "market_price_max": round(max(prices), 2) if prices else None,
    }


def build_filtered_rows(
    *,
    payload: Dict[str, Any],
    raw_rows: List[Dict[str, Any]],
    feature_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    merged = _merge_raw_and_features(raw_rows, feature_rows)
    source_nm_id = int(payload["source_nm_id"])
    source_price_promo = _safe_float(payload.get("source_price_promo"))

    rows: List[Dict[str, Any]] = []
    structural_rows: List[Dict[str, Any]] = []
    filter_errors: List[str] = []

    for raw_row, feature_row in merged:
        try:
            decision = apply_hard_filter(raw_row, feature_row)
            flags = dict(decision["hard_filter_flags_json"])
            row = {
                "run_date": payload["run_date"],
                "source_nm_id": source_nm_id,
                "keyword": raw_row["keyword"],
                "competitor_nm_id": int(raw_row["competitor_nm_id"]),
                "passed_hard_filters": False,
                "hard_filter_reason": decision["hard_filter_reason"],
                "hard_filter_flags_json": flags,
                "filter_profile": decision["filter_profile"],
                "filter_version": Config.WB_PRICE_AI_FILTER_VERSION,
                "is_llm_candidate": False,
                "filter_mode": "rejected",
                "effective_price_match": False,
                "is_price_outlier": False,
                "market_price_median": None,
                "source_to_market_price_ratio": None,
                "filter_status": "success",
                "filter_error": None,
            }
        except Exception as exc:
            row = {
                "run_date": payload["run_date"],
                "source_nm_id": source_nm_id,
                "keyword": raw_row["keyword"],
                "competitor_nm_id": int(raw_row["competitor_nm_id"]),
                "passed_hard_filters": False,
                "hard_filter_reason": "filter_exception",
                "hard_filter_flags_json": {"structural_compatible": False},
                "filter_profile": feature_row.get("source_subject_norm") or "generic_same_subject_price",
                "filter_version": Config.WB_PRICE_AI_FILTER_VERSION,
                "is_llm_candidate": False,
                "filter_mode": "rejected",
                "effective_price_match": False,
                "is_price_outlier": False,
                "market_price_median": None,
                "source_to_market_price_ratio": None,
                "filter_status": "failed",
                "filter_error": str(exc),
            }
            filter_errors.append(str(exc))
        rows.append(row)
        if row["hard_filter_flags_json"].get("structural_compatible") and _safe_float(raw_row.get("competitor_price_promo")) is not None:
            structural_rows.append({**raw_row, **row})

    market_stats = _build_market_stats(structural_rows)
    market_price_median = market_stats["market_price_median"]
    source_to_market_ratio = None
    if source_price_promo and market_price_median:
        source_to_market_ratio = round(source_price_promo / market_price_median, 4)
    is_price_outlier = bool(
        source_price_promo is not None
        and source_price_promo >= Config.WB_PRICE_AI_OUTLIER_SOURCE_PRICE_MIN
        and source_to_market_ratio is not None
        and source_to_market_ratio >= Config.WB_PRICE_AI_OUTLIER_RATIO_THRESHOLD
    )

    for row in rows:
        row["is_price_outlier"] = is_price_outlier
        row["market_price_median"] = market_price_median
        row["source_to_market_price_ratio"] = source_to_market_ratio
        row["hard_filter_flags_json"]["market_candidate_count"] = market_stats["market_candidate_count"]
        row["hard_filter_flags_json"]["market_price_min"] = market_stats["market_price_min"]
        row["hard_filter_flags_json"]["market_price_p25"] = market_stats["market_price_p25"]
        row["hard_filter_flags_json"]["market_price_median"] = market_stats["market_price_median"]
        row["hard_filter_flags_json"]["market_price_p75"] = market_stats["market_price_p75"]
        row["hard_filter_flags_json"]["market_price_max"] = market_stats["market_price_max"]
        row["hard_filter_flags_json"]["source_to_market_price_ratio"] = source_to_market_ratio
        row["hard_filter_flags_json"]["is_price_outlier"] = is_price_outlier

    # Price is an observed competitor attribute, not a validity rule. Every
    # structurally compatible card remains in the market pool; the former
    # +/- price window is retained only as a separate price-peer label.
    selected_mode = "structural_market" if structural_rows else "rejected"
    selected_rows: List[Dict[str, Any]] = list(structural_rows)

    top_ids = _select_top_unique_ids(
        selected_rows,
        limit=Config.WB_PRICE_AI_RELEVANCE_LIMIT_PER_SKU,
        mode=selected_mode,
        market_price_median=market_price_median,
        source_price_promo=source_price_promo,
    ) if selected_rows else set()

    selected_competitor_ids = {int(row["competitor_nm_id"]) for row in selected_rows}
    for row in rows:
        competitor_nm_id = int(row["competitor_nm_id"])
        structural_compatible = bool(row["hard_filter_flags_json"].get("structural_compatible"))
        if structural_compatible and competitor_nm_id in selected_competitor_ids:
            is_price_peer = bool(row["hard_filter_flags_json"].get("within_price_segment"))
            row["passed_hard_filters"] = True
            row["filter_mode"] = "price_peer" if is_price_peer else "market_competitor"
            row["hard_filter_reason"] = (
                "accepted_price_peer" if is_price_peer else "accepted_market_competitor"
            )
            row["effective_price_match"] = is_price_peer
            row["hard_filter_flags_json"]["is_price_peer"] = is_price_peer
            row["is_llm_candidate"] = competitor_nm_id in top_ids

    summary = {
        "hard_filter_pass_count": len({int(row["competitor_nm_id"]) for row in rows if row["passed_hard_filters"]}),
        "filter_errors": sorted(set(filter_errors)),
        "selected_mode": selected_mode,
        "market_candidate_count": market_stats["market_candidate_count"],
        "market_price_min": market_stats["market_price_min"],
        "market_price_p25": market_stats["market_price_p25"],
        "market_price_median": market_stats["market_price_median"],
        "market_price_p75": market_stats["market_price_p75"],
        "market_price_max": market_stats["market_price_max"],
        "is_price_outlier": is_price_outlier,
        "source_to_market_price_ratio": source_to_market_ratio,
    }
    return rows, summary


def run_one(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = _initial_result(payload)
    if payload.get("normalization_status") != "success":
        result["filter_status"] = "skipped_missing_features"
        return result

    Config.validate_db()
    os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        run_date = datetime.fromisoformat(f"{payload['run_date']}T00:00:00").date()
        raw_rows = db.get_raw_competitors_full(run_date, int(payload["source_nm_id"]))
        feature_rows = db.get_features_for_source(run_date, int(payload["source_nm_id"]))
        rows, summary = build_filtered_rows(
            payload=payload,
            raw_rows=raw_rows,
            feature_rows=feature_rows,
        )

        db.delete_filtered_rows(payload["run_date"], int(payload["source_nm_id"]))
        written = db.upsert_filtered_rows(rows)
        result["filter_status"] = "success" if not summary["filter_errors"] else "partial"
        result["filter_error"] = "; ".join(summary["filter_errors"]) if summary["filter_errors"] else None
        result["filter_rows_written"] = written
        result["hard_filter_pass_count"] = int(summary["hard_filter_pass_count"])
        path = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"competitors_filtered_{payload['run_date']}_{payload['source_nm_id']}.json",
        )
        dump_json(
            path,
            {
                "generated_at": datetime.now().isoformat(),
                "source_nm_id": payload["source_nm_id"],
                "rows_written": written,
                "hard_filter_pass_count": result["hard_filter_pass_count"],
                "selected_mode": summary["selected_mode"],
                "market_candidate_count": summary["market_candidate_count"],
                "market_price_min": summary["market_price_min"],
                "market_price_p25": summary["market_price_p25"],
                "market_price_median": summary["market_price_median"],
                "market_price_p75": summary["market_price_p75"],
                "market_price_max": summary["market_price_max"],
                "is_price_outlier": summary["is_price_outlier"],
                "source_to_market_price_ratio": summary["source_to_market_price_ratio"],
                "data": rows,
            },
        )
        return result
    except Exception as exc:
        result["filter_status"] = "failed"
        result["filter_error"] = str(exc)
        return result
    finally:
        db.close()
