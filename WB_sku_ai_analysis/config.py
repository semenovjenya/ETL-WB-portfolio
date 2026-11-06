"""Configuration for WB SKU AI analysis fetcher."""
import os
from typing import Optional

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

env_files = [
    os.path.join(PARENT_DIR, "API WB", ".env"),
    os.path.join(PARENT_DIR, ".env"),
]
for env_file in env_files:
    if os.path.exists(env_file):
        load_dotenv(dotenv_path=env_file)
        break


def _parse_db_from_url(url: Optional[str]) -> dict:
    if not url:
        return {}
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return {
            "host": parsed.hostname or os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST"),
            "port": parsed.port or int(os.getenv("DB_PORT", os.getenv("POSTGRES_PORT", "5432"))),
            "dbname": (parsed.path or "").lstrip("/") or os.getenv("DB_NAME") or os.getenv("POSTGRES_DB"),
            "user": parsed.username or os.getenv("DB_USER") or os.getenv("POSTGRES_USER"),
            "password": parsed.password or os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD"),
        }
    except Exception:
        return {}


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


class Config:
    """Runtime configuration."""

    WB_API_TOKEN: Optional[str] = os.getenv("WB_API_TOKEN") or os.getenv("WB_API_KEY")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL: Optional[str] = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")

    STOCKS_URL: str = "https://statistics-api.wildberries.ru/api/v1/supplier/stocks"
    CARDS_URL: str = "https://content-api.wildberries.ru/content/v2/get/cards/list"
    PRICES_URL: str = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
    FUNNEL_URL: str = "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products"
    STOCKS_REPORT_PRODUCTS_URL: str = (
        "https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/products"
    )
    WB_LINK_CARD_DETAIL_URL: str = "https://card.wb.ru/cards/v4/detail"
    WB_SEARCH_URL: str = "https://search.wb.ru/exactmatch/ru/common/v13/search"

    _db_from_url: dict = _parse_db_from_url(os.getenv("DATABASE_URL") or os.getenv("PG_DSN"))
    DB_HOST: Optional[str] = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or _db_from_url.get("host")
    DB_PORT: int = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or _db_from_url.get("port") or "5432")
    DB_NAME: Optional[str] = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or _db_from_url.get("dbname")
    DB_USER: Optional[str] = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or _db_from_url.get("user")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or _db_from_url.get("password")

    STOCKS_DATE_FROM_DEFAULT: str = "2019-06-20"
    CARDS_PAGE_LIMIT: int = 100
    PRICES_PAGE_LIMIT: int = 1000
    ANALYTICS_BATCH_LIMIT: int = 1000
    ANALYTICS_PERIOD_DAYS: int = int(os.getenv("WB_SKU_AI_ANALYSIS_PERIOD_DAYS", "30"))

    REQUEST_INTERVAL_STOCKS: float = 60.0
    REQUEST_INTERVAL_CONTENT: float = 0.7
    REQUEST_INTERVAL_ANALYTICS: float = 20.0
    REQUEST_INTERVAL_WB_LINKS: float = 0.4
    WB_SEARCH_REQUEST_INTERVAL: float = float(os.getenv("WB_SEARCH_REQUEST_INTERVAL", "10.0"))
    RETRY_COUNT: int = 3
    RETRY_DELAY: int = 5
    RETRY_DELAY_429: int = 60
    WB_LINK_BATCH_SIZE: int = 50
    WB_SEARCH_RETRY_COUNT: int = int(os.getenv("WB_SEARCH_RETRY_COUNT", "4"))
    WB_SEARCH_RETRY_DELAYS = [60, 120, 180, 300]
    WB_SEARCH_PAGE_LIMIT: int = int(os.getenv("WB_SEARCH_PAGE_LIMIT", "3"))
    WB_COMPETITORS_PER_SKU: int = int(os.getenv("WB_COMPETITORS_PER_SKU", "20"))
    WB_COMPETITOR_PRICE_SEGMENT_PCT: float = float(os.getenv("WB_COMPETITOR_PRICE_SEGMENT_PCT", "35"))
    WB_COMPETITOR_PHOTO_AI_ENABLED: bool = _parse_bool(
        os.getenv("WB_COMPETITOR_PHOTO_AI_ENABLED"),
        bool(OPENAI_API_KEY),
    )
    WB_COMPETITOR_PHOTO_AI_MODEL: str = os.getenv("WB_COMPETITOR_PHOTO_AI_MODEL", "gpt-4o-mini")
    WB_COMPETITOR_PHOTO_AI_TIMEOUT_SEC: float = float(os.getenv("WB_COMPETITOR_PHOTO_AI_TIMEOUT_SEC", "60"))
    WB_COMPETITOR_PHOTO_AI_MAX_OUTPUT_TOKENS: int = int(os.getenv("WB_COMPETITOR_PHOTO_AI_MAX_OUTPUT_TOKENS", "300"))
    WB_BROWSER_PROFILE_DIR: str = os.getenv("WB_BROWSER_PROFILE_DIR", os.path.expanduser("~/.wb_playwright_profile"))
    WB_BROWSER_HEADLESS: bool = _parse_bool(os.getenv("WB_BROWSER_HEADLESS"), False)
    WB_BROWSER_TIMEOUT_MS: int = int(os.getenv("WB_BROWSER_TIMEOUT_MS", "60000"))
    WB_BROWSER_POST_NAVIGATION_WAIT_MS: int = int(os.getenv("WB_BROWSER_POST_NAVIGATION_WAIT_MS", "7000"))
    WB_BROWSER_CHALLENGE_WAIT_MS: int = int(os.getenv("WB_BROWSER_CHALLENGE_WAIT_MS", "70000"))
    WB_BROWSER_TYPING_DELAY_MS: int = int(os.getenv("WB_BROWSER_TYPING_DELAY_MS", "120"))
    WB_BROWSER_SLOW_MO_MS: int = int(os.getenv("WB_BROWSER_SLOW_MO_MS", "0"))
    WB_BROWSER_VIEWPORT_WIDTH: int = int(os.getenv("WB_BROWSER_VIEWPORT_WIDTH", "1440"))
    WB_BROWSER_VIEWPORT_HEIGHT: int = int(os.getenv("WB_BROWSER_VIEWPORT_HEIGHT", "900"))
    WB_BROWSER_USER_AGENT: str = os.getenv(
        "WB_BROWSER_USER_AGENT",
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    )

    BASE_DIR: str = BASE_DIR
    JSON_OUTPUT_DIR: str = os.getenv("WB_RUNTIME_JSON_OUTPUT_DIR") or os.path.join(BASE_DIR, "json_data")

    @classmethod
    def validate_db(cls) -> None:
        missing_vars = []
        if not cls.DB_HOST:
            missing_vars.append("DB_HOST")
        if not cls.DB_NAME:
            missing_vars.append("DB_NAME")
        if not cls.DB_USER:
            missing_vars.append("DB_USER")
        if missing_vars:
            raise ValueError(f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}")

    @classmethod
    def validate(cls) -> None:
        if not cls.WB_API_TOKEN:
            raise ValueError("Отсутствуют обязательные переменные окружения: WB_API_TOKEN")
        cls.validate_db()

    @classmethod
    def get_db_connection_string(cls) -> str:
        parts = [
            f"host={cls.DB_HOST}",
            f"port={cls.DB_PORT}",
            f"dbname={cls.DB_NAME}",
            f"user={cls.DB_USER}",
        ]
        if cls.DB_PASSWORD:
            parts.append(f"password={cls.DB_PASSWORD}")
        return " ".join(parts)
