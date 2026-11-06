CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_price_ai_seo_keywords (
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
    ON reports.wb_price_ai_seo_keywords (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_seo_keywords_source_nm_id
    ON reports.wb_price_ai_seo_keywords (source_nm_id);

CREATE TABLE IF NOT EXISTS reports.wb_price_ai_competitors_raw (
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
    ON reports.wb_price_ai_competitors_raw (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_raw_source_nm_id
    ON reports.wb_price_ai_competitors_raw (source_nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_raw_competitor_nm_id
    ON reports.wb_price_ai_competitors_raw (competitor_nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_raw_source_keyword
    ON reports.wb_price_ai_competitors_raw (source_nm_id, keyword);

CREATE TABLE IF NOT EXISTS reports.wb_price_ai_competitor_features (
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
    ON reports.wb_price_ai_competitor_features (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_features_source_nm_id
    ON reports.wb_price_ai_competitor_features (source_nm_id);

CREATE TABLE IF NOT EXISTS reports.wb_price_ai_competitors_filtered (
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
    ON reports.wb_price_ai_competitors_filtered (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitors_filtered_source_nm_id
    ON reports.wb_price_ai_competitors_filtered (source_nm_id);

CREATE TABLE IF NOT EXISTS reports.wb_price_ai_competitor_relevance (
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
    ON reports.wb_price_ai_competitor_relevance (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_relevance_source_nm_id
    ON reports.wb_price_ai_competitor_relevance (source_nm_id);

CREATE TABLE IF NOT EXISTS reports.wb_price_ai_competitor_vision (
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
    ON reports.wb_price_ai_competitor_vision (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_vision_source_nm_id
    ON reports.wb_price_ai_competitor_vision (source_nm_id);

CREATE TABLE IF NOT EXISTS reports.wb_price_ai_competitor_jobs (
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
    ON reports.wb_price_ai_competitor_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_competitor_jobs_run_date
    ON reports.wb_price_ai_competitor_jobs (run_date);

CREATE TABLE IF NOT EXISTS reports.wb_price_ai_analysis (
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
    ON reports.wb_price_ai_analysis (run_date);

CREATE INDEX IF NOT EXISTS idx_wb_price_ai_analysis_source_nm_id
    ON reports.wb_price_ai_analysis (source_nm_id);

ALTER TABLE reports.wb_price_ai_analysis
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

ALTER TABLE reports.wb_price_ai_competitors_filtered
    ADD COLUMN IF NOT EXISTS filter_mode VARCHAR(32) NOT NULL DEFAULT 'rejected',
    ADD COLUMN IF NOT EXISTS effective_price_match BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_price_outlier BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS market_price_median NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS source_to_market_price_ratio NUMERIC(12, 4);

CREATE OR REPLACE VIEW reports.v_wb_price_ai_analysis_latest AS
SELECT analysis.*
FROM reports.wb_price_ai_analysis AS analysis
WHERE analysis.run_date = (
    SELECT MAX(run_date) FROM reports.wb_price_ai_analysis
);
