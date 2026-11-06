"""Конфигурация для read-only ETL маркетинга WB (Продвижение)."""
import os
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
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


class Config:
    """Класс для хранения конфигурации приложения (маркетинговые кампании WB)."""

    # API Wildberries Продвижение — advert-api
    WB_API_TOKEN: Optional[str] = os.getenv("WB_API_TOKEN") or os.getenv("WB_API_KEY")
    WB_API_CLIENT_SECRET: Optional[str] = (
        os.getenv("WB_API_CLIENT_SECRET")
        or os.getenv("WB_CLIENT_SECRET")
        or os.getenv("X_CLIENT_SECRET")
    )
    WB_API_TOKEN_MODE: str = os.getenv("WB_API_TOKEN_MODE", "auto-detect")
    WB_API_BASE_URL: str = "https://advert-api.wildberries.ru"

    # Эндпоинты — кампании
    PROMOTION_COUNT_URL: str = "https://advert-api.wildberries.ru/adv/v1/promotion/count"
    ADVERTS_V2_URL: str = "https://advert-api.wildberries.ru/api/advert/v2/adverts"
    MEDIA_ADVERTS_URL: str = "https://advert-api.wildberries.ru/adv/v1/adverts"

    # Эндпоинты — аналитика (кластеры, статистика, финансы)
    NORMQUERY_LIST_URL: str = "https://advert-api.wildberries.ru/adv/v0/normquery/list"
    NORMQUERY_GET_BIDS_URL: str = "https://advert-api.wildberries.ru/adv/v0/normquery/get-bids"
    NORMQUERY_GET_MINUS_URL: str = "https://advert-api.wildberries.ru/adv/v0/normquery/get-minus"
    NORMQUERY_STATS_URL: str = "https://advert-api.wildberries.ru/adv/v0/normquery/stats"
    NORMQUERY_STATS_V1_URL: str = "https://advert-api.wildberries.ru/adv/v1/normquery/stats"
    FULLSTATS_URL: str = "https://advert-api.wildberries.ru/adv/v3/fullstats"
    UPD_URL: str = "https://advert-api.wildberries.ru/adv/v1/upd"
    PAYMENTS_URL: str = "https://advert-api.wildberries.ru/adv/v1/payments"
    BALANCE_URL: str = "https://advert-api.wildberries.ru/adv/v1/balance"
    BUDGET_URL: str = "https://advert-api.wildberries.ru/adv/v1/budget"

    # PostgreSQL (POSTGRES_* — альтернативные имена из .env.example)
    DB_HOST: Optional[str] = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or "localhost"
    DB_PORT: int = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or "5432")
    DB_NAME: Optional[str] = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB")
    DB_USER: Optional[str] = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

    # Rate limiting: promotion/count и adverts v2 — 5/сек, 200 мс; media — 10/сек;
    # normquery — 5/сек, 200 мс; stats — 10/мин, 6 сек; fullstats — 3/мин, 20 сек;
    # upd / payments / balance — 1/сек; budget — 4/сек
    REQUEST_INTERVAL_PROMOTION: float = 0.2
    REQUEST_INTERVAL_MEDIA: float = 0.1
    REQUEST_INTERVAL_NORMQUERY: float = 0.2
    REQUEST_INTERVAL_STATS: float = 6.0
    REQUEST_INTERVAL_FULLSTATS: float = 20.0
    REQUEST_INTERVAL_UPD: float = 1.0
    REQUEST_INTERVAL_PAYMENTS: float = 1.0
    REQUEST_INTERVAL_BALANCE: float = 1.0
    REQUEST_INTERVAL_BUDGET: float = 0.25
    RETRY_COUNT: int = 6
    RETRY_DELAY: int = 5
    RETRY_DELAY_429: int = int(os.getenv("WB_MARKETING_RETRY_DELAY_429", "60"))
    BASE_TOKEN_RETRY_DELAY_429: int = int(os.getenv("WB_MARKETING_BASE_RETRY_DELAY_429", "300"))
    MAX_RATE_LIMIT_WAIT_SECONDS: float = float(
        os.getenv("WB_MARKETING_MAX_RATE_LIMIT_WAIT_SECONDS", "120")
    )

    # Пагинация медиа: размер страницы
    MEDIA_PAGE_LIMIT: int = 100

    # Пути к файлам
    BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
    JSON_OUTPUT_DIR: str = os.getenv("WB_RUNTIME_JSON_OUTPUT_DIR") or os.path.join(BASE_DIR, "json_data")
    PROGRESS_FILE: str = os.getenv("WB_RUNTIME_PROGRESS_FILE") or os.path.join(BASE_DIR, "progress.json")
    PROGRESS_DIR: str = os.path.dirname(PROGRESS_FILE)
    CAMPAIGNS_PROGRESS_FILE: str = os.path.join(PROGRESS_DIR, "campaigns_progress.json")
    STATS_PROGRESS_FILE: str = os.path.join(PROGRESS_DIR, "stats_progress.json")
    NORMQUERY_PROGRESS_FILE: str = os.path.join(PROGRESS_DIR, "normquery_progress.json")
    NORMQUERY_STATS_PROGRESS_FILE: str = os.path.join(PROGRESS_DIR, "normquery_stats_progress.json")

    @classmethod
    def validate(cls) -> None:
        """Валидация обязательных переменных окружения."""
        missing_vars = []
        if not cls.WB_API_TOKEN:
            missing_vars.append("WB_API_TOKEN")
        if not cls.DB_HOST:
            missing_vars.append("DB_HOST")
        if not cls.DB_NAME:
            missing_vars.append("DB_NAME")
        if not cls.DB_USER:
            missing_vars.append("DB_USER")
        if missing_vars:
            raise ValueError(
                f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}"
            )

    @classmethod
    def get_db_connection_string(cls) -> str:
        """Получить строку подключения к PostgreSQL."""
        conn_parts = [
            f"host={cls.DB_HOST}",
            f"port={cls.DB_PORT}",
            f"dbname={cls.DB_NAME}",
            f"user={cls.DB_USER}",
        ]
        if cls.DB_PASSWORD:
            conn_parts.append(f"password={cls.DB_PASSWORD}")
        return " ".join(conn_parts)
