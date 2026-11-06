CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_price_ai_seo_keywords') IS NOT NULL AND to_regclass('analytics_ai.wb_price_ai_seo_keywords') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_price_ai_seo_keywords SET SCHEMA analytics_ai';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_price_ai_competitors_raw') IS NOT NULL AND to_regclass('analytics_ai.wb_price_ai_competitors_raw') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_price_ai_competitors_raw SET SCHEMA analytics_ai';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_price_ai_competitor_features') IS NOT NULL AND to_regclass('analytics_ai.wb_price_ai_competitor_features') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_price_ai_competitor_features SET SCHEMA analytics_ai';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_price_ai_competitors_filtered') IS NOT NULL AND to_regclass('analytics_ai.wb_price_ai_competitors_filtered') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_price_ai_competitors_filtered SET SCHEMA analytics_ai';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_price_ai_competitor_relevance') IS NOT NULL AND to_regclass('analytics_ai.wb_price_ai_competitor_relevance') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_price_ai_competitor_relevance SET SCHEMA analytics_ai';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_price_ai_competitor_vision') IS NOT NULL AND to_regclass('analytics_ai.wb_price_ai_competitor_vision') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_price_ai_competitor_vision SET SCHEMA analytics_ai';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_price_ai_competitor_jobs') IS NOT NULL AND to_regclass('analytics_ai.wb_price_ai_competitor_jobs') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_price_ai_competitor_jobs SET SCHEMA analytics_ai';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_price_ai_analysis') IS NOT NULL AND to_regclass('analytics_ai.wb_price_ai_analysis') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_price_ai_analysis SET SCHEMA analytics_ai';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE TABLE IF NOT EXISTS analytics_ai.wb_price_ai_seo_keywords (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    source_snapshot_date DATE,
    source_nm_id BIGINT NOT NULL,
    source_title VARCHAR(1000),
    source_subject_name VARCHAR(500),
    source_brand VARCHAR(255),
    keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    keyword_count INTEGER NOT NULL DEFAULT 0,
    seo_model VARCHAR(100),
    seo_prompt_version VARCHAR(50),
    seo_status VARCHAR(32) NOT NULL,
    seo_error TEXT,
    raw_response_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_date, source_nm_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_seo_keywords_run_date
    ON analytics_ai.wb_price_ai_seo_keywords (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_seo_keywords_source_nm_id
    ON analytics_ai.wb_price_ai_seo_keywords (source_nm_id);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_price_ai_competitors_raw (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    source_snapshot_date DATE,
    source_nm_id BIGINT NOT NULL,
    source_barcode VARCHAR(255),
    source_brand VARCHAR(255),
    source_subject_name VARCHAR(500),
    source_title VARCHAR(1000),
    source_product_url TEXT,
    source_price_regular NUMERIC(12, 2),
    source_price_promo NUMERIC(12, 2),
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
    competitor_price_promo NUMERIC(12, 2),
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
    within_price_segment BOOLEAN NOT NULL DEFAULT FALSE,
    same_subject BOOLEAN NOT NULL DEFAULT FALSE,
    same_color BOOLEAN,
    search_payload_json JSONB,
    detail_payload_json JSONB,
    parser_status VARCHAR(32) NOT NULL,
    parser_error TEXT,
    competitor_status VARCHAR(32) NOT NULL DEFAULT 'success',
    competitor_error TEXT,
    task_attempt INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_date, source_nm_id, keyword, competitor_nm_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_raw_run_date
    ON analytics_ai.wb_price_ai_competitors_raw (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_raw_source_nm_id
    ON analytics_ai.wb_price_ai_competitors_raw (source_nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_raw_competitor_nm_id
    ON analytics_ai.wb_price_ai_competitors_raw (competitor_nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_raw_source_keyword
    ON analytics_ai.wb_price_ai_competitors_raw (source_nm_id, keyword);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_price_ai_competitor_features (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    source_nm_id BIGINT NOT NULL,
    keyword TEXT NOT NULL,
    competitor_nm_id BIGINT NOT NULL,
    source_subject_norm VARCHAR(255),
    source_subtype VARCHAR(255),
    source_dimensions_json JSONB,
    source_material VARCHAR(255),
    source_shape VARCHAR(255),
    source_platform JSONB,
    source_connection_type VARCHAR(255),
    source_bed_type VARCHAR(255),
    source_sleep_size_json JSONB,
    source_color_family VARCHAR(255),
    competitor_subject_norm VARCHAR(255),
    competitor_subtype VARCHAR(255),
    competitor_dimensions_json JSONB,
    competitor_material VARCHAR(255),
    competitor_shape VARCHAR(255),
    competitor_platform JSONB,
    competitor_connection_type VARCHAR(255),
    competitor_bed_type VARCHAR(255),
    competitor_sleep_size_json JSONB,
    competitor_color_family VARCHAR(255),
    normalization_status VARCHAR(32) NOT NULL,
    normalization_error TEXT,
    normalization_version VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_date, source_nm_id, keyword, competitor_nm_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_features_run_date
    ON analytics_ai.wb_price_ai_competitor_features (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_features_source_nm_id
    ON analytics_ai.wb_price_ai_competitor_features (source_nm_id);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_price_ai_competitors_filtered (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    source_nm_id BIGINT NOT NULL,
    keyword TEXT NOT NULL,
    competitor_nm_id BIGINT NOT NULL,
    passed_hard_filters BOOLEAN NOT NULL DEFAULT FALSE,
    hard_filter_reason TEXT,
    hard_filter_flags_json JSONB,
    filter_profile VARCHAR(255),
    filter_version VARCHAR(50),
    is_llm_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    filter_mode VARCHAR(32) NOT NULL DEFAULT 'rejected',
    effective_price_match BOOLEAN NOT NULL DEFAULT FALSE,
    is_price_outlier BOOLEAN NOT NULL DEFAULT FALSE,
    market_price_median NUMERIC(12, 2),
    source_to_market_price_ratio NUMERIC(12, 4),
    filter_status VARCHAR(32) NOT NULL,
    filter_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_date, source_nm_id, keyword, competitor_nm_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_filtered_run_date
    ON analytics_ai.wb_price_ai_competitors_filtered (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_filtered_source_nm_id
    ON analytics_ai.wb_price_ai_competitors_filtered (source_nm_id);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_price_ai_competitor_relevance (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    source_nm_id BIGINT NOT NULL,
    keyword TEXT NOT NULL,
    competitor_nm_id BIGINT NOT NULL,
    relevance_score NUMERIC(6, 4),
    relevance_verdict BOOLEAN,
    relevance_reason TEXT,
    matched_attributes_json JSONB,
    llm_model VARCHAR(100),
    llm_prompt_version VARCHAR(50),
    llm_status VARCHAR(32) NOT NULL,
    llm_error TEXT,
    raw_response_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_date, source_nm_id, keyword, competitor_nm_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_relevance_run_date
    ON analytics_ai.wb_price_ai_competitor_relevance (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_relevance_source_nm_id
    ON analytics_ai.wb_price_ai_competitor_relevance (source_nm_id);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_price_ai_competitor_vision (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    source_nm_id BIGINT NOT NULL,
    keyword TEXT NOT NULL,
    competitor_nm_id BIGINT NOT NULL,
    vision_score NUMERIC(6, 4),
    vision_grade VARCHAR(32),
    vision_reason TEXT,
    visual_signals_json JSONB,
    vision_model VARCHAR(100),
    vision_prompt_version VARCHAR(50),
    vision_status VARCHAR(32) NOT NULL,
    vision_error TEXT,
    raw_response_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_date, source_nm_id, keyword, competitor_nm_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_vision_run_date
    ON analytics_ai.wb_price_ai_competitor_vision (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_vision_source_nm_id
    ON analytics_ai.wb_price_ai_competitor_vision (source_nm_id);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_price_ai_competitor_jobs (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    source_nm_id BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    payload_json JSONB NOT NULL,
    result_json JSONB,
    worker_id VARCHAR(255),
    worker_host VARCHAR(255),
    worker_pid INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    claimed_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_date, source_nm_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_jobs_status
    ON analytics_ai.wb_price_ai_competitor_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_jobs_run_date
    ON analytics_ai.wb_price_ai_competitor_jobs (run_date);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_price_ai_analysis (
    id BIGSERIAL PRIMARY KEY,
    run_date DATE NOT NULL,
    source_snapshot_date DATE,
    source_nm_id BIGINT NOT NULL,
    source_vendor_code VARCHAR(255),
    source_supplier_article VARCHAR(255),
    source_brand VARCHAR(255),
    source_subject_name VARCHAR(500),
    source_title VARCHAR(1000),
    source_description TEXT,
    source_product_url TEXT,
    source_main_photo_url TEXT,
    source_barcodes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    variant_count INTEGER NOT NULL DEFAULT 0,
    source_total_quantity INTEGER NOT NULL DEFAULT 0,
    source_total_quantity_full INTEGER NOT NULL DEFAULT 0,
    source_warehouse_names_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_warehouse_count INTEGER NOT NULL DEFAULT 0,
    source_price_regular NUMERIC(12, 2),
    source_price_promo NUMERIC(12, 2),
    source_price_site_display NUMERIC(12, 2),
    source_price_site_wallet NUMERIC(12, 2),
    source_price_site_effective NUMERIC(12, 2),
    source_platform_discount_percent NUMERIC(8, 4),
    source_wallet_discount_percent NUMERIC(8, 4),
    source_report_to_site_discount_percent NUMERIC(8, 4),
    source_discount_percent NUMERIC(6, 2),
    seo_keywords_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    seo_keyword_count INTEGER NOT NULL DEFAULT 0,
    seo_model VARCHAR(100),
    seo_status VARCHAR(32) NOT NULL,
    seo_error TEXT,
    competitor_status VARCHAR(32) NOT NULL,
    competitor_error TEXT,
    competitor_count INTEGER NOT NULL DEFAULT 0,
    competitor_cheaper_count INTEGER NOT NULL DEFAULT 0,
    competitor_pricier_count INTEGER NOT NULL DEFAULT 0,
    competitor_price_min NUMERIC(12, 2),
    competitor_price_max NUMERIC(12, 2),
    competitor_price_avg NUMERIC(12, 2),
    competitor_price_median NUMERIC(12, 2),
    strict_competitor_count INTEGER NOT NULL DEFAULT 0,
    strict_competitor_cheaper_count INTEGER NOT NULL DEFAULT 0,
    strict_competitor_pricier_count INTEGER NOT NULL DEFAULT 0,
    strict_competitor_price_min NUMERIC(12, 2),
    strict_competitor_price_max NUMERIC(12, 2),
    strict_competitor_price_avg NUMERIC(12, 2),
    strict_competitor_price_median NUMERIC(12, 2),
    best_competitor_position INTEGER,
    hard_filter_pass_count INTEGER NOT NULL DEFAULT 0,
    llm_checked_count INTEGER NOT NULL DEFAULT 0,
    llm_kept_count INTEGER NOT NULL DEFAULT 0,
    relevance_avg_score NUMERIC(6, 4),
    relevance_threshold NUMERIC(6, 4),
    vision_checked_count INTEGER NOT NULL DEFAULT 0,
    vision_absolute_count INTEGER NOT NULL DEFAULT 0,
    vision_close_count INTEGER NOT NULL DEFAULT 0,
    vision_similar_count INTEGER NOT NULL DEFAULT 0,
    vision_not_analog_count INTEGER NOT NULL DEFAULT 0,
    vision_avg_score NUMERIC(6, 4),
    vision_prompt_version VARCHAR(50),
    pipeline_version VARCHAR(50),
    competitor_selection_mode VARCHAR(32),
    used_outlier_expanded_segment BOOLEAN NOT NULL DEFAULT FALSE,
    used_market_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    is_price_outlier BOOLEAN NOT NULL DEFAULT FALSE,
    market_candidate_count INTEGER NOT NULL DEFAULT 0,
    market_price_min NUMERIC(12, 2),
    market_price_p25 NUMERIC(12, 2),
    market_price_p75 NUMERIC(12, 2),
    market_price_max NUMERIC(12, 2),
    source_to_market_price_ratio NUMERIC(12, 4),
    competitors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    analysis_status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_date, source_nm_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_analysis_run_date
    ON analytics_ai.wb_price_ai_analysis (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_analysis_source_nm_id
    ON analytics_ai.wb_price_ai_analysis (source_nm_id);

ALTER TABLE analytics_ai.wb_price_ai_analysis
    ADD COLUMN IF NOT EXISTS hard_filter_pass_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS llm_checked_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS llm_kept_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS strict_competitor_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS strict_competitor_cheaper_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS strict_competitor_pricier_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS strict_competitor_price_min NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS strict_competitor_price_max NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS strict_competitor_price_avg NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS strict_competitor_price_median NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS relevance_avg_score NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS relevance_threshold NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS vision_checked_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vision_absolute_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vision_close_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vision_similar_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vision_not_analog_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vision_avg_score NUMERIC(6, 4),
    ADD COLUMN IF NOT EXISTS vision_prompt_version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS pipeline_version VARCHAR(50),
    ADD COLUMN IF NOT EXISTS competitor_selection_mode VARCHAR(32),
    ADD COLUMN IF NOT EXISTS used_outlier_expanded_segment BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS used_market_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_price_outlier BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS market_candidate_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS market_price_min NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS market_price_p25 NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS market_price_median NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS market_price_p75 NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS market_price_max NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS source_to_market_price_ratio NUMERIC(12, 4);

ALTER TABLE analytics_ai.wb_price_ai_analysis
    ADD COLUMN IF NOT EXISTS source_price_site_display NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS source_price_site_wallet NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS source_price_site_effective NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS source_platform_discount_percent NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS source_wallet_discount_percent NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS source_report_to_site_discount_percent NUMERIC(8, 4);

ALTER TABLE analytics_ai.wb_price_ai_competitors_filtered
    ADD COLUMN IF NOT EXISTS filter_mode VARCHAR(32) NOT NULL DEFAULT 'rejected',
    ADD COLUMN IF NOT EXISTS effective_price_match BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_price_outlier BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS market_price_median NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS source_to_market_price_ratio NUMERIC(12, 4);

CREATE OR REPLACE VIEW analytics_ai.v_wb_price_ai_analysis_latest AS
SELECT analysis.*
FROM analytics_ai.wb_price_ai_analysis AS analysis
WHERE analysis.run_date = (
    SELECT MAX(run_date) FROM analytics_ai.wb_price_ai_analysis
);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_serp_runs (
    run_id UUID PRIMARY KEY,
    batch_id UUID NOT NULL,
    batch_key TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source_snapshot_date DATE,
    source_nm_id BIGINT NOT NULL,
    source_title TEXT,
    source_price_regular NUMERIC(14, 2),
    source_price_display NUMERIC(14, 2),
    query TEXT NOT NULL,
    query_normalized TEXT NOT NULL,
    query_source VARCHAR(32) NOT NULL,
    query_rank INTEGER NOT NULL,
    query_orders_7d NUMERIC(14, 4) NOT NULL DEFAULT 0,
    query_frequency NUMERIC(18, 4) NOT NULL DEFAULT 0,
    region_dest VARCHAR(64) NOT NULL,
    currency VARCHAR(16) NOT NULL DEFAULT 'rub',
    locale VARCHAR(16) NOT NULL DEFAULT 'ru',
    device VARCHAR(32) NOT NULL DEFAULT 'desktop',
    browser_profile VARCHAR(500),
    requested_max_positions INTEGER NOT NULL,
    pages_scanned INTEGER NOT NULL DEFAULT 0,
    max_position_scanned INTEGER NOT NULL DEFAULT 0,
    organic_positions_scanned INTEGER NOT NULL DEFAULT 0,
    source_found_any BOOLEAN NOT NULL DEFAULT FALSE,
    source_found_organic BOOLEAN NOT NULL DEFAULT FALSE,
    source_found_sponsored BOOLEAN NOT NULL DEFAULT FALSE,
    source_position_absolute INTEGER,
    source_position_organic INTEGER,
    source_position_organic_absolute INTEGER,
    source_position_sponsored INTEGER,
    complete_until_source BOOLEAN NOT NULL DEFAULT FALSE,
    hit_position_limit BOOLEAN NOT NULL DEFAULT FALSE,
    result_count INTEGER NOT NULL DEFAULT 0,
    sponsored_count INTEGER NOT NULL DEFAULT 0,
    organic_count INTEGER NOT NULL DEFAULT 0,
    unknown_placement_count INTEGER NOT NULL DEFAULT 0,
    parser_status VARCHAR(32) NOT NULL,
    parser_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    UNIQUE (batch_id, source_nm_id, query_normalized),
    CHECK (query_source IN ('orders', 'frequency', 'seo', 'seo_fallback_stale')),
    CHECK (parser_status IN ('pending', 'running', 'success', 'source_not_found', 'partial', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_wb_serp_runs_observed_at
    ON analytics_ai.wb_serp_runs (observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_wb_serp_runs_source_query
    ON analytics_ai.wb_serp_runs (source_nm_id, query_normalized, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_wb_serp_runs_batch
    ON analytics_ai.wb_serp_runs (batch_id, parser_status);

-- Stable per-SKU search terms. The daily SERP DAG reads this registry first,
-- so positions remain comparable over time and an LLM/API outage cannot
-- silently change the monitored query set.
CREATE TABLE IF NOT EXISTS analytics_ai.wb_serp_query_sets (
    source_nm_id BIGINT PRIMARY KEY,
    query_specs_json JSONB NOT NULL,
    query_count INTEGER NOT NULL,
    frozen_from_batch_id UUID,
    frozen_from_observed_at TIMESTAMPTZ,
    created_reason VARCHAR(64) NOT NULL DEFAULT 'initial_selection',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (query_count BETWEEN 1 AND 5),
    CHECK (JSONB_TYPEOF(query_specs_json) = 'array'),
    CHECK (JSONB_ARRAY_LENGTH(query_specs_json) = query_count)
);

CREATE INDEX IF NOT EXISTS idx_wb_serp_query_sets_frozen_batch
    ON analytics_ai.wb_serp_query_sets (frozen_from_batch_id);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_serp_items (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES analytics_ai.wb_serp_runs(run_id),
    result_nm_id BIGINT NOT NULL,
    is_source BOOLEAN NOT NULL DEFAULT FALSE,
    catalog_page INTEGER NOT NULL,
    position_on_page INTEGER NOT NULL,
    position_absolute INTEGER NOT NULL,
    position_organic INTEGER,
    placement_type VARCHAR(16) NOT NULL,
    placement_detection VARCHAR(64),
    brand TEXT,
    subject_name TEXT,
    title TEXT,
    product_url TEXT,
    image_url TEXT,
    price_regular NUMERIC(14, 2),
    price_display NUMERIC(14, 2),
    price_wallet NUMERIC(14, 2),
    price_effective NUMERIC(14, 2),
    price_basis VARCHAR(16),
    discount_percent NUMERIC(8, 4),
    promo_label TEXT,
    rating NUMERIC(8, 4),
    feedbacks INTEGER,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, position_absolute),
    CHECK (placement_type IN ('organic', 'sponsored', 'unknown')),
    CHECK (price_basis IS NULL OR price_basis IN ('wallet', 'display', 'regular'))
);

CREATE INDEX IF NOT EXISTS idx_wb_serp_items_run
    ON analytics_ai.wb_serp_items (run_id, position_absolute);
CREATE INDEX IF NOT EXISTS idx_wb_serp_items_nm
    ON analytics_ai.wb_serp_items (result_nm_id);

CREATE TABLE IF NOT EXISTS analytics_ai.wb_serp_jobs (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID NOT NULL,
    batch_key TEXT NOT NULL,
    source_nm_id BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    payload_json JSONB NOT NULL,
    result_json JSONB,
    worker_id VARCHAR(255),
    worker_host VARCHAR(255),
    worker_pid INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    claimed_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (batch_id, source_nm_id),
    CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_wb_serp_jobs_queue
    ON analytics_ai.wb_serp_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_wb_serp_jobs_heartbeat
    ON analytics_ai.wb_serp_jobs (last_heartbeat_at)
    WHERE status = 'processing';

CREATE TABLE IF NOT EXISTS analytics_ai.wb_serp_worker_heartbeats (
    worker_id VARCHAR(255) PRIMARY KEY,
    worker_host VARCHAR(255) NOT NULL,
    worker_pid INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('running', 'stopped'))
);

CREATE OR REPLACE VIEW analytics_ai.mart_serp_query_daily AS
WITH ranked_runs AS (
    SELECT
        runs.*,
        ROW_NUMBER() OVER (
            PARTITION BY runs.observed_at::date, runs.source_nm_id, runs.query_normalized
            ORDER BY runs.observed_at DESC, runs.completed_at DESC NULLS LAST
        ) AS recency_rank
    FROM analytics_ai.wb_serp_runs runs
    WHERE runs.parser_status IN ('success', 'source_not_found')
),
selected_runs AS (
    SELECT * FROM ranked_runs WHERE recency_rank = 1
),
source_prices AS (
    SELECT
        run_id,
        COALESCE(
            MAX(price_regular) FILTER (WHERE is_source AND placement_type = 'organic'),
            MAX(price_regular) FILTER (WHERE is_source)
        ) AS source_price_regular,
        COALESCE(
            MAX(price_display) FILTER (WHERE is_source AND placement_type = 'organic'),
            MAX(price_display) FILTER (WHERE is_source)
        ) AS source_price_display,
        COALESCE(
            MAX(price_wallet) FILTER (WHERE is_source AND placement_type = 'organic'),
            MAX(price_wallet) FILTER (WHERE is_source)
        ) AS source_price_wallet,
        COALESCE(
            MAX(price_effective) FILTER (WHERE is_source AND placement_type = 'organic'),
            MAX(price_effective) FILTER (WHERE is_source)
        ) AS source_price_effective
    FROM analytics_ai.wb_serp_items
    GROUP BY run_id
),
item_stats AS (
    SELECT
        runs.run_id,
        COUNT(*) FILTER (WHERE NOT items.is_source) AS market_item_count,
        MIN(items.price_effective) FILTER (WHERE NOT items.is_source) AS market_price_min,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY items.price_effective)
            FILTER (WHERE NOT items.is_source AND items.price_effective IS NOT NULL) AS market_price_median,
        MAX(items.price_effective) FILTER (WHERE NOT items.is_source) AS market_price_max,
        COUNT(*) FILTER (
            WHERE runs.source_found_organic AND NOT items.is_source
              AND items.position_absolute < runs.source_position_organic_absolute
        ) AS competitors_before_source,
        COUNT(*) FILTER (
            WHERE runs.source_found_organic AND NOT items.is_source
              AND items.placement_type = 'organic'
              AND items.position_organic < runs.source_position_organic
        ) AS organic_competitors_before_source,
        MIN(items.price_effective) FILTER (
            WHERE runs.source_found_organic AND NOT items.is_source
              AND items.position_absolute < runs.source_position_organic_absolute
        ) AS price_before_min,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY items.price_effective) FILTER (
            WHERE runs.source_found_organic AND NOT items.is_source
              AND items.position_absolute < runs.source_position_organic_absolute
              AND items.price_effective IS NOT NULL
        ) AS price_before_median,
        MAX(items.price_effective) FILTER (
            WHERE runs.source_found_organic AND NOT items.is_source
              AND items.position_absolute < runs.source_position_organic_absolute
        ) AS price_before_max,
        COUNT(*) FILTER (
            WHERE runs.source_found_organic AND NOT items.is_source
              AND items.position_absolute < runs.source_position_organic_absolute
              AND items.price_effective < COALESCE(prices.source_price_effective, runs.source_price_display)
        ) AS cheaper_before_count
    FROM selected_runs runs
    LEFT JOIN source_prices prices ON prices.run_id = runs.run_id
    LEFT JOIN analytics_ai.wb_serp_items items ON items.run_id = runs.run_id
    GROUP BY runs.run_id
)
SELECT
    runs.observed_at::date AS snapshot_date,
    runs.observed_at,
    runs.batch_id,
    runs.run_id,
    runs.source_nm_id,
    runs.query,
    runs.query_normalized,
    runs.query_source,
    runs.query_rank,
    runs.query_orders_7d,
    runs.query_frequency,
    COALESCE(prices.source_price_regular, runs.source_price_regular)::numeric(14, 2) AS source_price_regular,
    COALESCE(prices.source_price_display, runs.source_price_display)::numeric(14, 2) AS source_price_display,
    runs.source_found_any,
    runs.source_found_organic,
    runs.source_found_sponsored,
    runs.source_position_absolute,
    runs.source_position_organic,
    runs.source_position_organic_absolute,
    runs.source_position_sponsored,
    runs.complete_until_source,
    runs.hit_position_limit,
    runs.max_position_scanned,
    runs.parser_status,
    stats.market_item_count,
    stats.market_price_min,
    stats.market_price_median,
    stats.market_price_max,
    CASE WHEN runs.source_found_organic THEN stats.competitors_before_source ELSE NULL END AS competitors_before_source,
    CASE WHEN runs.source_found_organic THEN stats.organic_competitors_before_source ELSE NULL END AS organic_competitors_before_source,
    CASE WHEN runs.source_found_organic THEN stats.price_before_min ELSE NULL END AS price_before_min,
    CASE WHEN runs.source_found_organic THEN stats.price_before_median ELSE NULL END AS price_before_median,
    CASE WHEN runs.source_found_organic THEN stats.price_before_max ELSE NULL END AS price_before_max,
    CASE WHEN runs.source_found_organic THEN stats.cheaper_before_count ELSE NULL END AS cheaper_before_count,
    CASE
        WHEN runs.source_found_organic AND stats.price_before_median > 0
        THEN ROUND((COALESCE(prices.source_price_effective, runs.source_price_display) / stats.price_before_median)::numeric, 4)
        ELSE NULL
    END AS source_to_before_median_price_ratio,
    prices.source_price_wallet,
    COALESCE(prices.source_price_effective, runs.source_price_display) AS source_price_effective
FROM selected_runs runs
LEFT JOIN source_prices prices ON prices.run_id = runs.run_id
JOIN item_stats stats ON stats.run_id = runs.run_id;

CREATE OR REPLACE VIEW analytics_ai.mart_serp_competitors_daily AS
SELECT
    query_daily.snapshot_date,
    query_daily.observed_at,
    query_daily.batch_id,
    query_daily.run_id,
    query_daily.source_nm_id,
    query_daily.query,
    query_daily.query_normalized,
    query_daily.query_source,
    query_daily.query_rank,
    query_daily.source_position_organic,
    query_daily.source_position_organic_absolute,
    items.result_nm_id AS competitor_nm_id,
    items.placement_type,
    items.position_absolute AS competitor_position_absolute,
    items.position_organic AS competitor_position_organic,
    items.brand AS competitor_brand,
    items.subject_name AS competitor_subject_name,
    items.title AS competitor_title,
    items.product_url AS competitor_product_url,
    items.image_url AS competitor_image_url,
    items.price_regular AS competitor_price_regular,
    items.price_display AS competitor_price_display,
    items.price_wallet AS competitor_price_wallet,
    items.price_effective AS competitor_price_effective,
    items.price_basis AS competitor_price_basis,
    COALESCE(
        query_daily.source_price_effective,
        source_prices.club_discounted_price,
        source_prices.discounted_price
    ) AS source_price_effective,
    items.price_effective - COALESCE(
        query_daily.source_price_effective,
        source_prices.club_discounted_price,
        source_prices.discounted_price
    ) AS price_delta_abs,
    ROUND(
        (
            items.price_effective - COALESCE(
                query_daily.source_price_effective,
                source_prices.club_discounted_price,
                source_prices.discounted_price
            )
        ) * 100.0
        / NULLIF(
            COALESCE(
                query_daily.source_price_effective,
                source_prices.club_discounted_price,
                source_prices.discounted_price
            ),
            0
        ),
        2
    ) AS price_delta_percent,
    CASE
        WHEN items.price_effective < COALESCE(query_daily.source_price_effective, source_prices.club_discounted_price, source_prices.discounted_price)
            THEN 'cheaper'
        WHEN items.price_effective > COALESCE(query_daily.source_price_effective, source_prices.club_discounted_price, source_prices.discounted_price)
            THEN 'pricier'
        ELSE 'equal'
    END AS price_relation,
    items.price_effective BETWEEN
        COALESCE(query_daily.source_price_effective, source_prices.club_discounted_price, source_prices.discounted_price) * 0.65
        AND COALESCE(query_daily.source_price_effective, source_prices.club_discounted_price, source_prices.discounted_price) * 1.35
        AS is_price_peer,
    TRUE AS is_serp_competitor,
    'above_organic_source'::text AS competitor_scope,
    items.rating,
    items.feedbacks,
    items.promo_label,
    items.discount_percent
FROM analytics_ai.mart_serp_query_daily AS query_daily
JOIN analytics_ai.wb_serp_items AS items
  ON items.run_id = query_daily.run_id
LEFT JOIN pricing.wb_supplier_prices AS source_prices
  ON source_prices.snapshot_date = query_daily.snapshot_date
 AND source_prices.nm_id = query_daily.source_nm_id
WHERE query_daily.source_found_organic
  AND NOT items.is_source
  AND items.position_absolute < query_daily.source_position_organic_absolute;

CREATE OR REPLACE VIEW analytics_ai.v_wb_serp_competitors_latest AS
SELECT competitors.*
FROM analytics_ai.mart_serp_competitors_daily AS competitors
WHERE competitors.snapshot_date = (
    SELECT MAX(snapshot_date)
    FROM analytics_ai.mart_serp_competitors_daily
);

CREATE OR REPLACE VIEW analytics_ai.mart_price_context_daily AS
WITH query_rows AS (
    SELECT
        query_daily.*,
        CASE
            WHEN SUM(query_orders_7d) OVER (PARTITION BY snapshot_date, source_nm_id) > 0 THEN query_orders_7d
            WHEN SUM(query_frequency) OVER (PARTITION BY snapshot_date, source_nm_id) > 0 THEN query_frequency
            ELSE 1
        END AS query_weight
    FROM analytics_ai.mart_serp_query_daily query_daily
),
serp_agg AS (
    SELECT
        snapshot_date,
        source_nm_id,
        MAX(source_price_regular) AS source_price_regular,
        MAX(source_price_display) AS source_price_display,
        MAX(source_price_wallet) AS source_price_wallet,
        MAX(source_price_effective) AS source_price_effective,
        COUNT(*) AS query_count,
        COUNT(*) FILTER (WHERE source_found_organic) AS source_found_query_count,
        ROUND(
            SUM(source_position_organic * query_weight) FILTER (WHERE source_position_organic IS NOT NULL)
            / NULLIF(SUM(query_weight) FILTER (WHERE source_position_organic IS NOT NULL), 0),
            4
        ) AS weighted_organic_position,
        MIN(market_price_min) AS market_price_min,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY market_price_median)
            FILTER (WHERE market_price_median IS NOT NULL) AS market_price_median,
        MAX(market_price_max) AS market_price_max,
        SUM(competitors_before_source) AS competitors_before_source,
        SUM(organic_competitors_before_source) AS organic_competitors_before_source,
        SUM(cheaper_before_count) AS cheaper_before_count,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_before_median)
            FILTER (WHERE price_before_median IS NOT NULL) AS price_before_median
    FROM query_rows
    GROUP BY snapshot_date, source_nm_id
),
marketing_daily AS (
    SELECT stat_date, nm_id, SUM(views) AS ad_views, SUM(clicks) AS ad_clicks,
           SUM(orders) AS ad_orders, ROUND(SUM(sum_spend), 2) AS ad_spend
    FROM marketing.wb_marketing_campaign_stats_daily_nms
    GROUP BY stat_date, nm_id
),
stocks_daily AS (
    SELECT snapshot_date, nm_id, SUM(quantity_full) AS stock_quantity
    FROM supply.wb_supplier_stocks
    GROUP BY snapshot_date, nm_id
),
orders_daily AS (
    SELECT COALESCE(date_ord::date, snapshot_date) AS order_date, nm_id,
           COUNT(DISTINCT srid) FILTER (WHERE NOT COALESCE(is_cancel, FALSE)) AS orders_count
    FROM sales.wb_supplier_orders
    GROUP BY COALESCE(date_ord::date, snapshot_date), nm_id
),
promotions_daily AS (
    SELECT snapshot_date, nm_id, BOOL_OR(in_action) AS in_promotion,
           MAX(discount) FILTER (WHERE in_action) AS promotion_discount
    FROM marketing.wb_calendar_promotions_nomenclatures
    GROUP BY snapshot_date, nm_id
)
SELECT
    serp.snapshot_date,
    serp.source_nm_id,
    COALESCE(prices.price, serp.source_price_regular) AS source_price_regular,
    COALESCE(prices.discounted_price, serp.source_price_display) AS source_price_display,
    COALESCE(prices.club_discounted_price, prices.discounted_price)::numeric(12, 2) AS source_price_club,
    prices.discount::numeric(5, 2) AS source_discount_percent,
    COALESCE(promotions.in_promotion, FALSE) AS in_promotion,
    promotions.promotion_discount,
    COALESCE(marketing.ad_views, 0) AS ad_views,
    COALESCE(marketing.ad_clicks, 0) AS ad_clicks,
    COALESCE(marketing.ad_orders, 0) AS ad_orders,
    COALESCE(marketing.ad_spend, 0) AS ad_spend,
    COALESCE(stocks.stock_quantity, 0) AS stock_quantity,
    COALESCE(orders.orders_count, 0) AS orders_count,
    serp.query_count,
    serp.source_found_query_count,
    ROUND(serp.source_found_query_count::numeric / NULLIF(serp.query_count, 0), 4) AS source_found_query_share,
    serp.weighted_organic_position,
    serp.market_price_min,
    serp.market_price_median,
    serp.market_price_max,
    serp.competitors_before_source,
    serp.organic_competitors_before_source,
    serp.cheaper_before_count,
    serp.price_before_median,
    CASE
        WHEN serp.price_before_median > 0
        THEN ROUND((COALESCE(serp.source_price_effective, prices.club_discounted_price, prices.discounted_price) / serp.price_before_median)::numeric, 4)
        ELSE NULL
    END AS source_to_before_median_price_ratio,
    COALESCE(prices.club_discounted_price, prices.discounted_price, serp.source_price_effective) AS source_price_effective,
    COALESCE(
        price_analysis.source_price_site_display,
        CASE
            WHEN serp.source_price_wallet IS NOT NULL
             AND serp.source_price_display = serp.source_price_wallet THEN NULL
            ELSE serp.source_price_display
        END
    )::numeric(12, 2) AS source_price_site_display,
    COALESCE(price_analysis.source_price_site_wallet, serp.source_price_wallet)::numeric(12, 2)
        AS source_price_site_wallet,
    COALESCE(price_analysis.source_price_site_effective, serp.source_price_effective)::numeric(12, 2)
        AS source_price_site_effective,
    COALESCE(
        price_analysis.source_platform_discount_percent,
        CASE
            WHEN serp.source_price_display IS NOT NULL
             AND (serp.source_price_wallet IS NULL OR serp.source_price_display <> serp.source_price_wallet)
            THEN ROUND(
                (COALESCE(prices.club_discounted_price, prices.discounted_price) - serp.source_price_display)
                * 100 / NULLIF(COALESCE(prices.club_discounted_price, prices.discounted_price), 0),
                4
            )
            ELSE NULL
        END
    ) AS source_platform_discount_percent,
    COALESCE(
        price_analysis.source_wallet_discount_percent,
        CASE
            WHEN serp.source_price_display IS NOT NULL
             AND serp.source_price_wallet IS NOT NULL
             AND serp.source_price_display <> serp.source_price_wallet
            THEN ROUND(
                (serp.source_price_display - serp.source_price_wallet)
                * 100 / NULLIF(serp.source_price_display, 0),
                4
            )
            ELSE NULL
        END
    ) AS source_wallet_discount_percent,
    COALESCE(
        price_analysis.source_report_to_site_discount_percent,
        ROUND(
            (COALESCE(prices.club_discounted_price, prices.discounted_price) - serp.source_price_effective)
            * 100 / NULLIF(COALESCE(prices.club_discounted_price, prices.discounted_price), 0),
            4
        )
    ) AS source_report_to_site_discount_percent
FROM serp_agg serp
LEFT JOIN pricing.wb_supplier_prices prices
    ON prices.snapshot_date = serp.snapshot_date AND prices.nm_id = serp.source_nm_id
LEFT JOIN analytics_ai.wb_price_ai_analysis price_analysis
    ON price_analysis.run_date = serp.snapshot_date
   AND price_analysis.source_nm_id = serp.source_nm_id
LEFT JOIN marketing_daily marketing
    ON marketing.stat_date = serp.snapshot_date AND marketing.nm_id = serp.source_nm_id
LEFT JOIN stocks_daily stocks
    ON stocks.snapshot_date = serp.snapshot_date AND stocks.nm_id = serp.source_nm_id
LEFT JOIN orders_daily orders
    ON orders.order_date = serp.snapshot_date AND orders.nm_id = serp.source_nm_id
LEFT JOIN promotions_daily promotions
    ON promotions.snapshot_date = serp.snapshot_date AND promotions.nm_id = serp.source_nm_id;

CREATE OR REPLACE VIEW analytics_ai.v_wb_serp_health AS
SELECT
    (SELECT MAX(observed_at) FROM analytics_ai.wb_serp_runs
     WHERE parser_status IN ('success', 'source_not_found')) AS latest_valid_observed_at,
    (SELECT MAX(last_heartbeat_at) FROM analytics_ai.wb_serp_worker_heartbeats
     WHERE status = 'running') AS latest_worker_heartbeat,
    COUNT(*) FILTER (WHERE status = 'pending') AS pending_jobs,
    COUNT(*) FILTER (WHERE status = 'processing') AS processing_jobs,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed_jobs,
    (SELECT COUNT(*) FROM analytics_ai.wb_serp_worker_heartbeats
     WHERE status = 'running'
       AND last_heartbeat_at >= CURRENT_TIMESTAMP - INTERVAL '10 minutes') AS active_workers
FROM analytics_ai.wb_serp_jobs;
