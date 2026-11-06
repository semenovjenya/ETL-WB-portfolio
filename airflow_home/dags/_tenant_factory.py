from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
project_root_str = str(PROJECT_ROOT)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

from tenants.registry import TenantRecord, list_tenants


def active_tenants() -> list[TenantRecord]:
    return list_tenants(include_disabled=False)


def tenant_dag_id(tenant_slug: str, suffix: str) -> str:
    return f"wb_{tenant_slug}_{suffix}"


def tenant_tags(tenant_slug: str, *base_tags: str) -> list[str]:
    return [*base_tags, f"tenant:{tenant_slug}"]
