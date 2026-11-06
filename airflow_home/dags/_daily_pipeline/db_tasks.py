from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterator

import psycopg2

from _daily_pipeline.common import get_conn, to_date, today_moscow
from _tenant_ops import run_tenant_job
from tenants.runtime import tenant_environment
from wb_schemas import (
    ANALYTICS_AI_SCHEMA,
    compat_bundle_enabled,
    compat_sql_path,
    compat_teardown_sql,
    domain_sql_path,
    execute_raw_sql,
    execute_sql,
)

logger = logging.getLogger(__name__)

DAILY_1PAGER_FILES = [
    domain_sql_path("1pager_daily_source.sql"),
    domain_sql_path("1pager_ai.sql"),
    domain_sql_path("1pager_ml.sql"),
]

ML_FORECAST_FILES = [
    domain_sql_path("schema_wb_ml_forecast.sql"),
    domain_sql_path("1pager_ml_forecast.sql"),
]

HOURLY_1PAGER_FILES = [
    domain_sql_path("1pager_ai_hourly.sql"),
]

MART_SCHEMA_FILE = domain_sql_path("schema_mart_ai_sales_planning.sql")
MARKETING_MART_SCHEMA_FILE = domain_sql_path("schema_wb_marketing_marts.sql")
MARKETING_DEMAND_FORECAST_SCHEMA_FILE = domain_sql_path("schema_wb_marketing_demand_forecast.sql")
PRICE_DECISION_SCHEMA_FILE = domain_sql_path("schema_mart_price_decision_latest.sql")
MARKETING_MART_NAMES = (
    "marketing.mart_marketing_query_daily",
    "marketing.mart_marketing_campaign_daily",
    "marketing.mart_marketing_query_bands",
    "marketing.mart_marketing_forecast_ready",
    "marketing.mart_marketing_query_demand_daily",
    "marketing.mart_marketing_query_share_daily",
    "marketing.mart_marketing_query_forecast_ready",
    "marketing.mart_marketing_campaign_demand_forecast",
)

CORE_FRESHNESS_CONTRACT = [
    ("reports.wb_supplier_stocks", "SELECT MAX(snapshot_date) FROM reports.wb_supplier_stocks", 0),
    ("reports.wb_supplier_sales", "SELECT MAX(snapshot_date) FROM reports.wb_supplier_sales", 0),
    ("reports.wb_supplier_orders", "SELECT MAX(snapshot_date) FROM reports.wb_supplier_orders", 0),
    ("reports.wb_supplies", "SELECT MAX(snapshot_date) FROM reports.wb_supplies", 0),
    ("reports.wb_supplier_prices", "SELECT MAX(snapshot_date) FROM reports.wb_supplier_prices", 0),
    ("reports.wb_tariffs_commission", "SELECT MAX(snapshot_date) FROM reports.wb_tariffs_commission", 0),
    ("reports.wb_calendar_promotions", "SELECT MAX(snapshot_date) FROM reports.wb_calendar_promotions", 0),
    (
        "reports.wb_sales_funnel_products_daily",
        "SELECT MAX(report_date) FROM reports.wb_sales_funnel_products_daily",
        1,
    ),
    (
        "reports.wb_report_detail_daily",
        "SELECT MAX(COALESCE(sale_dt::date, date_to)) FROM reports.wb_report_detail_daily",
        1,
    ),
]

MARKETING_FRESHNESS_CONTRACT = [
    ("reports.wb_marketing_campaigns", "SELECT MAX(snapshot_date) FROM reports.wb_marketing_campaigns", 0),
    (
        "reports.wb_marketing_campaign_stats_daily_nms",
        "SELECT MAX(stat_date) FROM reports.wb_marketing_campaign_stats_daily_nms",
        1,
    ),
    ("marketing.wb_marketing_normquery_clusters", "SELECT MAX(snapshot_date) FROM marketing.wb_marketing_normquery_clusters", 0),
    ("marketing.wb_marketing_normquery_bids", "SELECT MAX(snapshot_date) FROM marketing.wb_marketing_normquery_bids", 0),
    ("marketing.wb_marketing_normquery_minus", "SELECT MAX(snapshot_date) FROM marketing.wb_marketing_normquery_minus", 0),
    ("marketing.wb_marketing_normquery_stats_daily", "SELECT MAX(stat_date) FROM marketing.wb_marketing_normquery_stats_daily", 1),
]

SOURCE_QUALITY_WINDOW_DAYS = 90
SOURCE_PROGRESS_TOLERANCE = timedelta(minutes=5)
SOURCE_VOLUME_DROP_THRESHOLD = 0.8

MARKETING_STAGE_TASK_IDS = [
    "marketing_campaigns.fetch_ids",
    "marketing_campaigns.fetch_details_batches",
    "marketing_campaigns.finalize",
    "marketing_stats.fetch_balance",
    "marketing_stats.fetch_upd",
    "marketing_stats.fetch_payments",
    "marketing_stats.fetch_budget_batches",
    "marketing_stats.fetch_fullstats_batches",
    "marketing_stats.finalize",
    "marketing_normquery.prepare_pairs",
    "marketing_normquery.fetch_batches",
    "marketing_normquery.finalize",
    "marketing_normquery_stats.fetch_v0_batches",
    "marketing_normquery_stats.fetch_v1_batches",
    "marketing_normquery_stats.finalize",
]


@contextmanager
def _tenant_connection(tenant_id: str | None, *, autocommit: bool = False) -> Iterator[psycopg2.extensions.connection]:
    with tenant_environment(tenant_id):
        conn = get_conn()
        conn.autocommit = autocommit
        try:
            yield conn
        finally:
            conn.close()


def _apply_sql_file(cur: psycopg2.extensions.cursor, sql_path, *, label: str) -> None:
    if not sql_path.exists():
        raise FileNotFoundError(f"Не найден SQL-файл {label}: {sql_path}")
    compat_path = compat_sql_path(sql_path.name)
    compat_sql = None
    if compat_path.exists():
        compat_sql = compat_path.read_text(encoding="utf-8")
        execute_raw_sql(cur, compat_teardown_sql(compat_sql))
    execute_sql(cur, sql_path.read_text(encoding="utf-8"))
    if compat_sql and compat_bundle_enabled(sql_path.name):
        execute_raw_sql(cur, compat_sql)
    logger.info("%s применен из %s", label, sql_path.name)


def _collect_stale_sources(
    tenant_id: str,
    contract: list[tuple[str, str, int]],
) -> list[str]:
    today_msk = today_moscow()
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            stale_sources = []
            for source_name, sql, lag_days in contract:
                min_expected = today_msk - timedelta(days=lag_days)
                execute_sql(cur, sql)
                max_raw = cur.fetchone()[0]
                max_date = to_date(max_raw)
                logger.info(
                    "Источник %s: max_date=%s, min_expected=%s",
                    source_name,
                    max_date,
                    min_expected,
                )
                if max_date is None or max_date < min_expected:
                    stale_sources.append(
                        f"{source_name} (max={max_date}, min_expected={min_expected})"
                    )
    return stale_sources


def strict_freshness_gate_core_task(tenant_id: str, **context):
    """Fail if any critical core source is older than the freshness contract allows."""
    stale_sources = _collect_stale_sources(tenant_id, CORE_FRESHNESS_CONTRACT)
    if stale_sources:
        raise ValueError("Strict freshness gate failed:\n- " + "\n- ".join(stale_sources))
    logger.info("Strict freshness gate core passed")


def strict_freshness_gate_marketing_task(tenant_id: str, **context) -> bool:
    """Return True only if marketing tables are fresh enough for marts."""
    stale_sources = _collect_stale_sources(tenant_id, MARKETING_FRESHNESS_CONTRACT)
    if stale_sources:
        logger.warning("Marketing freshness gate skipped marts:\n- %s", "\n- ".join(stale_sources))
        return False
    logger.info("Strict freshness gate marketing passed")
    return True


def strict_freshness_gate_task(tenant_id: str, **context):
    """Backward-compatible alias for the strict core freshness gate."""
    return strict_freshness_gate_core_task(tenant_id, **context)


def _calculate_drop_pct(current_count: int, previous_count: int) -> float | None:
    if previous_count <= 0:
        return None
    return round((current_count - previous_count) * 100.0 / previous_count, 1)


def _is_critical_volume_drop(
    current_count: int,
    previous_count: int,
    drop_threshold: float = SOURCE_VOLUME_DROP_THRESHOLD,
) -> bool:
    if previous_count <= 0:
        return False
    return current_count < previous_count * (1 - drop_threshold)


def _is_progress_ahead(
    progress_value: datetime | None,
    max_loaded_value: datetime | None,
    tolerance: timedelta = SOURCE_PROGRESS_TOLERANCE,
) -> bool:
    if progress_value is None or max_loaded_value is None:
        return False
    return progress_value > max_loaded_value + tolerance


def validate_source_quality_task(tenant_id: str, **context):
    """Validate source completeness after the freshness gate passes."""
    today_msk = today_moscow()
    funnel_end = today_msk - timedelta(days=1)
    funnel_start = funnel_end - timedelta(days=SOURCE_QUALITY_WINDOW_DAYS - 1)
    dq_errors: list[str] = []

    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(
                cur,
                """
                WITH expected_dates AS (
                    SELECT generate_series(%s::date, %s::date, interval '1 day')::date AS report_date
                ),
                loaded_dates AS (
                    SELECT DISTINCT report_date
                    FROM reports.wb_sales_funnel_products_daily
                    WHERE report_date BETWEEN %s AND %s
                )
                SELECT e.report_date
                FROM expected_dates e
                LEFT JOIN loaded_dates l
                  ON l.report_date = e.report_date
                WHERE l.report_date IS NULL
                ORDER BY e.report_date
                """,
                (funnel_start, funnel_end, funnel_start, funnel_end),
            )
            missing_funnel_dates = [row[0] for row in cur.fetchall()]
            logger.info(
                "Source DQ sales_funnel window: %s -> %s, missing_dates=%s",
                funnel_start,
                funnel_end,
                len(missing_funnel_dates),
            )
            if missing_funnel_dates:
                dq_errors.append(
                    "sales_funnel содержит пропущенные даты в рабочем окне: "
                    + ", ".join(d.isoformat() for d in missing_funnel_dates)
                )

            execute_sql(
                cur,
                """
                WITH expected_dates AS (
                    SELECT generate_series(%s::date, %s::date, interval '1 day')::date AS report_date
                ),
                completed_dates AS (
                    SELECT DISTINCT date_to AS report_date
                    FROM reports.wb_report_detail_daily
                    WHERE date_to BETWEEN %s AND %s
                    UNION
                    SELECT DISTINCT last_processed_date AS report_date
                    FROM reports.wb_report_detail_progress
                    WHERE last_processed_date BETWEEN %s AND %s
                      AND (updated_at AT TIME ZONE 'Europe/Moscow')::date >= last_processed_date + 2
                )
                SELECT e.report_date
                FROM expected_dates e
                LEFT JOIN completed_dates c
                  ON c.report_date = e.report_date
                WHERE c.report_date IS NULL
                ORDER BY e.report_date
                """,
                (funnel_start, funnel_end, funnel_start, funnel_end, funnel_start, funnel_end),
            )
            missing_report_detail_dates = [row[0] for row in cur.fetchall()]
            logger.info(
                "Source DQ report_detail window: %s -> %s, missing_dates=%s",
                funnel_start,
                funnel_end,
                len(missing_report_detail_dates),
            )
            if missing_report_detail_dates:
                dq_errors.append(
                    "report_detail содержит пропущенные даты в рабочем окне: "
                    + ", ".join(d.isoformat() for d in missing_report_detail_dates)
                )

            for source_name, progress_table, data_table in (
                ("supplier_stocks", "reports.wb_supplier_stocks_progress", "reports.wb_supplier_stocks"),
                ("supplier_sales", "reports.wb_supplier_sales_progress", "reports.wb_supplier_sales"),
                ("supplier_orders", "reports.wb_supplier_orders_progress", "reports.wb_supplier_orders"),
            ):
                execute_sql(
                    cur,
                    f"""
                    SELECT
                        (SELECT last_change_date_from
                         FROM {progress_table}
                         ORDER BY updated_at DESC, id DESC
                         LIMIT 1) AS progress_value,
                        (SELECT MAX(last_change_date)
                         FROM {data_table}) AS max_loaded_value
                    """,
                )
                progress_value, max_loaded_value = cur.fetchone()
                logger.info(
                    "Source DQ %s progress vs fact: progress=%s, max_last_change=%s, tolerance=%s",
                    source_name,
                    progress_value,
                    max_loaded_value,
                    SOURCE_PROGRESS_TOLERANCE,
                )
                if _is_progress_ahead(progress_value, max_loaded_value):
                    dq_errors.append(
                        f"{source_name}: progress {progress_value} сильно опережает MAX(last_change_date) {max_loaded_value}"
                    )

            for source_name, date_column, table_name in (
                ("supplier_stocks", "snapshot_date", "reports.wb_supplier_stocks"),
                ("supplier_sales", "snapshot_date", "reports.wb_supplier_sales"),
                ("supplier_orders", "snapshot_date", "reports.wb_supplier_orders"),
                ("sales_funnel", "report_date", "reports.wb_sales_funnel_products_daily"),
            ):
                execute_sql(
                    cur,
                    f"""
                    SELECT {date_column} AS bucket_date, COUNT(*) AS row_count
                    FROM {table_name}
                    GROUP BY {date_column}
                    ORDER BY {date_column} DESC
                    LIMIT 2
                    """,
                )
                rows = cur.fetchall()
                if len(rows) < 2:
                    logger.info("Source DQ %s volume: недостаточно истории для сравнения", source_name)
                    continue
                (current_date, current_count), (previous_date, previous_count) = rows
                drop_pct = _calculate_drop_pct(current_count, previous_count)
                logger.info(
                    "Source DQ %s volume: current=%s (%s), previous=%s (%s), delta_pct=%s",
                    source_name,
                    current_count,
                    current_date,
                    previous_count,
                    previous_date,
                    drop_pct,
                )
                if _is_critical_volume_drop(current_count, previous_count):
                    dq_errors.append(
                        f"{source_name}: резкое падение объёма ({previous_count} -> {current_count}, delta_pct={drop_pct})"
                    )

            if dq_errors:
                raise ValueError("Source data-quality gate failed:\n- " + "\n- ".join(dq_errors))

    logger.info("Source data-quality gate passed")


def validate_source_quality_core_task(tenant_id: str, **context):
    """Backward-compatible wrapper around the core source quality gate."""
    return validate_source_quality_task(tenant_id, **context)


def _marketing_stage_failures(context) -> dict[str, dict]:
    ti = context["ti"]
    failures: dict[str, dict] = {}
    for task_id in MARKETING_STAGE_TASK_IDS:
        payload = ti.xcom_pull(task_ids=task_id)
        if not payload:
            failures[task_id] = {"status": "missing", "error": "xcom missing"}
            continue
        if payload.get("status") != "success":
            failures[task_id] = payload
    return failures


def validate_marketing_sources_task(tenant_id: str, **context) -> bool:
    """Return True only when all marketing stages completed successfully."""
    failures = _marketing_stage_failures(context)
    if failures:
        logger.warning("Marketing validation skipped marts because some stages did not finish cleanly")
        for task_id, payload in failures.items():
            logger.warning("Marketing stage issue: %s -> %s", task_id, payload)
        return False
    logger.info("Marketing source validation passed")
    return True


def marketing_branch_outcome_task(tenant_id: str, **context) -> dict[str, object]:
    """Summarize the marketing branch without failing the whole DAG."""
    ti = context["ti"]
    freshness_ok = ti.xcom_pull(task_ids="strict_freshness_gate_marketing")
    validation_ok = ti.xcom_pull(task_ids="validate_marketing_sources")
    failures = _marketing_stage_failures(context)
    latest_marketing_snapshot = None

    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, "SELECT MAX(snapshot_hour) FROM reports.wb_marketing_campaigns")
            latest_marketing_snapshot = cur.fetchone()[0]

    summary = {
        "marketing_freshness_ok": bool(freshness_ok),
        "marketing_validation_ok": bool(validation_ok),
        "failed_steps": {
            task_id: {
                "status": payload.get("status"),
                "error": payload.get("error"),
                "last_rate_limit": payload.get("last_rate_limit"),
            }
            for task_id, payload in failures.items()
        },
        "latest_marketing_snapshot_hour": latest_marketing_snapshot.isoformat() if latest_marketing_snapshot else None,
    }
    logger.info("Marketing branch outcome: %s", summary)
    return summary


def ensure_schema_task(tenant_id: str, **context):
    """Guarantee that the hourly stocks/sales summary and its source view exist."""
    schema_path = domain_sql_path("schema_stocks_sales_hourly.sql")
    if not schema_path.exists():
        raise FileNotFoundError(f"Не найден SQL-файл схемы: {schema_path}")

    with _tenant_connection(tenant_id, autocommit=True) as conn:
        with conn.cursor() as cur:
            _apply_sql_file(cur, schema_path, label="Схема wb_stocks_sales_hourly")
            logger.info("Схема wb_stocks_sales_hourly применена")


def ensure_daily_summary_schema_task(tenant_id: str, **context):
    """Guarantee that the daily stocks/sales summary and its source view exist."""
    schema_path = domain_sql_path("schema_stocks_sales_daily.sql")
    if not schema_path.exists():
        raise FileNotFoundError(f"Не найден SQL-файл схемы: {schema_path}")

    with _tenant_connection(tenant_id, autocommit=True) as conn:
        with conn.cursor() as cur:
            _apply_sql_file(cur, schema_path, label="Схема wb_stocks_sales_daily")
            logger.info("Схема wb_stocks_sales_daily применена")


def refresh_stocks_sales_daily_task(tenant_id: str, **context):
    """Refresh reports.wb_stocks_sales_daily for the latest supplier stocks snapshot."""
    query = """
    INSERT INTO reports.wb_stocks_sales_daily (
        snapshot_date,
        nm_id,
        warehouse_name,
        stock_quantity,
        stock_quantity_full,
        sales_count,
        sales_amount,
        updated_at
    )
    SELECT
        snapshot_date,
        nm_id,
        warehouse_name,
        stock_quantity,
        stock_quantity_full,
        sales_count,
        sales_amount,
        CURRENT_TIMESTAMP
    FROM reports.v_stocks_sales_daily
    WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM reports.wb_supplier_stocks)
    ON CONFLICT (snapshot_date, nm_id, warehouse_name)
    DO UPDATE SET
        stock_quantity = EXCLUDED.stock_quantity,
        stock_quantity_full = EXCLUDED.stock_quantity_full,
        sales_count = EXCLUDED.sales_count,
        sales_amount = EXCLUDED.sales_amount,
        updated_at = EXCLUDED.updated_at
    """

    with _tenant_connection(tenant_id, autocommit=True) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, query)
            logger.info("wb_stocks_sales_daily upsert выполнен; затронуто строк: %s", cur.rowcount)


def refresh_stocks_sales_hourly_task(tenant_id: str, **context):
    """Refresh reports.wb_stocks_sales_hourly for the latest supplier stocks snapshot hour."""
    query = """
    WITH target_hour AS (
        SELECT
            MAX(snapshot_hour) AS snapshot_hour,
            MAX(snapshot_date) AS snapshot_date
        FROM reports.wb_supplier_stocks
    ),
    latest_stock_state AS (
        SELECT
            th.snapshot_hour,
            th.snapshot_date,
            s.nm_id,
            s.warehouse_name,
            s.quantity,
            s.quantity_full,
            ROW_NUMBER() OVER (
                PARTITION BY s.barcode, s.warehouse_name
                ORDER BY s.snapshot_hour DESC, s.id DESC
            ) AS rn
        FROM target_hour th
        JOIN reports.wb_supplier_stocks s
          ON s.snapshot_hour <= th.snapshot_hour
        WHERE s.nm_id IS NOT NULL
    ),
    stock_agg AS (
        SELECT
            snapshot_hour,
            snapshot_date,
            nm_id,
            warehouse_name,
            SUM(COALESCE(quantity, 0)) AS stock_quantity,
            SUM(COALESCE(quantity_full, 0)) AS stock_quantity_full
        FROM latest_stock_state
        WHERE rn = 1
        GROUP BY snapshot_hour, snapshot_date, nm_id, warehouse_name
    ),
    sales_ranked AS (
        SELECT
            th.snapshot_hour,
            th.snapshot_date,
            s.nm_id,
            s.warehouse_name,
            COALESCE(s.for_pay, 0) AS for_pay,
            ROW_NUMBER() OVER (
                PARTITION BY COALESCE(s.date_ord::date, th.snapshot_date), s.srid
                ORDER BY s.snapshot_hour DESC, s.id DESC
            ) AS rn
        FROM target_hour th
        JOIN reports.wb_supplier_sales s
          ON s.snapshot_hour <= th.snapshot_hour
        WHERE s.nm_id IS NOT NULL
          AND s.date_ord IS NOT NULL
          AND s.date_ord::date = th.snapshot_date
    ),
    sales_agg AS (
        SELECT
            snapshot_hour,
            snapshot_date,
            nm_id,
            warehouse_name,
            COUNT(*) FILTER (WHERE rn = 1) AS sales_count,
            SUM(for_pay) FILTER (WHERE rn = 1) AS sales_amount
        FROM sales_ranked
        GROUP BY snapshot_hour, snapshot_date, nm_id, warehouse_name
    )
    INSERT INTO reports.wb_stocks_sales_hourly (
        snapshot_hour,
        snapshot_date,
        nm_id,
        warehouse_name,
        stock_quantity,
        stock_quantity_full,
        sales_count,
        sales_amount,
        updated_at
    )
    SELECT
        sa.snapshot_hour,
        sa.snapshot_date,
        sa.nm_id,
        sa.warehouse_name,
        sa.stock_quantity,
        sa.stock_quantity_full,
        COALESCE(sla.sales_count, 0) AS sales_count,
        COALESCE(sla.sales_amount, 0) AS sales_amount,
        CURRENT_TIMESTAMP
    FROM stock_agg sa
    LEFT JOIN sales_agg sla
      ON sla.snapshot_hour = sa.snapshot_hour
     AND sla.snapshot_date = sa.snapshot_date
     AND sla.nm_id = sa.nm_id
     AND sla.warehouse_name = sa.warehouse_name
    ON CONFLICT (snapshot_hour, nm_id, warehouse_name)
    DO UPDATE SET
        snapshot_date = EXCLUDED.snapshot_date,
        stock_quantity = EXCLUDED.stock_quantity,
        stock_quantity_full = EXCLUDED.stock_quantity_full,
        sales_count = EXCLUDED.sales_count,
        sales_amount = EXCLUDED.sales_amount,
        updated_at = EXCLUDED.updated_at
    """

    with _tenant_connection(tenant_id, autocommit=True) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, query)
            logger.info("wb_stocks_sales_hourly upsert выполнен; затронуто строк: %s", cur.rowcount)


def validate_refresh_task(tenant_id: str, **context):
    """Verify that the refreshed stocks/sales summary contains rows for the latest snapshot."""
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, "SELECT MAX(snapshot_date) FROM reports.wb_supplier_stocks")
            target_date = cur.fetchone()[0]
            if target_date is None:
                raise ValueError("Нет данных в reports.wb_supplier_stocks: невозможно обновить сводку")

            execute_sql(cur, 
                "SELECT COUNT(*) FROM reports.wb_stocks_sales_daily WHERE snapshot_date = %s",
                (target_date,),
            )
            rows_cnt = cur.fetchone()[0]
            logger.info("wb_stocks_sales_daily: snapshot_date=%s, rows=%s", target_date, rows_cnt)
            if rows_cnt == 0:
                raise ValueError(
                    f"После refresh нет строк в reports.wb_stocks_sales_daily за дату {target_date}"
                )


def validate_hourly_refresh_task(tenant_id: str, **context):
    """Verify that the refreshed hourly stocks/sales summary contains rows for the latest snapshot hour."""
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, "SELECT MAX(snapshot_hour) FROM reports.wb_supplier_stocks")
            target_hour = cur.fetchone()[0]
            if target_hour is None:
                raise ValueError("Нет данных в reports.wb_supplier_stocks: невозможно обновить hourly-сводку")

            execute_sql(cur, 
                "SELECT COUNT(*) FROM reports.wb_stocks_sales_hourly WHERE snapshot_hour = %s",
                (target_hour,),
            )
            rows_cnt = cur.fetchone()[0]
            logger.info("wb_stocks_sales_hourly: snapshot_hour=%s, rows=%s", target_hour, rows_cnt)
            if rows_cnt == 0:
                raise ValueError(
                    f"После refresh нет строк в reports.wb_stocks_sales_hourly за час {target_hour}"
                )


def refresh_profit_calculator_task(tenant_id: str, **context):
    """Re-apply calculator schemas and refresh their physical tables."""
    with _tenant_connection(tenant_id, autocommit=True) as conn:
        with conn.cursor() as cur:
            for sql_path in (
                domain_sql_path("schema_wb_unit_economics.sql"),
                domain_sql_path("schema_wb_profit_calculator.sql"),
            ):
                _apply_sql_file(cur, sql_path, label="Схема калькулятора")

            execute_sql(cur, "SELECT reports.refresh_wb_unit_economics()")
            unit_economics_rows = cur.fetchone()[0]
            logger.info("wb_unit_economics refreshed; rows=%s", unit_economics_rows)

            execute_sql(cur, "SELECT reports.sync_wb_profit_calculator_scenarios_from_stocks()")
            synced_scenarios = cur.fetchone()[0]
            logger.info(
                "wb_profit_calculator_scenarios synced from mart_ai_sales_planning; inserted=%s",
                synced_scenarios,
            )

            execute_sql(cur, "SELECT reports.refresh_wb_profit_calculator_results()")
            profit_rows = cur.fetchone()[0]
            logger.info("wb_profit_calculator_results refreshed; rows=%s", profit_rows)


def validate_profit_calculator_task(tenant_id: str, **context):
    """Ensure profit calculator results are populated after refresh."""
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, "SELECT COUNT(*) FROM reports.wb_profit_calculator_scenarios WHERE is_active = TRUE")
            active_scenarios = cur.fetchone()[0]

            execute_sql(cur, "SELECT COUNT(*) FROM reports.wb_profit_calculator_results")
            result_rows = cur.fetchone()[0]

            logger.info(
                "wb_profit_calculator: active_scenarios=%s, result_rows=%s",
                active_scenarios,
                result_rows,
            )

            if active_scenarios > 0 and result_rows == 0:
                raise ValueError(
                    "Калькулятор прибыли пуст после refresh при наличии активных сценариев"
                )

            execute_sql(cur, 
                """
                WITH latest_mart_date AS (
                    SELECT MAX(report_date) AS report_date
                    FROM reports.mart_ai_sales_planning
                ),
                in_stock_nm_ids AS (
                    SELECT DISTINCT m.nm_id
                    FROM reports.mart_ai_sales_planning m
                    JOIN latest_mart_date d
                      ON d.report_date = m.report_date
                    WHERE m.nm_id IS NOT NULL
                      AND COALESCE(m.stock_qty, 0) > 0
                )
                SELECT COUNT(*)
                FROM in_stock_nm_ids st
                LEFT JOIN reports.wb_profit_calculator_scenarios sc
                  ON sc.nm_id = st.nm_id
                 AND sc.is_active = TRUE
                WHERE sc.nm_id IS NULL
                """
            )
            missing_in_stock_scenarios = cur.fetchone()[0]
            logger.info(
                "wb_profit_calculator: mart stock_qty>0 nm_id without active scenario=%s",
                missing_in_stock_scenarios,
            )

            if missing_in_stock_scenarios > 0:
                raise ValueError(
                    "Не все товары из mart_ai_sales_planning со stock_qty > 0 попали в активные сценарии калькулятора"
                )

            execute_sql(cur, 
                """
                WITH latest_mart_date AS (
                    SELECT MAX(report_date) AS report_date
                    FROM reports.mart_ai_sales_planning
                ),
                in_stock_nm_ids AS (
                    SELECT DISTINCT m.nm_id
                    FROM reports.mart_ai_sales_planning m
                    JOIN latest_mart_date d
                      ON d.report_date = m.report_date
                    WHERE m.nm_id IS NOT NULL
                      AND COALESCE(m.stock_qty, 0) > 0
                )
                SELECT COUNT(*)
                FROM reports.wb_profit_calculator_scenarios sc
                LEFT JOIN in_stock_nm_ids st
                  ON st.nm_id = sc.nm_id
                WHERE sc.is_active = TRUE
                  AND st.nm_id IS NULL
                """
            )
            extra_active_scenarios = cur.fetchone()[0]
            logger.info(
                "wb_profit_calculator: active scenarios outside mart stock_qty>0 slice=%s",
                extra_active_scenarios,
            )

            if extra_active_scenarios > 0:
                raise ValueError(
                    "В калькуляторе остались активные сценарии вне актуального среза mart_ai_sales_planning"
                )

            execute_sql(cur,
                """
                SELECT COUNT(*)
                FROM reports.wb_profit_calculator_scenarios sc
                JOIN finance.wb_product_costs pc
                  ON pc.nm_id = sc.nm_id
                WHERE sc.is_active = TRUE
                  AND pc.cost_price_rub > 0
                  AND COALESCE(sc.cost_price_rub, 0) = 0
                """
            )
            active_scenarios_missing_cost = cur.fetchone()[0]
            logger.info(
                "wb_profit_calculator: active scenarios with wb_product_costs but zero scenario cost=%s",
                active_scenarios_missing_cost,
            )

            if active_scenarios_missing_cost > 0:
                raise ValueError(
                    "В калькуляторе остались активные сценарии с нулевой себестоимостью при наличии finance.wb_product_costs"
                )


def refresh_marketing_marts_task(tenant_id: str, **context):
    """Refresh marketing forecast marts used by price decisioning."""
    with _tenant_connection(tenant_id, autocommit=True) as conn:
        try:
            with conn.cursor() as cur:
                for mart_name in MARKETING_MART_NAMES:
                    execute_sql(cur, f"REFRESH MATERIALIZED VIEW {mart_name}")
                    logger.info("Marketing mart refreshed: %s", mart_name)
        except psycopg2.errors.UndefinedTable:
            logger.warning(
                "Marketing marts отсутствуют. Применяется bootstrap SQL для нового tenant."
            )
            with conn.cursor() as cur:
                _apply_sql_file(cur, MARKETING_MART_SCHEMA_FILE, label="Схема marketing marts")
                _apply_sql_file(cur, MARKETING_DEMAND_FORECAST_SCHEMA_FILE, label="Схема marketing demand forecast")
                for mart_name in MARKETING_MART_NAMES:
                    execute_sql(cur, f"REFRESH MATERIALIZED VIEW {mart_name}")
                    logger.info("Marketing mart refreshed after bootstrap: %s", mart_name)


def validate_marketing_marts_task(tenant_id: str, **context):
    """Validate that marketing marts contain the latest forecast-ready slice."""
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            validations = [
                ("marketing.mart_marketing_query_daily", "stat_date"),
                ("marketing.mart_marketing_campaign_daily", "stat_date"),
                ("marketing.mart_marketing_query_bands", "snapshot_date"),
                ("marketing.mart_marketing_forecast_ready", "snapshot_date"),
                ("marketing.mart_marketing_query_demand_daily", "snapshot_date"),
                ("marketing.mart_marketing_query_share_daily", "snapshot_date"),
                ("marketing.mart_marketing_query_forecast_ready", "snapshot_date"),
                ("marketing.mart_marketing_campaign_demand_forecast", "snapshot_date"),
            ]

            for relation_name, marker_column in validations:
                execute_sql(
                    cur,
                    f"SELECT COUNT(*), MAX({marker_column}) FROM {relation_name}",
                )
                row_count, max_marker = cur.fetchone()
                logger.info(
                    "%s: rows=%s, max_%s=%s",
                    relation_name,
                    row_count,
                    marker_column,
                    max_marker,
                )
                if row_count == 0:
                    raise ValueError(f"{relation_name} пустая после refresh")

            execute_sql(
                cur,
                """
                SELECT
                    COUNT(*) FILTER (WHERE payment_type = 'unknown') AS unknown_payment_type_rows,
                    COUNT(*) FILTER (WHERE decision_hint IS NULL) AS empty_decision_rows
                FROM marketing.mart_marketing_forecast_ready
                """,
            )
            unknown_payment_type_rows, empty_decision_rows = cur.fetchone()
            logger.info(
                "marketing.mart_marketing_forecast_ready: unknown_payment_type_rows=%s, empty_decision_rows=%s",
                unknown_payment_type_rows,
                empty_decision_rows,
            )
            if empty_decision_rows > 0:
                raise ValueError(
                    "marketing.mart_marketing_forecast_ready содержит строки без decision_hint"
                )

            execute_sql(
                cur,
                """
                SELECT
                    COUNT(*) FILTER (WHERE share_resolution_status = 'demand_unresolved') AS unresolved_rows,
                    COUNT(*) FILTER (WHERE COALESCE(action_hint, '') = '') AS empty_action_rows
                FROM marketing.mart_marketing_query_forecast_ready
                """,
            )
            unresolved_rows, empty_action_rows = cur.fetchone()
            logger.info(
                "marketing.mart_marketing_query_forecast_ready: unresolved_rows=%s, empty_action_rows=%s",
                unresolved_rows,
                empty_action_rows,
            )
            if empty_action_rows > 0:
                raise ValueError(
                    "marketing.mart_marketing_query_forecast_ready содержит строки без action_hint"
                )


def refresh_mart_task(tenant_id: str, **context):
    """Refresh reports.mart_ai_sales_planning with a concurrent refresh when possible."""
    with _tenant_connection(tenant_id, autocommit=True) as conn:
        try:
            with conn.cursor() as cur:
                logger.info("Запуск REFRESH MATERIALIZED VIEW CONCURRENTLY ...")
                execute_sql(cur, 
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY reports.mart_ai_sales_planning"
                )
            logger.info("Витрина mart_ai_sales_planning обновлена")
        except psycopg2.errors.UndefinedTable:
            logger.warning(
                "Витрина mart_ai_sales_planning отсутствует. "
                "Применяется bootstrap SQL для нового tenant."
            )
            with conn.cursor() as cur:
                _apply_sql_file(cur, MART_SCHEMA_FILE, label="Схема mart_ai_sales_planning")
                execute_sql(cur, "REFRESH MATERIALIZED VIEW reports.mart_ai_sales_planning")
            logger.info("Витрина mart_ai_sales_planning создана и заполнена")
        except psycopg2.errors.ObjectNotInPrerequisiteState:
            logger.warning(
                "CONCURRENTLY недоступен (возможно, первый запуск). "
                "Выполняется обычный REFRESH MATERIALIZED VIEW."
            )
            with conn.cursor() as cur:
                execute_sql(cur, "REFRESH MATERIALIZED VIEW reports.mart_ai_sales_planning")
            logger.info("Витрина mart_ai_sales_planning заполнена (первый запуск)")


def validate_mart_task(tenant_id: str, **context):
    """Check that the mart is populated and surface a few quick data-quality indicators."""
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, "SELECT COUNT(*) FROM reports.mart_ai_sales_planning")
            total_rows = cur.fetchone()[0]
            logger.info("Витрина: %d строк", total_rows)
            if total_rows == 0:
                raise ValueError("Витрина пустая после REFRESH — проверьте источники данных")

            execute_sql(cur, 
                "SELECT MIN(report_date), MAX(report_date) "
                "FROM reports.mart_ai_sales_planning"
            )
            min_d, max_d = cur.fetchone()
            logger.info("Диапазон дат: %s -> %s", min_d, max_d)

            execute_sql(cur, "SELECT COUNT(DISTINCT nm_id) FROM reports.mart_ai_sales_planning")
            nm_count = cur.fetchone()[0]
            logger.info("Уникальных nm_id: %d", nm_count)

            execute_sql(cur, 
                "SELECT ROUND(100.0 * SUM(CASE WHEN price_elasticity_point IS NOT NULL THEN 1 ELSE 0 END)"
                "       / NULLIF(COUNT(*), 0), 1) "
                "FROM reports.mart_ai_sales_planning"
            )
            elasticity_pct = cur.fetchone()[0]
            logger.info("Строк с эластичностью: %s%%", elasticity_pct)

            execute_sql(cur, 
                "SELECT reorder_flag, COUNT(*) "
                "FROM reports.mart_ai_sales_planning "
                "WHERE report_date = (SELECT MAX(report_date) FROM reports.mart_ai_sales_planning) "
                "GROUP BY reorder_flag ORDER BY reorder_flag"
            )
            for flag, count in cur.fetchall():
                logger.info("reorder_flag='%s': %d строк (последняя дата)", flag, count)

            execute_sql(cur, 
                """
                WITH latest AS (
                    SELECT MAX(report_date) AS report_date
                    FROM reports.mart_ai_sales_planning
                )
                SELECT
                    COUNT(*) AS latest_rows,
                    COUNT(*) FILTER (
                        WHERE revenue_gross IS NULL
                          AND revenue_net IS NULL
                          AND ppvz_for_pay IS NULL
                          AND commission_pct IS NULL
                          AND delivery_cost IS NULL
                          AND storage_fee IS NULL
                          AND penalty IS NULL
                    ) AS finance_missing_rows,
                    COUNT(*) FILTER (WHERE buyout_count_day > 0) AS buyout_rows,
                    COUNT(*) FILTER (
                        WHERE product_rating IS NULL AND feedback_rating IS NULL
                    ) AS rating_missing_rows,
                    COUNT(*) FILTER (
                        WHERE (product_rating IS NULL) <> (feedback_rating IS NULL)
                    ) AS rating_partial_rows,
                    COUNT(*) FILTER (
                        WHERE product_rating = 0
                          AND feedback_rating = 0
                    ) AS rating_zero_rows,
                    COUNT(*) FILTER (
                        WHERE pending_supply_qty > 0
                          AND last_supply_date IS NULL
                    ) AS pending_without_supply_rows,
                    COUNT(*) FILTER (WHERE is_conversion_anomaly) AS conversion_anomaly_rows
                FROM reports.mart_ai_sales_planning
                WHERE report_date = (SELECT report_date FROM latest)
                """
            )
            (
                latest_rows,
                finance_missing_rows,
                buyout_rows,
                rating_missing_rows,
                rating_partial_rows,
                rating_zero_rows,
                pending_without_supply_rows,
                conversion_anomaly_rows,
            ) = cur.fetchone()

            logger.info(
                "DQ latest-date summary: rows=%s, finance_missing_rows=%s, buyout_rows=%s, "
                "rating_missing_rows=%s, rating_partial_rows=%s, rating_zero_rows=%s, pending_without_supply_rows=%s, conversion_anomaly_rows=%s",
                latest_rows,
                finance_missing_rows,
                buyout_rows,
                rating_missing_rows,
                rating_partial_rows,
                rating_zero_rows,
                pending_without_supply_rows,
                conversion_anomaly_rows,
            )

            dq_errors = []
            if latest_rows and finance_missing_rows == latest_rows and buyout_rows > 0:
                dq_errors.append(
                    "Финансовый блок на последнюю дату полностью отсутствует при наличии выкупов."
                )
            if latest_rows and pending_without_supply_rows > 0:
                logger.warning(
                    "Есть товары с pending_supply_qty > 0, но без last_supply_date на последнюю дату: %s. "
                    "Для нового tenant это допустимо, если по SKU еще не было завершенных поставок.",
                    pending_without_supply_rows,
                )
            if conversion_anomaly_rows > 0:
                dq_errors.append(
                    f"Обнаружены строки с аномальными funnel-конверсиями: {conversion_anomaly_rows}."
                )
            if latest_rows and rating_missing_rows == latest_rows:
                logger.warning(
                    "Исторические рейтинги не подтверждены для всех строк на последнюю дату. "
                    "Проверьте время наблюдения и происхождение metadata; это не означает пустой источник."
                )
            if dq_errors:
                raise ValueError("Провалена валидация витрины:\n- " + "\n- ".join(dq_errors))

            context["ti"].xcom_push(key="total_rows", value=total_rows)
            context["ti"].xcom_push(key="nm_count", value=nm_count)
            context["ti"].xcom_push(key="date_max", value=str(max_d))

    logger.info("Валидация витрины завершена")


def refresh_price_decision_task(tenant_id: str, **context):
    """Refresh pricing.mart_price_decision_latest with concurrent refresh when possible."""
    with _tenant_connection(tenant_id, autocommit=True) as conn:
        try:
            with conn.cursor() as cur:
                logger.info("Запуск REFRESH MATERIALIZED VIEW CONCURRENTLY pricing.mart_price_decision_latest ...")
                execute_sql(
                    cur,
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY pricing.mart_price_decision_latest",
                )
            logger.info("Витрина pricing.mart_price_decision_latest обновлена")
        except psycopg2.errors.UndefinedTable:
            logger.warning(
                "Витрина pricing.mart_price_decision_latest отсутствует. "
                "Применяется bootstrap SQL."
            )
            with conn.cursor() as cur:
                _apply_sql_file(cur, PRICE_DECISION_SCHEMA_FILE, label="Схема price decision mart")
                execute_sql(cur, "REFRESH MATERIALIZED VIEW pricing.mart_price_decision_latest")
            logger.info("Витрина pricing.mart_price_decision_latest создана и заполнена")
        except psycopg2.errors.ObjectNotInPrerequisiteState:
            logger.warning(
                "CONCURRENTLY недоступен для pricing.mart_price_decision_latest. "
                "Выполняется обычный REFRESH MATERIALIZED VIEW."
            )
            with conn.cursor() as cur:
                execute_sql(cur, "REFRESH MATERIALIZED VIEW pricing.mart_price_decision_latest")
            logger.info("Витрина pricing.mart_price_decision_latest заполнена (первый запуск)")


def validate_price_decision_task(tenant_id: str, **context):
    """Validate pricing.mart_price_decision_latest after refresh."""
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(
                cur,
                """
                WITH latest_sales_date AS (
                    SELECT MAX(report_date) AS report_date
                    FROM sales.wb_sales_funnel_products_daily
                ),
                sales_7d AS (
                    SELECT
                        s.nm_id,
                        ROUND(SUM(COALESCE(s.order_count, 0))::numeric, 4) AS baseline_orders_7d_expected,
                        ROUND(SUM(COALESCE(s.order_sum, 0))::numeric, 2) AS baseline_revenue_gross_7d_expected
                    FROM sales.wb_sales_funnel_products_daily s
                    JOIN latest_sales_date d
                      ON s.report_date BETWEEN d.report_date - INTERVAL '6 day' AND d.report_date
                    WHERE s.nm_id IS NOT NULL
                    GROUP BY s.nm_id
                )
                SELECT
                    COUNT(*) AS total_rows,
                    COUNT(DISTINCT m.nm_id) AS distinct_nm_ids,
                    COUNT(*) FILTER (WHERE MOD(m.recommended_price::numeric, 5) <> 0) AS non_step_rows,
                    COUNT(*) FILTER (WHERE m.recommended_price <= 0) AS non_positive_rows,
                    COUNT(*) FILTER (WHERE m.decision_status = 'blocked_missing_inputs') AS blocked_rows,
                    COUNT(*) FILTER (
                        WHERE m.market_ceiling_enabled
                          AND m.competitor_price_max IS NOT NULL
                          AND m.recommended_price > m.competitor_price_max
                    ) AS ceiling_violation_rows,
                    COUNT(*) FILTER (
                        WHERE ROUND(COALESCE(m.baseline_orders_7d, 0)::numeric, 4)
                          <> ROUND(COALESCE(s.baseline_orders_7d_expected, 0)::numeric, 4)
                    ) AS sales_orders_mismatch_rows,
                    COUNT(*) FILTER (
                        WHERE ROUND(COALESCE(m.baseline_revenue_gross_7d, 0)::numeric, 2)
                          <> ROUND(COALESCE(s.baseline_revenue_gross_7d_expected, 0)::numeric, 2)
                    ) AS sales_revenue_mismatch_rows,
                    ROUND(
                        100.0 * COUNT(*) FILTER (WHERE m.elasticity_source = 'fallback_default')
                        / NULLIF(COUNT(*), 0),
                        2
                    ) AS fallback_default_pct
                FROM pricing.mart_price_decision_latest m
                LEFT JOIN sales_7d s
                  ON s.nm_id = m.nm_id
                """,
            )
            (
                total_rows,
                distinct_nm_ids,
                non_step_rows,
                non_positive_rows,
                blocked_rows,
                ceiling_violation_rows,
                sales_orders_mismatch_rows,
                sales_revenue_mismatch_rows,
                fallback_default_pct,
            ) = cur.fetchone()

            logger.info(
                "pricing.mart_price_decision_latest: total_rows=%s, distinct_nm_ids=%s, "
                "non_step_rows=%s, non_positive_rows=%s, blocked_rows=%s, ceiling_violation_rows=%s, "
                "sales_orders_mismatch_rows=%s, sales_revenue_mismatch_rows=%s, fallback_default_pct=%s",
                total_rows,
                distinct_nm_ids,
                non_step_rows,
                non_positive_rows,
                blocked_rows,
                ceiling_violation_rows,
                sales_orders_mismatch_rows,
                sales_revenue_mismatch_rows,
                fallback_default_pct,
            )

            if total_rows == 0:
                raise ValueError("pricing.mart_price_decision_latest пустая после refresh")
            if total_rows != distinct_nm_ids:
                raise ValueError(
                    "pricing.mart_price_decision_latest содержит дубли по nm_id"
                )
            if non_step_rows > 0:
                raise ValueError(
                    "pricing.mart_price_decision_latest содержит recommended_price, не кратные шагу 5 ₽"
                )
            if non_positive_rows > 0:
                raise ValueError(
                    "pricing.mart_price_decision_latest содержит non-positive recommended_price"
                )
            if blocked_rows > 0:
                raise ValueError(
                    "pricing.mart_price_decision_latest содержит blocked_missing_inputs для eligible SKU"
                )
            if ceiling_violation_rows > 0:
                raise ValueError(
                    "pricing.mart_price_decision_latest содержит рекомендации выше competitor_price_max при активном ceiling"
                )
            if sales_orders_mismatch_rows > 0:
                raise ValueError(
                    "pricing.mart_price_decision_latest содержит baseline_orders_7d, не совпадающие с sales.wb_sales_funnel_products_daily"
                )
            if sales_revenue_mismatch_rows > 0:
                raise ValueError(
                    "pricing.mart_price_decision_latest содержит baseline_revenue_gross_7d, не совпадающие с sales.wb_sales_funnel_products_daily"
                )


def apply_feature_views_task(tenant_id: str, **context):
    """Re-apply the daily 1pager views after mart refresh."""
    with _tenant_connection(tenant_id, autocommit=True) as conn:
        with conn.cursor() as cur:
            for sql_path in DAILY_1PAGER_FILES:
                _apply_sql_file(cur, sql_path, label="1pager daily-витрина")


def apply_hourly_feature_views_task(tenant_id: str, **context):
    """Re-apply the hourly 1pager artifacts after hourly snapshot refresh."""
    with _tenant_connection(tenant_id, autocommit=True) as conn:
        with conn.cursor() as cur:
            for sql_path in HOURLY_1PAGER_FILES:
                _apply_sql_file(cur, sql_path, label="1pager hourly-витрина")


def refresh_1pager_ai_hourly_task(tenant_id: str, **context):
    """Upsert the latest hourly 1pager slice into the accumulated hourly table."""
    with _tenant_connection(tenant_id, autocommit=True) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, "SELECT MAX(snapshot_hour) FROM reports.wb_stocks_sales_hourly")
            target_hour = cur.fetchone()[0]
            if target_hour is None:
                raise ValueError("reports.wb_stocks_sales_hourly пуст: нечего обновлять в wb_1pager_ai_hourly")

            execute_sql(cur, 
                """
                INSERT INTO reports.wb_1pager_ai_hourly_target (target_key, snapshot_hour, updated_at)
                VALUES ('build', %s, CURRENT_TIMESTAMP)
                ON CONFLICT (target_key) DO UPDATE SET
                    snapshot_hour = EXCLUDED.snapshot_hour,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (target_hour,),
            )

            execute_sql(cur, 
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'wb_1pager_ai_hourly'
                ORDER BY ordinal_position
                """,
                (ANALYTICS_AI_SCHEMA,),
            )
            table_columns = [row[0] for row in cur.fetchall()]
            if not table_columns:
                raise ValueError("Не найдена таблица reports.wb_1pager_ai_hourly после применения SQL")

            data_columns = [column for column in table_columns if column != "updated_at"]
            conflict_columns = {"snapshot_hour", "id"}
            update_columns = [column for column in data_columns if column not in conflict_columns]

            insert_sql = f"""
                INSERT INTO reports.wb_1pager_ai_hourly ({", ".join(data_columns)}, updated_at)
                SELECT {", ".join(data_columns)}, CURRENT_TIMESTAMP
                FROM reports.v_1pager_ai_hourly_source
                ON CONFLICT (snapshot_hour, id)
                DO UPDATE SET
                    {", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)},
                    updated_at = EXCLUDED.updated_at
            """
            execute_sql(cur, insert_sql)
            logger.info(
                "wb_1pager_ai_hourly upsert выполнен; target_hour=%s, затронуто строк: %s",
                target_hour,
                cur.rowcount,
            )


def validate_feature_views_task(tenant_id: str, **context):
    """Ensure daily 1pager views point to the expected source dates after each DAG run."""
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, "SELECT MAX(report_date) FROM reports.v_1pager_daily_source")
            source_max_date = cur.fetchone()[0]
            if source_max_date is None:
                raise ValueError("reports.v_1pager_daily_source пустая: нечего валидировать в 1pager views")

            execute_sql(
                cur,
                """
                SELECT MAX(report_date)
                FROM reports.v_1pager_daily_source
                WHERE report_date < timezone('Europe/Moscow', now())::date
                """,
            )
            source_latest_complete_date = cur.fetchone()[0]

            validations = [
                ("reports.v_1pager_ai", None, source_latest_complete_date),
                ("reports.v_1pager_ai_daily", None, source_latest_complete_date),
                ("reports.v_1pager_ml", 5, source_latest_complete_date),
            ]

            for view_name, expected_recent_dates, expected_max_date in validations:
                execute_sql(cur, f"SELECT MAX(report_date), COUNT(*) FROM {view_name}")
                view_max_date, total_rows = cur.fetchone()
                logger.info(
                    "%s: max_date=%s, rows=%s, expected_max_date=%s, source_max_date=%s",
                    view_name,
                    view_max_date,
                    total_rows,
                    expected_max_date,
                    source_max_date,
                )
                if expected_max_date is None:
                    logger.warning(
                        "%s: в source view пока нет полного дня для валидации, пропускаем проверку max_date",
                        view_name,
                    )
                    continue
                if total_rows == 0:
                    raise ValueError(f"{view_name} пустая после обновления DAG")
                if view_max_date != expected_max_date:
                    raise ValueError(
                        f"{view_name} не видит ожидаемую дату source view: "
                        f"view_max_date={view_max_date}, expected_max_date={expected_max_date}, "
                        f"source_max_date={source_max_date}"
                    )

                if expected_recent_dates is not None:
                    execute_sql(cur, f"SELECT COUNT(DISTINCT report_date) FROM {view_name}")
                    distinct_dates = cur.fetchone()[0]
                    logger.info("%s: distinct report_date=%s", view_name, distinct_dates)
                    if distinct_dates > expected_recent_dates:
                        raise ValueError(
                            f"{view_name} содержит слишком много дат: "
                            f"{distinct_dates} > {expected_recent_dates}"
                        )

    logger.info("Валидация 1pager views завершена")


def ensure_ml_schema_task(tenant_id: str, **context):
    """Apply ML forecast tables and consumer view."""
    with _tenant_connection(tenant_id, autocommit=True) as conn:
        with conn.cursor() as cur:
            for sql_path in ML_FORECAST_FILES:
                _apply_sql_file(cur, sql_path, label="ML forecast schema")


def predict_ml_forecast_daily_task(tenant_id: str, **context):
    """Run daily ML scoring on the latest completed 1pager_ml date."""
    result = run_tenant_job(
        tenant_id=tenant_id,
        module_dir="ML",
        action="callable",
        module_name="predict_daily",
        attr_name="run",
    )
    logger.info("ML daily scoring result: %s", result)
    context["ti"].xcom_push(key="ml_forecast_daily_result", value=result)


def explain_ml_forecast_daily_task(tenant_id: str, **context):
    """Generate LLM explanations for the latest ML forecast slice without failing the DAG on LLM errors."""
    result = run_tenant_job(
        tenant_id=tenant_id,
        module_dir="ML",
        action="callable",
        module_name="explain_daily",
        attr_name="run",
    )
    logger.info("ML daily explanations result: %s", result)
    context["ti"].xcom_push(key="ml_forecast_explanations_result", value=result)


def validate_ml_forecast_daily_task(tenant_id: str, **context):
    """Validate that the daily ML forecast exists for the latest completed serving date."""
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, "SELECT MAX(report_date) FROM reports.v_1pager_ml")
            report_date = cur.fetchone()[0]
            if report_date is None:
                raise ValueError("reports.v_1pager_ml пустая: нечего валидировать в ML forecast")

            execute_sql(
                cur,
                "SELECT COUNT(*) FROM reports.v_1pager_ml WHERE report_date = %s",
                (report_date,),
            )
            source_rows = cur.fetchone()[0]
            if source_rows == 0:
                raise ValueError(f"reports.v_1pager_ml не содержит строк за {report_date}")

            execute_sql(
                cur,
                """
                SELECT model_version
                FROM reports.wb_ml_forecast_daily
                WHERE report_date = %s
                ORDER BY updated_at DESC, model_version DESC
                LIMIT 1
                """,
                (report_date,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Не найден ML forecast за {report_date}")
            model_version = row[0]

            execute_sql(
                cur,
                """
                SELECT COUNT(*)
                FROM reports.wb_ml_forecast_daily
                WHERE report_date = %s
                  AND model_version = %s
                """,
                (report_date, model_version),
            )
            forecast_rows = cur.fetchone()[0]
            if forecast_rows != source_rows:
                raise ValueError(
                    f"ML forecast row count mismatch for {report_date}: "
                    f"source_rows={source_rows}, forecast_rows={forecast_rows}, model_version={model_version}"
                )

            execute_sql(
                cur,
                """
                SELECT COUNT(*)
                FROM (
                    SELECT report_date, nm_id, model_version, COUNT(*) AS dup_count
                    FROM reports.wb_ml_forecast_daily
                    WHERE report_date = %s
                      AND model_version = %s
                    GROUP BY report_date, nm_id, model_version
                    HAVING COUNT(*) > 1
                ) dupes
                """,
                (report_date, model_version),
            )
            duplicate_rows = cur.fetchone()[0]
            if duplicate_rows > 0:
                raise ValueError(
                    f"ML forecast содержит дубли по (report_date, nm_id, model_version): {duplicate_rows}"
                )

            execute_sql(
                cur,
                """
                SELECT COUNT(*)
                FROM reports.wb_ml_forecast_explanations
                WHERE report_date = %s
                  AND model_version = %s
                """,
                (report_date, model_version),
            )
            explanation_rows = cur.fetchone()[0]
            logger.info(
                "ML forecast validated: report_date=%s, model_version=%s, source_rows=%s, forecast_rows=%s, explanation_rows=%s",
                report_date,
                model_version,
                source_rows,
                forecast_rows,
                explanation_rows,
            )


def validate_hourly_feature_views_task(tenant_id: str, **context):
    """Ensure the accumulated hourly 1pager table exposes rows for the latest snapshot hour."""
    with _tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            execute_sql(cur, "SELECT MAX(snapshot_hour) FROM reports.wb_stocks_sales_hourly")
            target_hour = cur.fetchone()[0]
            if target_hour is None:
                raise ValueError("reports.wb_stocks_sales_hourly пуст: нечего валидировать в hourly 1pager")

            execute_sql(cur, 
                """
                SELECT
                    COUNT(*) AS source_rows,
                    COUNT(*) FILTER (WHERE COALESCE(stock_quantity, 0) > 0) AS source_rows_with_stock
                FROM reports.wb_stocks_sales_hourly
                WHERE snapshot_hour = %s
                """,
                (target_hour,),
            )
            source_rows, source_rows_with_stock = cur.fetchone()
            logger.info(
                "reports.wb_stocks_sales_hourly: target_hour=%s, rows=%s, rows_with_stock=%s",
                target_hour,
                source_rows,
                source_rows_with_stock,
            )
            if source_rows == 0:
                raise ValueError(
                    "reports.wb_stocks_sales_hourly не содержит строк за последний snapshot_hour "
                    f"({target_hour})"
                )

            execute_sql(cur, 
                """
                SELECT MAX(snapshot_hour), COUNT(*)
                FROM reports.wb_1pager_ai_hourly
                WHERE snapshot_hour = %s
                """,
                (target_hour,),
            )
            table_max_hour, total_rows = cur.fetchone()
            logger.info(
                "reports.wb_1pager_ai_hourly: max_hour=%s, rows=%s, target_hour=%s",
                table_max_hour,
                total_rows,
                target_hour,
            )
            if total_rows == 0:
                if source_rows_with_stock == 0:
                    logger.warning(
                        "reports.wb_1pager_ai_hourly пустая за %s, потому что в hourly summary нет "
                        "товаров с остатком > 0",
                        target_hour,
                    )
                    return
                raise ValueError("reports.wb_1pager_ai_hourly пустая после hourly DAG")
            if table_max_hour != target_hour:
                raise ValueError(
                    "reports.wb_1pager_ai_hourly не синхронизирована с последним snapshot_hour "
                    f"(table={table_max_hour}, expected={target_hour})"
                )

            execute_sql(cur, "SELECT MAX(snapshot_hour), COUNT(*) FROM reports.v_1pager_ai")
            alias_max_hour, alias_rows = cur.fetchone()
            logger.info(
                "reports.v_1pager_ai: max_hour=%s, rows=%s, target_hour=%s",
                alias_max_hour,
                alias_rows,
                target_hour,
            )
            if alias_rows == 0:
                raise ValueError("reports.v_1pager_ai пустая после hourly DAG")
            if alias_max_hour != target_hour:
                raise ValueError(
                    "reports.v_1pager_ai не указывает на последний snapshot_hour "
                    f"(alias={alias_max_hour}, expected={target_hour})"
                )

    logger.info("Валидация hourly 1pager завершена")
