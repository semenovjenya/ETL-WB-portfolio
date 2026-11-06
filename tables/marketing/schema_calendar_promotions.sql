CREATE SCHEMA IF NOT EXISTS marketing;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_calendar_promotions') IS NOT NULL AND to_regclass('marketing.wb_calendar_promotions') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_calendar_promotions SET SCHEMA marketing';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_calendar_promotions_progress') IS NOT NULL AND to_regclass('marketing.wb_calendar_promotions_progress') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_calendar_promotions_progress SET SCHEMA marketing';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_calendar_promotions_details') IS NOT NULL AND to_regclass('marketing.wb_calendar_promotions_details') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_calendar_promotions_details SET SCHEMA marketing';
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('reports.wb_calendar_promotions_nomenclatures') IS NOT NULL AND to_regclass('marketing.wb_calendar_promotions_nomenclatures') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_calendar_promotions_nomenclatures SET SCHEMA marketing';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS marketing;
CREATE TABLE IF NOT EXISTS marketing.wb_calendar_promotions (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    promotion_id BIGINT NOT NULL,
    name VARCHAR(500),
    start_date_time TIMESTAMP WITH TIME ZONE,
    end_date_time TIMESTAMP WITH TIME ZONE,
    type VARCHAR(100),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS marketing.wb_calendar_promotions_progress (
    id SERIAL PRIMARY KEY,
    end_date_time_to TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS marketing.wb_calendar_promotions_details (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    promotion_id BIGINT NOT NULL,
    name VARCHAR(500),
    description TEXT,
    advantages JSONB,
    start_date_time TIMESTAMP WITH TIME ZONE,
    end_date_time TIMESTAMP WITH TIME ZONE,
    in_promo_action_leftovers INT,
    in_promo_action_total INT,
    not_in_promo_action_leftovers INT,
    not_in_promo_action_total INT,
    participation_percentage NUMERIC(8, 2),
    type VARCHAR(100),
    exception_products_count INT,
    ranging JSONB,
    details_json JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS marketing.wb_calendar_promotions_nomenclatures (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    promotion_id BIGINT NOT NULL,
    nm_id BIGINT NOT NULL,
    in_action BOOLEAN NOT NULL,
    price NUMERIC(18, 2),
    currency_code VARCHAR(10),
    plan_price NUMERIC(18, 2),
    discount NUMERIC(8, 2),
    plan_discount NUMERIC(8, 2),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE marketing.wb_calendar_promotions_details ADD COLUMN IF NOT EXISTS details_json JSONB;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'marketing.wb_calendar_promotions'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE marketing.wb_calendar_promotions DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'marketing.wb_calendar_promotions_details'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE marketing.wb_calendar_promotions_details DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'marketing.wb_calendar_promotions_nomenclatures'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE marketing.wb_calendar_promotions_nomenclatures DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_calendar_promotions_snapshot_date_key
    ON marketing.wb_calendar_promotions (promotion_id, snapshot_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_calendar_promotions_details_snapshot_date_key
    ON marketing.wb_calendar_promotions_details (snapshot_date, promotion_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_calendar_promotions_nom_snapshot_date_key
    ON marketing.wb_calendar_promotions_nomenclatures (snapshot_date, promotion_id, nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_snapshot_date ON marketing.wb_calendar_promotions(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_promotion_id ON marketing.wb_calendar_promotions(promotion_id);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_dates ON marketing.wb_calendar_promotions(start_date_time, end_date_time);

CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_details_snapshot ON marketing.wb_calendar_promotions_details(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_details_promotion ON marketing.wb_calendar_promotions_details(promotion_id);

CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_nom_snapshot ON marketing.wb_calendar_promotions_nomenclatures(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_nom_promotion ON marketing.wb_calendar_promotions_nomenclatures(promotion_id);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_nom_nm ON marketing.wb_calendar_promotions_nomenclatures(nm_id);

CREATE OR REPLACE VIEW marketing.v_wb_calendar_promotions_latest_daily AS
SELECT *
FROM marketing.wb_calendar_promotions;

CREATE OR REPLACE VIEW marketing.v_wb_calendar_promotions_latest_snapshot AS
SELECT *
FROM marketing.wb_calendar_promotions
WHERE snapshot_date = (
    SELECT MAX(snapshot_date)
    FROM marketing.wb_calendar_promotions
);

CREATE OR REPLACE VIEW marketing.v_wb_calendar_promotions_details_latest_daily AS
SELECT *
FROM marketing.wb_calendar_promotions_details;

CREATE OR REPLACE VIEW marketing.v_wb_calendar_promotions_details_latest_snapshot AS
SELECT *
FROM marketing.wb_calendar_promotions_details
WHERE snapshot_date = (
    SELECT MAX(snapshot_date)
    FROM marketing.wb_calendar_promotions_details
);

CREATE OR REPLACE VIEW marketing.v_wb_calendar_promotions_nomenclatures_latest_daily AS
SELECT *
FROM marketing.wb_calendar_promotions_nomenclatures;

CREATE OR REPLACE VIEW marketing.v_wb_calendar_promotions_nomenclatures_latest_snapshot AS
SELECT *
FROM marketing.wb_calendar_promotions_nomenclatures
WHERE snapshot_date = (
    SELECT MAX(snapshot_date)
    FROM marketing.wb_calendar_promotions_nomenclatures
);
