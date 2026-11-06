CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_marketing_campaigns (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
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

ALTER TABLE reports.wb_marketing_campaigns ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
UPDATE reports.wb_marketing_campaigns
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;
ALTER TABLE reports.wb_marketing_campaigns ALTER COLUMN snapshot_hour SET NOT NULL;

DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_marketing_campaigns'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_marketing_campaigns DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_snapshot_hour_key
    ON reports.wb_marketing_campaigns (snapshot_hour, campaign_type, external_id);

CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_snapshot_date ON reports.wb_marketing_campaigns(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_snapshot_hour ON reports.wb_marketing_campaigns(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_campaign_type ON reports.wb_marketing_campaigns(campaign_type);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_status ON reports.wb_marketing_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_external_id ON reports.wb_marketing_campaigns(external_id);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaigns_last_synced ON reports.wb_marketing_campaigns(last_synced_at);

CREATE OR REPLACE VIEW reports.v_wb_marketing_campaigns_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_marketing_campaigns
    GROUP BY snapshot_date
)
SELECT c.*
FROM reports.wb_marketing_campaigns c
JOIN latest_hours h
  ON h.snapshot_date = c.snapshot_date
 AND h.snapshot_hour = c.snapshot_hour;

CREATE OR REPLACE VIEW reports.v_wb_marketing_campaigns_latest_snapshot AS
SELECT *
FROM reports.wb_marketing_campaigns
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_marketing_campaigns
);
