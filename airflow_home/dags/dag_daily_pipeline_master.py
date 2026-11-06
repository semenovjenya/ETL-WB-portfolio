"""
Single Airflow DAG for the WB daily source pipeline.

Flow:
  1) Execute shared source stages sequentially.
  2) Split into:
     - core branch with strict freshness/DQ and critical marts
     - marketing branch with best-effort source stages and optional marts
"""
from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.models.baseoperator import chain
from airflow.operators.python import PythonOperator, ShortCircuitOperator
from airflow.utils.trigger_rule import TriggerRule

from _daily_pipeline.db_tasks import (
    marketing_branch_outcome_task,
    refresh_marketing_marts_task,
    refresh_mart_task,
    refresh_price_decision_task,
    refresh_profit_calculator_task,
    strict_freshness_gate_core_task,
    strict_freshness_gate_marketing_task,
    validate_marketing_marts_task,
    validate_marketing_sources_task,
    validate_mart_task,
    validate_price_decision_task,
    validate_profit_calculator_task,
    validate_source_quality_core_task,
)
from _daily_pipeline.source_groups import (
    CORE_BRANCH_SOURCE_GROUP_BUILDERS,
    MARKETING_SOURCE_GROUP_BUILDERS,
    PRE_BRANCH_SOURCE_GROUP_BUILDERS,
)
from _runtime_env import bootstrap_runtime_env
from _tenant_factory import active_tenants, tenant_dag_id, tenant_tags

bootstrap_runtime_env()

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
    "retry_delay": timedelta(minutes=5),
    "start_date": pendulum.datetime(2024, 1, 1, tz="Europe/Moscow"),
}


def _marketing_marts_ready(**context) -> bool:
    ti = context["ti"]
    freshness_ok = bool(ti.xcom_pull(task_ids="strict_freshness_gate_marketing"))
    validation_ok = bool(ti.xcom_pull(task_ids="validate_marketing_sources"))
    return freshness_ok and validation_ok


def build_daily_pipeline_dag(tenant) -> DAG:
    dag = DAG(
        tenant_dag_id(tenant.tenant_slug, "daily_pipeline_master"),
        default_args=default_args,
        description="Tenant daily ETL: shared sources -> core strict branch + best-effort marketing branch",
        schedule=tenant.schedules.get("daily_pipeline_master") or "30 7 * * *",
        catchup=False,
        max_active_runs=1,
        tags=tenant_tags(tenant.tenant_slug, "wildberries", "master", "daily", "etl"),
    )

    pre_branch_groups = [builder(dag, tenant_id=tenant.tenant_id) for builder in PRE_BRANCH_SOURCE_GROUP_BUILDERS]
    core_branch_groups = [builder(dag, tenant_id=tenant.tenant_id) for builder in CORE_BRANCH_SOURCE_GROUP_BUILDERS]
    marketing_branch_groups = [builder(dag, tenant_id=tenant.tenant_id) for builder in MARKETING_SOURCE_GROUP_BUILDERS]

    strict_freshness_gate_core = PythonOperator(
        task_id="strict_freshness_gate_core",
        python_callable=strict_freshness_gate_core_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    validate_source_quality_core = PythonOperator(
        task_id="validate_source_quality_core",
        python_callable=validate_source_quality_core_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    strict_freshness_gate_marketing = PythonOperator(
        task_id="strict_freshness_gate_marketing",
        python_callable=strict_freshness_gate_marketing_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    validate_marketing_sources = PythonOperator(
        task_id="validate_marketing_sources",
        python_callable=validate_marketing_sources_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    marketing_marts_ready = ShortCircuitOperator(
        task_id="marketing_marts_ready",
        python_callable=_marketing_marts_ready,
        dag=dag,
        ignore_downstream_trigger_rules=False,
    )
    refresh_mart = PythonOperator(
        task_id="refresh_mart_ai_sales_planning",
        python_callable=refresh_mart_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    validate_mart = PythonOperator(
        task_id="validate_mart_ai_sales_planning",
        python_callable=validate_mart_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    refresh_profit_calculator = PythonOperator(
        task_id="refresh_profit_calculator",
        python_callable=refresh_profit_calculator_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    validate_profit_calculator = PythonOperator(
        task_id="validate_profit_calculator",
        python_callable=validate_profit_calculator_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    refresh_marketing_marts = PythonOperator(
        task_id="refresh_marketing_marts",
        python_callable=refresh_marketing_marts_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    validate_marketing_marts = PythonOperator(
        task_id="validate_marketing_marts",
        python_callable=validate_marketing_marts_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    marketing_branch_outcome = PythonOperator(
        task_id="marketing_branch_outcome",
        python_callable=marketing_branch_outcome_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
        trigger_rule=TriggerRule.ALL_DONE,
    )
    refresh_price_decision = PythonOperator(
        task_id="refresh_price_decision_mart",
        python_callable=refresh_price_decision_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )
    validate_price_decision = PythonOperator(
        task_id="validate_price_decision_mart",
        python_callable=validate_price_decision_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
    )

    chain(*pre_branch_groups)

    sales_funnel_group = pre_branch_groups[-1]
    sales_funnel_group >> core_branch_groups[0]
    sales_funnel_group >> marketing_branch_groups[0]

    chain(
        *core_branch_groups,
        strict_freshness_gate_core,
        validate_source_quality_core,
        refresh_mart,
        validate_mart,
        refresh_profit_calculator,
        validate_profit_calculator,
        refresh_price_decision,
        validate_price_decision,
    )

    chain(
        *marketing_branch_groups,
        strict_freshness_gate_marketing,
        validate_marketing_sources,
        marketing_marts_ready,
        refresh_marketing_marts,
        validate_marketing_marts,
        marketing_branch_outcome,
    )

    marketing_marts_ready >> marketing_branch_outcome

    return dag


for _tenant in active_tenants():
    _dag = build_daily_pipeline_dag(_tenant)
    globals()[_dag.dag_id] = _dag
