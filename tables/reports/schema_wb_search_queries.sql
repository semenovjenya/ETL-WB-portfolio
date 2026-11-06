CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_search_query_api_requests (
    id BIGSERIAL PRIMARY KEY,
    request_key VARCHAR(64) NOT NULL UNIQUE,
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    method_name VARCHAR(64) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    batch_index INT,
    offset_value INT,
    limit_value INT,
    current_period_start DATE,
    current_period_end DATE,
    past_period_start DATE,
    past_period_end DATE,
    nm_id BIGINT,
    top_order_by VARCHAR(64),
    position_cluster VARCHAR(64),
    include_substituted_skus BOOLEAN,
    include_search_texts BOOLEAN,
    request_payload JSONB NOT NULL,
    response_payload JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wb_search_query_api_requests_snapshot_hour
    ON reports.wb_search_query_api_requests(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_search_query_api_requests_method_name
    ON reports.wb_search_query_api_requests(method_name);
CREATE INDEX IF NOT EXISTS idx_wb_search_query_api_requests_nm_id
    ON reports.wb_search_query_api_requests(nm_id);

CREATE TABLE IF NOT EXISTS reports.wb_search_query_report_overview (
    id BIGSERIAL PRIMARY KEY,
    request_key VARCHAR(64) NOT NULL UNIQUE,
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    current_period_start DATE NOT NULL,
    current_period_end DATE NOT NULL,
    past_period_start DATE,
    past_period_end DATE,
    batch_index INT,
    offset_value INT,
    total_products BIGINT,
    supplier_rating_current NUMERIC(12, 4),
    supplier_rating_dynamics NUMERIC(12, 4),
    advertised_products_current NUMERIC(12, 4),
    advertised_products_dynamics NUMERIC(12, 4),
    position_average_current NUMERIC(12, 4),
    position_average_dynamics NUMERIC(12, 4),
    position_median_current NUMERIC(12, 4),
    position_median_dynamics NUMERIC(12, 4),
    cluster_first_hundred_current NUMERIC(12, 4),
    cluster_first_hundred_dynamics NUMERIC(12, 4),
    cluster_second_hundred_current NUMERIC(12, 4),
    cluster_second_hundred_dynamics NUMERIC(12, 4),
    cluster_below_current NUMERIC(12, 4),
    cluster_below_dynamics NUMERIC(12, 4),
    visibility_current NUMERIC(12, 4),
    visibility_dynamics NUMERIC(12, 4),
    open_card_current NUMERIC(12, 4),
    open_card_dynamics NUMERIC(12, 4),
    currency VARCHAR(16),
    api_response JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wb_search_query_report_overview_snapshot_hour
    ON reports.wb_search_query_report_overview(snapshot_hour);

CREATE TABLE IF NOT EXISTS reports.wb_search_query_report_groups (
    id BIGSERIAL PRIMARY KEY,
    request_key VARCHAR(64) NOT NULL,
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    current_period_start DATE NOT NULL,
    current_period_end DATE NOT NULL,
    past_period_start DATE,
    past_period_end DATE,
    batch_index INT,
    offset_value INT,
    row_index INT NOT NULL,
    subject_id BIGINT,
    subject_name VARCHAR(500),
    brand_name VARCHAR(255),
    tag_id BIGINT,
    tag_name VARCHAR(255),
    metric_avg_position_current NUMERIC(12, 4),
    metric_avg_position_dynamics NUMERIC(12, 4),
    metric_open_card_current NUMERIC(12, 4),
    metric_open_card_dynamics NUMERIC(12, 4),
    metric_add_to_cart_current NUMERIC(12, 4),
    metric_add_to_cart_dynamics NUMERIC(12, 4),
    metric_open_to_cart_current NUMERIC(12, 4),
    metric_open_to_cart_dynamics NUMERIC(12, 4),
    metric_orders_current NUMERIC(12, 4),
    metric_orders_dynamics NUMERIC(12, 4),
    metric_cart_to_order_current NUMERIC(12, 4),
    metric_cart_to_order_dynamics NUMERIC(12, 4),
    metric_visibility_current NUMERIC(12, 4),
    metric_visibility_dynamics NUMERIC(12, 4),
    currency VARCHAR(16),
    api_response JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (request_key, row_index)
);

CREATE INDEX IF NOT EXISTS idx_wb_search_query_report_groups_snapshot_hour
    ON reports.wb_search_query_report_groups(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_search_query_report_groups_subject_id
    ON reports.wb_search_query_report_groups(subject_id);

CREATE TABLE IF NOT EXISTS reports.wb_search_query_groups (
    id BIGSERIAL PRIMARY KEY,
    request_key VARCHAR(64) NOT NULL,
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    current_period_start DATE NOT NULL,
    current_period_end DATE NOT NULL,
    past_period_start DATE,
    past_period_end DATE,
    batch_index INT,
    offset_value INT,
    row_index INT NOT NULL,
    subject_id BIGINT,
    subject_name VARCHAR(500),
    brand_name VARCHAR(255),
    tag_id BIGINT,
    tag_name VARCHAR(255),
    metric_avg_position_current NUMERIC(12, 4),
    metric_avg_position_dynamics NUMERIC(12, 4),
    metric_open_card_current NUMERIC(12, 4),
    metric_open_card_dynamics NUMERIC(12, 4),
    metric_add_to_cart_current NUMERIC(12, 4),
    metric_add_to_cart_dynamics NUMERIC(12, 4),
    metric_open_to_cart_current NUMERIC(12, 4),
    metric_open_to_cart_dynamics NUMERIC(12, 4),
    metric_orders_current NUMERIC(12, 4),
    metric_orders_dynamics NUMERIC(12, 4),
    metric_cart_to_order_current NUMERIC(12, 4),
    metric_cart_to_order_dynamics NUMERIC(12, 4),
    metric_visibility_current NUMERIC(12, 4),
    metric_visibility_dynamics NUMERIC(12, 4),
    currency VARCHAR(16),
    api_response JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (request_key, row_index)
);

CREATE INDEX IF NOT EXISTS idx_wb_search_query_groups_snapshot_hour
    ON reports.wb_search_query_groups(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_search_query_groups_subject_id
    ON reports.wb_search_query_groups(subject_id);

CREATE TABLE IF NOT EXISTS reports.wb_search_query_details (
    id BIGSERIAL PRIMARY KEY,
    request_key VARCHAR(64) NOT NULL,
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    current_period_start DATE NOT NULL,
    current_period_end DATE NOT NULL,
    past_period_start DATE,
    past_period_end DATE,
    batch_index INT,
    offset_value INT,
    nm_id BIGINT NOT NULL,
    name VARCHAR(1000),
    vendor_code VARCHAR(255),
    subject_name VARCHAR(500),
    brand_name VARCHAR(255),
    main_photo TEXT,
    is_advertised BOOLEAN,
    is_substituted_sku BOOLEAN,
    is_card_rated BOOLEAN,
    rating NUMERIC(12, 4),
    feedback_rating NUMERIC(12, 4),
    min_price NUMERIC(14, 2),
    max_price NUMERIC(14, 2),
    avg_position_current NUMERIC(12, 4),
    avg_position_dynamics NUMERIC(12, 4),
    open_card_current NUMERIC(12, 4),
    open_card_dynamics NUMERIC(12, 4),
    add_to_cart_current NUMERIC(12, 4),
    add_to_cart_dynamics NUMERIC(12, 4),
    open_to_cart_current NUMERIC(12, 4),
    open_to_cart_dynamics NUMERIC(12, 4),
    orders_current NUMERIC(12, 4),
    orders_dynamics NUMERIC(12, 4),
    cart_to_order_current NUMERIC(12, 4),
    cart_to_order_dynamics NUMERIC(12, 4),
    visibility_current NUMERIC(12, 4),
    visibility_dynamics NUMERIC(12, 4),
    currency VARCHAR(16),
    api_response JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (request_key, nm_id)
);

CREATE INDEX IF NOT EXISTS idx_wb_search_query_details_snapshot_hour
    ON reports.wb_search_query_details(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_search_query_details_nm_id
    ON reports.wb_search_query_details(nm_id);

CREATE TABLE IF NOT EXISTS reports.wb_search_query_texts (
    id BIGSERIAL PRIMARY KEY,
    request_key VARCHAR(64) NOT NULL,
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    current_period_start DATE NOT NULL,
    current_period_end DATE NOT NULL,
    past_period_start DATE,
    past_period_end DATE,
    batch_index INT,
    top_order_by VARCHAR(64) NOT NULL,
    nm_id BIGINT NOT NULL,
    text TEXT NOT NULL,
    subject_name VARCHAR(500),
    brand_name VARCHAR(255),
    vendor_code VARCHAR(255),
    product_name VARCHAR(1000),
    is_card_rated BOOLEAN,
    rating NUMERIC(12, 4),
    feedback_rating NUMERIC(12, 4),
    min_price NUMERIC(14, 2),
    max_price NUMERIC(14, 2),
    frequency_current NUMERIC(12, 4),
    frequency_dynamics NUMERIC(12, 4),
    week_frequency BIGINT,
    median_position_current NUMERIC(12, 4),
    median_position_dynamics NUMERIC(12, 4),
    avg_position_current NUMERIC(12, 4),
    avg_position_dynamics NUMERIC(12, 4),
    open_card_current NUMERIC(12, 4),
    open_card_dynamics NUMERIC(12, 4),
    open_card_percentile NUMERIC(12, 4),
    add_to_cart_current NUMERIC(12, 4),
    add_to_cart_dynamics NUMERIC(12, 4),
    add_to_cart_percentile NUMERIC(12, 4),
    open_to_cart_current NUMERIC(12, 4),
    open_to_cart_dynamics NUMERIC(12, 4),
    open_to_cart_percentile NUMERIC(12, 4),
    orders_current NUMERIC(12, 4),
    orders_dynamics NUMERIC(12, 4),
    orders_percentile NUMERIC(12, 4),
    cart_to_order_current NUMERIC(12, 4),
    cart_to_order_dynamics NUMERIC(12, 4),
    cart_to_order_percentile NUMERIC(12, 4),
    visibility_current NUMERIC(12, 4),
    visibility_dynamics NUMERIC(12, 4),
    currency VARCHAR(16),
    api_response JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_hour, current_period_start, current_period_end, nm_id, text, top_order_by)
);

CREATE INDEX IF NOT EXISTS idx_wb_search_query_texts_snapshot_hour
    ON reports.wb_search_query_texts(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_search_query_texts_nm_id
    ON reports.wb_search_query_texts(nm_id);

CREATE TABLE IF NOT EXISTS reports.wb_search_query_orders_total_daily (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    current_period_start DATE NOT NULL,
    current_period_end DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    dt DATE NOT NULL,
    avg_position NUMERIC(12, 4),
    orders_count NUMERIC(12, 4),
    api_response JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_hour, current_period_start, current_period_end, nm_id, dt)
);

CREATE INDEX IF NOT EXISTS idx_wb_search_query_orders_total_daily_snapshot_hour
    ON reports.wb_search_query_orders_total_daily(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_search_query_orders_total_daily_nm_id
    ON reports.wb_search_query_orders_total_daily(nm_id);

CREATE TABLE IF NOT EXISTS reports.wb_search_query_orders_text_daily (
    id BIGSERIAL PRIMARY KEY,
    request_key VARCHAR(64) NOT NULL,
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    current_period_start DATE NOT NULL,
    current_period_end DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    text TEXT NOT NULL,
    frequency NUMERIC(12, 4),
    dt DATE NOT NULL,
    avg_position NUMERIC(12, 4),
    orders_count NUMERIC(12, 4),
    api_response JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_hour, current_period_start, current_period_end, nm_id, text, dt)
);

CREATE INDEX IF NOT EXISTS idx_wb_search_query_orders_text_daily_snapshot_hour
    ON reports.wb_search_query_orders_text_daily(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_search_query_orders_text_daily_nm_id
    ON reports.wb_search_query_orders_text_daily(nm_id);
