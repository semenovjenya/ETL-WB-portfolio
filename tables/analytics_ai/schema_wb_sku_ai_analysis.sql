CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_sku_ai_analysis') IS NOT NULL AND to_regclass('analytics_ai.wb_sku_ai_analysis') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_sku_ai_analysis SET SCHEMA analytics_ai';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE TABLE IF NOT EXISTS analytics_ai.wb_sku_ai_analysis (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    barcode VARCHAR(255) NOT NULL,
    imt_id BIGINT,
    chrt_id BIGINT,
    tech_size VARCHAR(100),
    vendor_code VARCHAR(255),
    supplier_article VARCHAR(255),
    brand VARCHAR(255),
    subject_name VARCHAR(500),
    title VARCHAR(1000),
    description TEXT,
    need_kiz BOOLEAN,
    last_change_date TIMESTAMPTZ,
    total_quantity INTEGER DEFAULT 0,
    total_in_way_to_client INTEGER DEFAULT 0,
    total_in_way_from_client INTEGER DEFAULT 0,
    total_quantity_full INTEGER DEFAULT 0,
    warehouse_count INTEGER DEFAULT 0,
    warehouse_names JSONB,
    warehouses_json JSONB,
    product_url TEXT,
    main_photo_url TEXT,
    photo_urls JSONB,
    video_url TEXT,
    length_cm NUMERIC(10, 2),
    width_cm NUMERIC(10, 2),
    height_cm NUMERIC(10, 2),
    weight_brutto_kg NUMERIC(12, 3),
    dimensions_json JSONB,
    characteristics_json JSONB,
    sizes_json JSONB,
    tags_json JSONB,
    price NUMERIC(12, 2),
    discounted_price NUMERIC(12, 2),
    club_discounted_price NUMERIC(12, 2),
    discount NUMERIC(6, 2),
    club_discount NUMERIC(6, 2),
    currency_code VARCHAR(10),
    price_sizes_json JSONB,
    analytics_main_photo_url TEXT,
    analytics_availability VARCHAR(64),
    analytics_stock_count INTEGER,
    analytics_stock_sum NUMERIC(14, 2),
    analytics_current_price_min NUMERIC(12, 2),
    analytics_current_price_max NUMERIC(12, 2),
    analytics_orders_count INTEGER,
    analytics_orders_sum NUMERIC(14, 2),
    analytics_buyout_count INTEGER,
    analytics_buyout_sum NUMERIC(14, 2),
    analytics_buyout_percent NUMERIC(6, 2),
    analytics_open_count INTEGER,
    analytics_cart_count INTEGER,
    analytics_add_to_wishlist INTEGER,
    analytics_avg_price NUMERIC(12, 2),
    analytics_avg_orders_per_day NUMERIC(12, 4),
    analytics_to_client_count INTEGER,
    analytics_from_client_count INTEGER,
    analytics_sale_rate_days INTEGER,
    analytics_sale_rate_hours INTEGER,
    product_rating NUMERIC(6, 2),
    feedback_rating NUMERIC(6, 2),
    card_json JSONB,
    price_json JSONB,
    funnel_json JSONB,
    stocks_report_json JSONB,
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, nm_id, barcode)
);

CREATE INDEX IF NOT EXISTS idx_wb_sku_ai_analysis_snapshot_date
    ON analytics_ai.wb_sku_ai_analysis (snapshot_date);

CREATE INDEX IF NOT EXISTS idx_wb_sku_ai_analysis_nm_id
    ON analytics_ai.wb_sku_ai_analysis (nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_sku_ai_analysis_barcode
    ON analytics_ai.wb_sku_ai_analysis (barcode);

CREATE INDEX IF NOT EXISTS idx_wb_sku_ai_analysis_vendor_code
    ON analytics_ai.wb_sku_ai_analysis (vendor_code);

ALTER TABLE analytics_ai.wb_sku_ai_analysis
    ADD COLUMN IF NOT EXISTS length_cm NUMERIC(10, 2),
    ADD COLUMN IF NOT EXISTS width_cm NUMERIC(10, 2),
    ADD COLUMN IF NOT EXISTS height_cm NUMERIC(10, 2),
    ADD COLUMN IF NOT EXISTS weight_brutto_kg NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS wb_link_price_regular NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS wb_link_price_promo NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS wb_link_discount_percent NUMERIC(6, 2),
    ADD COLUMN IF NOT EXISTS wb_link_is_promo BOOLEAN,
    ADD COLUMN IF NOT EXISTS wb_link_panel_promo_id BIGINT,
    ADD COLUMN IF NOT EXISTS wb_link_promotions_json JSONB,
    ADD COLUMN IF NOT EXISTS wb_link_sale_conditions BIGINT,
    ADD COLUMN IF NOT EXISTS wb_link_price_payload_json JSONB,
    ADD COLUMN IF NOT EXISTS wb_link_price_checked_at TIMESTAMPTZ;

UPDATE analytics_ai.wb_sku_ai_analysis
SET
    length_cm = COALESCE(
        NULLIF(dimensions_json->>'length', '')::NUMERIC,
        length_cm
    ),
    width_cm = COALESCE(
        NULLIF(dimensions_json->>'width', '')::NUMERIC,
        width_cm
    ),
    height_cm = COALESCE(
        NULLIF(dimensions_json->>'height', '')::NUMERIC,
        height_cm
    ),
    weight_brutto_kg = COALESCE(
        NULLIF(dimensions_json->>'weightBrutto', '')::NUMERIC,
        NULLIF(dimensions_json->>'weight', '')::NUMERIC,
        weight_brutto_kg
    )
WHERE dimensions_json IS NOT NULL;
