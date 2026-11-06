CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_supplier_sales (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    date_ord TIMESTAMP WITH TIME ZONE,
    last_change_date TIMESTAMP WITH TIME ZONE NOT NULL,
    warehouse_name VARCHAR(255),
    warehouse_type VARCHAR(255),
    country_name VARCHAR(255),
    oblast_okrug_name VARCHAR(255),
    region_name VARCHAR(255),
    supplier_article VARCHAR(255),
    nm_id BIGINT,
    barcode VARCHAR(255),
    category VARCHAR(500),
    subject VARCHAR(500),
    brand VARCHAR(255),
    tech_size VARCHAR(100),
    income_id BIGINT,
    is_supply BOOLEAN,
    is_realization BOOLEAN,
    total_price DECIMAL(12, 2),
    discount_percent DECIMAL(5, 2),
    spp DECIMAL(5, 2),
    payment_sale_amount DECIMAL(12, 2),
    for_pay DECIMAL(12, 2),
    finished_price DECIMAL(12, 2),
    price_with_disc DECIMAL(12, 2),
    sale_id VARCHAR(255),
    sticker VARCHAR(255),
    g_number VARCHAR(255),
    srid VARCHAR(500) NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE reports.wb_supplier_sales ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
UPDATE reports.wb_supplier_sales
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;
ALTER TABLE reports.wb_supplier_sales ALTER COLUMN snapshot_hour SET NOT NULL;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_supplier_sales'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_supplier_sales DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_supplier_sales_snapshot_hour_key
    ON reports.wb_supplier_sales (srid, snapshot_hour);

CREATE TABLE IF NOT EXISTS reports.wb_supplier_sales_progress (
    id SERIAL PRIMARY KEY,
    last_change_date_from TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wb_supplier_sales_snapshot_date ON reports.wb_supplier_sales(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_sales_snapshot_hour ON reports.wb_supplier_sales(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_sales_nm_id ON reports.wb_supplier_sales(nm_id);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_sales_last_change ON reports.wb_supplier_sales(last_change_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_sales_srid ON reports.wb_supplier_sales(srid);

CREATE OR REPLACE VIEW reports.v_wb_supplier_sales_latest_daily AS
WITH ranked AS (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY COALESCE(s.date_ord::date, s.snapshot_date), s.srid
            ORDER BY s.snapshot_hour DESC, s.id DESC
        ) AS rn
    FROM reports.wb_supplier_sales s
)
SELECT *
FROM ranked
WHERE rn = 1;

CREATE OR REPLACE VIEW reports.v_wb_supplier_sales_latest_snapshot AS
WITH ranked AS (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.srid
            ORDER BY s.snapshot_hour DESC, s.id DESC
        ) AS rn
    FROM reports.wb_supplier_sales s
)
SELECT *
FROM ranked
WHERE rn = 1;
