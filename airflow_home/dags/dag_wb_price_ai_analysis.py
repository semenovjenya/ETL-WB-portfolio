from __future__ import annotations

from datetime import date, timedelta

import pendulum
from airflow import DAG
from airflow.decorators import task
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
    "retries": 0,
    "retry_delay": timedelta(minutes=5),
    "start_date": pendulum.datetime(2024, 1, 1, tz="Europe/Moscow"),
}


def build_wb_price_ai_analysis_dag(tenant) -> DAG:
    dag = DAG(
        tenant_dag_id(tenant.tenant_slug, "price_ai_analysis"),
        default_args=default_args,
        description="Tenant per-SKU AI price analysis pipeline with mapped SEO and competitor tasks",
        schedule=tenant.schedules.get("price_ai_analysis"),
        catchup=False,
        max_active_runs=1,
        tags=tenant_tags(tenant.tenant_slug, "wildberries", "price", "analysis", "ai"),
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

    @task(task_id="prepare_active_sku_inputs", dag=dag)
    def prepare_active_sku_inputs() -> list[dict]:
        result = run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="prepare_active_skus",
            attr_name="run",
        )
        return result or []

    @task(task_id="generate_seo_keywords_per_sku", dag=dag)
    def generate_seo_keywords_per_sku(payload: dict) -> dict:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="generate_seo_keywords",
            attr_name="run_one",
            payload={"payload": payload},
        )

    @task(task_id="fetch_raw_competitors_per_sku", dag=dag)
    def fetch_raw_competitors_per_sku(seo_payload: dict) -> dict:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="fetch_raw_competitors_per_sku",
            attr_name="run_one",
            payload={"payload": seo_payload},
        )

    @task(task_id="normalize_candidate_attributes_per_sku", dag=dag)
    def normalize_candidate_attributes_per_sku(raw_payload: dict) -> dict:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="normalize_candidate_attributes_per_sku",
            attr_name="run_one",
            payload={"payload": raw_payload},
        )

    @task(task_id="apply_hard_filters_per_sku", dag=dag)
    def apply_hard_filters_per_sku(normalized_payload: dict) -> dict:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="apply_hard_filters_per_sku",
            attr_name="run_one",
            payload={"payload": normalized_payload},
        )

    @task(task_id="score_relevance_with_llm_per_sku", dag=dag)
    def score_relevance_with_llm_per_sku(filtered_payload: dict) -> dict:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="score_relevance_with_llm_per_sku",
            attr_name="run_one",
            payload={"payload": filtered_payload},
        )

    @task(task_id="grade_visual_match_per_sku", dag=dag)
    def grade_visual_match_per_sku(relevance_payload: dict) -> dict:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="grade_visual_match_per_sku",
            attr_name="run_one",
            payload={"payload": relevance_payload},
        )

    @task(task_id="finalize_price_ai_row_per_sku", dag=dag)
    def finalize_price_ai_row_per_sku(vision_payload: dict) -> dict:
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="finalize_price_ai_row",
            attr_name="run_one",
            payload={"payload": vision_payload},
        )

    @task(task_id="merge_run_stats", dag=dag)
    def merge_run_stats(sku_payloads: list[dict]) -> dict:
        run_date = date.today().isoformat()
        if sku_payloads:
            run_date = str(sku_payloads[0]["run_date"])
        return run_tenant_job(
            tenant_id=tenant.tenant_id,
            module_dir="wb_price_ai_analysis",
            action="callable",
            module_name="merge_run_stats",
            attr_name="run",
            payload={"run_date": run_date},
        )

    sku_payloads = prepare_active_sku_inputs()
    seo_results = generate_seo_keywords_per_sku.expand(payload=sku_payloads)
    raw_results = fetch_raw_competitors_per_sku.expand(seo_payload=seo_results)
    normalized_results = normalize_candidate_attributes_per_sku.expand(raw_payload=raw_results)
    filtered_results = apply_hard_filters_per_sku.expand(normalized_payload=normalized_results)
    relevance_results = score_relevance_with_llm_per_sku.expand(filtered_payload=filtered_results)
    vision_results = grade_visual_match_per_sku.expand(relevance_payload=relevance_results)
    finalized_rows = finalize_price_ai_row_per_sku.expand(vision_payload=vision_results)
    merged_stats = merge_run_stats(sku_payloads)

    build_snapshot >> parse_wb_link_prices >> sku_payloads
    sku_payloads >> seo_results >> raw_results >> normalized_results >> filtered_results >> relevance_results >> vision_results >> finalized_rows >> merged_stats
    return dag


for _tenant in active_tenants():
    _dag = build_wb_price_ai_analysis_dag(_tenant)
    globals()[_dag.dag_id] = _dag
