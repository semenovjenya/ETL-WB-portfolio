"""Configuration for wb_price_ai_analysis."""
import os
import socket
from pathlib import Path
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


def _normalize_db_host(host: Optional[str]) -> Optional[str]:
    if not host:
        return host
    if host == "host.docker.internal" and not Path("/.dockerenv").exists():
        return "localhost"
    return host


class Config:
    """Runtime configuration."""

    SEO_KEYWORD_OPENAI_API_KEY: Optional[str] = os.getenv("SEO_KEYWORD_OPENAI_API_KEY")
    WB_PRICE_AI_RELEVANCE_OPENAI_API_KEY: Optional[str] = os.getenv("WB_PRICE_AI_RELEVANCE_OPENAI_API_KEY")
    OPENAI_API_KEY: Optional[str] = (
        SEO_KEYWORD_OPENAI_API_KEY
        or os.getenv("OPENAI_API_KEY")
    )
    OPENAI_BASE_URL: Optional[str] = (
        os.getenv("SEO_KEYWORD_OPENAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
        or (None if SEO_KEYWORD_OPENAI_API_KEY else "https://polza.ai/api/v1")
    )

    _db_from_url: dict = _parse_db_from_url(os.getenv("DATABASE_URL") or os.getenv("PG_DSN"))
    DB_HOST: Optional[str] = _normalize_db_host(
        os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or _db_from_url.get("host")
    )
    DB_PORT: int = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or _db_from_url.get("port") or "5432")
    DB_NAME: Optional[str] = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or _db_from_url.get("dbname")
    DB_USER: Optional[str] = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or _db_from_url.get("user")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or _db_from_url.get("password")

    WB_PRICE_AI_SEO_MODEL: str = os.getenv("WB_PRICE_AI_SEO_MODEL", "openai/gpt-5.4")
    WB_PRICE_AI_SEO_MAX_OUTPUT_TOKENS: int = int(os.getenv("WB_PRICE_AI_SEO_MAX_OUTPUT_TOKENS", "400"))
    WB_PRICE_AI_SEO_TIMEOUT_SEC: float = float(os.getenv("WB_PRICE_AI_SEO_TIMEOUT_SEC", "60"))
    WB_PRICE_AI_SEO_PROMPT_VERSION: str = os.getenv("WB_PRICE_AI_SEO_PROMPT_VERSION", "v1")
    WB_PRICE_AI_SEO_RETRIES: int = int(os.getenv("WB_PRICE_AI_SEO_RETRIES", "1"))

    WB_PRICE_AI_RELEVANCE_MODEL: str = os.getenv("WB_PRICE_AI_RELEVANCE_MODEL", "gpt-4o-mini")
    WB_PRICE_AI_RELEVANCE_TIMEOUT_SEC: float = float(os.getenv("WB_PRICE_AI_RELEVANCE_TIMEOUT_SEC", "60"))
    WB_PRICE_AI_RELEVANCE_MAX_OUTPUT_TOKENS: int = int(os.getenv("WB_PRICE_AI_RELEVANCE_MAX_OUTPUT_TOKENS", "300"))
    WB_PRICE_AI_RELEVANCE_PROMPT_VERSION: str = os.getenv("WB_PRICE_AI_RELEVANCE_PROMPT_VERSION", "v1")
    WB_PRICE_AI_RELEVANCE_THRESHOLD: float = float(os.getenv("WB_PRICE_AI_RELEVANCE_THRESHOLD", "0.75"))
    WB_PRICE_AI_RELEVANCE_LIMIT_PER_SKU: int = int(os.getenv("WB_PRICE_AI_RELEVANCE_LIMIT_PER_SKU", "20"))
    WB_PRICE_AI_VISION_OPENAI_API_KEY: Optional[str] = os.getenv("WB_PRICE_AI_VISION_OPENAI_API_KEY")
    WB_PRICE_AI_VISION_MODEL: str = os.getenv("WB_PRICE_AI_VISION_MODEL", "gpt-4o-mini")
    WB_PRICE_AI_VISION_TIMEOUT_SEC: float = float(os.getenv("WB_PRICE_AI_VISION_TIMEOUT_SEC", "60"))
    WB_PRICE_AI_VISION_MAX_OUTPUT_TOKENS: int = int(os.getenv("WB_PRICE_AI_VISION_MAX_OUTPUT_TOKENS", "300"))
    WB_PRICE_AI_VISION_PROMPT_VERSION: str = os.getenv("WB_PRICE_AI_VISION_PROMPT_VERSION", "v1")
    WB_PRICE_AI_VISION_LIMIT_PER_SKU: int = int(os.getenv("WB_PRICE_AI_VISION_LIMIT_PER_SKU", "3"))
    WB_PRICE_AI_NORMALIZATION_VERSION: str = os.getenv("WB_PRICE_AI_NORMALIZATION_VERSION", "v1")
    WB_PRICE_AI_FILTER_VERSION: str = os.getenv("WB_PRICE_AI_FILTER_VERSION", "v1")
    WB_PRICE_AI_PIPELINE_VERSION: str = os.getenv("WB_PRICE_AI_PIPELINE_VERSION", "v2")
    WB_PRICE_AI_OUTLIER_SOURCE_PRICE_MIN: float = float(
        os.getenv("WB_PRICE_AI_OUTLIER_SOURCE_PRICE_MIN", "2000"),
    )
    WB_PRICE_AI_OUTLIER_RATIO_THRESHOLD: float = float(
        os.getenv("WB_PRICE_AI_OUTLIER_RATIO_THRESHOLD", "1.8"),
    )

    WB_PRICE_AI_COMPETITOR_LIMIT: int = int(os.getenv("WB_PRICE_AI_COMPETITOR_LIMIT", "20"))
    WB_PRICE_AI_COMPETITOR_PAGE_LIMIT: int = int(os.getenv("WB_PRICE_AI_COMPETITOR_PAGE_LIMIT", "3"))
    WB_PRICE_AI_COMPETITOR_BROWSER_PROFILE_DIR: str = os.getenv(
        "WB_PRICE_AI_COMPETITOR_BROWSER_PROFILE_DIR",
        os.path.expanduser("~/.wb_playwright_profile"),
    )
    WB_PRICE_AI_COMPETITOR_HEADLESS: bool = _parse_bool(
        os.getenv("WB_PRICE_AI_COMPETITOR_HEADLESS"),
        False,
    )
    WB_PRICE_AI_COMPETITOR_PHOTO_AI_ENABLED: bool = _parse_bool(
        os.getenv("WB_PRICE_AI_COMPETITOR_PHOTO_AI_ENABLED"),
        False,
    )
    WB_PRICE_AI_HOST_RUNNER_ENABLED: bool = _parse_bool(
        os.getenv("WB_PRICE_AI_HOST_RUNNER_ENABLED"),
        True,
    )
    WB_PRICE_AI_HOST_RUNNER_POLL_INTERVAL_SEC: float = float(
        os.getenv("WB_PRICE_AI_HOST_RUNNER_POLL_INTERVAL_SEC", "5"),
    )
    WB_PRICE_AI_HOST_RUNNER_TIMEOUT_SEC: float = float(
        os.getenv("WB_PRICE_AI_HOST_RUNNER_TIMEOUT_SEC", "3600"),
    )
    WB_PRICE_AI_HOST_RUNNER_STALE_SEC: int = int(
        os.getenv("WB_PRICE_AI_HOST_RUNNER_STALE_SEC", "1800"),
    )
    WB_PRICE_AI_HOST_WORKER_ID: str = os.getenv(
        "WB_PRICE_AI_HOST_WORKER_ID",
        f"{socket.gethostname()}:{os.getpid()}",
    )

    WB_SERP_MAX_QUERIES_PER_SKU: int = int(os.getenv("WB_SERP_MAX_QUERIES_PER_SKU", "5"))
    WB_SERP_QUERY_MAX_AGE_DAYS: int = int(os.getenv("WB_SERP_QUERY_MAX_AGE_DAYS", "14"))
    WB_SERP_MAX_POSITIONS: int = int(os.getenv("WB_SERP_MAX_POSITIONS", "200"))
    WB_SERP_MAX_PAGES: int = int(os.getenv("WB_SERP_MAX_PAGES", "5"))
    WB_SERP_DEST: str = os.getenv("WB_SERP_DEST", "-1257786")
    WB_SERP_CURRENCY: str = os.getenv("WB_SERP_CURRENCY", "rub")
    WB_SERP_LOCALE: str = os.getenv("WB_SERP_LOCALE", "ru")
    WB_SERP_DEVICE: str = os.getenv("WB_SERP_DEVICE", "desktop")
    WB_SERP_OWN_BRAND_ALIASES: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv("WB_SERP_OWN_BRAND_ALIASES", "lifecode,лайфкод,лайф код").split(",")
        if value.strip()
    )
    WB_SERP_MIN_COMPLETION_RATIO: float = float(os.getenv("WB_SERP_MIN_COMPLETION_RATIO", "0.80"))
    WB_SERP_JOB_TIMEOUT_SEC: float = float(os.getenv("WB_SERP_JOB_TIMEOUT_SEC", "7200"))
    WB_SERP_WORKER_STALE_SEC: int = int(os.getenv("WB_SERP_WORKER_STALE_SEC", "1800"))

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
    def validate_openai(cls) -> None:
        if not cls.OPENAI_API_KEY:
            raise ValueError("Отсутствует OPENAI_API_KEY для seo optimizer")

    @classmethod
    def get_relevance_openai_api_key(cls) -> Optional[str]:
        return cls.WB_PRICE_AI_RELEVANCE_OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")

    @classmethod
    def get_relevance_openai_base_url(cls) -> Optional[str]:
        return os.getenv("WB_PRICE_AI_RELEVANCE_OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")

    @classmethod
    def validate_relevance_openai(cls) -> None:
        if not cls.get_relevance_openai_api_key():
            raise ValueError("Отсутствует OPENAI API key для relevance scorer")

    @classmethod
    def get_vision_openai_api_key(cls) -> Optional[str]:
        return cls.WB_PRICE_AI_VISION_OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")

    @classmethod
    def get_vision_openai_base_url(cls) -> Optional[str]:
        return os.getenv("WB_PRICE_AI_VISION_OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")

    @classmethod
    def validate_vision_openai(cls) -> None:
        if not cls.get_vision_openai_api_key():
            raise ValueError("Отсутствует OPENAI API key для vision scorer")

    @classmethod
    def validate_host_browser_runtime(cls) -> None:
        if Path("/.dockerenv").exists():
            raise RuntimeError("wb_price_ai_analysis competitor stage requires host runtime with GUI; Docker Airflow is unsupported")

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
