from __future__ import annotations

import importlib
from pathlib import Path
import sys

from airflow_home.dags._tenant_factory import tenant_dag_id, tenant_tags
from airflow_home.dags._tenant_ops import _load_runner_result
from scripts.provision_tenant import normalize_slug, tenant_identity
from tenants.registry import PROJECT_ROOT, get_tenant, list_tenants
from tenants.runtime import build_tenant_env, resolve_tenant


def test_legacy_default_tenant_exists() -> None:
    tenant = get_tenant(tenant_id="legacy-default")
    assert tenant is not None
    assert tenant.tenant_slug == "legacy-default"
    assert any(item.tenant_id == "legacy-default" for item in list_tenants())


def test_build_tenant_env_sets_runtime_paths() -> None:
    tenant = resolve_tenant("legacy-default")
    env = build_tenant_env(tenant, module_dir="stocks")

    assert env["TENANT_ID"] == "legacy-default"
    assert env["TENANT_SLUG"] == "legacy-default"
    assert env["WB_RUNTIME_JSON_OUTPUT_DIR"].endswith("runtime/legacy-default/stocks/json_data")
    assert env["WB_RUNTIME_PROGRESS_FILE"].endswith("runtime/legacy-default/stocks/progress.json")
    assert str(PROJECT_ROOT) in env["PYTHONPATH"]
    assert Path(env["WB_RUNTIME_JSON_OUTPUT_DIR"]).exists()


def test_slug_and_identity_helpers() -> None:
    slug = normalize_slug("  My Seller / 2026  ")
    tenant_id, container_name, db_name = tenant_identity(slug, "abc-123-xyz")

    assert slug == "my-seller-2026"
    assert tenant_id.startswith("my-seller-2026-")
    assert container_name == "wb-db-my-seller-2026"
    assert db_name == "wb_my_seller_2026"


def test_tenant_dag_helpers() -> None:
    assert tenant_dag_id("legacy-default", "daily_pipeline_master") == "wb_legacy-default_daily_pipeline_master"
    assert tenant_tags("legacy-default", "wildberries", "daily") == [
        "wildberries",
        "daily",
        "tenant:legacy-default",
    ]


def test_demo_daily_schedule_is_after_finance_reports_are_ready() -> None:
    tenant = get_tenant(tenant_slug="demo")
    assert tenant is not None
    assert tenant.schedules["daily_pipeline_master"] == "30 7 * * *"
    assert tenant.schedules["hourly_snapshots"] is None
    assert tenant.schedules["serp_snapshot"] == "30 10 * * *"


def test_hourly_dag_is_not_created_for_tenant_without_schedule() -> None:
    dags_dir = PROJECT_ROOT / "airflow_home" / "dags"
    sys.path.insert(0, str(dags_dir))
    module = importlib.import_module("airflow_home.dags.dag_hourly_snapshots")
    module = importlib.reload(module)

    assert "wb_demo_hourly_snapshots" not in module.__dict__
    assert "wb_legacy-default_hourly_snapshots" in module.__dict__


def test_serp_dag_is_only_created_for_tenant_with_schedule() -> None:
    dags_dir = PROJECT_ROOT / "airflow_home" / "dags"
    sys.path.insert(0, str(dags_dir))
    module = importlib.import_module("airflow_home.dags.dag_serp_snapshot")
    module = importlib.reload(module)

    assert "wb_demo_serp_snapshot" in module.__dict__
    assert "wb_legacy-default_serp_snapshot" not in module.__dict__


def test_load_runner_result_reads_json_payload(tmp_path) -> None:
    result_path = tmp_path / "tenant-job-result.json"
    result_path.write_text('{"result": {"rows": 15, "status": "ok"}}', encoding="utf-8")

    assert _load_runner_result(result_path) == {"rows": 15, "status": "ok"}
