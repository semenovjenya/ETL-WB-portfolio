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


def _resolve_snapshot_hour(context: dict[str, Any]) -> str | None:
    data_interval_end = context.get("data_interval_end")
    if data_interval_end is None:
        return None
    return data_interval_end.in_timezone("Europe/Moscow").isoformat()


def _run_search_queries_stage(
    *,
    tenant_id: str,
    method_name: str,
    snapshot_hour: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"method_name": method_name}
    if snapshot_hour:
        payload["snapshot_hour"] = snapshot_hour
    return run_tenant_job(
        tenant_id=tenant_id,
        module_dir="search_queries",
        action="fetcher-method",
        module_name="fetch_search_queries",
        attr_name="SearchQueriesFetcher",
        payload=payload,
    ) or {}


def _run_marketing_stage(
    *,
    tenant_id: str,
    module_name: str,
    attr_name: str,
    method_name: str,
    snapshot_hour: str | None,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"method_name": method_name}
    if snapshot_hour:
        payload["snapshot_hour"] = snapshot_hour
    if extra_payload:
        payload.update(extra_payload)
    return run_tenant_job(
        tenant_id=tenant_id,
        module_dir="marketing",
        action="fetcher-method",
        module_name=module_name,
        attr_name=attr_name,
        payload=payload,
    ) or {}


def _next_stage_payload(previous_payload: dict[str, Any], stage_result: dict[str, Any], stage_name: str) -> dict[str, Any]:
    snapshot_hour = stage_result.get("snapshot_hour") or previous_payload.get("snapshot_hour")
    merged = dict(previous_payload)
    merged["snapshot_hour"] = snapshot_hour
    merged["last_stage"] = stage_name
    merged["last_result"] = stage_result
    merged["rate_limited_seen"] = bool(previous_payload.get("rate_limited_seen") or stage_result.get("rate_limited"))
    return merged


def _secondary_stage_skip_result(stage_payload: dict[str, Any], stage_name: str) -> dict[str, Any] | None:
    if not stage_payload.get("rate_limited_seen"):
        return None
    return {
        "snapshot_hour": stage_payload.get("snapshot_hour"),
        "skipped": True,
        "skip_reason": "rate_limited_seen",
        "stage": stage_name,
    }


def _merge_branch_payloads(
    prepared_payload: dict[str, Any],
    search_payload: dict[str, Any],
) -> dict[str, Any]:
    snapshot_hour = search_payload.get("snapshot_hour") or prepared_payload.get("snapshot_hour")
    return {
        "snapshot_hour": snapshot_hour,
        "search_report": search_payload,
    }


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=10),
    "start_date": pendulum.datetime(2024, 1, 1, tz="Europe/Moscow"),
}


def build_search_queries_dag(tenant) -> DAG:
    schedule = tenant.schedules.get("search_queries")
    if not schedule:
        return None

    dag = DAG(
        tenant_dag_id(tenant.tenant_slug, "search_queries"),
        default_args=default_args,
        description="Tenant WB search queries DAG: search-report stages plus query-demand marts",
        schedule=schedule,
        catchup=False,
        max_active_runs=1,
        tags=tenant_tags(tenant.tenant_slug, "wildberries", "search", "queries", "analytics"),
    )

    @task(task_id="prepare_context", dag=dag, execution_timeout=timedelta(minutes=30))
    def prepare_context() -> dict[str, Any]:
        context = get_current_context()
        snapshot_hour = _resolve_snapshot_hour(context)
        return _run_search_queries_stage(
            tenant_id=tenant.tenant_id,
            method_name="prepare",
            snapshot_hour=snapshot_hour,
        )

    @task(task_id="fetch_report", dag=dag, execution_timeout=timedelta(hours=4))
    def fetch_report(stage_payload: dict[str, Any]) -> dict[str, Any]:
        skipped = _secondary_stage_skip_result(stage_payload, "report")
        if skipped is not None:
            return _next_stage_payload(stage_payload, skipped, "report")
        result = _run_search_queries_stage(
            tenant_id=tenant.tenant_id,
            method_name="run_report_stage",
            snapshot_hour=stage_payload.get("snapshot_hour"),
        )
        return _next_stage_payload(stage_payload, result, "report")

    @task(task_id="fetch_details", dag=dag, execution_timeout=timedelta(hours=4))
    def fetch_details(stage_payload: dict[str, Any]) -> dict[str, Any]:
        skipped = _secondary_stage_skip_result(stage_payload, "details")
        if skipped is not None:
            return _next_stage_payload(stage_payload, skipped, "details")
        result = _run_search_queries_stage(
            tenant_id=tenant.tenant_id,
            method_name="run_details_stage",
            snapshot_hour=stage_payload.get("snapshot_hour"),
        )
        return _next_stage_payload(stage_payload, result, "details")

    @task(task_id="fetch_groups", dag=dag, execution_timeout=timedelta(hours=4))
    def fetch_groups(stage_payload: dict[str, Any]) -> dict[str, Any]:
        skipped = _secondary_stage_skip_result(stage_payload, "groups")
        if skipped is not None:
            return _next_stage_payload(stage_payload, skipped, "groups")
        result = _run_search_queries_stage(
            tenant_id=tenant.tenant_id,
            method_name="run_groups_stage",
            snapshot_hour=stage_payload.get("snapshot_hour"),
        )
        return _next_stage_payload(stage_payload, result, "groups")

    @task(task_id="fetch_search_texts", dag=dag, execution_timeout=timedelta(hours=6))
    def fetch_search_texts(stage_payload: dict[str, Any]) -> dict[str, Any]:
        result = _run_search_queries_stage(
            tenant_id=tenant.tenant_id,
            method_name="run_search_texts_stage",
            snapshot_hour=stage_payload.get("snapshot_hour"),
        )
        return _next_stage_payload(stage_payload, result, "search_texts")

    @task(task_id="fetch_order_search_texts", dag=dag, execution_timeout=timedelta(hours=2))
    def fetch_order_search_texts(stage_payload: dict[str, Any]) -> dict[str, Any]:
        result = _run_search_queries_stage(
            tenant_id=tenant.tenant_id,
            method_name="run_order_search_texts_stage",
            snapshot_hour=stage_payload.get("snapshot_hour"),
        )
        return _next_stage_payload(stage_payload, result, "order_search_texts")

    @task(task_id="fetch_orders", dag=dag, execution_timeout=timedelta(hours=8))
    def fetch_orders(stage_payload: dict[str, Any]) -> dict[str, Any]:
        result = _run_search_queries_stage(
            tenant_id=tenant.tenant_id,
            method_name="run_orders_stage",
            snapshot_hour=stage_payload.get("snapshot_hour"),
        )
        return _next_stage_payload(stage_payload, result, "orders")

    @task(task_id="refresh_query_demand_marts", dag=dag, execution_timeout=timedelta(hours=2))
    def refresh_query_demand_marts(stage_payload: dict[str, Any]) -> dict[str, Any]:
        result = _run_marketing_stage(
            tenant_id=tenant.tenant_id,
            module_name="marts.refresh_query_demand_marts",
            attr_name="QueryDemandMartsRefresher",
            method_name="run",
            snapshot_hour=stage_payload.get("snapshot_hour"),
        )
        return _next_stage_payload(stage_payload, result, "refresh_query_demand_marts")

    @task(task_id="validate_query_demand_marts", dag=dag, execution_timeout=timedelta(hours=1))
    def validate_query_demand_marts(stage_payload: dict[str, Any]) -> dict[str, Any]:
        result = _run_marketing_stage(
            tenant_id=tenant.tenant_id,
            module_name="marts.validate_query_demand_marts",
            attr_name="QueryDemandMartsValidator",
            method_name="run",
            snapshot_hour=stage_payload.get("snapshot_hour"),
        )
        return _next_stage_payload(stage_payload, result, "validate_query_demand_marts")

    @task(task_id="join_branches", dag=dag, execution_timeout=timedelta(minutes=15))
    def join_branches(prepared_payload: dict[str, Any], search_payload: dict[str, Any]) -> dict[str, Any]:
        return _merge_branch_payloads(prepared_payload, search_payload)

    @task(task_id="validate_load", dag=dag, execution_timeout=timedelta(minutes=30))
    def validate_load(stage_payload: dict[str, Any]) -> dict[str, Any]:
        search_result = _run_search_queries_stage(
            tenant_id=tenant.tenant_id,
            method_name="validate_snapshot",
            snapshot_hour=stage_payload.get("snapshot_hour"),
        )
        mart_validation = stage_payload.get("last_result") or {}
        loaded_rows = sum(
            int(search_result.get(key) or 0)
            for key in (
                "report_overview",
                "report_groups",
                "groups",
                "details",
                "search_texts",
                "orders_total_daily",
                "orders_text_daily",
            )
        )
        result = {
            "snapshot_hour": stage_payload.get("snapshot_hour"),
            "search_report": search_result,
            "query_demand_marts": mart_validation,
        }
        if loaded_rows == 0:
            raise RuntimeError(f"WB search-report snapshot contains zero loaded rows: {result}")
        if mart_validation.get("status") == "error":
            raise RuntimeError(f"WB query-demand validation failed: {result}")
        return result

    prepared = prepare_context()
    order_search_texts = fetch_order_search_texts(prepared)
    orders = fetch_orders(order_search_texts)

    report = fetch_report(orders)
    details = fetch_details(report)
    groups = fetch_groups(details)

    joined = join_branches(prepared, groups)
    query_demand_marts = refresh_query_demand_marts(joined)
    query_demand_marts_validated = validate_query_demand_marts(query_demand_marts)
    validate_load(query_demand_marts_validated)

    return dag


for _tenant in active_tenants():
    _dag = build_search_queries_dag(_tenant)
    if _dag is not None:
        globals()[_dag.dag_id] = _dag
