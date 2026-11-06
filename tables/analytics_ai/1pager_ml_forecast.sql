CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

DROP VIEW IF EXISTS analytics_ai.v_1pager_ml_forecast;

CREATE VIEW analytics_ai.v_1pager_ml_forecast AS
WITH latest_versions AS (
    SELECT
        report_date,
        MAX(model_version) AS model_version
    FROM analytics_ai.wb_ml_forecast_daily
    GROUP BY report_date
)
SELECT
    f.report_date,
    f.nm_id,
    f.sku,
    f.pred_buyouts_7d AS forecast_7d,
    f.pred_sales_baseline_7d AS sales_baseline_7d,
    f.pred_trend_ratio AS trend_ratio,
    f.pred_trend_label AS trend_label,
    f.sales_formula_v1_forecast_7d,
    f.sales_formula_v1_baseline_7d,
    f.sales_formula_v1_trend_ratio,
    f.sales_formula_v1_trend_label,
    f.sales_formula_v1_reason_summary,
    f.sales_formula_v1_reason_1,
    f.sales_formula_v1_reason_2,
    f.sales_formula_v2_forecast_7d,
    f.sales_formula_v2_baseline_7d,
    f.sales_formula_v2_trend_ratio,
    f.sales_formula_v2_trend_label,
    f.sales_formula_v2_reason_summary,
    f.sales_formula_v2_reason_1,
    f.sales_formula_v2_reason_2,
    f.pred_buyouts_7d,
    f.pred_orders_7d,
    f.pred_sales_baseline_7d,
    f.pred_trend_ratio,
    f.pred_trend_label,
    f.pred_delta_pct,
    f.pred_confidence_score,
    f.pred_confidence_label,
    f.model_version,
    f.trained_on_max_date,
    e.reason_summary,
    e.reason_1,
    e.reason_2,
    e.reason_3,
    e.llm_model,
    e.prompt_version,
    e.source_features_hash,
    f.created_at,
    f.updated_at,
    e.created_at AS explanation_created_at
FROM analytics_ai.wb_ml_forecast_daily f
JOIN latest_versions lv
  ON lv.report_date = f.report_date
 AND lv.model_version = f.model_version
LEFT JOIN analytics_ai.wb_ml_forecast_explanations e
  ON e.report_date = f.report_date
 AND e.nm_id = f.nm_id
 AND e.model_version = f.model_version;

COMMENT ON VIEW analytics_ai.v_1pager_ml_forecast IS
'Joined ML forecast and LLM explanation layer for 1pager_ml. One row per report_date, nm_id, model_version.';
