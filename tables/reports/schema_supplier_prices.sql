CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_supplier_prices (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    vendor_code VARCHAR(255),
    currency_iso_code VARCHAR(10),
    discount DECIMAL(5, 2),
    club_discount DECIMAL(5, 2),
    editable_size_price BOOLEAN,
    is_bad_turnover BOOLEAN,
    price DECIMAL(12, 2),
    discounted_price DECIMAL(12, 2),
    club_discounted_price DECIMAL(12, 2),
    sizes_json JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE reports.wb_supplier_prices ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
UPDATE reports.wb_supplier_prices
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;
ALTER TABLE reports.wb_supplier_prices ALTER COLUMN snapshot_hour SET NOT NULL;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_supplier_prices'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_supplier_prices DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_supplier_prices_snapshot_hour_key
    ON reports.wb_supplier_prices (nm_id, snapshot_hour);

CREATE INDEX IF NOT EXISTS idx_wb_supplier_prices_snapshot_date ON reports.wb_supplier_prices(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_prices_snapshot_hour ON reports.wb_supplier_prices(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_prices_nm_id ON reports.wb_supplier_prices(nm_id);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_prices_last_synced ON reports.wb_supplier_prices(last_synced_at);

COMMENT ON TABLE reports.wb_supplier_prices IS
'Срезы цен и скидок товаров WB с детализацией до часа.';

CREATE OR REPLACE VIEW reports.v_wb_supplier_prices_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_supplier_prices
    GROUP BY snapshot_date
)
SELECT p.*
FROM reports.wb_supplier_prices p
JOIN latest_hours h
  ON h.snapshot_date = p.snapshot_date
 AND h.snapshot_hour = p.snapshot_hour;

CREATE OR REPLACE VIEW reports.v_wb_supplier_prices_latest_snapshot AS
SELECT *
FROM reports.wb_supplier_prices
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_supplier_prices
);
