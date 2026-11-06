"""Create wb_price_ai_analysis tables."""
import logging

from database import WBPriceAIAnalysisDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run() -> None:
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
    finally:
        db.close()


if __name__ == "__main__":
    run()
