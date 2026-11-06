from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from tenants.registry import PROJECT_ROOT, RUNTIME_DIR, TenantRecord, get_tenant, tenant_env_path


ROOT_ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXPORT_KEYS = (
    "WB_API_TOKEN",
    "WB_API_KEY",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "PG_DSN",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "SEO_KEYWORD_OPENAI_API_KEY",
    "SEO_KEYWORD_OPENAI_BASE_URL",
    "WB_PRICE_AI_RELEVANCE_OPENAI_API_KEY",
    "WB_PRICE_AI_RELEVANCE_OPENAI_BASE_URL",
    "WB_PRICE_AI_VISION_OPENAI_API_KEY",
    "WB_PRICE_AI_VISION_OPENAI_BASE_URL",
    "WB_PRICE_AI_VISION_LIMIT_PER_SKU",
    "WB_PRICE_AI_SEO_MODEL",
    "WB_SERP_MAX_QUERIES_PER_SKU",
    "WB_SERP_QUERY_MAX_AGE_DAYS",
    "WB_SERP_MAX_POSITIONS",
    "WB_SERP_MAX_PAGES",
    "WB_SERP_DEST",
    "WB_SERP_CURRENCY",
    "WB_SERP_LOCALE",
    "WB_SERP_DEVICE",
    "WB_SERP_MIN_COMPLETION_RATIO",
    "WB_SERP_JOB_TIMEOUT_SEC",
    "WB_SERP_WORKER_STALE_SEC",
)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        values[key] = value
    return values


def dump_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in sorted(values.items()):
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key}="{escaped}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_root_env() -> dict[str, str]:
    return parse_env_file(ROOT_ENV_FILE)


def resolve_tenant(tenant_id: str | None) -> TenantRecord:
    if not tenant_id:
        tenant_id = os.getenv("TENANT_ID") or "legacy-default"
    tenant = get_tenant(tenant_id=tenant_id)
    if tenant is None:
        raise KeyError(f"Unknown tenant_id: {tenant_id}")
    return tenant


def tenant_runtime_root(tenant: TenantRecord) -> Path:
    return RUNTIME_DIR / tenant.tenant_slug


def module_runtime_dir(tenant: TenantRecord, module_dir: str) -> Path:
    path = tenant_runtime_root(tenant) / module_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_tenant_env_file(tenant: TenantRecord) -> Path:
    fallback = tenant_env_path(tenant.tenant_id)
    if not tenant.tenant_env_file:
        return fallback
    configured = Path(tenant.tenant_env_file)
    if configured.exists():
        return configured
    if configured.is_absolute():
        try:
            relative = configured.relative_to(PROJECT_ROOT)
        except ValueError:
            return fallback
        candidate = PROJECT_ROOT / relative
        if candidate.exists():
            return candidate
    return fallback


def build_tenant_env(tenant: TenantRecord, *, module_dir: str | None = None) -> dict[str, str]:
    env = dict(os.environ)
    root_env = load_root_env()
    env.update(root_env)

    tenant_env_file = resolve_tenant_env_file(tenant)
    if tenant_env_file.exists():
        env.update(parse_env_file(tenant_env_file))

    env["TENANT_ID"] = tenant.tenant_id
    env["TENANT_SLUG"] = tenant.tenant_slug
    env["TENANT_ENV_FILE"] = str(tenant_env_file)
    env["DB_HOST"] = tenant.db_host
    env["DB_PORT"] = str(tenant.db_port_internal)
    env["DB_NAME"] = tenant.db_name
    env["DB_USER"] = tenant.db_user
    env["POSTGRES_HOST"] = tenant.db_host
    env["POSTGRES_PORT"] = str(tenant.db_port_internal)
    env["POSTGRES_DB"] = tenant.db_name
    env["POSTGRES_USER"] = tenant.db_user
    if env.get("DB_PASSWORD") and not env.get("POSTGRES_PASSWORD"):
        env["POSTGRES_PASSWORD"] = env["DB_PASSWORD"]
    if env.get("POSTGRES_PASSWORD") and not env.get("DB_PASSWORD"):
        env["DB_PASSWORD"] = env["POSTGRES_PASSWORD"]

    if module_dir:
        runtime_dir = module_runtime_dir(tenant, module_dir)
        json_dir = runtime_dir / "json_data"
        json_dir.mkdir(parents=True, exist_ok=True)
        env["WB_RUNTIME_ROOT"] = str(runtime_dir)
        env["WB_RUNTIME_JSON_OUTPUT_DIR"] = str(json_dir)
        env["WB_RUNTIME_PROGRESS_FILE"] = str(runtime_dir / "progress.json")

    pythonpath_parts = [str(PROJECT_ROOT)]
    if env.get("PYTHONPATH"):
        pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    return env


@contextmanager
def tenant_environment(tenant_id: str | None, *, module_dir: str | None = None) -> Iterator[TenantRecord]:
    tenant = resolve_tenant(tenant_id)
    new_env = build_tenant_env(tenant, module_dir=module_dir)
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(new_env)
    try:
        yield tenant
    finally:
        os.environ.clear()
        os.environ.update(previous)


def tenant_schedule(tenant: TenantRecord, key: str, default: str | None = None) -> str | None:
    value = tenant.schedules.get(key)
    if value in ("", None):
        return default
    return str(value)
