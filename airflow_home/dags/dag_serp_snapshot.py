from __future__ import annotations

from datetime import timedelta
from typing import Any

import pendulum
from airflow import DAG
from airflow.decorators import task
from airflow.operators.python import get_current_context

from _runtime_env import bootstrap_runtime_env
from _tenant_factory import active_tenants, tenant_dag_id, tenant_tags
from _tenant_ops import run_tenant_job

bootstrap_runtime_env()


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=10),
    "start_date": pendulum.datetime(2024, 1, 1, tz="Europe/Moscow"),
}


def build_serp_snapshot_dag(tenant) -> DAG | None:
    schedule = tenant.schedules.get("serp_snapshot")
    if not schedule:
        return None

    dag = DAG(
        tenant_dag_id(tenant.tenant_slug, "serp_snapshot"),
        default_args=default_args,
        description="Daily canonical WB SERP positions and public competitor prices",
        schedule=schedule,
        catchup=False,
        max_active_runs=1,
        tags=tenant_tags(tenant.tenant_slug, "wildberries", "serp", "seo", "price"),
    )

    @task(task_id="prepare_active_skus", dag=dag, execution_timeout=timedelta(hours=1))
    def prepare_active_skus() -> list[dict[str, Any]]:
        context = get_current_context()
        dag_run = context.get("dag_run")
        run_conf = getattr(dag_run, "conf", None) or {}
        configured_observed_at = run_conf.get("observed_at")
        if configured_observed_at:
            observed_at = pendulum.parse(str(configured_observed_at)).in_timezone("Europe/Moscow").isoformat()
        else:
            observed_at = context["data_interval_end"].in_timezone("Europe/Moscow").isoformat()
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="serp_snapshot",
            attr_name="prepare_serp_skus",
            payload={"observed_at": observed_at, "tenant_id": tenant.tenant_id},
        ) or []

    @task(task_id="select_queries_per_sku", dag=dag, execution_timeout=timedelta(minutes=20))
    def select_queries_per_sku(payload: dict[str, Any]) -> dict[str, Any]:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="serp_snapshot",
            attr_name="select_queries_per_sku",
            payload={"payload": payload},
        )

    @task(task_id="collect_serp_per_sku", dag=dag, execution_timeout=timedelta(hours=3))
    def collect_serp_per_sku(payload: dict[str, Any]) -> dict[str, Any]:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="serp_snapshot",
            attr_name="enqueue_and_wait_serp_job",
            payload={"payload": payload},
        )

    @task(task_id="normalize_serp_competitors_per_sku", dag=dag, execution_timeout=timedelta(minutes=30))
    def normalize_serp_competitors_per_sku(payload: dict[str, Any]) -> dict[str, Any]:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="normalize_candidate_attributes_per_sku",
            attr_name="run_one",
            payload={"payload": payload},
        )

    @task(task_id="classify_serp_competitors_per_sku", dag=dag, execution_timeout=timedelta(minutes=30))
    def classify_serp_competitors_per_sku(payload: dict[str, Any]) -> dict[str, Any]:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="apply_hard_filters_per_sku",
            attr_name="run_one",
            payload={"payload": payload},
        )

    @task(task_id="finalize_serp_competitors_per_sku", dag=dag, execution_timeout=timedelta(minutes=30))
    def finalize_serp_competitors_per_sku(payload: dict[str, Any]) -> dict[str, Any]:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="finalize_price_ai_row",
            attr_name="run_one",
            payload={"payload": payload},
        )

    @task(task_id="validate_batch", dag=dag, execution_timeout=timedelta(minutes=30))
    def validate_batch(selected_payloads: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
        batch_id = next((row.get("batch_id") for row in selected_payloads if row.get("batch_id")), None)
        if not batch_id:
            raise RuntimeError("SERP batch has no active SKU payloads")
        summary = run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="serp_snapshot",
            attr_name="validate_serp_batch",
            payload={"batch_id": batch_id},
        )
        summary["sku_jobs"] = len(results)
        summary["sku_job_failures"] = sum(
            1 for row in results if row.get("status") not in {"completed", "partial"}
        )
        return summary

    sku_payloads = prepare_active_skus()
    selected = select_queries_per_sku.expand(payload=sku_payloads)
    results = collect_serp_per_sku.expand(payload=selected)
    normalized = normalize_serp_competitors_per_sku.expand(payload=results)
    classified = classify_serp_competitors_per_sku.expand(payload=normalized)
    finalized = finalize_serp_competitors_per_sku.expand(payload=classified)
    quality = validate_batch(selected, results)
    finalized >> quality
    return dag


for _tenant in active_tenants():
    _dag = build_serp_snapshot_dag(_tenant)
    if _dag is not None:
        globals()[_dag.dag_id] = _dag
