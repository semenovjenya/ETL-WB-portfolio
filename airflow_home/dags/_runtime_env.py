"""Runtime bootstrap for DAG execution environment in Docker."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv


def bootstrap_runtime_env() -> None:
    """Load project .env and set docker-safe defaults for API/DB vars."""
    project_root = Path(__file__).resolve().parents[2]
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

    env_candidates = [
        Path(os.getenv("TENANT_ENV_FILE")) if os.getenv("TENANT_ENV_FILE") else None,
        project_root / ".env",
        project_root / "API WB" / ".env",
    ]
    for env_file in env_candidates:
        if env_file and env_file.exists():
            load_dotenv(env_file, override=False)
            if env_file.name != ".env":
                break

    if os.getenv("WB_API_KEY") and not os.getenv("WB_API_TOKEN"):
        os.environ["WB_API_TOKEN"] = os.getenv("WB_API_KEY", "")

    if not Path("/.dockerenv").exists():
        return

    if os.getenv("DB_HOST") in {None, "", "localhost", "127.0.0.1"}:
        os.environ["DB_HOST"] = "host.docker.internal"
    if os.getenv("POSTGRES_HOST") in {None, "", "localhost", "127.0.0.1"}:
        os.environ["POSTGRES_HOST"] = os.environ.get("DB_HOST", "host.docker.internal")

    dsn = os.getenv("DATABASE_URL") or os.getenv("PG_DSN")
    if dsn:
        try:
            parsed = urlparse(dsn)
            if parsed.hostname in {"localhost", "127.0.0.1"}:
                docker_host = os.environ.get("DB_HOST") or os.environ.get("POSTGRES_HOST") or "host.docker.internal"
                netloc = parsed.netloc
                if "@" in netloc:
                    auth, host_port = netloc.rsplit("@", 1)
                    _, sep, port = host_port.partition(":")
                    host_port = docker_host if not sep else f"{docker_host}:{port}"
                    netloc = f"{auth}@{host_port}"
                else:
                    _, sep, port = netloc.partition(":")
                    netloc = docker_host if not sep else f"{docker_host}:{port}"
                normalized_dsn = urlunparse(parsed._replace(netloc=netloc))
                if os.getenv("DATABASE_URL") == dsn:
                    os.environ["DATABASE_URL"] = normalized_dsn
                if os.getenv("PG_DSN") == dsn:
                    os.environ["PG_DSN"] = normalized_dsn
                dsn = normalized_dsn
                parsed = urlparse(dsn)
            if parsed.username:
                os.environ.setdefault("DB_USER", parsed.username)
            if parsed.password:
                os.environ.setdefault("DB_PASSWORD", parsed.password)
            if parsed.port:
                os.environ.setdefault("DB_PORT", str(parsed.port))
                os.environ.setdefault("POSTGRES_PORT", str(parsed.port))
            db_name = (parsed.path or "").lstrip("/")
            if db_name:
                os.environ.setdefault("DB_NAME", db_name)
            if parsed.hostname and parsed.hostname not in {"localhost", "127.0.0.1"}:
                os.environ.setdefault("DB_HOST", parsed.hostname)
                os.environ.setdefault("POSTGRES_HOST", parsed.hostname)
        except Exception:
            pass

    os.environ.setdefault("DB_PORT", os.getenv("POSTGRES_PORT", "55433"))
    os.environ.setdefault("POSTGRES_PORT", os.getenv("DB_PORT", "55433"))
    os.environ.setdefault("DB_NAME", os.getenv("POSTGRES_DB", "wb_docs"))
    os.environ.setdefault("DB_USER", os.getenv("POSTGRES_USER", "wb_user"))
    os.environ.setdefault("DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "wb_pass"))
