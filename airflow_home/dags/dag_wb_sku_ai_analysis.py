from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

from _tenant_factory import active_tenants, tenant_dag_id, tenant_tags
from _tenant_ops import run_tenant_job
from _runtime_env import bootstrap_runtime_env

bootstrap_runtime_env()


def run_wb_sku_ai_analysis_task(tenant_id: str, **context) -> None:
    result = run_tenant_job(
        tenant_id=tenant_id,
        module_dir="WB_sku_ai_analysis",
        action="callable",
        module_name="fetch_wb_sku_ai_analysis",
        attr_name="run_fetcher",
    )
    context["ti"].xcom_push(key="result", value=result)


def run_wb_link_prices_task(tenant_id: str, **context) -> None:
    result = run_tenant_job(
        tenant_id=tenant_id,
        module_dir="WB_sku_ai_analysis",
        action="callable",
        module_name="parse_wb_link_prices",
        attr_name="run_parser",
    )
    context["ti"].xcom_push(key="wb_link_prices_result", value=result)


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "start_date": pendulum.datetime(2024, 1, 1, tz="Europe/Moscow"),
}


def build_wb_sku_ai_analysis_dag(tenant) -> DAG:
    dag = DAG(
        tenant_dag_id(tenant.tenant_slug, "sku_ai_analysis"),
        default_args=default_args,
        description="Tenant-wide SKU AI snapshot with WB links and product enrichments",
        schedule=tenant.schedules.get("sku_ai_analysis") or "45 8 * * *",
        catchup=False,
        max_active_runs=1,
        tags=tenant_tags(tenant.tenant_slug, "wildberries", "sku", "analysis", "ai"),
    )

    build_snapshot = PythonOperator(
        task_id="build_wb_sku_ai_analysis_snapshot",
        python_callable=run_wb_sku_ai_analysis_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
        execution_timeout=timedelta(hours=3),
    )

    parse_wb_link_prices = PythonOperator(
        task_id="parse_wb_link_prices",
        python_callable=run_wb_link_prices_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
        execution_timeout=timedelta(hours=1),
    )

    build_snapshot >> parse_wb_link_prices
    return dag


for _tenant in active_tenants():
    _dag = build_wb_sku_ai_analysis_dag(_tenant)
    globals()[_dag.dag_id] = _dag
