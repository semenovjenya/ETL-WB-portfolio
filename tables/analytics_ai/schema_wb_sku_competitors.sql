CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_sku_competitors') IS NOT NULL AND to_regclass('analytics_ai.wb_sku_competitors') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_sku_competitors SET SCHEMA analytics_ai';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE TABLE IF NOT EXISTS analytics_ai.wb_sku_competitors (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    searched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_snapshot_date DATE,
    source_nm_id BIGINT NOT NULL,
    source_barcode VARCHAR(255),
    source_brand VARCHAR(255),
    source_subject_name VARCHAR(500),
    source_title VARCHAR(1000),
    source_product_url TEXT,
    source_price_regular NUMERIC(12, 2),
    source_price_promo NUMERIC(12, 2) NOT NULL,
    source_price_segment_min NUMERIC(12, 2),
    source_price_segment_max NUMERIC(12, 2),
    source_colors_json JSONB,
    keyword TEXT NOT NULL,
    keyword_order INTEGER NOT NULL,
    catalog_page INTEGER,
    catalog_position_on_page INTEGER,
    catalog_position_absolute INTEGER,
    competitor_nm_id BIGINT NOT NULL,
    competitor_brand VARCHAR(255),
    competitor_supplier_name VARCHAR(500),
    competitor_supplier_id BIGINT,
    competitor_subject_name VARCHAR(500),
    competitor_title VARCHAR(1000),
    competitor_description_short TEXT,
    competitor_colors_json JSONB,
    competitor_main_photo_url TEXT,
    competitor_product_url TEXT NOT NULL,
    competitor_price_regular NUMERIC(12, 2),
    competitor_price_promo NUMERIC(12, 2) NOT NULL,
    competitor_discount_percent NUMERIC(6, 2),
    competitor_rating NUMERIC(6, 2),
    competitor_feedbacks INTEGER,
    photo_ai_is_competitor BOOLEAN,
    photo_ai_confidence NUMERIC(6, 4),
    photo_ai_reason TEXT,
    photo_ai_model VARCHAR(100),
    photo_ai_raw_json JSONB,
    price_delta_abs NUMERIC(12, 2),
    price_delta_percent NUMERIC(6, 2),
    within_price_segment BOOLEAN NOT NULL,
    same_subject BOOLEAN NOT NULL,
    same_color BOOLEAN,
    search_payload_json JSONB,
    detail_payload_json JSONB,
    parser_status VARCHAR(32) NOT NULL,
    parser_error TEXT,
    UNIQUE (run_date, source_nm_id, keyword, competitor_nm_id)
);

ALTER TABLE analytics_ai.wb_sku_competitors
    ADD COLUMN IF NOT EXISTS source_price_segment_min NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS source_price_segment_max NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS source_colors_json JSONB,
    ADD COLUMN IF NOT EXISTS competitor_supplier_name VARCHAR(500),
    ADD COLUMN IF NOT EXISTS competitor_supplier_id BIGINT,
    ADD COLUMN IF NOT EXISTS competitor_colors_json JSONB,
    ADD COLUMN IF NOT EXISTS competitor_main_photo_url TEXT,
    ADD COLUMN IF NOT EXISTS same_color BOOLEAN,
    ADD COLUMN IF NOT EXISTS photo_ai_is_competitor BOOLEAN,
    ADD COLUMN IF NOT EXISTS photo_ai_confidence NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS photo_ai_reason TEXT,
    ADD COLUMN IF NOT EXISTS photo_ai_model VARCHAR(100),
    ADD COLUMN IF NOT EXISTS photo_ai_raw_json JSONB;

CREATE INDEX IF NOT EXISTS idx_wb_sku_competitors_run_date
    ON analytics_ai.wb_sku_competitors (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_sku_competitors_source_nm_id
    ON analytics_ai.wb_sku_competitors (source_nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_sku_competitors_competitor_nm_id
    ON analytics_ai.wb_sku_competitors (competitor_nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_sku_competitors_source_filters
    ON analytics_ai.wb_sku_competitors (source_nm_id, within_price_segment, same_subject);

CREATE INDEX IF NOT EXISTS idx_wb_sku_competitors_source_color
    ON analytics_ai.wb_sku_competitors (source_nm_id, same_color);

CREATE INDEX IF NOT EXISTS idx_wb_sku_competitors_source_keyword
    ON analytics_ai.wb_sku_competitors (source_nm_id, keyword);

CREATE INDEX IF NOT EXISTS idx_wb_sku_competitors_keyword_position
    ON analytics_ai.wb_sku_competitors (keyword, catalog_position_absolute);

DROP VIEW IF EXISTS analytics_ai.v_wb_sku_competitors_export;

CREATE OR REPLACE VIEW analytics_ai.v_wb_sku_competitors_export AS
SELECT
    run_date,
    source_nm_id,
    source_title,
    keyword,
    competitor_nm_id,
    competitor_product_url,
    competitor_price_regular,
    competitor_price_promo,
    competitor_supplier_name,
    competitor_supplier_id,
    source_price_segment_min,
    source_price_segment_max,
    source_colors_json,
    catalog_position_absolute,
    catalog_page,
    catalog_position_on_page,
    price_delta_abs,
    price_delta_percent,
    competitor_brand,
    competitor_subject_name,
    competitor_title,
    competitor_description_short,
    competitor_colors_json,
    competitor_main_photo_url,
    same_color,
    photo_ai_is_competitor,
    photo_ai_confidence,
    photo_ai_reason,
    photo_ai_model,
    competitor_rating,
    competitor_feedbacks
FROM analytics_ai.wb_sku_competitors;
