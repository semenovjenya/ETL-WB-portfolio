from wb_schemas import (
    ANALYTICS_AI_SCHEMA,
    FINANCE_SCHEMA,
    MARKETING_SCHEMA,
    PRICING_SCHEMA,
    SALES_SCHEMA,
    SUPPLY_SCHEMA,
    compat_bundle_enabled,
    compat_sql_path,
    domain_sql_path,
    qualify_object,
    rewrite_reports_sql,
)


def test_qualify_object_routes_to_expected_domain():
    assert qualify_object("wb_supplier_stocks") == f"{SUPPLY_SCHEMA}.wb_supplier_stocks"
    assert qualify_object("wb_supplier_sales") == f"{SALES_SCHEMA}.wb_supplier_sales"
    assert qualify_object("wb_supplier_prices") == f"{PRICING_SCHEMA}.wb_supplier_prices"
    assert qualify_object("wb_marketing_campaigns") == f"{MARKETING_SCHEMA}.wb_marketing_campaigns"
    assert qualify_object("mart_marketing_forecast_ready") == f"{MARKETING_SCHEMA}.mart_marketing_forecast_ready"
    assert qualify_object("wb_report_detail_daily") == f"{FINANCE_SCHEMA}.wb_report_detail_daily"
    assert qualify_object("wb_product_costs") == f"{FINANCE_SCHEMA}.wb_product_costs"
    assert qualify_object("wb_profit_calculator_results") == f"{FINANCE_SCHEMA}.wb_profit_calculator_results"
    assert qualify_object("mart_ai_sales_planning") == f"{ANALYTICS_AI_SCHEMA}.mart_ai_sales_planning"


def test_rewrite_reports_sql_rewrites_cross_domain_references():
    sql = """
    SELECT *
    FROM reports.wb_supplier_stocks s
    JOIN reports.wb_supplier_sales sale ON sale.nm_id = s.nm_id
    JOIN reports.wb_report_detail_daily rd ON rd.nm_id = s.nm_id
    JOIN reports.mart_ai_sales_planning mart ON mart.nm_id = s.nm_id
    """
    rewritten = rewrite_reports_sql(sql)
    assert f"{SUPPLY_SCHEMA}.wb_supplier_stocks" in rewritten
    assert f"{SALES_SCHEMA}.wb_supplier_sales" in rewritten
    assert f"{FINANCE_SCHEMA}.wb_report_detail_daily" in rewritten
    assert rewrite_reports_sql("SELECT * FROM reports.wb_product_costs") == f"SELECT * FROM {FINANCE_SCHEMA}.wb_product_costs"
    assert rewrite_reports_sql("SELECT * FROM reports.wb_profit_calculator_results") == f"SELECT * FROM {FINANCE_SCHEMA}.wb_profit_calculator_results"
    assert rewrite_reports_sql("SELECT reports.sync_wb_profit_calculator_scenarios_from_sku_ai_analysis()") == f"SELECT {FINANCE_SCHEMA}.sync_wb_profit_calculator_scenarios_from_sku_ai_analysis()"
    assert f"{ANALYTICS_AI_SCHEMA}.mart_ai_sales_planning" in rewritten


def test_generated_domain_and_compat_paths_exist():
    assert domain_sql_path("schema_supplier_stocks.sql").exists()
    assert domain_sql_path("schema_mart_ai_sales_planning.sql").exists()
    assert domain_sql_path("schema_wb_marketing_marts.sql").exists()
    assert domain_sql_path("schema_wb_marketing_demand_forecast.sql").exists()
    assert domain_sql_path("1pager_daily_source.sql").exists()
    assert domain_sql_path("schema_stocks_sales_hourly.sql").exists()
    assert domain_sql_path("schema_wb_ml_forecast.sql").exists()
    assert domain_sql_path("1pager_ml_forecast.sql").exists()
    assert domain_sql_path("1pager_ml_forecast_readable.sql").exists()
    assert domain_sql_path("1pager_ml_forecast_brief.sql").exists()
    assert compat_sql_path("schema_supplier_stocks.sql").exists()
    assert compat_sql_path("1pager_daily_source.sql").exists()
    assert compat_sql_path("schema_stocks_sales_hourly.sql").exists()
    assert compat_sql_path("1pager_ml_forecast.sql").exists()
    assert compat_sql_path("1pager_ml_forecast_readable.sql").exists()
    assert compat_sql_path("1pager_ml_forecast_brief.sql").exists()


def test_only_1pager_bundles_recreate_reports_compat_views():
    assert compat_bundle_enabled("1pager_daily_source.sql") is True
    assert compat_bundle_enabled("1pager_ai.sql") is True
    assert compat_bundle_enabled("1pager_ai_hourly.sql") is True
    assert compat_bundle_enabled("1pager_ml.sql") is True
    assert compat_bundle_enabled("1pager_ml_forecast.sql") is True
    assert compat_bundle_enabled("1pager_ml_forecast_readable.sql") is True
    assert compat_bundle_enabled("1pager_ml_forecast_brief.sql") is True
    assert compat_bundle_enabled("schema_supplier_stocks.sql") is False
    assert compat_bundle_enabled("schema_wb_tariffs.sql") is False


def test_marketing_analytics_schema_contains_payments_and_snapshot_hour_contract():
    sql = domain_sql_path("schema_wb_marketing_analytics.sql").read_text(encoding="utf-8")
    campaign_sql = domain_sql_path("schema_wb_marketing_campaigns.sql").read_text(encoding="utf-8")

    assert "marketing.wb_marketing_payments" in sql
    assert "snapshot_hour TIMESTAMP WITH TIME ZONE" in sql
    assert "snapshot_hour TIMESTAMP WITH TIME ZONE" in campaign_sql


def test_marketing_marts_schema_contains_forecast_materialized_views():
    sql = domain_sql_path("schema_wb_marketing_marts.sql").read_text(encoding="utf-8")

    assert "marketing.mart_marketing_query_daily" in sql
    assert "marketing.mart_marketing_campaign_daily" in sql
    assert "marketing.mart_marketing_query_bands" in sql
    assert "marketing.mart_marketing_forecast_ready" in sql
    assert "CREATE MATERIALIZED VIEW marketing.mart_marketing_query_daily" in sql
    assert "CREATE MATERIALIZED VIEW marketing.mart_marketing_forecast_ready" in sql


def test_marketing_demand_forecast_schema_contains_query_share_materialized_views():
    sql = domain_sql_path("schema_wb_marketing_demand_forecast.sql").read_text(encoding="utf-8")

    assert "marketing.normalize_query_text" in sql
    assert "marketing.mart_marketing_query_demand_daily" in sql
    assert "marketing.mart_marketing_query_share_daily" in sql
    assert "marketing.mart_marketing_query_forecast_ready" in sql
    assert "marketing.mart_marketing_campaign_demand_forecast" in sql
    assert "CREATE MATERIALIZED VIEW marketing.mart_marketing_query_share_daily" in sql
    assert "CREATE MATERIALIZED VIEW marketing.mart_marketing_campaign_demand_forecast" in sql


def test_price_ai_schema_contains_canonical_serp_contract_and_marts():
    sql = domain_sql_path("schema_wb_price_ai_analysis.sql").read_text(encoding="utf-8")

    assert "analytics_ai.wb_serp_runs" in sql
    assert "analytics_ai.wb_serp_query_sets" in sql
    assert "analytics_ai.wb_serp_items" in sql
    assert "analytics_ai.wb_serp_jobs" in sql
    assert "analytics_ai.wb_serp_worker_heartbeats" in sql
    assert "analytics_ai.mart_serp_query_daily" in sql
    assert "analytics_ai.mart_serp_competitors_daily" in sql
    assert "source_price_site_display" in sql
    assert "source_report_to_site_discount_percent" in sql
    assert "analytics_ai.v_wb_serp_competitors_latest" in sql
    assert "analytics_ai.mart_price_context_daily" in sql
    assert "source_position_organic_absolute" in sql
    assert "placement_type IN ('organic', 'sponsored', 'unknown')" in sql
    assert "parser_status IN ('success', 'source_not_found')" in sql
    assert "source_price_effective" in sql
