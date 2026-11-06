from __future__ import annotations

import argparse
import re
import secrets
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tenants.registry import (  # noqa: E402
    DEFAULT_SCHEDULES,
    PROJECT_ROOT as TENANT_PROJECT_ROOT,
    TenantRecord,
    append_audit_log,
    ensure_layout,
    get_tenant,
    tenant_env_path,
    upsert_tenant,
    utc_now_iso,
)
from tenants.runtime import dump_env_file, load_root_env  # noqa: E402


SELLER_INFO_URL = "https://common-api.wildberries.ru/api/v1/seller-info"
DEFAULT_DB_IMAGE = "pgvector/pgvector:pg16"
DEFAULT_DB_USER = "wb_user"
DEFAULT_NETWORK = "wb-shared-network"
CYRILLIC_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision WB multi-tenant database and registry entry")
    parser.add_argument("--tenant-slug", required=True, help="Human-readable slug used in container and DAG ids")
    parser.add_argument("--wb-api-token", required=True, help="Wildberries seller token")
    parser.add_argument("--db-image", default=DEFAULT_DB_IMAGE, help="Docker image for tenant database")
    parser.add_argument("--db-user", default=DEFAULT_DB_USER, help="Database user for tenant database")
    parser.add_argument("--network", default=DEFAULT_NETWORK, help="Docker network for Airflow and tenant DB containers")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the provisioning plan without docker changes")
    return parser.parse_args()


def normalize_slug(value: str) -> str:
    normalized_chars = []
    for char in value.strip().lower():
        normalized_chars.append(CYRILLIC_TRANSLIT.get(char, char))
    normalized = "".join(normalized_chars)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        raise ValueError("tenant_slug пуст после нормализации")
    return slug


def fetch_seller_info(token: str) -> dict[str, Any]:
    response = requests.get(
        SELLER_INFO_URL,
        headers={"Authorization": token.strip(), "Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not data.get("sid"):
        raise ValueError("WB seller-info не вернул sid продавца")
    return data


def tenant_identity(slug: str, seller_sid: str) -> tuple[str, str, str]:
    sid_suffix = re.sub(r"[^a-z0-9]+", "", seller_sid.lower())[:12] or "seller"
    tenant_id = f"{slug}-{sid_suffix}"
    container_name = f"wb-db-{slug}"
    db_name = f"wb_{slug.replace('-', '_')}"
    return tenant_id, container_name, db_name


def build_secret_values(*, token: str, container_name: str, db_name: str, db_user: str, db_password: str) -> dict[str, str]:
    root_env = load_root_env()
    values = {
        "WB_API_TOKEN": token.strip(),
        "DB_HOST": container_name,
        "DB_PORT": "5432",
        "DB_NAME": db_name,
        "DB_USER": db_user,
        "DB_PASSWORD": db_password,
        "POSTGRES_HOST": container_name,
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": db_name,
        "POSTGRES_USER": db_user,
        "POSTGRES_PASSWORD": db_password,
        "PG_DSN": f"postgresql://{db_user}:{db_password}@{container_name}:5432/{db_name}",
        "DATABASE_URL": f"postgresql://{db_user}:{db_password}@{container_name}:5432/{db_name}",
    }
    for key in (
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
    ):
        if root_env.get(key):
            values[key] = root_env[key]
    return values


def run_command(command: list[str], *, dry_run: bool) -> None:
    if dry_run:
        print("$", " ".join(command))
        return
    subprocess.run(command, check=True)


def ensure_docker_network(network: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"$ docker network inspect {network} || docker network create {network}")
        return
    inspect = subprocess.run(
        ["docker", "network", "inspect", network],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if inspect.returncode != 0:
        subprocess.run(["docker", "network", "create", network], check=True)


def wait_for_database(container_name: str, db_user: str, db_name: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"# wait for {container_name} readiness skipped in dry-run")
        return
    for _ in range(30):
        probe = subprocess.run(
            ["docker", "exec", container_name, "pg_isready", "-U", db_user, "-d", db_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError(f"База {container_name} не стала ready вовремя")


def create_tenant_database(*, container_name: str, volume_name: str, db_name: str, db_user: str, db_password: str, db_image: str, network: str, dry_run: bool) -> None:
    ensure_docker_network(network, dry_run=dry_run)
    run_command(["docker", "volume", "create", volume_name], dry_run=dry_run)
    init_sql = TENANT_PROJECT_ROOT / "db" / "init.sql"
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "--restart",
        "unless-stopped",
        "--network",
        network,
        "-e",
        f"POSTGRES_DB={db_name}",
        "-e",
        f"POSTGRES_USER={db_user}",
        "-e",
        f"POSTGRES_PASSWORD={db_password}",
        "-v",
        f"{volume_name}:/var/lib/postgresql/data",
        "-v",
        f"{init_sql}:/docker-entrypoint-initdb.d/01-init.sql:ro",
        db_image,
    ]
    run_command(command, dry_run=dry_run)
    wait_for_database(container_name, db_user, db_name, dry_run=dry_run)


def update_existing_tenant(existing: TenantRecord, token: str, *, dry_run: bool) -> TenantRecord:
    secret_path = Path(existing.tenant_env_file) if existing.tenant_env_file else tenant_env_path(existing.tenant_id)
    current_values = build_secret_values(
        token=token,
        container_name=existing.db_host,
        db_name=existing.db_name,
        db_user=existing.db_user,
        db_password=load_root_env().get("DB_PASSWORD", "wb_pass"),
    )
    if secret_path.exists():
        from tenants.runtime import parse_env_file

        current_values.update(parse_env_file(secret_path))
        current_values["WB_API_TOKEN"] = token.strip()
    if dry_run:
        print(f"# update secret file: {secret_path}")
    else:
        dump_env_file(secret_path, current_values)
    updated_record = replace(existing, tenant_env_file=str(secret_path), status="active", updated_at=utc_now_iso())
    if not dry_run:
        upsert_tenant(updated_record)
    append_audit_log(
        {
            "event": "tenant_secret_rotated",
            "tenant_id": existing.tenant_id,
            "tenant_slug": existing.tenant_slug,
            "seller_sid": existing.seller_sid,
            "secret_path": str(secret_path),
        }
    )
    return updated_record


def main() -> None:
    args = parse_args()
    ensure_layout()
    seller_info = fetch_seller_info(args.wb_api_token)
    seller_sid = str(seller_info["sid"])
    seller_name = str(seller_info.get("name") or seller_info.get("tradeMark") or args.tenant_slug)
    tenant_slug = normalize_slug(args.tenant_slug)

    existing_by_sid = get_tenant(seller_sid=seller_sid)
    if existing_by_sid is not None:
        updated = update_existing_tenant(existing_by_sid, args.wb_api_token, dry_run=args.dry_run)
        print(f"Updated existing tenant secret: {updated.tenant_id}")
        return

    existing_by_slug = get_tenant(tenant_slug=tenant_slug)
    if existing_by_slug is not None:
        raise SystemExit(f"Tenant slug already exists: {tenant_slug}")

    tenant_id, container_name, db_name = tenant_identity(tenant_slug, seller_sid)
    volume_name = f"wb_db_data_{tenant_slug.replace('-', '_')}"
    db_password = secrets.token_urlsafe(24)
    secret_path = tenant_env_path(tenant_id)
    secret_values = build_secret_values(
        token=args.wb_api_token,
        container_name=container_name,
        db_name=db_name,
        db_user=args.db_user,
        db_password=db_password,
    )

    if not args.dry_run:
        dump_env_file(secret_path, secret_values)
    else:
        print(f"# create secret file: {secret_path}")

    create_tenant_database(
        container_name=container_name,
        volume_name=volume_name,
        db_name=db_name,
        db_user=args.db_user,
        db_password=db_password,
        db_image=args.db_image,
        network=args.network,
        dry_run=args.dry_run,
    )

    record = TenantRecord(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        seller_sid=seller_sid,
        seller_name=seller_name,
        status="active",
        legacy=False,
        db_container_name=container_name,
        db_volume_name=volume_name,
        db_host=container_name,
        db_port_internal=5432,
        db_name=db_name,
        db_user=args.db_user,
        db_password_secret_ref=str(secret_path),
        wb_api_token_secret_ref=str(secret_path),
        tenant_env_file=str(secret_path),
        schedules=dict(DEFAULT_SCHEDULES),
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )

    if not args.dry_run:
        upsert_tenant(record)
    append_audit_log(
        {
            "event": "tenant_provisioned",
            "tenant_id": record.tenant_id,
            "tenant_slug": record.tenant_slug,
            "seller_sid": record.seller_sid,
            "db_container_name": record.db_container_name,
            "db_volume_name": record.db_volume_name,
            "tenant_env_file": record.tenant_env_file,
            "dry_run": args.dry_run,
        }
    )
    print(f"Provisioned tenant: {record.tenant_id}")


if __name__ == "__main__":
    main()
