CREATE SCHEMA IF NOT EXISTS marketing;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_marketing_campaigns') IS NOT NULL AND to_regclass('marketing.wb_marketing_campaigns') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_marketing_campaigns SET SCHEMA marketing';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS marketing;
CREATE TABLE IF NOT EXISTS marketing.wb_marketing_campaigns (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    campaign_type VARCHAR(20) NOT NULL CHECK (campaign_type IN ('promotion', 'media')),
    external_id BIGINT NOT NULL,
    name VARCHAR(500),
    status INTEGER,
    type INTEGER,
    payment_type VARCHAR(20),
    brand VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    deleted_at TIMESTAMP WITH TIME ZONE,
    change_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    settings_json JSONB,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE marketing.wb_marketing_campaigns ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
UPDATE marketing.wb_marketing_campaigns
SET snapshot_hour = COALESCE(snapshot_hour, snapshot_date::timestamp::timestamptz)
WHERE snapshot_hour IS NULL;
ALTER TABLE marketing.wb_marketing_campaigns ALTER COLUMN snapshot_hour SET NOT NULL;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'marketing.wb_marketing_campaigns'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE marketing.wb_marketing_campaigns DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

DROP INDEX IF EXISTS marketing.idx_wb_marketing_campaigns_snapshot_date_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_snapshot_hour_key
    ON marketing.wb_marketing_campaigns (snapshot_hour, campaign_type, external_id);

CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_snapshot_date ON marketing.wb_marketing_campaigns(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_snapshot_hour ON marketing.wb_marketing_campaigns(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_campaign_type ON marketing.wb_marketing_campaigns(campaign_type);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_status ON marketing.wb_marketing_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_external_id ON marketing.wb_marketing_campaigns(external_id);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_last_synced ON marketing.wb_marketing_campaigns(last_synced_at);

CREATE OR REPLACE VIEW marketing.v_wb_marketing_campaigns_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM marketing.wb_marketing_campaigns
    GROUP BY snapshot_date
)
SELECT c.*
FROM marketing.wb_marketing_campaigns c
JOIN latest_hours h
  ON h.snapshot_date = c.snapshot_date
 AND h.snapshot_hour = c.snapshot_hour;

CREATE OR REPLACE VIEW marketing.v_wb_marketing_campaigns_latest_snapshot AS
SELECT *
FROM marketing.wb_marketing_campaigns
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM marketing.wb_marketing_campaigns
);
