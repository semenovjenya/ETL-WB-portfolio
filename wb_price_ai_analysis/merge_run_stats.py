"""Build run-level summary for wb_price_ai_analysis."""
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, Optional

from config import Config
from database import WBPriceAIAnalysisDatabase, dump_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run(run_date: Optional[date] = None) -> Dict[str, Any]:
    Config.validate_db()
    os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
    if run_date is None:
        run_date = date.today()
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        summary = db.get_run_summary(run_date)
        summary["data"] = db.get_run_analysis_rows(run_date)
        path = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"wb_price_ai_analysis_{run_date.isoformat()}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json",
        )
        dump_json(
            path,
            {
                "generated_at": datetime.now().isoformat(),
                **summary,
            },
        )
        summary["json_path"] = path
        return summary
    finally:
        db.close()
