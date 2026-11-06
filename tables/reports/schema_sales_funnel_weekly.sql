-- sales_funnel по неделям (API sales-funnel/products/history, aggregationLevel=week). Одна строка = один nm_id на одну неделю.
CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_sales_funnel_products_weekly (
    id BIGSERIAL PRIMARY KEY,
    report_week_start DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    title VARCHAR(1000),
    vendor_code VARCHAR(255),
    brand_name VARCHAR(255),
    subject_id BIGINT,
    subject_name VARCHAR(500),
    open_count INT,
    cart_count INT,
    order_count INT,
    order_sum DECIMAL(12, 2),
    buyout_count INT,
    buyout_sum DECIMAL(12, 2),
    buyout_percent DECIMAL(5, 2),
    add_to_cart_conversion DECIMAL(5, 2),
    cart_to_order_conversion DECIMAL(5, 2),
    add_to_wishlist_count INT,
    currency VARCHAR(10),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (nm_id, report_week_start)
);

CREATE INDEX IF NOT EXISTS idx_wb_sales_funnel_weekly_week ON reports.wb_sales_funnel_products_weekly(report_week_start);
CREATE INDEX IF NOT EXISTS idx_wb_sales_funnel_weekly_nm_id ON reports.wb_sales_funnel_products_weekly(nm_id);
