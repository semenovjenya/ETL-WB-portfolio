CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

DROP VIEW IF EXISTS analytics_ai.v_1pager_ml_forecast_brief;

CREATE VIEW analytics_ai.v_1pager_ml_forecast_brief AS
SELECT
    report_date,
    sku,
    recent_orders_7d,
    ml_forecast_7d,
    sales_check_forecast_7d,
    forecast_consistency_label AS trust_level,
    CASE
        WHEN forecast_consistency_label = 'high' THEN
            CONCAT('ML и контрольный прогноз близки. ', sales_check_summary)
        WHEN forecast_consistency_label = 'medium' THEN
            CONCAT('Прогноз спорный: ML и контрольный прогноз расходятся умеренно. ', sanity_check_comment)
        ELSE
            CONCAT('Прогноз требует ручной проверки. ', sanity_check_comment)
    END AS short_summary,
    model_version,
    updated_at
FROM analytics_ai.v_1pager_ml_forecast_readable;

COMMENT ON VIEW analytics_ai.v_1pager_ml_forecast_brief IS
'Brief business-readable 1pager ML forecast view with only SKU, ML forecast, sales-check forecast, trust level, and short summary.';
