from __future__ import annotations

import importlib
import os
import sys
from contextlib import suppress
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import psycopg2

from _runtime_env import bootstrap_runtime_env

bootstrap_runtime_env()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def get_conn():
    """Create a psycopg2 connection from the project environment."""

    def _env(*keys: str, default: Optional[str] = None) -> Optional[str]:
        for key in keys:
            value = os.getenv(key)
            if value:
                return value
        return default

    dsn_url = _env("DATABASE_URL", "PG_DSN")
    if dsn_url:
        return psycopg2.connect(dsn_url)

    parts = [
        f"host={_env('DB_HOST', 'POSTGRES_HOST', default='localhost')}",
        f"port={_env('DB_PORT', 'POSTGRES_PORT', default='5432')}",
        f"dbname={_env('DB_NAME', 'POSTGRES_DB', default='postgres')}",
        f"user={_env('DB_USER', 'POSTGRES_USER', default='postgres')}",
    ]
    password = _env("DB_PASSWORD", "POSTGRES_PASSWORD")
    if password:
        parts.append(f"password={password}")
    return psycopg2.connect(" ".join(parts))


def to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def today_moscow() -> date:
    return datetime.now(MOSCOW_TZ).date()


def floor_to_moscow_hour(value: datetime) -> datetime:
    """Convert a datetime to Europe/Moscow and truncate it to hour precision."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=MOSCOW_TZ)
    return value.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


def resolve_snapshot_hour(context: dict[str, Any]) -> datetime:
    """Resolve a stable snapshot hour from the Airflow run context."""
    for key in ("logical_date", "execution_date", "data_interval_end"):
        value = context.get(key)
        if isinstance(value, datetime):
            return floor_to_moscow_hour(value)
    raise ValueError("Не удалось определить snapshot_hour из Airflow context")


def configure_module_import(
    module_dir: str,
    excluded_keywords: Iterable[str],
    purge_modules: Iterable[str] = ("database", "config"),
) -> Path:
    """Put the source directory first in sys.path and evict conflicting cached modules."""
    module_path = PROJECT_ROOT / module_dir
    module_path_str = str(module_path)
    sys.path = [
        module_path_str,
        *[
            path
            for path in sys.path
            if path != module_path_str and all(keyword not in path for keyword in excluded_keywords)
        ],
    ]

    module_prefix = module_path_str + os.sep
    for module_name in purge_modules:
        module = sys.modules.get(module_name)
        module_file = getattr(module, "__file__", "") if module else ""
        if not module_file:
            continue
        with suppress(Exception):
            if not os.path.abspath(str(module_file)).startswith(module_prefix):
                del sys.modules[module_name]

    importlib.invalidate_caches()
    return module_path


def load_attr(
    module_dir: str,
    excluded_keywords: Iterable[str],
    module_name: str,
    attr_name: str,
) -> Any:
    """Import an attribute from a source folder after preparing an isolated sys.path."""
    configure_module_import(module_dir, excluded_keywords)
    with suppress(KeyError):
        del sys.modules[module_name]
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def dag_task_ref(context: dict[str, Any], task_id: str) -> str:
    """Return a fully qualified task id inside the current TaskGroup when needed."""
    task_group = getattr(context.get("task"), "task_group", None)
    group_id = getattr(task_group, "group_id", None)
    if group_id:
        return f"{group_id}.{task_id}"
    return task_id


def dsn_hostname(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return urlparse(value).hostname
