"""Конфигурация для скрипта получения финансовых отчетов из API Wildberries."""
import os
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)  # родитель текущей папки

# PARENT_DIR — корень проекта (DAG Airflow/)
env_files = [
    os.path.join(PARENT_DIR, "API WB", ".env"),
    os.path.join(PARENT_DIR, ".env"),
]

for env_file in env_files:
    if os.path.exists(env_file):
        load_dotenv(dotenv_path=env_file)
        break


def _parse_db_from_url(url: Optional[str]):
    """Из DATABASE_URL или PG_DSN извлечь host, port, dbname, user, password."""
    if not url:
        return {}
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        return {
            "host": p.hostname or os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST"),
            "port": p.port or int(os.getenv("DB_PORT", os.getenv("POSTGRES_PORT", "5432"))),
            "dbname": (p.path or "").lstrip("/") or os.getenv("DB_NAME") or os.getenv("POSTGRES_DB"),
            "user": p.username or os.getenv("DB_USER") or os.getenv("POSTGRES_USER"),
            "password": p.password or os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD"),
        }
    except Exception:
        return {}


class Config:
    """Класс для хранения конфигурации приложения."""

    # API Wildberries Statistics
    WB_API_TOKEN: Optional[str] = os.getenv("WB_API_TOKEN") or os.getenv("WB_API_KEY")
    WB_API_BASE_URL: str = "https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod"
    WB_REPORT_PERIOD: str = "daily"

    # PostgreSQL
    _db_from_url: dict = _parse_db_from_url(os.getenv("DATABASE_URL") or os.getenv("PG_DSN"))
    DB_HOST: Optional[str] = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or _db_from_url.get("host")
    DB_PORT: int = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or _db_from_url.get("port") or "5432")
    DB_NAME: Optional[str] = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or _db_from_url.get("dbname")
    DB_USER: Optional[str] = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or _db_from_url.get("user")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or _db_from_url.get("password")

    # Начальная дата для сбора данных (данные доступны с 29 января 2024)
    START_DATE: str = "2024-01-29"

    # Лимит записей в одном ответе API (integer <= 100000)
    API_LIMIT: int = 100000

    # Интервал запроса к API (дней за один запрос)
    INTERVAL_DAYS: int = 31

    # Rolling window по умолчанию для daily DAG: последние 90 дней до вчера
    ROLLING_WINDOW_DAYS: int = 90

    # Rate limiting настройки
    REQUEST_INTERVAL: float = 20.0  # секунды между запросами (лимит API: 3 запроса в минуту)
    RETRY_COUNT: int = 3
    RETRY_DELAY: int = 5  # секунды между повторами

    # Пути к файлам
    BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
    PROGRESS_FILE: str = os.getenv("WB_RUNTIME_PROGRESS_FILE") or os.path.join(BASE_DIR, "progress.json")
    JSON_OUTPUT_DIR: str = os.getenv("WB_RUNTIME_JSON_OUTPUT_DIR") or os.path.join(BASE_DIR, "json_data")

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
            f"user={cls.DB_USER}"
        ]

        if cls.DB_PASSWORD:
            conn_parts.append(f"password={cls.DB_PASSWORD}")

        return " ".join(conn_parts)
