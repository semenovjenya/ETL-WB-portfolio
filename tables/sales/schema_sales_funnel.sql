CREATE SCHEMA IF NOT EXISTS sales;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_sales_funnel_products') IS NOT NULL AND to_regclass('sales.wb_sales_funnel_products') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_sales_funnel_products SET SCHEMA sales';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_sales_funnel_progress') IS NOT NULL AND to_regclass('sales.wb_sales_funnel_progress') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_sales_funnel_progress SET SCHEMA sales';
    END IF;
END $$;

-- sales_funnel (API analytics v3 sales-funnel/products). 1 срез = отчёт за период по товарам.
CREATE SCHEMA IF NOT EXISTS sales;
CREATE TABLE IF NOT EXISTS sales.wb_sales_funnel_products (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    title VARCHAR(1000),
    vendor_code VARCHAR(255),
    brand_name VARCHAR(255),
    subject_id BIGINT,
    subject_name VARCHAR(500),
    product_rating DECIMAL(5, 2),
    feedback_rating DECIMAL(5, 2),
    stocks_wb INT,
    stocks_mp INT,
    balance_sum DECIMAL(12, 2),
    open_count INT,
    cart_count INT,
    order_count INT,
    order_sum DECIMAL(12, 2),
    buyout_count INT,
    buyout_sum DECIMAL(12, 2),
    cancel_count INT,
    cancel_sum DECIMAL(12, 2),
    avg_price DECIMAL(12, 2),
    avg_orders_count_per_day DECIMAL(12, 4),
    share_order_percent DECIMAL(5, 2),
    add_to_wishlist INT,
    localization_percent INT,
    add_to_cart_percent DECIMAL(5, 2),
    cart_to_order_percent DECIMAL(5, 2),
    buyout_percent DECIMAL(5, 2),
    currency VARCHAR(10),
    api_response JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, nm_id)
);

-- Добавить колонку полного ответа API, если таблица уже создана
ALTER TABLE sales.wb_sales_funnel_products ADD COLUMN IF NOT EXISTS api_response JSONB;

CREATE TABLE IF NOT EXISTS sales.wb_sales_funnel_progress (
    id SERIAL PRIMARY KEY,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    snapshot_date DATE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wb_sales_funnel_snapshot ON sales.wb_sales_funnel_products(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_sales_funnel_nm_id ON sales.wb_sales_funnel_products(nm_id);
CREATE INDEX IF NOT EXISTS idx_wb_sales_funnel_period ON sales.wb_sales_funnel_products(period_start, period_end);
