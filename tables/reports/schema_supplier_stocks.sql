CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_supplier_stocks (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    last_change_date TIMESTAMP WITH TIME ZONE NOT NULL,
    warehouse_name VARCHAR(255) NOT NULL,
    supplier_article VARCHAR(255),
    nm_id BIGINT,
    barcode VARCHAR(255) NOT NULL,
    quantity INTEGER DEFAULT 0,
    in_way_to_client INTEGER DEFAULT 0,
    in_way_from_client INTEGER DEFAULT 0,
    quantity_full INTEGER DEFAULT 0,
    category VARCHAR(500),
    subject VARCHAR(500),
    brand VARCHAR(255),
    tech_size VARCHAR(100),
    price DECIMAL(12, 2),
    discount DECIMAL(5, 2),
    is_supply BOOLEAN,
    is_realization BOOLEAN,
    sc_code VARCHAR(100),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE reports.wb_supplier_stocks ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
UPDATE reports.wb_supplier_stocks
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;
ALTER TABLE reports.wb_supplier_stocks ALTER COLUMN snapshot_hour SET NOT NULL;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_supplier_stocks'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_supplier_stocks DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_supplier_stocks_snapshot_hour_key
    ON reports.wb_supplier_stocks (barcode, warehouse_name, snapshot_hour);

CREATE TABLE IF NOT EXISTS reports.wb_supplier_stocks_progress (
    id SERIAL PRIMARY KEY,
    last_change_date_from TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wb_supplier_stocks_snapshot_date ON reports.wb_supplier_stocks(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_stocks_snapshot_hour ON reports.wb_supplier_stocks(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_stocks_nm_id ON reports.wb_supplier_stocks(nm_id);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_stocks_warehouse ON reports.wb_supplier_stocks(warehouse_name);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_stocks_last_change ON reports.wb_supplier_stocks(last_change_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_stocks_last_synced ON reports.wb_supplier_stocks(last_synced_at);

CREATE OR REPLACE VIEW reports.v_wb_supplier_stocks_latest_daily AS
WITH day_cutoffs AS (
    SELECT
        snapshot_date,
        MAX(snapshot_hour) AS cutoff_hour
    FROM reports.wb_supplier_stocks
    GROUP BY snapshot_date
),
ranked AS (
    SELECT
        dc.snapshot_date AS effective_snapshot_date,
        dc.cutoff_hour AS effective_snapshot_hour,
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY dc.snapshot_date, s.barcode, s.warehouse_name
            ORDER BY s.snapshot_hour DESC, s.id DESC
        ) AS rn
    FROM day_cutoffs dc
    JOIN reports.wb_supplier_stocks s
      ON s.snapshot_hour <= dc.cutoff_hour
)
SELECT
    id,
    last_change_date,
    warehouse_name,
    supplier_article,
    nm_id,
    barcode,
    quantity,
    in_way_to_client,
    in_way_from_client,
    quantity_full,
    category,
    subject,
    brand,
    tech_size,
    price,
    discount,
    is_supply,
    is_realization,
    sc_code,
    last_synced_at,
    effective_snapshot_date AS snapshot_date,
    effective_snapshot_hour AS snapshot_hour
FROM ranked
WHERE rn = 1;

CREATE OR REPLACE VIEW reports.v_wb_supplier_stocks_latest_snapshot AS
WITH cutoff AS (
    SELECT
        MAX(snapshot_hour) AS snapshot_hour,
        MAX(snapshot_date) AS snapshot_date
    FROM reports.wb_supplier_stocks
),
ranked AS (
    SELECT
        c.snapshot_hour AS effective_snapshot_hour,
        c.snapshot_date AS effective_snapshot_date,
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.barcode, s.warehouse_name
            ORDER BY s.snapshot_hour DESC, s.id DESC
        ) AS rn
    FROM cutoff c
    JOIN reports.wb_supplier_stocks s
      ON s.snapshot_hour <= c.snapshot_hour
)
SELECT
    id,
    last_change_date,
    warehouse_name,
    supplier_article,
    nm_id,
    barcode,
    quantity,
    in_way_to_client,
    in_way_from_client,
    quantity_full,
    category,
    subject,
    brand,
    tech_size,
    price,
    discount,
    is_supply,
    is_realization,
    sc_code,
    last_synced_at,
    effective_snapshot_date AS snapshot_date,
    effective_snapshot_hour AS snapshot_hour
FROM ranked
WHERE rn = 1;
