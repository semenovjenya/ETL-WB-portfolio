CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_report_detail_daily (
    rrd_id BIGINT PRIMARY KEY,
    realizationreport_id BIGINT,
    srid VARCHAR(255),
    date_from DATE,
    date_to DATE,
    create_dt TIMESTAMP WITH TIME ZONE,
    currency_name VARCHAR(50),
    suppliercontract_code VARCHAR(255),
    gi_id BIGINT,
    nm_id BIGINT,
    subject_name VARCHAR(500),
    brand_name VARCHAR(255),
    sa_name VARCHAR(255),
    ts_name VARCHAR(100),
    barcode VARCHAR(255),
    doc_type_name VARCHAR(255),
    quantity INTEGER DEFAULT 0,
    retail_price DECIMAL(12, 2),
    retail_amount DECIMAL(12, 2),
    sale_percent DECIMAL(5, 2),
    commission_percent DECIMAL(5, 2),
    retail_price_withdisc_rub DECIMAL(12, 2),
    product_discount_for_report DECIMAL(12, 2),
    office_name VARCHAR(255),
    supplier_oper_name VARCHAR(255),
    order_dt TIMESTAMP WITH TIME ZONE,
    sale_dt TIMESTAMP WITH TIME ZONE,
    rr_dt DATE,
    shk_id BIGINT,
    delivery_amount DECIMAL(12, 2),
    return_amount DECIMAL(12, 2),
    delivery_rub DECIMAL(12, 2),
    gi_box_type_name VARCHAR(255),
    delivery_method VARCHAR(255),
    supplier_promo DECIMAL(12, 2),
    ppvz_spp_prc DECIMAL(12, 2),
    ppvz_kvw_prc_base DECIMAL(12, 2),
    ppvz_kvw_prc DECIMAL(12, 2),
    sup_rating_prc_up DECIMAL(12, 2),
    seller_promo_id BIGINT,
    seller_promo_discount DECIMAL(5, 2),
    loyalty_id BIGINT,
    loyalty_discount DECIMAL(5, 2),
    uuid_promocode VARCHAR(255),
    sale_price_promocode_discount_prc DECIMAL(5, 2),
    wibes_wb_discount_percent DECIMAL(5, 2),
    ppvz_sales_commission DECIMAL(12, 2),
    ppvz_for_pay DECIMAL(12, 2),
    ppvz_reward DECIMAL(12, 2),
    acquiring_fee DECIMAL(12, 2),
    acquiring_percent DECIMAL(5, 2),
    payment_processing VARCHAR(255),
    acquiring_bank VARCHAR(255),
    ppvz_vw DECIMAL(12, 2),
    ppvz_vw_nds DECIMAL(12, 2),
    ppvz_office_name VARCHAR(255),
    ppvz_office_id BIGINT,
    ppvz_supplier_id BIGINT,
    ppvz_supplier_name VARCHAR(255),
    ppvz_inn VARCHAR(50),
    declaration_number VARCHAR(255),
    bonus_type_name VARCHAR(255),
    sticker_id VARCHAR(255),
    site_country VARCHAR(100),
    srv_dbs BOOLEAN,
    penalty DECIMAL(12, 2),
    additional_payment DECIMAL(12, 2),
    rebill_logistic_cost DECIMAL(12, 2),
    rebill_logistic_org VARCHAR(500),
    storage_fee DECIMAL(12, 2),
    deduction DECIMAL(12, 2),
    acceptance DECIMAL(12, 2),
    assembly_id BIGINT,
    kiz TEXT,
    report_type INTEGER,
    is_legal_entity BOOLEAN,
    is_kgvp_v2 INTEGER,
    trbx_id VARCHAR(255),
    installment_cofinancing_amount DECIMAL(12, 2),
    cashback_amount DECIMAL(12, 2),
    cashback_discount DECIMAL(12, 2),
    cashback_commission_change DECIMAL(12, 2),
    order_uid VARCHAR(255),
    payment_schedule INTEGER,
    dlv_prc DECIMAL(12, 2),
    fix_tariff_date_from DATE,
    fix_tariff_date_to DATE,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reports.wb_report_detail_progress (
    id SERIAL PRIMARY KEY,
    last_processed_date DATE NOT NULL UNIQUE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE reports.wb_report_detail_daily
    DROP CONSTRAINT IF EXISTS wb_report_detail_daily_srid_key;

CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_date_from ON reports.wb_report_detail_daily(date_from);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_date_to ON reports.wb_report_detail_daily(date_to);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_nm_id ON reports.wb_report_detail_daily(nm_id);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_realizationreport_id ON reports.wb_report_detail_daily(realizationreport_id);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_sale_dt ON reports.wb_report_detail_daily(sale_dt);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_rr_dt ON reports.wb_report_detail_daily(rr_dt);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_srid ON reports.wb_report_detail_daily(srid);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_last_synced_at ON reports.wb_report_detail_daily(last_synced_at);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_progress_last_processed_date ON reports.wb_report_detail_progress(last_processed_date);
