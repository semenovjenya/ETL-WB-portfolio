"""Конфигурация для скрипта получения остатков (supplier/stocks) из API Wildberries."""
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
    """Класс для хранения конфигурации приложения (остатки на складах WB)."""

    # API Wildberries Statistics — остатки supplier/stocks
    WB_API_TOKEN: Optional[str] = os.getenv("WB_API_TOKEN") or os.getenv("WB_API_KEY")
    WB_API_BASE_URL: str = "https://statistics-api.wildberries.ru/api/v1/supplier/stocks"

    # PostgreSQL
    _db_from_url: dict = _parse_db_from_url(os.getenv("DATABASE_URL") or os.getenv("PG_DSN"))
    DB_HOST: Optional[str] = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or _db_from_url.get("host")
    DB_PORT: int = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or _db_from_url.get("port") or "5432")
    DB_NAME: Optional[str] = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or _db_from_url.get("dbname")
    DB_USER: Optional[str] = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or _db_from_url.get("user")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or _db_from_url.get("password")

    # Пагинация: с какой даты брать остатки (dateFrom). API отдаёт до 60000 строк за запрос.
    STOCKS_DATE_FROM_DEFAULT: str = "2019-06-20"

    # Rate limiting: 1 запрос в минуту (документация WB)
    REQUEST_INTERVAL: float = 60.0
    RETRY_COUNT: int = 3
    RETRY_DELAY: int = 5

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
            f"user={cls.DB_USER}",
        ]
        if cls.DB_PASSWORD:
            conn_parts.append(f"password={cls.DB_PASSWORD}")
        return " ".join(conn_parts)
