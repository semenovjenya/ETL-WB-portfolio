CREATE SCHEMA IF NOT EXISTS supply;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_supplies') IS NOT NULL AND to_regclass('supply.wb_supplies') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_supplies SET SCHEMA supply';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_supplies_goods') IS NOT NULL AND to_regclass('supply.wb_supplies_goods') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_supplies_goods SET SCHEMA supply';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_supplies_progress') IS NOT NULL AND to_regclass('supply.wb_supplies_progress') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_supplies_progress SET SCHEMA supply';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS supply;
CREATE TABLE IF NOT EXISTS supply.wb_supplies (
    id BIGSERIAL PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS supply.wb_supplies_goods (
    id BIGSERIAL PRIMARY KEY,
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

DROP INDEX IF EXISTS idx_wb_supplies_unique_supply;
DROP INDEX IF EXISTS idx_wb_supplies_unique_preorder;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_supplies_unique_supply
    ON supply.wb_supplies(snapshot_date, supply_id) WHERE supply_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_supplies_unique_preorder
    ON supply.wb_supplies(snapshot_date, preorder_id) WHERE supply_id IS NULL;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'supply.wb_supplies_goods'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE supply.wb_supplies_goods DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_supplies_goods_snapshot_date_key
    ON supply.wb_supplies_goods (supply_id, barcode, snapshot_date);

CREATE TABLE IF NOT EXISTS supply.wb_supplies_progress (
    id SERIAL PRIMARY KEY,
    last_create_date TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wb_supplies_snapshot_date ON supply.wb_supplies(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_supply_id ON supply.wb_supplies(supply_id);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_preorder_id ON supply.wb_supplies(preorder_id);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_create_date ON supply.wb_supplies(create_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_status_id ON supply.wb_supplies(status_id);

CREATE INDEX IF NOT EXISTS idx_wb_supplies_goods_snapshot_date ON supply.wb_supplies_goods(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_goods_supply_id ON supply.wb_supplies_goods(supply_id);
CREATE INDEX IF NOT EXISTS idx_wb_supplies_goods_nm_id ON supply.wb_supplies_goods(nm_id);

CREATE OR REPLACE VIEW supply.v_wb_supplies_latest_daily AS
SELECT *
FROM supply.wb_supplies;

CREATE OR REPLACE VIEW supply.v_wb_supplies_latest_snapshot AS
SELECT *
FROM supply.wb_supplies
WHERE snapshot_date = (
    SELECT MAX(snapshot_date)
    FROM supply.wb_supplies
);

CREATE OR REPLACE VIEW supply.v_wb_supplies_goods_latest_daily AS
SELECT *
FROM supply.wb_supplies_goods;

CREATE OR REPLACE VIEW supply.v_wb_supplies_goods_latest_snapshot AS
SELECT *
FROM supply.wb_supplies_goods
WHERE snapshot_date = (
    SELECT MAX(snapshot_date)
    FROM supply.wb_supplies_goods
);
