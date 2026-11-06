"""Create reports.wb_sku_competitors table."""
import logging

from database import WBSkuAIAnalysisDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    db = WBSkuAIAnalysisDatabase()
    try:
        db.connect()
        db.create_competitor_tables()
        logger.info("Таблица reports.wb_sku_competitors готова")
    finally:
        db.close()


if __name__ == "__main__":
    main()
