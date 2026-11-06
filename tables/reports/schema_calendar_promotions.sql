CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_calendar_promotions (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    promotion_id BIGINT NOT NULL,
    name VARCHAR(500),
    start_date_time TIMESTAMP WITH TIME ZONE,
    end_date_time TIMESTAMP WITH TIME ZONE,
    type VARCHAR(100),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reports.wb_calendar_promotions_progress (
    id SERIAL PRIMARY KEY,
    end_date_time_to TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reports.wb_calendar_promotions_details (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
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

CREATE TABLE IF NOT EXISTS reports.wb_calendar_promotions_nomenclatures (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
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

ALTER TABLE reports.wb_calendar_promotions ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
ALTER TABLE reports.wb_calendar_promotions_details ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
ALTER TABLE reports.wb_calendar_promotions_nomenclatures ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
ALTER TABLE reports.wb_calendar_promotions_details ADD COLUMN IF NOT EXISTS details_json JSONB;

UPDATE reports.wb_calendar_promotions
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;

UPDATE reports.wb_calendar_promotions_details
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;

UPDATE reports.wb_calendar_promotions_nomenclatures
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;

ALTER TABLE reports.wb_calendar_promotions ALTER COLUMN snapshot_hour SET NOT NULL;
ALTER TABLE reports.wb_calendar_promotions_details ALTER COLUMN snapshot_hour SET NOT NULL;
ALTER TABLE reports.wb_calendar_promotions_nomenclatures ALTER COLUMN snapshot_hour SET NOT NULL;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_calendar_promotions'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_calendar_promotions DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_calendar_promotions_details'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_calendar_promotions_details DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_calendar_promotions_nomenclatures'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_calendar_promotions_nomenclatures DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_calendar_promotions_snapshot_hour_key
    ON reports.wb_calendar_promotions (promotion_id, snapshot_hour);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_calendar_promotions_details_snapshot_hour_key
    ON reports.wb_calendar_promotions_details (snapshot_hour, promotion_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_calendar_promotions_nom_snapshot_hour_key
    ON reports.wb_calendar_promotions_nomenclatures (snapshot_hour, promotion_id, nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_snapshot_date ON reports.wb_calendar_promotions(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_snapshot_hour ON reports.wb_calendar_promotions(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_promotion_id ON reports.wb_calendar_promotions(promotion_id);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_dates ON reports.wb_calendar_promotions(start_date_time, end_date_time);

CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_details_snapshot ON reports.wb_calendar_promotions_details(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_details_snapshot_hour ON reports.wb_calendar_promotions_details(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_details_promotion ON reports.wb_calendar_promotions_details(promotion_id);

CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_nom_snapshot ON reports.wb_calendar_promotions_nomenclatures(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_nom_snapshot_hour ON reports.wb_calendar_promotions_nomenclatures(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_nom_promotion ON reports.wb_calendar_promotions_nomenclatures(promotion_id);
CREATE INDEX IF NOT EXISTS idx_wb_calendar_promotions_nom_nm ON reports.wb_calendar_promotions_nomenclatures(nm_id);

CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_calendar_promotions
    GROUP BY snapshot_date
)
SELECT p.*
FROM reports.wb_calendar_promotions p
JOIN latest_hours h
  ON h.snapshot_date = p.snapshot_date
 AND h.snapshot_hour = p.snapshot_hour;

CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_latest_snapshot AS
SELECT *
FROM reports.wb_calendar_promotions
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_calendar_promotions
);

CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_details_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_calendar_promotions_details
    GROUP BY snapshot_date
)
SELECT d.*
FROM reports.wb_calendar_promotions_details d
JOIN latest_hours h
  ON h.snapshot_date = d.snapshot_date
 AND h.snapshot_hour = d.snapshot_hour;

CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_details_latest_snapshot AS
SELECT *
FROM reports.wb_calendar_promotions_details
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_calendar_promotions_details
);

CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_nomenclatures_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_calendar_promotions_nomenclatures
    GROUP BY snapshot_date
)
SELECT n.*
FROM reports.wb_calendar_promotions_nomenclatures n
JOIN latest_hours h
  ON h.snapshot_date = n.snapshot_date
 AND h.snapshot_hour = n.snapshot_hour;

CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_nomenclatures_latest_snapshot AS
SELECT *
FROM reports.wb_calendar_promotions_nomenclatures
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_calendar_promotions_nomenclatures
);
