CREATE SCHEMA IF NOT EXISTS analytics_ai;

CREATE TABLE IF NOT EXISTS analytics_ai.wb_ml_forecast_daily (
    report_date DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    sku VARCHAR(255),
    pred_buyouts_7d NUMERIC(14, 4),
    pred_orders_7d NUMERIC(14, 4),
    pred_sales_baseline_7d NUMERIC(14, 4),
    pred_trend_ratio NUMERIC(14, 6),
    pred_trend_label VARCHAR(32),
    pred_delta_pct NUMERIC(14, 4),
    pred_confidence_score NUMERIC(10, 6),
    pred_confidence_label VARCHAR(16),
    sales_formula_v1_forecast_7d NUMERIC(14, 4),
    sales_formula_v1_baseline_7d NUMERIC(14, 4),
    sales_formula_v1_trend_ratio NUMERIC(14, 6),
    sales_formula_v1_trend_label VARCHAR(32),
    sales_formula_v1_reason_summary TEXT,
    sales_formula_v1_reason_1 TEXT,
    sales_formula_v1_reason_2 TEXT,
    sales_formula_v2_forecast_7d NUMERIC(14, 4),
    sales_formula_v2_baseline_7d NUMERIC(14, 4),
    sales_formula_v2_trend_ratio NUMERIC(14, 6),
    sales_formula_v2_trend_label VARCHAR(32),
    sales_formula_v2_reason_summary TEXT,
    sales_formula_v2_reason_1 TEXT,
    sales_formula_v2_reason_2 TEXT,
    model_version VARCHAR(128) NOT NULL,
    trained_on_max_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (report_date, nm_id, model_version)
);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS pred_sales_baseline_7d NUMERIC(14, 4);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS pred_trend_ratio NUMERIC(14, 6);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v1_forecast_7d NUMERIC(14, 4);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v1_baseline_7d NUMERIC(14, 4);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v1_trend_ratio NUMERIC(14, 6);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v1_trend_label VARCHAR(32);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v1_reason_summary TEXT;

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v1_reason_1 TEXT;

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v1_reason_2 TEXT;

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v2_forecast_7d NUMERIC(14, 4);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v2_baseline_7d NUMERIC(14, 4);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v2_trend_ratio NUMERIC(14, 6);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v2_trend_label VARCHAR(32);

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v2_reason_summary TEXT;

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v2_reason_1 TEXT;

ALTER TABLE analytics_ai.wb_ml_forecast_daily
    ADD COLUMN IF NOT EXISTS sales_formula_v2_reason_2 TEXT;

CREATE INDEX IF NOT EXISTS idx_wb_ml_forecast_daily_report_date
    ON analytics_ai.wb_ml_forecast_daily (report_date);

CREATE INDEX IF NOT EXISTS idx_wb_ml_forecast_daily_model_version
    ON analytics_ai.wb_ml_forecast_daily (model_version);

CREATE INDEX IF NOT EXISTS idx_wb_ml_forecast_daily_sku
    ON analytics_ai.wb_ml_forecast_daily (sku);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_ml_forecast_explanations (
    report_date DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    sku VARCHAR(255),
    model_version VARCHAR(128) NOT NULL,
    reason_summary TEXT,
    reason_1 TEXT,
    reason_2 TEXT,
    reason_3 TEXT,
    llm_model VARCHAR(100),
    prompt_version VARCHAR(50),
    source_features_hash VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (report_date, nm_id, model_version)
);

CREATE INDEX IF NOT EXISTS idx_wb_ml_forecast_explanations_report_date
    ON analytics_ai.wb_ml_forecast_explanations (report_date);

CREATE INDEX IF NOT EXISTS idx_wb_ml_forecast_explanations_model_version
    ON analytics_ai.wb_ml_forecast_explanations (model_version);
