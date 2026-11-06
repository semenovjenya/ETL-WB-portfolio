CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_supplies (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    supply_id BIGINT,
    preorder_id BIGINT,
    create_date TIMESTAMP WITH TIME ZONE,
    supply_date DATE,
    fact_date TIMESTAMP WITH TIME ZONE,
    updated_date TIMESTAMP WITH TIME ZONE,
    status_id SMALLINT,
    phone VARCHAR(50),
    box_type_id SMALLINT,
    warehouse_id INT,
    warehouse_name VARCHAR(255),
    actual_warehouse_id INT,
    actual_warehouse_name VARCHAR(255),
    transit_warehouse_id INT,
    transit_warehouse_name VARCHAR(255),
    acceptance_cost DECIMAL(12, 2),
    paid_acceptance_coefficient INT,
    reject_reason TEXT,
    supplier_assign_name VARCHAR(255),
    storage_coef VARCHAR(50),
    delivery_coef VARCHAR(50),
    quantity INT,
    ready_for_sale_quantity INT,
    accepted_quantity INT,
    unloading_quantity INT,
    depersonalized_quantity INT,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reports.wb_supplies_goods (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    supply_id BIGINT NOT NULL,
    barcode VARCHAR(255),
    vendor_code VARCHAR(255),
    nm_id BIGINT,
    need_kiz BOOLEAN,
    tnved VARCHAR(50),
    tech_size VARCHAR(100),
    color VARCHAR(255),
    supplier_box_amount INT,
    quantity INT,
    ready_for_sale_quantity INT,
    unloading_quantity INT,
    accepted_quantity INT,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE reports.wb_supplies ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
ALTER TABLE reports.wb_supplies_goods ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;

UPDATE reports.wb_supplies
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;

UPDATE reports.wb_supplies_goods
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;

ALTER TABLE reports.wb_supplies ALTER COLUMN snapshot_hour SET NOT NULL;
ALTER TABLE reports.wb_supplies_goods ALTER COLUMN snapshot_hour SET NOT NULL;

DROP INDEX IF EXISTS idx_wb_supplies_unique_supply;
DROP INDEX IF EXISTS idx_wb_supplies_unique_preorder;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_supplies_unique_supply
    ON reports.wb_supplies(snapshot_hour, supply_id) WHERE supply_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_supplies_unique_preorder
    ON reports.wb_supplies(snapshot_hour, preorder_id) WHERE supply_id IS NULL;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_supplies_goods'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_supplies_goods DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_supplies_goods_snapshot_hour_key
    ON reports.wb_supplies_goods (supply_id, barcode, snapshot_hour);

CREATE TABLE IF NOT EXISTS reports.wb_supplies_progress (
    id SERIAL PRIMARY KEY,
    last_create_date TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wb_supplies_snapshot_date ON reports.wb_supplies(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_snapshot_hour ON reports.wb_supplies(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_supply_id ON reports.wb_supplies(supply_id);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_preorder_id ON reports.wb_supplies(preorder_id);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_create_date ON reports.wb_supplies(create_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_status_id ON reports.wb_supplies(status_id);

CREATE INDEX IF NOT EXISTS idx_wb_supplies_goods_snapshot_date ON reports.wb_supplies_goods(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_goods_snapshot_hour ON reports.wb_supplies_goods(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_goods_supply_id ON reports.wb_supplies_goods(supply_id);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_goods_nm_id ON reports.wb_supplies_goods(nm_id);

CREATE OR REPLACE VIEW reports.v_wb_supplies_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_supplies
    GROUP BY snapshot_date
)
SELECT s.*
FROM reports.wb_supplies s
JOIN latest_hours h
  ON h.snapshot_date = s.snapshot_date
 AND h.snapshot_hour = s.snapshot_hour;

CREATE OR REPLACE VIEW reports.v_wb_supplies_latest_snapshot AS
SELECT *
FROM reports.wb_supplies
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_supplies
);

CREATE OR REPLACE VIEW reports.v_wb_supplies_goods_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_supplies_goods
    GROUP BY snapshot_date
)
SELECT g.*
FROM reports.wb_supplies_goods g
JOIN latest_hours h
  ON h.snapshot_date = g.snapshot_date
 AND h.snapshot_hour = g.snapshot_hour;

CREATE OR REPLACE VIEW reports.v_wb_supplies_goods_latest_snapshot AS
SELECT *
FROM reports.wb_supplies_goods
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_supplies_goods
);
