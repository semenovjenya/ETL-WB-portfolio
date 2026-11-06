from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

from _tenant_factory import active_tenants, tenant_dag_id, tenant_tags
from _tenant_ops import run_tenant_job
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


def _run_ml_job(tenant_id: str, module_name: str, attr_name: str) -> dict:
    return run_tenant_job(
        tenant_id=tenant_id,
        module_dir="ML",
        action="callable",
        module_name=module_name,
        attr_name=attr_name,
    )


def train_buyouts_7d_model_task(tenant_id: str, **context) -> dict:
    return _run_ml_job(tenant_id, "train_buyouts_7d", "run")


def train_orders_7d_model_task(tenant_id: str, **context) -> dict:
    return _run_ml_job(tenant_id, "train_orders_7d", "run")


def validate_ml_models_task(tenant_id: str, **context) -> dict:
    return _run_ml_job(tenant_id, "pipeline", "validate_models")


def publish_model_meta_task(tenant_id: str, **context) -> dict:
    return _run_ml_job(tenant_id, "pipeline", "publish_model_meta")


def build_ml_retrain_weekly_dag(tenant) -> DAG:
    dag = DAG(
        tenant_dag_id(tenant.tenant_slug, "ml_retrain_weekly"),
        default_args=default_args,
        description="Tenant weekly retrain for 1pager ML forecast models",
        schedule=tenant.schedules.get("ml_retrain_weekly") or "0 6 * * 1",
        catchup=False,
        max_active_runs=1,
        tags=tenant_tags(tenant.tenant_slug, "wildberries", "ml", "weekly", "retrain"),
    )

    train_buyouts_7d_model = PythonOperator(
        task_id="train_buyouts_7d_model",
        python_callable=train_buyouts_7d_model_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
        execution_timeout=timedelta(hours=2),
    )
    train_orders_7d_model = PythonOperator(
        task_id="train_orders_7d_model",
        python_callable=train_orders_7d_model_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
        execution_timeout=timedelta(hours=2),
    )
    validate_ml_models = PythonOperator(
        task_id="validate_ml_models",
        python_callable=validate_ml_models_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
        execution_timeout=timedelta(minutes=30),
    )
    publish_model_meta = PythonOperator(
        task_id="publish_model_meta",
        python_callable=publish_model_meta_task,
        dag=dag,
        op_kwargs={"tenant_id": tenant.tenant_id},
        execution_timeout=timedelta(minutes=30),
    )

    train_buyouts_7d_model >> train_orders_7d_model >> validate_ml_models >> publish_model_meta
    return dag


for _tenant in active_tenants():
    _dag = build_ml_retrain_weekly_dag(_tenant)
    globals()[_dag.dag_id] = _dag
