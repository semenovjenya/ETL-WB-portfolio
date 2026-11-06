"""Конфигурация для скрипта получения тарифов WB из API common-api (wb-tariffs)."""
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
    """Класс для хранения конфигурации приложения (тарифы WB)."""

    # API Wildberries Common — тарифы (wb-tariffs)
    WB_API_TOKEN: Optional[str] = os.getenv("WB_API_TOKEN") or os.getenv("WB_API_KEY")
    WB_API_BASE_URL: str = "https://common-api.wildberries.ru"

    # PostgreSQL
    DB_HOST: Optional[str] = os.getenv("DB_HOST")
    DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
    DB_NAME: Optional[str] = os.getenv("DB_NAME")
    DB_USER: Optional[str] = os.getenv("DB_USER")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD")

    # Лимиты: commission 1 req/min, box/pallet/return 60/min, acceptance 6/10sec
    REQUEST_INTERVAL: float = 1.0
    RETRY_COUNT: int = 3
    RETRY_DELAY: int = 5

    # Пути к файлам
    BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
    JSON_OUTPUT_DIR: str = os.getenv("WB_RUNTIME_JSON_OUTPUT_DIR") or os.path.join(BASE_DIR, "json_data")

    @classmethod
    def validate(cls) -> None:
        """Валидация обязательных переменных окружения."""
        missing_vars = []
        if not cls.WB_API_TOKEN:
            missing_vars.append("WB_API_TOKEN или WB_API_KEY")
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
