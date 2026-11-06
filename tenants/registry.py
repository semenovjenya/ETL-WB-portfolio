from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TENANTS_DIR = PROJECT_ROOT / "tenants"
REGISTRY_PATH = TENANTS_DIR / "registry.yaml"
SECRETS_DIR = TENANTS_DIR / "secrets"
AUDIT_LOG_PATH = TENANTS_DIR / "audit.log"
RUNTIME_DIR = PROJECT_ROOT / "runtime"

DEFAULT_SCHEDULES = {
    "daily_pipeline_master": "30 7 * * *",
    "hourly_snapshots": "5 * * * *",
    "sku_ai_analysis": "45 8 * * *",
    "price_ai_analysis": None,
    "serp_snapshot": "30 10 * * *",
    "ml_retrain_weekly": "0 6 * * 1",
}


@dataclass(frozen=True)
class TenantRecord:
    tenant_id: str
    tenant_slug: str
    seller_sid: str
    seller_name: str
    status: str
    db_container_name: str
    db_volume_name: str
    db_host: str
    db_port_internal: int
    db_name: str
    db_user: str
    db_password_secret_ref: str | None
    wb_api_token_secret_ref: str | None
    tenant_env_file: str | None
    schedules: dict[str, Any]
    created_at: str
    updated_at: str
    legacy: bool = False

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TenantRecord":
        return cls(
            tenant_id=str(data["tenant_id"]),
            tenant_slug=str(data["tenant_slug"]),
            seller_sid=str(data["seller_sid"]),
            seller_name=str(data.get("seller_name") or data["tenant_slug"]),
            status=str(data.get("status") or "active"),
            db_container_name=str(data.get("db_container_name") or ""),
            db_volume_name=str(data.get("db_volume_name") or ""),
            db_host=str(data.get("db_host") or ""),
            db_port_internal=int(data.get("db_port_internal") or 5432),
            db_name=str(data.get("db_name") or ""),
            db_user=str(data.get("db_user") or ""),
            db_password_secret_ref=_optional_text(data.get("db_password_secret_ref")),
            wb_api_token_secret_ref=_optional_text(data.get("wb_api_token_secret_ref")),
            tenant_env_file=_optional_text(data.get("tenant_env_file")),
            schedules=dict(data.get("schedules") or DEFAULT_SCHEDULES),
            created_at=str(data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
            legacy=bool(data.get("legacy", False)),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "tenant_slug": self.tenant_slug,
            "seller_sid": self.seller_sid,
            "seller_name": self.seller_name,
            "status": self.status,
            "legacy": self.legacy,
            "db_container_name": self.db_container_name,
            "db_volume_name": self.db_volume_name,
            "db_host": self.db_host,
            "db_port_internal": self.db_port_internal,
            "db_name": self.db_name,
            "db_user": self.db_user,
            "db_password_secret_ref": self.db_password_secret_ref,
            "wb_api_token_secret_ref": self.wb_api_token_secret_ref,
            "tenant_env_file": self.tenant_env_file,
            "schedules": dict(self.schedules),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _optional_text(value: Any) -> str | None:
    if value in (None, "", "null"):
        return None
    return str(value)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_registry() -> dict[str, Any]:
    return {"version": 1, "tenants": []}


def ensure_layout() -> None:
    TENANTS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_PATH.exists():
        save_registry(default_registry())


def load_registry(path: Path | None = None) -> dict[str, Any]:
    target = path or REGISTRY_PATH
    if not target.exists():
        return default_registry()
    raw = target.read_text(encoding="utf-8").strip()
    if not raw:
        return default_registry()
    data = json.loads(raw)
    if "tenants" not in data:
        data["tenants"] = []
    return data


def save_registry(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or REGISTRY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_tenants(*, include_disabled: bool = True) -> list[TenantRecord]:
    ensure_layout()
    registry = load_registry()
    tenants = [TenantRecord.from_mapping(item) for item in registry.get("tenants", [])]
    if include_disabled:
        return tenants
    return [tenant for tenant in tenants if tenant.status == "active"]


def get_tenant(*, tenant_id: str | None = None, tenant_slug: str | None = None, seller_sid: str | None = None) -> TenantRecord | None:
    for tenant in list_tenants(include_disabled=True):
        if tenant_id and tenant.tenant_id == tenant_id:
            return tenant
        if tenant_slug and tenant.tenant_slug == tenant_slug:
            return tenant
        if seller_sid and tenant.seller_sid == seller_sid:
            return tenant
    return None


def upsert_tenant(record: TenantRecord) -> None:
    ensure_layout()
    registry = load_registry()
    items = registry.get("tenants", [])
    for index, item in enumerate(items):
        existing = TenantRecord.from_mapping(item)
        if existing.tenant_id == record.tenant_id or existing.seller_sid == record.seller_sid:
            items[index] = record.to_mapping()
            break
    else:
        items.append(record.to_mapping())
    registry["tenants"] = sorted(items, key=lambda item: str(item.get("tenant_slug") or item.get("tenant_id")))
    save_registry(registry)


def tenant_env_path(tenant_id: str) -> Path:
    return SECRETS_DIR / f"{tenant_id}.env"


def append_audit_log(event: dict[str, Any]) -> None:
    ensure_layout()
    payload = {"timestamp": utc_now_iso(), **event}
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
