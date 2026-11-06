CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_report_detail_daily') IS NOT NULL AND to_regclass('finance.wb_report_detail_daily') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_report_detail_daily SET SCHEMA finance';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_report_detail_progress') IS NOT NULL AND to_regclass('finance.wb_report_detail_progress') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_report_detail_progress SET SCHEMA finance';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS finance;
CREATE TABLE IF NOT EXISTS finance.wb_report_detail_daily (
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

CREATE TABLE IF NOT EXISTS finance.wb_report_detail_progress (
    id SERIAL PRIMARY KEY,
    last_processed_date DATE NOT NULL UNIQUE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS finance.wb_product_costs (
    vendor_code VARCHAR(255) PRIMARY KEY,
    nm_id BIGINT NOT NULL UNIQUE,
    product_name VARCHAR(500) NOT NULL,
    brand_name VARCHAR(255),
    cost_price_rub NUMERIC(12, 2) NOT NULL CHECK (cost_price_rub >= 0),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO finance.wb_product_costs (
    vendor_code,
    nm_id,
    product_name,
    brand_name,
    cost_price_rub
)
VALUES
    ('46224', 51928949, 'Патчи гидрогелевые с лифтинг эффектом', 'Lifecode', 401),
    ('46225', 51931559, 'Патчи гидрогелевые с ботокс эффектом', 'Lifecode', 401),
    ('46227', 70194686, 'Биоактивная лифтинг-сыворотка для лица', 'Lifecode', 344),
    ('46229', 70195171, 'Сыворотка для ухода за кожей лица и области вокруг глаз пептидная с эффектом ботокса', 'Lifecode', 379),
    ('46230', 70195339, 'Омолаживающая и укрепляющая "ANTI-AGE" сыворотка для лица', 'Lifecode', 344),
    ('46232', 73041159, 'Сыворотка-мезококтель', 'Lifecode', 365),
    ('46233', 73259052, 'Противоотечная маска с пептидным комплексом EYE REGENER', 'Lifecode', 186),
    ('46234', 73259742, 'Детокс-маска ACTIFLOW', 'Lifecode', 186),
    ('46235', 75241521, 'Тоник для лица', 'Lifecode', 302),
    ('46236', 81558446, 'Пенка для умывания', 'Lifecode', 306),
    ('46239', 113273939, 'Крем увлажняющий для лица, 50мл', 'Lifecode', 609),
    ('46241', 112523725, 'Сыворотка Аква-флюид с витамином С, 50мл', 'Lifecode', 524),
    ('46242', 111584696, 'Мицеллярная вода для лица, 250мл', 'Lifecode', 324),
    ('46244', 116822913, 'Набор для лица и области вокруг глаз лифтинг уход "Facelift set 2"', 'Lifecode', 799),
    ('46245', 116829464, 'Набор для ухода за лицом с ботокс эффектом "Botox Care set"', 'Lifecode', 834),
    ('46260', 133741672, 'Шампунь для роста волос', 'Lifecode', 426),
    ('46261', 133586658, 'Сыворотка активатор роста волос', 'Lifecode', 455),
    ('46262', 123647705, 'Спрей для волос несмываемый', 'Lifecode', 318),
    ('46263', 133014572, 'Крем для рук', 'Lifecode', 242),
    ('46266', 137602808, 'Тканевая маска супер лифтинг для лица', 'Lifecode', 195),
    ('46269', 138771063, 'Набор для ежедневного ухода за лицом.', 'Lifecode', 662),
    ('46275', 142962756, 'Крем для ног', 'Lifecode', 249),
    ('46276', 142735184, 'Набор масок Тканевая маска супер лифтинг для лица(зеленая) 5шт', 'Lifecode', 679),
    ('46277', 142745322, 'Набор Масок Противоотечная маска с пептидным комплексом EYE REGENER 5шт', 'Lifecode', 428),
    ('46278', 142743295, 'Набор тканевых масок с комплексом ACTIFLOW', 'Lifecode', 428),
    ('46280', 145786601, 'Маска антисептическая Anti Acne', 'Lifecode', 304),
    ('46281', 145754206, 'Гель анти-акне', 'Lifecode', 394),
    ('46282', 146099140, 'Сыворотка анти-акне', 'Lifecode', 429),
    ('46283', 147331442, 'Крем анти-акне', 'Lifecode', 439),
    ('46285', 147788159, 'Крем-маттинг', 'Lifecode', 441),
    ('46291', 149620954, 'Набор для ухода за лицом matting must have', 'Lifecode', 795),
    ('46297', 149923084, 'Набор everyday matting care', 'Lifecode', 972),
    ('46298', 151488637, 'Бальзам для волос', 'Lifecode', 447),
    ('46299', 155863996, 'Мультифункциональная спрей-сыворотка 5 в 1', 'Lifecode', 389),
    ('46300', 156051054, 'Крем-хайлайтер для лица, 15 SPF', 'Lifecode', 489),
    ('46301', 153994566, 'Набор для ухода и восстановления волос "Hair care repair and set"', 'Lifecode', 927),
    ('46302', 161878080, 'Крем для тела увлажняющий, крем баттер для тела', 'Lifecode', 478),
    ('46303', 171742855, 'Крем для лица с цирамидами', 'Lifecode', 459),
    ('46306', 180286536, 'Питательный мультипептидный крем для лица с лифтинг эффектом', 'Lifecode', 535),
    ('46305', 171693234, 'набор мезококтель', 'Lifecode', 601),
    ('46307', 178768191, 'набор для ухода Омоложение и питание', 'Lifecode', 695),
    ('46212', 172445985, 'Щетка в пакете', 'Lifecode', 267),
    ('46211', 48691113, 'Щетка в коробке', 'Lifecode', 319),
    ('46308', 209190486, 'Стайлинг пудра для волос для прикорневого объема', 'Lifecode', 535),
    ('46310', 221513179, 'Тоник для лица увлажняющий с охлаждающим эффектом', 'Lifecode', 355),
    ('46313', 768260062, 'Крем увлажняющий для лица с PDRN, восстанавливающий, с эффектом омоложения', 'Lifecode', 440)
ON CONFLICT (vendor_code) DO UPDATE
SET
    nm_id = EXCLUDED.nm_id,
    product_name = EXCLUDED.product_name,
    brand_name = EXCLUDED.brand_name,
    cost_price_rub = EXCLUDED.cost_price_rub,
    updated_at = CURRENT_TIMESTAMP;

ALTER TABLE finance.wb_report_detail_daily
    DROP CONSTRAINT IF EXISTS wb_report_detail_daily_srid_key;

CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_date_from ON finance.wb_report_detail_daily(date_from);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_date_to ON finance.wb_report_detail_daily(date_to);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_nm_id ON finance.wb_report_detail_daily(nm_id);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_realizationreport_id ON finance.wb_report_detail_daily(realizationreport_id);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_sale_dt ON finance.wb_report_detail_daily(sale_dt);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_rr_dt ON finance.wb_report_detail_daily(rr_dt);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_srid ON finance.wb_report_detail_daily(srid);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_daily_last_synced_at ON finance.wb_report_detail_daily(last_synced_at);
CREATE INDEX IF NOT EXISTS idx_wb_report_detail_progress_last_processed_date ON finance.wb_report_detail_progress(last_processed_date);
CREATE INDEX IF NOT EXISTS idx_wb_product_costs_brand_name ON finance.wb_product_costs(brand_name);
