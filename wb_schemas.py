from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


SUPPLY_SCHEMA = "supply"
SALES_SCHEMA = "sales"
PRICING_SCHEMA = "pricing"
MARKETING_SCHEMA = "marketing"
FINANCE_SCHEMA = "finance"
ANALYTICS_AI_SCHEMA = "analytics_ai"
COMPAT_SCHEMA = "reports"
COMPAT_VIEW_BUNDLES: frozenset[str] = frozenset(
    {
        "1pager_daily_source.sql",
        "1pager_ai.sql",
        "1pager_ai_hourly.sql",
        "1pager_ml.sql",
        "1pager_ml_forecast.sql",
        "1pager_ml_forecast_readable.sql",
        "1pager_ml_forecast_brief.sql",
    }
)
VIEWLESS_DDL_FILES: frozenset[str] = frozenset(
    {
        "schema_wb_tariffs.sql",
        "schema_wb_marketing_campaigns.sql",
        "schema_wb_marketing_analytics.sql",
    }
)

PROJECT_ROOT = Path(__file__).resolve().parent
TABLES_ROOT = PROJECT_ROOT / "tables"

DDL_FILE_SCHEMAS: dict[str, str] = {
    "schema_supplier_stocks.sql": SUPPLY_SCHEMA,
    "schema_wb_supplies.sql": SUPPLY_SCHEMA,
    "schema_supplier_sales.sql": SALES_SCHEMA,
    "schema_supplier_orders.sql": SALES_SCHEMA,
    "schema_sales_funnel.sql": SALES_SCHEMA,
    "schema_sales_funnel_daily.sql": SALES_SCHEMA,
    "schema_sales_funnel_weekly.sql": SALES_SCHEMA,
    "schema_supplier_prices.sql": PRICING_SCHEMA,
    "schema_mart_price_decision_latest.sql": PRICING_SCHEMA,
    "schema_wb_tariffs.sql": PRICING_SCHEMA,
    "schema_wb_marketing_campaigns.sql": MARKETING_SCHEMA,
    "schema_wb_marketing_analytics.sql": MARKETING_SCHEMA,
    "schema_wb_marketing_marts.sql": MARKETING_SCHEMA,
    "schema_wb_marketing_demand_forecast.sql": MARKETING_SCHEMA,
    "schema_calendar_promotions.sql": MARKETING_SCHEMA,
    "schema_wb_search_queries.sql": MARKETING_SCHEMA,
    "schema_report_detail.sql": FINANCE_SCHEMA,
    "schema_stocks_sales_daily.sql": ANALYTICS_AI_SCHEMA,
    "schema_stocks_sales_hourly.sql": ANALYTICS_AI_SCHEMA,
    "schema_mart_ai_sales_planning.sql": ANALYTICS_AI_SCHEMA,
    "1pager_daily_source.sql": ANALYTICS_AI_SCHEMA,
    "1pager_ai.sql": ANALYTICS_AI_SCHEMA,
    "1pager_ai_hourly.sql": ANALYTICS_AI_SCHEMA,
    "1pager_ml.sql": ANALYTICS_AI_SCHEMA,
    "schema_wb_ml_forecast.sql": ANALYTICS_AI_SCHEMA,
    "1pager_ml_forecast.sql": ANALYTICS_AI_SCHEMA,
    "1pager_ml_forecast_readable.sql": ANALYTICS_AI_SCHEMA,
    "1pager_ml_forecast_brief.sql": ANALYTICS_AI_SCHEMA,
    "view_stocks_sales_daily_readable.sql": ANALYTICS_AI_SCHEMA,
    "report_products.sql": ANALYTICS_AI_SCHEMA,
    "report_stocks_reorder.sql": ANALYTICS_AI_SCHEMA,
    "schema_wb_unit_economics.sql": ANALYTICS_AI_SCHEMA,
    "schema_wb_profit_calculator.sql": FINANCE_SCHEMA,
    "schema_wb_sku_ai_analysis.sql": ANALYTICS_AI_SCHEMA,
    "schema_wb_sku_competitors.sql": ANALYTICS_AI_SCHEMA,
    "schema_wb_price_ai_analysis.sql": ANALYTICS_AI_SCHEMA,
    "quality_mart_ai_sales_planning_latest.sql": ANALYTICS_AI_SCHEMA,
}

EXACT_OBJECT_SCHEMAS: dict[str, str] = {
    "parse_wb_numeric": PRICING_SCHEMA,
    "mart_ai_sales_planning": ANALYTICS_AI_SCHEMA,
    "refresh_wb_unit_economics": ANALYTICS_AI_SCHEMA,
    "refresh_wb_profit_calculator_results": FINANCE_SCHEMA,
    "set_wb_profit_calc_updated_at": FINANCE_SCHEMA,
    "sync_wb_profit_calculator_scenarios_from_sku_ai_analysis": FINANCE_SCHEMA,
    "sync_wb_profit_calculator_scenarios_from_stocks": FINANCE_SCHEMA,
    "seed_wb_profit_calculator_scenarios": FINANCE_SCHEMA,
    "v_stocks_sales_daily": ANALYTICS_AI_SCHEMA,
    "v_stocks_sales_hourly": ANALYTICS_AI_SCHEMA,
    "v_stocks_sales_daily_readable": ANALYTICS_AI_SCHEMA,
    "v_1pager_daily_source": ANALYTICS_AI_SCHEMA,
    "v_1pager_ai": ANALYTICS_AI_SCHEMA,
    "v_1pager_ai_daily": ANALYTICS_AI_SCHEMA,
    "v_1pager_ai_hourly": ANALYTICS_AI_SCHEMA,
    "v_1pager_ai_hourly_source": ANALYTICS_AI_SCHEMA,
    "v_1pager_ml_train": ANALYTICS_AI_SCHEMA,
    "v_1pager_ml": ANALYTICS_AI_SCHEMA,
    "wb_ml_forecast_daily": ANALYTICS_AI_SCHEMA,
    "wb_ml_forecast_explanations": ANALYTICS_AI_SCHEMA,
    "v_1pager_ml_forecast": ANALYTICS_AI_SCHEMA,
    "v_1pager_ml_forecast_readable": ANALYTICS_AI_SCHEMA,
    "v_1pager_ml_forecast_brief": ANALYTICS_AI_SCHEMA,
    "v_report_products": ANALYTICS_AI_SCHEMA,
    "v_report_stocks_reorder": ANALYTICS_AI_SCHEMA,
    "v_report_stocks_reorder_alert": ANALYTICS_AI_SCHEMA,
    "v_wb_profit_calculator_results_source": FINANCE_SCHEMA,
    "v_wb_price_ai_analysis_latest": ANALYTICS_AI_SCHEMA,
    "mart_serp_query_daily": ANALYTICS_AI_SCHEMA,
    "mart_serp_competitors_daily": ANALYTICS_AI_SCHEMA,
    "v_wb_serp_competitors_latest": ANALYTICS_AI_SCHEMA,
    "mart_price_context_daily": ANALYTICS_AI_SCHEMA,
    "v_wb_serp_health": ANALYTICS_AI_SCHEMA,
    "v_wb_sku_competitors_export": ANALYTICS_AI_SCHEMA,
    "v_wb_unit_economics": ANALYTICS_AI_SCHEMA,
}

PREFIX_SCHEMAS: tuple[tuple[str, str], ...] = (
    ("wb_supplier_stocks", SUPPLY_SCHEMA),
    ("v_wb_supplier_stocks", SUPPLY_SCHEMA),
    ("wb_supplies", SUPPLY_SCHEMA),
    ("v_wb_supplies", SUPPLY_SCHEMA),
    ("wb_supplier_sales", SALES_SCHEMA),
    ("v_wb_supplier_sales", SALES_SCHEMA),
    ("wb_supplier_orders", SALES_SCHEMA),
    ("v_wb_supplier_orders", SALES_SCHEMA),
    ("wb_sales_funnel", SALES_SCHEMA),
    ("wb_supplier_prices", PRICING_SCHEMA),
    ("v_wb_supplier_prices", PRICING_SCHEMA),
    ("wb_tariffs", PRICING_SCHEMA),
    ("v_wb_tariffs", PRICING_SCHEMA),
    ("wb_marketing", MARKETING_SCHEMA),
    ("mart_marketing", MARKETING_SCHEMA),
    ("v_wb_marketing", MARKETING_SCHEMA),
    ("wb_calendar_promotions", MARKETING_SCHEMA),
    ("v_wb_calendar_promotions", MARKETING_SCHEMA),
    ("wb_search_query", MARKETING_SCHEMA),
    ("wb_report_detail", FINANCE_SCHEMA),
    ("wb_product_cost", FINANCE_SCHEMA),
    ("wb_stocks_sales", ANALYTICS_AI_SCHEMA),
    ("wb_1pager_ai_hourly", ANALYTICS_AI_SCHEMA),
    ("wb_ml_forecast", ANALYTICS_AI_SCHEMA),
    ("wb_unit_economics", ANALYTICS_AI_SCHEMA),
    ("wb_profit_calculator", FINANCE_SCHEMA),
    ("wb_sku_", ANALYTICS_AI_SCHEMA),
    ("wb_price_ai", ANALYTICS_AI_SCHEMA),
    ("wb_serp_", ANALYTICS_AI_SCHEMA),
)

REPORTS_OBJECT_RE = re.compile(r"\breports\.([A-Za-z_][A-Za-z0-9_]*)\b")
COMPAT_VIEW_CREATE_RE = re.compile(
    r"(?ims)^\s*CREATE\s+OR\s+REPLACE\s+VIEW\b.*?;\s*"
)
GENERIC_VIEW_CREATE_RE = re.compile(
    r"(?ims)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\b.*?;\s*"
)
COMMENT_ON_VIEW_RE = re.compile(
    r"(?ims)^\s*COMMENT\s+ON\s+VIEW\b.*?;\s*"
)


def canonical_schema_for_object(object_name: str) -> str:
    schema = EXACT_OBJECT_SCHEMAS.get(object_name)
    if schema:
        return schema
    for prefix, candidate in PREFIX_SCHEMAS:
        if object_name.startswith(prefix):
            return candidate
    raise KeyError(f"Unknown schema mapping for object: {object_name}")


def qualify_object(object_name: str) -> str:
    return f"{canonical_schema_for_object(object_name)}.{object_name}"


def compat_qualified_object(object_name: str) -> str:
    return f"{COMPAT_SCHEMA}.{object_name}"


def rewrite_reports_sql(sql: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        object_name = match.group(1)
        try:
            return qualify_object(object_name)
        except KeyError:
            return match.group(0)

    return REPORTS_OBJECT_RE.sub(_replace, sql)


def domain_sql_path(filename: str) -> Path:
    schema = DDL_FILE_SCHEMAS[filename]
    return TABLES_ROOT / schema / filename


def compat_sql_path(filename: str) -> Path:
    return TABLES_ROOT / "compat_reports" / filename


def compat_bundle_enabled(filename: str) -> bool:
    return filename in COMPAT_VIEW_BUNDLES


def load_sql_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def compat_teardown_sql(sql: str) -> str:
    return COMPAT_VIEW_CREATE_RE.sub("", sql)


def strip_view_sql(sql: str) -> str:
    sql = GENERIC_VIEW_CREATE_RE.sub("", sql)
    sql = COMMENT_ON_VIEW_RE.sub("", sql)
    return sql


def execute_sql(cursor, sql: str, params=None):
    return cursor.execute(rewrite_reports_sql(sql), params)


def execute_raw_sql(cursor, sql: str, params=None):
    return cursor.execute(sql, params)


def executemany_sql(cursor, sql: str, param_list: Iterable[object]):
    return cursor.executemany(rewrite_reports_sql(sql), param_list)


def execute_ddl_bundle(cursor, filename: str) -> None:
    compat_path = compat_sql_path(filename)
    compat_sql = None
    if compat_path.exists():
        compat_sql = load_sql_file(compat_path)
        execute_raw_sql(cursor, compat_teardown_sql(compat_sql))
    domain_sql = load_sql_file(domain_sql_path(filename))
    if filename in VIEWLESS_DDL_FILES:
        domain_sql = strip_view_sql(domain_sql)
    execute_sql(cursor, domain_sql)
    if compat_sql and compat_bundle_enabled(filename):
        execute_raw_sql(cursor, compat_sql)
