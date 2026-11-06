"""Normalize candidate/source attributes for one SKU."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from competitor_pipeline import build_competitor_features, build_source_features
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
            "normalization_status": "failed",
            "normalization_error": None,
            "normalization_rows_written": 0,
        }
    )
    return result


def run_one(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = _initial_result(payload)
    if payload.get("raw_status") != "success":
        result["normalization_status"] = "skipped_missing_raw"
        return result

    Config.validate_db()
    os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        run_date = datetime.fromisoformat(f"{payload['run_date']}T00:00:00").date()
        raw_rows = db.get_raw_competitors_full(run_date, int(payload["source_nm_id"]))
        source_features = build_source_features(payload)
        rows: List[Dict[str, Any]] = []
        for raw_row in raw_rows:
            try:
                row = {
                    "run_date": payload["run_date"],
                    "source_nm_id": int(payload["source_nm_id"]),
                    "keyword": raw_row["keyword"],
                    "competitor_nm_id": int(raw_row["competitor_nm_id"]),
                    **source_features,
                    **build_competitor_features(raw_row),
                    "normalization_status": "success",
                    "normalization_error": None,
                    "normalization_version": Config.WB_PRICE_AI_NORMALIZATION_VERSION,
                }
            except Exception as exc:
                row = {
                    "run_date": payload["run_date"],
                    "source_nm_id": int(payload["source_nm_id"]),
                    "keyword": raw_row["keyword"],
                    "competitor_nm_id": int(raw_row["competitor_nm_id"]),
                    **source_features,
                    "competitor_subject_norm": None,
                    "competitor_subtype": None,
                    "competitor_dimensions_json": None,
                    "competitor_material": None,
                    "competitor_shape": None,
                    "competitor_platform": [],
                    "competitor_connection_type": None,
                    "competitor_bed_type": None,
                    "competitor_sleep_size_json": None,
                    "competitor_color_family": None,
                    "normalization_status": "failed",
                    "normalization_error": str(exc),
                    "normalization_version": Config.WB_PRICE_AI_NORMALIZATION_VERSION,
                }
            rows.append(row)
        db.delete_feature_rows(payload["run_date"], int(payload["source_nm_id"]))
        written = db.upsert_feature_rows(rows)
        result["normalization_status"] = "success"
        result["normalization_error"] = None
        result["normalization_rows_written"] = written
        path = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"competitor_features_{payload['run_date']}_{payload['source_nm_id']}.json",
        )
        dump_json(
            path,
            {
                "generated_at": datetime.now().isoformat(),
                "source_nm_id": payload["source_nm_id"],
                "rows_written": written,
                "data": rows,
            },
        )
        return result
    except Exception as exc:
        result["normalization_status"] = "failed"
        result["normalization_error"] = str(exc)
        return result
    finally:
        db.close()
