"""Prepare per-SKU payloads for wb_price_ai_analysis."""
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from config import Config
from database import WBPriceAIAnalysisDatabase, dump_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _normalize_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_score(row: Dict[str, Any]) -> int:
    score = 0
    for key, weight in (
        ("wb_link_price_promo", 10),
        ("wb_link_price_regular", 5),
        ("product_url", 3),
        ("main_photo_url", 2),
        ("title", 2),
        ("description", 1),
    ):
        if row.get(key) not in (None, "", [], {}):
            score += weight
    return score


def collapse_source_rows(
    rows: List[Dict[str, Any]],
    run_date: Optional[date] = None,
    *,
    require_price: bool = True,
) -> List[Dict[str, Any]]:
    if run_date is None:
        run_date = date.today()
    grouped: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        nm_id = row.get("nm_id")
        if nm_id is None:
            continue
        nm_id = int(nm_id)
        bucket = grouped.setdefault(
            nm_id,
            {
                "run_date": run_date.isoformat(),
                "source_snapshot_date": row.get("snapshot_date").isoformat() if hasattr(row.get("snapshot_date"), "isoformat") else str(row.get("snapshot_date")),
                "source_nm_id": nm_id,
                "source_vendor_code": None,
                "source_supplier_article": None,
                "source_brand": None,
                "source_subject_name": None,
                "source_title": None,
                "source_description": None,
                "source_product_url": None,
                "source_main_photo_url": None,
                "source_price_regular": None,
                "source_price_promo": None,
                "source_characteristics_json": None,
                "source_tags_json": None,
                "source_sizes_json": None,
                "source_barcodes_json": [],
                "source_total_quantity": 0,
                "source_total_quantity_full": 0,
                "source_warehouse_names_json": [],
                "source_warehouse_count": 0,
            },
        )
        best = bucket.get("_best_row")
        if best is None or _source_score(row) > _source_score(best):
            bucket["_best_row"] = row
            bucket["source_snapshot_date"] = row.get("snapshot_date").isoformat() if hasattr(row.get("snapshot_date"), "isoformat") else str(row.get("snapshot_date"))
            bucket["source_vendor_code"] = _normalize_text(row.get("vendor_code"))
            bucket["source_supplier_article"] = _normalize_text(row.get("supplier_article"))
            bucket["source_brand"] = _normalize_text(row.get("brand"))
            bucket["source_subject_name"] = _normalize_text(row.get("subject_name"))
            bucket["source_title"] = _normalize_text(row.get("title"))
            bucket["source_description"] = _normalize_text(row.get("description"))
            bucket["source_product_url"] = _normalize_text(row.get("product_url"))
            bucket["source_main_photo_url"] = _normalize_text(row.get("main_photo_url"))
            bucket["source_price_regular"] = float(row["wb_link_price_regular"]) if row.get("wb_link_price_regular") is not None else None
            bucket["source_price_promo"] = float(row["wb_link_price_promo"]) if row.get("wb_link_price_promo") is not None else None
            bucket["source_characteristics_json"] = row.get("characteristics_json")
            bucket["source_tags_json"] = row.get("tags_json")
            bucket["source_sizes_json"] = row.get("sizes_json")

        barcode = _normalize_text(row.get("barcode"))
        if barcode and barcode not in bucket["source_barcodes_json"]:
            bucket["source_barcodes_json"].append(barcode)
        for warehouse_name in row.get("warehouse_names") or []:
            if warehouse_name not in bucket["source_warehouse_names_json"]:
                bucket["source_warehouse_names_json"].append(warehouse_name)
        bucket["source_total_quantity"] += int(row.get("total_quantity") or 0)
        bucket["source_total_quantity_full"] += int(row.get("total_quantity_full") or 0)
        bucket["source_warehouse_count"] = len(bucket["source_warehouse_names_json"])

    payloads: List[Dict[str, Any]] = []
    for item in grouped.values():
        item.pop("_best_row", None)
        if max(item["source_total_quantity"], item["source_total_quantity_full"]) <= 0:
            continue
        if require_price and item.get("source_price_promo") is None:
            continue
        payloads.append(item)
    payloads.sort(key=lambda item: int(item["source_nm_id"]))
    return payloads


def run() -> List[Dict[str, Any]]:
    Config.validate_db()
    os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        rows = db.get_latest_source_rows()
        payloads = collapse_source_rows(rows, run_date=date.today())
        path = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"active_sku_inputs_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        )
        dump_json(
            path,
            {
                "generated_at": datetime.now().isoformat(),
                "total_items": len(payloads),
                "data": payloads,
            },
        )
        logger.info("Подготовлено активных SKU для wb_price_ai_analysis: %s", len(payloads))
        return payloads
    finally:
        db.close()


if __name__ == "__main__":
    run()
