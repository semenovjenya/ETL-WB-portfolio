-- sales_funnel по дням (API sales-funnel/products/history). Одна строка = один nm_id на одну дату.
CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_sales_funnel_products_daily (
    id BIGSERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    title VARCHAR(1000),
    vendor_code VARCHAR(255),
    brand_name VARCHAR(255),
    subject_id BIGINT,
    subject_name VARCHAR(500),
    product_tags_json JSONB,
    product_rating DECIMAL(5, 2),
    feedback_rating DECIMAL(5, 2),
    stocks_wb INT,
    stocks_mp INT,
    balance_sum DECIMAL(12, 2),
    selected_period_start DATE,
    selected_period_end DATE,
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
    buyout_percent DECIMAL(5, 2),
    add_to_cart_conversion DECIMAL(5, 2),
    cart_to_order_conversion DECIMAL(5, 2),
    add_to_wishlist_count INT,
    time_to_ready_days INT,
    time_to_ready_hours INT,
    time_to_ready_mins INT,
    localization_percent INT,
    selected_wb_club_order_count INT,
    selected_wb_club_order_sum DECIMAL(12, 2),
    selected_wb_club_buyout_sum DECIMAL(12, 2),
    selected_wb_club_buyout_count INT,
    selected_wb_club_cancel_sum DECIMAL(12, 2),
    selected_wb_club_cancel_count INT,
    selected_wb_club_avg_price DECIMAL(12, 2),
    selected_wb_club_buyout_percent DECIMAL(5, 2),
    selected_wb_club_avg_order_count_per_day DECIMAL(12, 4),
    past_period_start DATE,
    past_period_end DATE,
    past_open_count INT,
    past_cart_count INT,
    past_order_count INT,
    past_order_sum DECIMAL(12, 2),
    past_buyout_count INT,
    past_buyout_sum DECIMAL(12, 2),
    past_cancel_count INT,
    past_cancel_sum DECIMAL(12, 2),
    past_avg_price DECIMAL(12, 2),
    past_avg_orders_count_per_day DECIMAL(12, 4),
    past_share_order_percent DECIMAL(5, 2),
    past_add_to_wishlist_count INT,
    past_time_to_ready_days INT,
    past_time_to_ready_hours INT,
    past_time_to_ready_mins INT,
    past_localization_percent INT,
    past_wb_club_order_count INT,
    past_wb_club_order_sum DECIMAL(12, 2),
    past_wb_club_buyout_sum DECIMAL(12, 2),
    past_wb_club_buyout_count INT,
    past_wb_club_cancel_sum DECIMAL(12, 2),
    past_wb_club_cancel_count INT,
    past_wb_club_avg_price DECIMAL(12, 2),
    past_wb_club_buyout_percent DECIMAL(5, 2),
    past_wb_club_avg_order_count_per_day DECIMAL(12, 4),
    past_add_to_cart_percent DECIMAL(5, 2),
    past_cart_to_order_percent DECIMAL(5, 2),
    past_buyout_percent DECIMAL(5, 2),
    comparison_open_count_dynamic DECIMAL(12, 2),
    comparison_cart_count_dynamic DECIMAL(12, 2),
    comparison_order_count_dynamic DECIMAL(12, 2),
    comparison_order_sum_dynamic DECIMAL(12, 2),
    comparison_buyout_count_dynamic DECIMAL(12, 2),
    comparison_buyout_sum_dynamic DECIMAL(12, 2),
    comparison_cancel_count_dynamic DECIMAL(12, 2),
    comparison_cancel_sum_dynamic DECIMAL(12, 2),
    comparison_avg_orders_count_per_day_dynamic DECIMAL(12, 4),
    comparison_avg_price_dynamic DECIMAL(12, 2),
    comparison_share_order_percent_dynamic DECIMAL(12, 2),
    comparison_add_to_wishlist_dynamic DECIMAL(12, 2),
    comparison_time_to_ready_days INT,
    comparison_time_to_ready_hours INT,
    comparison_time_to_ready_mins INT,
    comparison_localization_percent_dynamic DECIMAL(12, 2),
    comparison_wb_club_order_count_dynamic DECIMAL(12, 2),
    comparison_wb_club_order_sum_dynamic DECIMAL(12, 2),
    comparison_wb_club_buyout_sum_dynamic DECIMAL(12, 2),
    comparison_wb_club_buyout_count_dynamic DECIMAL(12, 2),
    comparison_wb_club_cancel_sum_dynamic DECIMAL(12, 2),
    comparison_wb_club_cancel_count_dynamic DECIMAL(12, 2),
    comparison_wb_club_avg_price_dynamic DECIMAL(12, 2),
    comparison_wb_club_buyout_percent_dynamic DECIMAL(12, 2),
    comparison_wb_club_avg_order_count_per_day_dynamic DECIMAL(12, 4),
    comparison_add_to_cart_percent DECIMAL(5, 2),
    comparison_cart_to_order_percent DECIMAL(5, 2),
    comparison_buyout_percent DECIMAL(5, 2),
    currency VARCHAR(10),
    api_response JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (nm_id, report_date)
);

ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS product_tags_json JSONB;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS product_rating DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS feedback_rating DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS stocks_wb INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS stocks_mp INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS balance_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_period_start DATE;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_period_end DATE;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS cancel_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS cancel_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS avg_price DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS avg_orders_count_per_day DECIMAL(12, 4);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS share_order_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS time_to_ready_days INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS time_to_ready_hours INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS time_to_ready_mins INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS localization_percent INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_wb_club_order_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_wb_club_order_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_wb_club_buyout_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_wb_club_buyout_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_wb_club_cancel_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_wb_club_cancel_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_wb_club_avg_price DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_wb_club_buyout_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS selected_wb_club_avg_order_count_per_day DECIMAL(12, 4);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_period_start DATE;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_period_end DATE;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_open_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_cart_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_order_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_order_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_buyout_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_buyout_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_cancel_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_cancel_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_avg_price DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_avg_orders_count_per_day DECIMAL(12, 4);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_share_order_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_add_to_wishlist_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_time_to_ready_days INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_time_to_ready_hours INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_time_to_ready_mins INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_localization_percent INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_wb_club_order_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_wb_club_order_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_wb_club_buyout_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_wb_club_buyout_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_wb_club_cancel_sum DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_wb_club_cancel_count INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_wb_club_avg_price DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_wb_club_buyout_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_wb_club_avg_order_count_per_day DECIMAL(12, 4);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_add_to_cart_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_cart_to_order_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS past_buyout_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_open_count_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_cart_count_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_order_count_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_order_sum_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_buyout_count_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_buyout_sum_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_cancel_count_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_cancel_sum_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_avg_orders_count_per_day_dynamic DECIMAL(12, 4);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_avg_price_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_share_order_percent_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_add_to_wishlist_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_time_to_ready_days INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_time_to_ready_hours INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_time_to_ready_mins INT;
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_localization_percent_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_wb_club_order_count_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_wb_club_order_sum_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_wb_club_buyout_sum_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_wb_club_buyout_count_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_wb_club_cancel_sum_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_wb_club_cancel_count_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_wb_club_avg_price_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_wb_club_buyout_percent_dynamic DECIMAL(12, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_wb_club_avg_order_count_per_day_dynamic DECIMAL(12, 4);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_add_to_cart_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_cart_to_order_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS comparison_buyout_percent DECIMAL(5, 2);
ALTER TABLE reports.wb_sales_funnel_products_daily ADD COLUMN IF NOT EXISTS api_response JSONB;

CREATE INDEX IF NOT EXISTS idx_wb_sales_funnel_daily_report_date ON reports.wb_sales_funnel_products_daily(report_date);
CREATE INDEX IF NOT EXISTS idx_wb_sales_funnel_daily_nm_id ON reports.wb_sales_funnel_products_daily(nm_id);
