CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

DROP VIEW IF EXISTS analytics_ai.v_1pager_ml_forecast_readable;

CREATE VIEW analytics_ai.v_1pager_ml_forecast_readable AS
WITH recent_activity AS (
    SELECT
        current_day.report_date,
        current_day.nm_id,
        SUM(COALESCE(history.order_count_day, 0)) AS recent_orders_7d,
        SUM(COALESCE(history.buyout_count_day, 0)) AS recent_buyouts_7d
    FROM analytics_ai.v_1pager_daily_source current_day
    JOIN analytics_ai.v_1pager_daily_source history
      ON history.nm_id = current_day.nm_id
     AND history.report_date BETWEEN current_day.report_date - INTERVAL '6 days' AND current_day.report_date
    GROUP BY current_day.report_date, current_day.nm_id
)
SELECT
    f.report_date,
    f.nm_id,
    f.sku,
    COALESCE(a.recent_orders_7d, 0) AS recent_orders_7d,
    COALESCE(a.recent_buyouts_7d, 0) AS recent_buyouts_7d,
    f.sales_baseline_7d,
    f.forecast_7d AS ml_forecast_7d,
    f.trend_label AS ml_trend_label,
    f.sales_formula_v2_forecast_7d AS sales_check_forecast_7d,
    f.sales_formula_v2_trend_label AS sales_check_trend_label,
    CASE
        WHEN f.sales_formula_v2_forecast_7d IS NULL THEN NULL
        WHEN f.sales_formula_v2_forecast_7d = 0 THEN NULL
        ELSE ROUND(ABS(f.forecast_7d - f.sales_formula_v2_forecast_7d) / f.sales_formula_v2_forecast_7d * 100.0, 4)
    END AS ml_vs_sales_check_gap_pct,
    CASE
        WHEN f.sales_formula_v2_forecast_7d IS NULL THEN 'unknown'
        WHEN f.sales_formula_v2_forecast_7d = 0 AND f.forecast_7d = 0 THEN 'high'
        WHEN f.sales_formula_v2_forecast_7d = 0 THEN 'low'
        WHEN ABS(f.forecast_7d - f.sales_formula_v2_forecast_7d) / f.sales_formula_v2_forecast_7d <= 0.25 THEN 'high'
        WHEN ABS(f.forecast_7d - f.sales_formula_v2_forecast_7d) / f.sales_formula_v2_forecast_7d <= 0.50 THEN 'medium'
        ELSE 'low'
    END AS forecast_consistency_label,
    CASE
        WHEN f.sales_formula_v2_forecast_7d IS NULL THEN 'Нет контрольного sales-check прогноза.'
        WHEN f.sales_formula_v2_forecast_7d = 0 AND f.forecast_7d = 0 THEN 'ML и контрольный sales-check оба показывают почти нулевой прогноз.'
        WHEN f.sales_formula_v2_forecast_7d = 0 AND f.forecast_7d > 0 THEN 'ML заметно агрессивнее контрольного sales-check.'
        WHEN f.forecast_7d > f.sales_formula_v2_forecast_7d * 1.50 THEN 'ML заметно агрессивнее контрольного sales-check.'
        WHEN f.forecast_7d < f.sales_formula_v2_forecast_7d * 0.67 THEN 'ML заметно консервативнее контрольного sales-check.'
        ELSE 'ML близок к контрольному sales-check.'
    END AS sanity_check_comment,
    f.sales_formula_v2_reason_summary AS sales_check_summary,
    f.sales_formula_v2_reason_1 AS sales_check_reason_1,
    f.sales_formula_v2_reason_2 AS sales_check_reason_2,
    f.model_version,
    f.created_at,
    f.updated_at,
    f.explanation_created_at
FROM analytics_ai.v_1pager_ml_forecast f
LEFT JOIN recent_activity a
  ON a.report_date = f.report_date
 AND a.nm_id = f.nm_id;

COMMENT ON VIEW analytics_ai.v_1pager_ml_forecast_readable IS
'Readable 1pager ML forecast view with ML forecast, sales-check forecast, consistency label, and short rule-based explanations.';
