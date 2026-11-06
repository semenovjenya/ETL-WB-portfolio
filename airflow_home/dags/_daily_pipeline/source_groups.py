from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from airflow.operators.python import PythonOperator
from airflow.utils.task_group import TaskGroup

from _daily_pipeline.common import resolve_snapshot_hour
from _tenant_ops import run_tenant_job

logger = logging.getLogger(__name__)

RETRY_5M = {"retries": 2, "retry_delay": timedelta(minutes=5)}
RETRY_10M = {"retries": 1, "retry_delay": timedelta(minutes=10)}
RETRY_15M = {"retries": 1, "retry_delay": timedelta(minutes=15)}
RETRY_30M = {"retries": 1, "retry_delay": timedelta(minutes=30)}
SUPPLIER_PRICES_TASK_ARGS = {
    **RETRY_30M,
    "execution_timeout": timedelta(hours=8),
}
SALES_FUNNEL_TASK_ARGS = {
    **RETRY_30M,
    "execution_timeout": timedelta(hours=72),
}
MARKETING_CAMPAIGNS_TASK_ARGS = {
    **RETRY_15M,
    "execution_timeout": timedelta(hours=8),
}
MARKETING_STATS_TASK_ARGS = {
    **RETRY_30M,
    "execution_timeout": timedelta(hours=12),
}
MARKETING_NORMQUERY_TASK_ARGS = {
    **RETRY_15M,
    "execution_timeout": timedelta(hours=8),
}
MARKETING_NORMQUERY_STATS_TASK_ARGS = {
    **RETRY_30M,
    "execution_timeout": timedelta(hours=12),
}


def _run_progress_check(
    tenant_id: str,
    module_dir: str,
    module_name: str,
    fetcher_attr: str,
    action: str,
    method_name: str,
    xcom_key: str,
    missing_message: str,
    found_message: str,
    **context,
) -> None:
    last_value = run_tenant_job(
        tenant_id=tenant_id,
        module_dir=module_dir,
        action=action,
        module_name=module_name,
        attr_name=fetcher_attr,
        payload={"method_name": method_name},
    )
    if last_value:
        logger.info(found_message, last_value)
        context["ti"].xcom_push(key=xcom_key, value=last_value)
    else:
        logger.info(missing_message)
        context["ti"].xcom_push(key=xcom_key, value=None)


def _run_fetcher_task(
    tenant_id: str,
    module_dir: str,
    module_name: str,
    fetcher_attr: str,
    start_message: str,
    success_message: str,
    run_kwargs: dict | None = None,
    use_snapshot_hour: bool = False,
    **context,
) -> None:
    logger.info(start_message)
    effective_run_kwargs = dict(run_kwargs or {})
    if use_snapshot_hour:
        effective_run_kwargs["snapshot_hour"] = resolve_snapshot_hour(context).isoformat()
    run_tenant_job(
        tenant_id=tenant_id,
        module_dir=module_dir,
        action="fetcher-run",
        module_name=module_name,
        attr_name=fetcher_attr,
        payload=effective_run_kwargs,
    )
    logger.info(success_message)


def _run_fetcher_method_task(
    tenant_id: str,
    module_dir: str,
    module_name: str,
    fetcher_attr: str,
    method_name: str,
    start_message: str,
    success_message: str,
    run_kwargs: dict | None = None,
    use_snapshot_hour: bool = False,
    **context,
) -> Any:
    logger.info(start_message)
    payload = {"method_name": method_name, **(run_kwargs or {})}
    if use_snapshot_hour:
        payload["snapshot_hour"] = resolve_snapshot_hour(context).isoformat()
    result = run_tenant_job(
        tenant_id=tenant_id,
        module_dir=module_dir,
        action="fetcher-method",
        module_name=module_name,
        attr_name=fetcher_attr,
        payload=payload,
    )
    logger.info(success_message)
    return result


def _run_marketing_stage_task(
    tenant_id: str,
    module_dir: str,
    module_name: str,
    fetcher_attr: str,
    method_name: str,
    start_message: str,
    success_message: str,
    run_kwargs: dict | None = None,
    use_snapshot_hour: bool = False,
    **context,
) -> dict[str, Any]:
    payload = {"method_name": method_name, **(run_kwargs or {})}
    snapshot_hour = None
    if use_snapshot_hour:
        snapshot_hour = resolve_snapshot_hour(context).isoformat()
        payload["snapshot_hour"] = snapshot_hour
    try:
        result = _run_fetcher_method_task(
            tenant_id=tenant_id,
            module_dir=module_dir,
            module_name=module_name,
            fetcher_attr=fetcher_attr,
            method_name=method_name,
            start_message=start_message,
            success_message=success_message,
            run_kwargs=run_kwargs,
            use_snapshot_hour=use_snapshot_hour,
            **context,
        )
        return {
            "status": "success",
            "method_name": method_name,
            "snapshot_hour": snapshot_hour,
            "result": result,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Marketing stage %s.%s завершился ошибкой: %s", module_name, method_name, exc)
        progress = {}
        if snapshot_hour is not None:
            try:
                progress = run_tenant_job(
                    tenant_id=tenant_id,
                    module_dir=module_dir,
                    action="fetcher-method",
                    module_name=module_name,
                    attr_name=fetcher_attr,
                    payload={"method_name": "_load_progress", "snapshot_hour": snapshot_hour},
                ) or {}
            except Exception:  # noqa: BLE001
                progress = {}
        return {
            "status": "rate_limited_or_failed",
            "method_name": method_name,
            "snapshot_hour": snapshot_hour,
            "error": str(exc),
            "progress": progress,
            "last_rate_limit": (progress or {}).get("last_rate_limit"),
        }


def _completion_task(message: str, **context) -> None:
    logger.info(message)


def supplier_stocks_check_progress_task(tenant_id: str, **context) -> None:
    logger.info("Проверка прогресса выгрузки остатков")
    _run_progress_check(
        tenant_id=tenant_id,
        module_dir="stocks",
        module_name="fetch_stocks",
        fetcher_attr="StocksFetcher",
        action="fetcher-db-method",
        method_name="get_last_change_date_from",
        xcom_key="last_change_date_from",
        missing_message="Прогресс не найден, будет использована начальная дата",
        found_message="Последний dateFrom в прогрессе: %s",
        **context,
    )


def supplier_stocks_fetch_stocks_data_task(tenant_id: str, use_snapshot_hour: bool = False, **context) -> None:
    _run_fetcher_task(
        tenant_id=tenant_id,
        module_dir="stocks",
        module_name="fetch_stocks",
        fetcher_attr="StocksFetcher",
        start_message="Начало выгрузки остатков supplier/stocks",
        success_message="stocks успешно выгружены",
        run_kwargs={"full_snapshot": False},
        use_snapshot_hour=use_snapshot_hour,
        **context,
    )


def supplier_stocks_update_progress_task(**context) -> None:
    _completion_task("Выгрузка остатков завершена, прогресс обновлён в процессе выполнения")


def supplier_sales_check_progress_task(tenant_id: str, **context) -> None:
    logger.info("Проверка прогресса выгрузки продаж")
    _run_progress_check(
        tenant_id=tenant_id,
        module_dir="sales",
        module_name="fetch_sales",
        fetcher_attr="SalesFetcher",
        action="fetcher-db-method",
        method_name="get_last_change_date_from",
        xcom_key="last_change_date_from",
        missing_message="Прогресс не найден, будет использована начальная дата",
        found_message="Последний dateFrom в прогрессе: %s",
        **context,
    )


def supplier_sales_fetch_sales_data_task(tenant_id: str, use_snapshot_hour: bool = False, **context) -> None:
    _run_fetcher_task(
        tenant_id=tenant_id,
        module_dir="sales",
        module_name="fetch_sales",
        fetcher_attr="SalesFetcher",
        start_message="Начало выгрузки продаж supplier/sales",
        success_message="sales успешно выгружены",
        run_kwargs={"full_snapshot": False},
        use_snapshot_hour=use_snapshot_hour,
        **context,
    )


def supplier_sales_update_progress_task(**context) -> None:
    _completion_task("Выгрузка продаж завершена")


def supplier_orders_check_progress_task(tenant_id: str, **context) -> None:
    logger.info("Проверка прогресса выгрузки заказов")
    _run_progress_check(
        tenant_id=tenant_id,
        module_dir="orders",
        module_name="fetch_orders",
        fetcher_attr="OrdersFetcher",
        action="fetcher-db-method",
        method_name="get_last_change_date_from",
        xcom_key="last_change_date_from",
        missing_message="Прогресс не найден, будет использована начальная дата",
        found_message="Последний dateFrom в прогрессе: %s",
        **context,
    )


def supplier_orders_fetch_orders_data_task(tenant_id: str, use_snapshot_hour: bool = False, **context) -> None:
    _run_fetcher_task(
        tenant_id=tenant_id,
        module_dir="orders",
        module_name="fetch_orders",
        fetcher_attr="OrdersFetcher",
        start_message="Начало выгрузки заказов supplier/orders",
        success_message="orders успешно выгружены",
        run_kwargs={"full_snapshot": False},
        use_snapshot_hour=use_snapshot_hour,
        **context,
    )


def supplier_orders_update_progress_task(**context) -> None:
    _completion_task("Выгрузка заказов завершена")


def supplies_check_progress_task(tenant_id: str, **context) -> None:
    logger.info("Проверка прогресса выгрузки поставок")
    _run_progress_check(
        tenant_id=tenant_id,
        module_dir="supplies",
        module_name="fetch_supplies",
        fetcher_attr="SuppliesFetcher",
        action="fetcher-db-method",
        method_name="get_last_create_date_from",
        xcom_key="last_create_date",
        missing_message="Прогресс не найден, будет использована начальная дата",
        found_message="Последний createDateFrom в прогрессе: %s",
        **context,
    )


def supplies_fetch_supplies_data_task(tenant_id: str, use_snapshot_hour: bool = False, **context) -> None:
    _run_fetcher_task(
        tenant_id=tenant_id,
        module_dir="supplies",
        module_name="fetch_supplies",
        fetcher_attr="SuppliesFetcher",
        start_message="Начало выгрузки поставок WB (supplies)",
        success_message="supplies успешно выгружены",
        run_kwargs={"full_snapshot": False},
        use_snapshot_hour=use_snapshot_hour,
        **context,
    )


def supplies_update_progress_task(**context) -> None:
    _completion_task("Выгрузка поставок завершена")


def supplier_prices_fetch_prices_data_task(tenant_id: str, use_snapshot_hour: bool = False, **context) -> None:
    _run_fetcher_task(
        tenant_id=tenant_id,
        module_dir="prices",
        module_name="fetch_prices",
        fetcher_attr="PricesFetcher",
        start_message="Начало выгрузки цен list/goods/filter",
        success_message="prices успешно выгружены",
        use_snapshot_hour=use_snapshot_hour,
        **context,
    )


def sales_funnel_fetch_funnel_90d_daily_task(tenant_id: str, **context) -> None:
    logger.info("Запуск выгрузки воронки продаж по дням за 90 дней")
    run_tenant_job(
        tenant_id=tenant_id,
        module_dir="sales_funnel",
        action="callable",
        module_name="fetch_sales_funnel_90d_daily",
        attr_name="run_90d_daily",
        payload={"days": 90, "save_json": False},
    )
    logger.info("Воронка по дням за 90 дней выгружена")


def report_detail_check_progress_task(tenant_id: str, **context) -> None:
    logger.info("Проверка прогресса загрузки данных")
    last_date = run_tenant_job(
        tenant_id=tenant_id,
        module_dir="finance",
        action="fetcher-method",
        module_name="fetch_report_detail",
        attr_name="ReportDetailFetcher",
        payload={"method_name": "load_progress"},
    )
    if last_date:
        logger.info("Последняя обработанная дата: %s", last_date)
        context["ti"].xcom_push(key="last_processed_date", value=last_date)
    else:
        logger.info("Прогресс не найден, будет использована начальная дата")
        context["ti"].xcom_push(key="last_processed_date", value=None)


def report_detail_fetch_report_data_task(tenant_id: str, **context) -> None:
    logger.info("Начало gap-aware получения данных финансовых отчетов")
    run_tenant_job(
        tenant_id=tenant_id,
        module_dir="finance",
        action="fetcher-run",
        module_name="fetch_report_detail",
        attr_name="ReportDetailFetcher",
        payload={},
    )
    logger.info("Данные успешно получены и сохранены")


def report_detail_update_progress_task(**context) -> None:
    _completion_task("Прогресс обновлен в процессе загрузки данных")


def tariffs_fetch_tariffs_data_task(tenant_id: str, use_snapshot_hour: bool = False, **context) -> None:
    _run_fetcher_task(
        tenant_id=tenant_id,
        module_dir="tariffs",
        module_name="fetch_tariffs",
        fetcher_attr="TariffsFetcher",
        start_message="Начало выгрузки тарифов WB",
        success_message="tariffs успешно выгружены",
        use_snapshot_hour=use_snapshot_hour,
        **context,
    )


def marketing_campaigns_fetch_ids_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_campaigns",
        fetcher_attr="CampaignsFetcher",
        method_name="fetch_ids",
        start_message="Начало fetch_ids для marketing_campaigns",
        success_message="marketing_campaigns.fetch_ids завершён",
        use_snapshot_hour=True,
        **context,
    )


def marketing_campaigns_fetch_details_batches_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_campaigns",
        fetcher_attr="CampaignsFetcher",
        method_name="fetch_details_batches",
        start_message="Начало fetch_details_batches для marketing_campaigns",
        success_message="marketing_campaigns.fetch_details_batches завершён",
        use_snapshot_hour=True,
        **context,
    )


def marketing_campaigns_finalize_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_campaigns",
        fetcher_attr="CampaignsFetcher",
        method_name="finalize",
        start_message="Начало finalize для marketing_campaigns",
        success_message="marketing_campaigns.finalize завершён",
        use_snapshot_hour=True,
        **context,
    )


def marketing_stats_fetch_balance_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_marketing_stats",
        fetcher_attr="MarketingStatsFetcher",
        method_name="fetch_balance_stage",
        start_message="Начало fetch_balance для marketing_stats",
        success_message="marketing_stats.fetch_balance завершён",
        use_snapshot_hour=True,
        **context,
    )


def marketing_stats_fetch_upd_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_marketing_stats",
        fetcher_attr="MarketingStatsFetcher",
        method_name="fetch_upd_stage",
        start_message="Начало fetch_upd для marketing_stats",
        success_message="marketing_stats.fetch_upd завершён",
        run_kwargs={"days_back": 31},
        use_snapshot_hour=True,
        **context,
    )


def marketing_stats_fetch_payments_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_marketing_stats",
        fetcher_attr="MarketingStatsFetcher",
        method_name="fetch_payments_stage",
        start_message="Начало fetch_payments для marketing_stats",
        success_message="marketing_stats.fetch_payments завершён",
        run_kwargs={"days_back": 31},
        use_snapshot_hour=True,
        **context,
    )


def marketing_stats_fetch_budget_batches_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_marketing_stats",
        fetcher_attr="MarketingStatsFetcher",
        method_name="fetch_budget_batches",
        start_message="Начало fetch_budget_batches для marketing_stats",
        success_message="marketing_stats.fetch_budget_batches завершён",
        use_snapshot_hour=True,
        **context,
    )


def marketing_stats_fetch_fullstats_batches_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_marketing_stats",
        fetcher_attr="MarketingStatsFetcher",
        method_name="fetch_fullstats_batches",
        start_message="Начало fetch_fullstats_batches для marketing_stats",
        success_message="marketing_stats.fetch_fullstats_batches завершён",
        run_kwargs={"days_back": 31},
        use_snapshot_hour=True,
        **context,
    )


def marketing_stats_finalize_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_marketing_stats",
        fetcher_attr="MarketingStatsFetcher",
        method_name="finalize",
        start_message="Начало finalize для marketing_stats",
        success_message="marketing_stats.finalize завершён",
        use_snapshot_hour=True,
        **context,
    )


def marketing_normquery_prepare_pairs_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_normquery",
        fetcher_attr="NormqueryFetcher",
        method_name="prepare_pairs",
        start_message="Начало prepare_pairs для marketing_normquery",
        success_message="marketing_normquery.prepare_pairs завершён",
        use_snapshot_hour=True,
        **context,
    )


def marketing_normquery_fetch_batches_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_normquery",
        fetcher_attr="NormqueryFetcher",
        method_name="fetch_batches",
        start_message="Начало fetch_batches для marketing_normquery",
        success_message="marketing_normquery.fetch_batches завершён",
        use_snapshot_hour=True,
        **context,
    )


def marketing_normquery_finalize_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_normquery",
        fetcher_attr="NormqueryFetcher",
        method_name="finalize",
        start_message="Начало finalize для marketing_normquery",
        success_message="marketing_normquery.finalize завершён",
        use_snapshot_hour=True,
        **context,
    )


def marketing_normquery_stats_fetch_v0_batches_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_normquery_stats",
        fetcher_attr="NormqueryStatsFetcher",
        method_name="fetch_v0_batches",
        start_message="Начало fetch_v0_batches для marketing_normquery_stats",
        success_message="marketing_normquery_stats.fetch_v0_batches завершён",
        run_kwargs={"days": 7},
        use_snapshot_hour=True,
        **context,
    )


def marketing_normquery_stats_fetch_v1_batches_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_normquery_stats",
        fetcher_attr="NormqueryStatsFetcher",
        method_name="fetch_v1_batches",
        start_message="Начало fetch_v1_batches для marketing_normquery_stats",
        success_message="marketing_normquery_stats.fetch_v1_batches завершён",
        run_kwargs={"days": 7},
        use_snapshot_hour=True,
        **context,
    )


def marketing_normquery_stats_finalize_task(tenant_id: str, **context) -> dict[str, Any]:
    return _run_marketing_stage_task(
        tenant_id=tenant_id,
        module_dir="marketing",
        module_name="fetch_normquery_stats",
        fetcher_attr="NormqueryStatsFetcher",
        method_name="finalize",
        start_message="Начало finalize для marketing_normquery_stats",
        success_message="marketing_normquery_stats.finalize завершён",
        run_kwargs={"days": 7},
        use_snapshot_hour=True,
        **context,
    )


def calendar_promotions_fetch_calendar_promotions_task(tenant_id: str, use_snapshot_hour: bool = False, **context) -> None:
    _run_fetcher_task(
        tenant_id=tenant_id,
        module_dir="promotions",
        module_name="fetch_promotions",
        fetcher_attr="PromotionsFetcher",
        start_message="Начало выгрузки календаря акций WB",
        success_message="Календарь акций успешно выгружен",
        run_kwargs={"full_snapshot": False},
        use_snapshot_hour=use_snapshot_hour,
        **context,
    )


def calendar_promotions_fetch_details_task(tenant_id: str, use_snapshot_hour: bool = False, **context) -> None:
    _run_fetcher_task(
        tenant_id=tenant_id,
        module_dir="promotions",
        module_name="fetch_promotions_details",
        fetcher_attr="PromotionsDetailsFetcher",
        start_message="Начало выгрузки подробностей календарных акций WB",
        success_message="Подробности календарных акций успешно выгружены",
        use_snapshot_hour=use_snapshot_hour,
        **context,
    )


def calendar_promotions_fetch_nomenclatures_task(tenant_id: str, use_snapshot_hour: bool = False, **context) -> None:
    _run_fetcher_task(
        tenant_id=tenant_id,
        module_dir="promotions",
        module_name="fetch_promotions_nomenclatures",
        fetcher_attr="PromotionsNomenclaturesFetcher",
        start_message="Начало выгрузки номенклатур календарных акций WB",
        success_message="Номенклатуры календарных акций успешно выгружены",
        use_snapshot_hour=use_snapshot_hour,
        **context,
    )


def _build_three_step_group(
    dag,
    tenant_id: str,
    group_id: str,
    check_callable,
    fetch_task_id: str,
    fetch_callable,
    update_callable,
    task_args: dict,
    fetch_op_kwargs: dict | None = None,
):
    with TaskGroup(group_id=group_id, dag=dag) as group:
        check_progress = PythonOperator(
            task_id="check_progress",
            python_callable=check_callable,
            dag=dag,
            op_kwargs={"tenant_id": tenant_id},
            **task_args,
        )
        fetch = PythonOperator(
            task_id=fetch_task_id,
            python_callable=fetch_callable,
            dag=dag,
            op_kwargs={"tenant_id": tenant_id, **(fetch_op_kwargs or {})},
            **task_args,
        )
        update_progress = PythonOperator(
            task_id="update_progress",
            python_callable=update_callable,
            dag=dag,
            **task_args,
        )
        check_progress >> fetch >> update_progress
    return group


def _build_single_task_group(
    dag,
    tenant_id: str,
    group_id: str,
    task_id: str,
    python_callable,
    task_args: dict,
    op_kwargs: dict | None = None,
):
    with TaskGroup(group_id=group_id, dag=dag) as group:
        PythonOperator(
            task_id=task_id,
            python_callable=python_callable,
            dag=dag,
            op_kwargs={"tenant_id": tenant_id, **(op_kwargs or {})},
            **task_args,
        )
    return group


def _build_marketing_stage_group(
    dag,
    tenant_id: str,
    group_id: str,
    task_specs: list[tuple[str, Any, dict[str, Any] | None]],
    task_args: dict,
):
    with TaskGroup(group_id=group_id, dag=dag) as group:
        previous = None
        for task_id, python_callable, op_kwargs in task_specs:
            current = PythonOperator(
                task_id=task_id,
                python_callable=python_callable,
                dag=dag,
                op_kwargs={"tenant_id": tenant_id, **(op_kwargs or {})},
                **task_args,
            )
            if previous is not None:
                previous >> current
            previous = current
    return group


def build_supplier_stocks_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_three_step_group(
        dag,
        tenant_id,
        "supplier_stocks",
        supplier_stocks_check_progress_task,
        "fetch_stocks_data",
        supplier_stocks_fetch_stocks_data_task,
        supplier_stocks_update_progress_task,
        RETRY_5M,
        fetch_op_kwargs=fetch_op_kwargs,
    )


def build_supplier_sales_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_three_step_group(
        dag,
        tenant_id,
        "supplier_sales",
        supplier_sales_check_progress_task,
        "fetch_sales_data",
        supplier_sales_fetch_sales_data_task,
        supplier_sales_update_progress_task,
        RETRY_5M,
        fetch_op_kwargs=fetch_op_kwargs,
    )


def build_supplier_orders_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_three_step_group(
        dag,
        tenant_id,
        "supplier_orders",
        supplier_orders_check_progress_task,
        "fetch_orders_data",
        supplier_orders_fetch_orders_data_task,
        supplier_orders_update_progress_task,
        RETRY_5M,
        fetch_op_kwargs=fetch_op_kwargs,
    )


def build_supplies_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_three_step_group(
        dag,
        tenant_id,
        "supplies",
        supplies_check_progress_task,
        "fetch_supplies_data",
        supplies_fetch_supplies_data_task,
        supplies_update_progress_task,
        RETRY_5M,
        fetch_op_kwargs=fetch_op_kwargs,
    )


def build_supplier_prices_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_single_task_group(
        dag,
        tenant_id,
        "supplier_prices",
        "fetch_prices_data",
        supplier_prices_fetch_prices_data_task,
        SUPPLIER_PRICES_TASK_ARGS,
        op_kwargs=fetch_op_kwargs,
    )


def build_sales_funnel_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_single_task_group(
        dag,
        tenant_id,
        "sales_funnel",
        "fetch_funnel_90d_daily",
        sales_funnel_fetch_funnel_90d_daily_task,
        SALES_FUNNEL_TASK_ARGS,
        op_kwargs=fetch_op_kwargs,
    )


def build_report_detail_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_three_step_group(
        dag,
        tenant_id,
        "report_detail",
        report_detail_check_progress_task,
        "fetch_report_data",
        report_detail_fetch_report_data_task,
        report_detail_update_progress_task,
        RETRY_5M,
        fetch_op_kwargs=fetch_op_kwargs,
    )


def build_tariffs_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_single_task_group(
        dag,
        tenant_id,
        "tariffs",
        "fetch_tariffs_data",
        tariffs_fetch_tariffs_data_task,
        RETRY_5M,
        op_kwargs=fetch_op_kwargs,
    )


def build_marketing_campaigns_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_marketing_stage_group(
        dag,
        tenant_id,
        "marketing_campaigns",
        [
            ("fetch_ids", marketing_campaigns_fetch_ids_task, fetch_op_kwargs),
            ("fetch_details_batches", marketing_campaigns_fetch_details_batches_task, fetch_op_kwargs),
            ("finalize", marketing_campaigns_finalize_task, fetch_op_kwargs),
        ],
        MARKETING_CAMPAIGNS_TASK_ARGS,
    )


def build_marketing_stats_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_marketing_stage_group(
        dag,
        tenant_id,
        "marketing_stats",
        [
            ("fetch_balance", marketing_stats_fetch_balance_task, fetch_op_kwargs),
            ("fetch_upd", marketing_stats_fetch_upd_task, fetch_op_kwargs),
            ("fetch_payments", marketing_stats_fetch_payments_task, fetch_op_kwargs),
            ("fetch_budget_batches", marketing_stats_fetch_budget_batches_task, fetch_op_kwargs),
            ("fetch_fullstats_batches", marketing_stats_fetch_fullstats_batches_task, fetch_op_kwargs),
            ("finalize", marketing_stats_finalize_task, fetch_op_kwargs),
        ],
        MARKETING_STATS_TASK_ARGS,
    )


def build_marketing_normquery_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_marketing_stage_group(
        dag,
        tenant_id,
        "marketing_normquery",
        [
            ("prepare_pairs", marketing_normquery_prepare_pairs_task, fetch_op_kwargs),
            ("fetch_batches", marketing_normquery_fetch_batches_task, fetch_op_kwargs),
            ("finalize", marketing_normquery_finalize_task, fetch_op_kwargs),
        ],
        MARKETING_NORMQUERY_TASK_ARGS,
    )


def build_marketing_normquery_stats_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    return _build_marketing_stage_group(
        dag,
        tenant_id,
        "marketing_normquery_stats",
        [
            ("fetch_v0_batches", marketing_normquery_stats_fetch_v0_batches_task, fetch_op_kwargs),
            ("fetch_v1_batches", marketing_normquery_stats_fetch_v1_batches_task, fetch_op_kwargs),
            ("finalize", marketing_normquery_stats_finalize_task, fetch_op_kwargs),
        ],
        MARKETING_NORMQUERY_STATS_TASK_ARGS,
    )


def build_calendar_promotions_group(dag, tenant_id: str, fetch_op_kwargs: dict | None = None):
    with TaskGroup(group_id="calendar_promotions", dag=dag) as group:
        fetch_calendar_promotions = PythonOperator(
            task_id="fetch_calendar_promotions",
            python_callable=calendar_promotions_fetch_calendar_promotions_task,
            dag=dag,
            op_kwargs={"tenant_id": tenant_id, **(fetch_op_kwargs or {})},
            **RETRY_10M,
        )
        fetch_promotion_details = PythonOperator(
            task_id="fetch_promotion_details",
            python_callable=calendar_promotions_fetch_details_task,
            dag=dag,
            op_kwargs={"tenant_id": tenant_id, **(fetch_op_kwargs or {})},
            **RETRY_10M,
        )
        fetch_promotion_nomenclatures = PythonOperator(
            task_id="fetch_promotion_nomenclatures",
            python_callable=calendar_promotions_fetch_nomenclatures_task,
            dag=dag,
            op_kwargs={"tenant_id": tenant_id, **(fetch_op_kwargs or {})},
            **RETRY_10M,
        )
        fetch_calendar_promotions >> fetch_promotion_details >> fetch_promotion_nomenclatures
    return group


PRE_BRANCH_SOURCE_GROUP_BUILDERS = [
    build_supplier_stocks_group,
    build_supplier_sales_group,
    build_supplier_orders_group,
    build_supplies_group,
    build_supplier_prices_group,
    build_sales_funnel_group,
]

CORE_BRANCH_SOURCE_GROUP_BUILDERS = [
    build_report_detail_group,
    build_tariffs_group,
    build_calendar_promotions_group,
]

MARKETING_SOURCE_GROUP_BUILDERS = [
    build_marketing_campaigns_group,
    build_marketing_stats_group,
    build_marketing_normquery_group,
    build_marketing_normquery_stats_group,
]

SOURCE_GROUP_BUILDERS = [
    *PRE_BRANCH_SOURCE_GROUP_BUILDERS,
    *MARKETING_SOURCE_GROUP_BUILDERS,
    *CORE_BRANCH_SOURCE_GROUP_BUILDERS,
]
