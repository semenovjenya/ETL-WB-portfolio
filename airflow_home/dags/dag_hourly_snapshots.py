"""
Hourly Airflow DAG for fast WB snapshot sources.

Flow:
  1) Sequentially execute fast source stages with a shared snapshot hour.
"""
from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.models.baseoperator import chain

from _tenant_factory import active_tenants, tenant_dag_id, tenant_tags
from _daily_pipeline.source_groups import (
    build_calendar_promotions_group,
    build_marketing_campaigns_group,
    build_supplier_orders_group,
    build_supplier_prices_group,
    build_supplier_sales_group,
    build_supplier_stocks_group,
    build_supplies_group,
    build_tariffs_group,
)
from _runtime_env import bootstrap_runtime_env

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


def build_hourly_snapshots_dag(tenant) -> DAG | None:
    schedule = tenant.schedules.get("hourly_snapshots")
    if not schedule:
        return None

    dag = DAG(
        tenant_dag_id(tenant.tenant_slug, "hourly_snapshots"),
        default_args=default_args,
        description="Tenant hourly ETL for fast WB snapshots with snapshot_hour grain",
        schedule=schedule,
        catchup=False,
        max_active_runs=1,
        tags=tenant_tags(tenant.tenant_slug, "wildberries", "hourly", "snapshots", "etl"),
    )

    hourly_fetch_kwargs = {"use_snapshot_hour": True}
    source_groups = [
        build_supplier_stocks_group(dag, tenant_id=tenant.tenant_id, fetch_op_kwargs=hourly_fetch_kwargs),
        build_supplier_sales_group(dag, tenant_id=tenant.tenant_id, fetch_op_kwargs=hourly_fetch_kwargs),
        build_supplier_orders_group(dag, tenant_id=tenant.tenant_id, fetch_op_kwargs=hourly_fetch_kwargs),
        build_supplies_group(dag, tenant_id=tenant.tenant_id, fetch_op_kwargs=hourly_fetch_kwargs),
        build_supplier_prices_group(dag, tenant_id=tenant.tenant_id, fetch_op_kwargs=hourly_fetch_kwargs),
        build_tariffs_group(dag, tenant_id=tenant.tenant_id, fetch_op_kwargs=hourly_fetch_kwargs),
        build_marketing_campaigns_group(dag, tenant_id=tenant.tenant_id, fetch_op_kwargs=hourly_fetch_kwargs),
        build_calendar_promotions_group(dag, tenant_id=tenant.tenant_id, fetch_op_kwargs=hourly_fetch_kwargs),
    ]

    chain(*source_groups)
    return dag


for _tenant in active_tenants():
    _dag = build_hourly_snapshots_dag(_tenant)
    if _dag is not None:
        globals()[_dag.dag_id] = _dag
