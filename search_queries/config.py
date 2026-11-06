"""Конфигурация для выгрузки поисковых запросов WB (search-report/*)."""
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


def _parse_db_from_url(url: Optional[str]):
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


def _parse_list(value: Optional[str], default: list[str]) -> list[str]:
    if not value:
        return default
    items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


class Config:
    """Конфигурация приложения."""

    WB_API_TOKEN: Optional[str] = os.getenv("WB_API_TOKEN") or os.getenv("WB_API_KEY")
    WB_API_BASE_URL: str = "https://seller-analytics-api.wildberries.ru"

    REPORT_ENDPOINT: str = "/api/v2/search-report/report"
    GROUPS_ENDPOINT: str = "/api/v2/search-report/table/groups"
    DETAILS_ENDPOINT: str = "/api/v2/search-report/table/details"
    SEARCH_TEXTS_ENDPOINT: str = "/api/v2/search-report/product/search-texts"
    ORDERS_ENDPOINT: str = "/api/v2/search-report/product/orders"

    _db_from_url: dict = _parse_db_from_url(os.getenv("DATABASE_URL") or os.getenv("PG_DSN"))
    DB_HOST: Optional[str] = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or _db_from_url.get("host")
    DB_PORT: int = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or _db_from_url.get("port") or "5432")
    DB_NAME: Optional[str] = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or _db_from_url.get("dbname")
    DB_USER: Optional[str] = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or _db_from_url.get("user")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or _db_from_url.get("password")

    ACTIVE_NM_LOOKBACK_DAYS: int = int(os.getenv("WB_SEARCH_ACTIVE_NM_LOOKBACK_DAYS", "90"))
    MAX_ACTIVE_NM_IDS: int = int(os.getenv("WB_SEARCH_MAX_ACTIVE_NM_IDS", "0"))
    SEARCH_PERIOD_DAYS: int = int(os.getenv("WB_SEARCH_PERIOD_DAYS", "7"))
    REQUEST_TIMEOUT: int = int(os.getenv("WB_SEARCH_REQUEST_TIMEOUT", "120"))

    REQUEST_INTERVAL_SEC: float = float(os.getenv("WB_SEARCH_REQUEST_INTERVAL_SEC", "20"))
    REQUESTS_PER_MINUTE: int = int(os.getenv("WB_SEARCH_REQUESTS_PER_MINUTE", "3"))
    RETRY_COUNT: int = int(os.getenv("WB_SEARCH_RETRY_COUNT", "3"))
    RETRY_DELAY: int = int(os.getenv("WB_SEARCH_RETRY_DELAY", "5"))
    RETRY_DELAY_429: int = int(os.getenv("WB_SEARCH_RETRY_DELAY_429", "60"))
    RETRY_JITTER_SEC: float = float(os.getenv("WB_SEARCH_RETRY_JITTER_SEC", "2"))
    STOP_ON_429: bool = os.getenv("WB_SEARCH_STOP_ON_429", "true").lower() == "true"

    SEARCH_TEXTS_REQUEST_INTERVAL_SEC: float = _env_float(
        "WB_SEARCH_SEARCH_TEXTS_REQUEST_INTERVAL_SEC",
        max(REQUEST_INTERVAL_SEC, 65.0),
    )
    SEARCH_TEXTS_REQUESTS_PER_MINUTE: int = _env_int(
        "WB_SEARCH_SEARCH_TEXTS_REQUESTS_PER_MINUTE",
        1,
    )
    SEARCH_TEXTS_RETRY_COUNT: int = _env_int(
        "WB_SEARCH_SEARCH_TEXTS_RETRY_COUNT",
        max(RETRY_COUNT, 6),
    )
    SEARCH_TEXTS_RETRY_DELAY: int = _env_int(
        "WB_SEARCH_SEARCH_TEXTS_RETRY_DELAY",
        max(RETRY_DELAY, 15),
    )
    SEARCH_TEXTS_RETRY_DELAY_429: int = _env_int(
        "WB_SEARCH_SEARCH_TEXTS_RETRY_DELAY_429",
        max(RETRY_DELAY_429, 120),
    )

    ORDERS_REQUEST_INTERVAL_SEC: float = _env_float(
        "WB_SEARCH_ORDERS_REQUEST_INTERVAL_SEC",
        max(REQUEST_INTERVAL_SEC, 65.0),
    )
    ORDERS_REQUESTS_PER_MINUTE: int = _env_int(
        "WB_SEARCH_ORDERS_REQUESTS_PER_MINUTE",
        1,
    )
    ORDERS_RETRY_COUNT: int = _env_int(
        "WB_SEARCH_ORDERS_RETRY_COUNT",
        max(RETRY_COUNT, 6),
    )
    ORDERS_RETRY_DELAY: int = _env_int(
        "WB_SEARCH_ORDERS_RETRY_DELAY",
        max(RETRY_DELAY, 15),
    )
    ORDERS_RETRY_DELAY_429: int = _env_int(
        "WB_SEARCH_ORDERS_RETRY_DELAY_429",
        max(RETRY_DELAY_429, 120),
    )

    NM_IDS_BATCH_SIZE: int = int(os.getenv("WB_SEARCH_NM_IDS_BATCH_SIZE", "50"))
    SEARCH_TEXTS_NM_IDS_BATCH_SIZE: int = int(os.getenv("WB_SEARCH_SEARCH_TEXTS_NM_IDS_BATCH_SIZE", "20"))
    REPORT_LIMIT: int = int(os.getenv("WB_SEARCH_REPORT_LIMIT", "1000"))
    GROUPS_LIMIT: int = int(os.getenv("WB_SEARCH_GROUPS_LIMIT", "1000"))
    DETAILS_LIMIT: int = int(os.getenv("WB_SEARCH_DETAILS_LIMIT", "1000"))
    SEARCH_TEXTS_LIMIT: int = int(os.getenv("WB_SEARCH_TEXTS_LIMIT", "30"))
    ORDERS_TEXTS_CHUNK_SIZE: int = int(os.getenv("WB_SEARCH_ORDERS_TEXTS_CHUNK_SIZE", "30"))
    ORDER_SEARCH_TEXTS_MAX_BATCHES_PER_RUN: int = int(os.getenv("WB_SEARCH_ORDER_TEXTS_MAX_BATCHES_PER_RUN", "1"))
    ORDERS_MAX_NM_PER_RUN: int = int(os.getenv("WB_SEARCH_ORDERS_MAX_NM_PER_RUN", "1"))

    POSITION_CLUSTER: str = os.getenv("WB_SEARCH_POSITION_CLUSTER", "all")
    ORDER_BY_FIELD: str = os.getenv("WB_SEARCH_ORDER_BY_FIELD", "avgPosition")
    ORDER_BY_MODE: str = os.getenv("WB_SEARCH_ORDER_BY_MODE", "asc")
    INCLUDE_SUBSTITUTED_SKUS: bool = os.getenv("WB_SEARCH_INCLUDE_SUBSTITUTED_SKUS", "true").lower() == "true"
    INCLUDE_SEARCH_TEXTS: bool = os.getenv("WB_SEARCH_INCLUDE_SEARCH_TEXTS", "true").lower() == "true"
    TOP_ORDER_BY_VALUES: list[str] = _parse_list(
        os.getenv("WB_SEARCH_TOP_ORDER_BY_VALUES"),
        ["openCard", "addToCart", "openToCart", "orders", "cartToOrder"],
    )
    ORDER_SEARCH_TEXT_TOP_ORDER_BY_VALUES: list[str] = _parse_list(
        os.getenv("WB_SEARCH_ORDER_SEARCH_TEXT_TOP_ORDER_BY_VALUES"),
        ["orders"],
    )

    BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
    JSON_OUTPUT_DIR: str = os.getenv("WB_RUNTIME_JSON_OUTPUT_DIR") or os.path.join(BASE_DIR, "json_data")

    @classmethod
    def validate(cls) -> None:
        missing = []
        if not cls.WB_API_TOKEN:
            missing.append("WB_API_TOKEN")
        if not cls.DB_HOST:
            missing.append("DB_HOST")
        if not cls.DB_NAME:
            missing.append("DB_NAME")
        if not cls.DB_USER:
            missing.append("DB_USER")
        if cls.SEARCH_PERIOD_DAYS < 1 or cls.SEARCH_PERIOD_DAYS > 7:
            raise ValueError("WB_SEARCH_PERIOD_DAYS должен быть в диапазоне 1..7")
        if not cls.INCLUDE_SUBSTITUTED_SKUS and not cls.INCLUDE_SEARCH_TEXTS:
            raise ValueError("Нельзя одновременно отключить INCLUDE_SUBSTITUTED_SKUS и INCLUDE_SEARCH_TEXTS")
        if missing:
            raise ValueError(f"Отсутствуют переменные окружения: {', '.join(missing)}")

    @classmethod
    def get_db_connection_string(cls) -> str:
        conn_parts = [
            f"host={cls.DB_HOST}",
            f"port={cls.DB_PORT}",
            f"dbname={cls.DB_NAME}",
            f"user={cls.DB_USER}",
        ]
        if cls.DB_PASSWORD:
            conn_parts.append(f"password={cls.DB_PASSWORD}")
        return " ".join(conn_parts)
