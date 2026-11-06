-- Аналитика маркетинга WB: поисковые кластеры, ставки, минус-фразы, статистика, затраты, баланс.
-- Не по подписке: данные из API Продвижения (normquery, fullstats, upd, balance, budget).
CREATE SCHEMA IF NOT EXISTS reports;

-- Поисковые кластеры по кампаниям и номенклатуре (active / excluded), снимок на дату
CREATE TABLE IF NOT EXISTS reports.wb_marketing_normquery_clusters (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    nm_id BIGINT NOT NULL,
    is_active BOOLEAN NOT NULL,
    norm_query TEXT NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, advert_id, nm_id, is_active, norm_query)
);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_clusters_snapshot ON reports.wb_marketing_normquery_clusters(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_clusters_advert_nm ON reports.wb_marketing_normquery_clusters(advert_id, nm_id);

-- Ставки по поисковым кластерам (копейки)
CREATE TABLE IF NOT EXISTS reports.wb_marketing_normquery_bids (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    nm_id BIGINT NOT NULL,
    norm_query TEXT NOT NULL,
    bid INTEGER NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, advert_id, nm_id, norm_query)
);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_bids_snapshot ON reports.wb_marketing_normquery_bids(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_bids_advert_nm ON reports.wb_marketing_normquery_bids(advert_id, nm_id);

-- Минус-фразы по кампаниям и номенклатуре
CREATE TABLE IF NOT EXISTS reports.wb_marketing_normquery_minus (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    nm_id BIGINT NOT NULL,
    norm_query TEXT NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_date, advert_id, nm_id, norm_query)
);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_minus_snapshot ON reports.wb_marketing_normquery_minus(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_minus_advert_nm ON reports.wb_marketing_normquery_minus(advert_id, nm_id);

-- Статистика по поисковым кластерам за период (v0, без детализации по дням)
CREATE TABLE IF NOT EXISTS reports.wb_marketing_normquery_stats (
    id BIGSERIAL PRIMARY KEY,
    period_from DATE NOT NULL,
    period_to DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    nm_id BIGINT NOT NULL,
    norm_query TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    ctr DECIMAL(12, 4),
    cpc INTEGER,
    cpm INTEGER,
    orders INTEGER DEFAULT 0,
    atbs INTEGER DEFAULT 0,
    avg_pos DECIMAL(8, 2),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (period_from, period_to, advert_id, nm_id, norm_query)
);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_stats_period ON reports.wb_marketing_normquery_stats(period_from, period_to);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_stats_advert_nm ON reports.wb_marketing_normquery_stats(advert_id, nm_id);

-- Статистика по поисковым кластерам по дням (v1)
CREATE TABLE IF NOT EXISTS reports.wb_marketing_normquery_stats_daily (
    id BIGSERIAL PRIMARY KEY,
    stat_date DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    nm_id BIGINT NOT NULL,
    norm_query TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    ctr DECIMAL(12, 4),
    cpc DECIMAL(12, 4),
    cpm DECIMAL(12, 4),
    orders INTEGER DEFAULT 0,
    shks INTEGER DEFAULT 0,
    atbs INTEGER DEFAULT 0,
    avg_pos DECIMAL(8, 2),
    spend DECIMAL(12, 2),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stat_date, advert_id, nm_id, norm_query)
);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_stats_daily_date ON reports.wb_marketing_normquery_stats_daily(stat_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_nq_stats_daily_advert_nm ON reports.wb_marketing_normquery_stats_daily(advert_id, nm_id);

-- Фактические затраты по кампаниям за период (GET /adv/v1/upd)
CREATE TABLE IF NOT EXISTS reports.wb_marketing_upd (
    id BIGSERIAL PRIMARY KEY,
    period_from DATE NOT NULL,
    period_to DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    camp_name VARCHAR(500),
    upd_sum DECIMAL(12, 2) NOT NULL,
    upd_time TIMESTAMP WITH TIME ZONE,
    advert_type INTEGER,
    payment_type VARCHAR(100),
    advert_status INTEGER,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_upd_period ON reports.wb_marketing_upd(period_from, period_to);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_upd_advert ON reports.wb_marketing_upd(advert_id);

-- Баланс кабинета Продвижения (снимок на дату)
CREATE TABLE IF NOT EXISTS reports.wb_marketing_balance (
    id SERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    balance DECIMAL(12, 2) DEFAULT 0,
    net DECIMAL(12, 2) DEFAULT 0,
    bonus DECIMAL(12, 2) DEFAULT 0,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE reports.wb_marketing_balance ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
UPDATE reports.wb_marketing_balance
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;
ALTER TABLE reports.wb_marketing_balance ALTER COLUMN snapshot_hour SET NOT NULL;
DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_marketing_balance'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_marketing_balance DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_marketing_balance_snapshot_hour_key
    ON reports.wb_marketing_balance (snapshot_hour);

-- Бюджет кампаний (снимок на дату)
CREATE TABLE IF NOT EXISTS reports.wb_marketing_budget (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    cash DECIMAL(12, 2) DEFAULT 0,
    netting DECIMAL(12, 2) DEFAULT 0,
    total DECIMAL(12, 2) DEFAULT 0,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE reports.wb_marketing_budget ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
UPDATE reports.wb_marketing_budget
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;
ALTER TABLE reports.wb_marketing_budget ALTER COLUMN snapshot_hour SET NOT NULL;
DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_marketing_budget'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_marketing_budget DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_marketing_budget_snapshot_hour_key
    ON reports.wb_marketing_budget (snapshot_hour, advert_id);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_budget_snapshot ON reports.wb_marketing_budget(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_budget_snapshot_hour ON reports.wb_marketing_budget(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_budget_advert ON reports.wb_marketing_budget(advert_id);

-- Агрегированная статистика по кампаниям за период (из fullstats, по дням)
CREATE TABLE IF NOT EXISTS reports.wb_marketing_campaign_stats_daily (
    id BIGSERIAL PRIMARY KEY,
    stat_date DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    views INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    ctr DECIMAL(12, 4),
    cpc DECIMAL(12, 4),
    orders INTEGER DEFAULT 0,
    shks INTEGER DEFAULT 0,
    sum_spend DECIMAL(12, 2) DEFAULT 0,
    atbs INTEGER DEFAULT 0,
    canceled INTEGER DEFAULT 0,
    cr DECIMAL(12, 4),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stat_date, advert_id)
);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaign_stats_daily_date ON reports.wb_marketing_campaign_stats_daily(stat_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaign_stats_daily_advert ON reports.wb_marketing_campaign_stats_daily(advert_id);

-- Детализация кампаний по номенклатуре (nm_id = карточка/SKU): какие номенклатуры в каких кампаниях
CREATE TABLE IF NOT EXISTS reports.wb_marketing_campaign_nms (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    nm_id BIGINT NOT NULL,
    subject_id INTEGER,
    subject_name VARCHAR(500),
    bid_search_kopecks INTEGER DEFAULT 0,
    bid_recommendations_kopecks INTEGER DEFAULT 0,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE reports.wb_marketing_campaign_nms ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
UPDATE reports.wb_marketing_campaign_nms
SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp)
WHERE snapshot_hour IS NULL;
ALTER TABLE reports.wb_marketing_campaign_nms ALTER COLUMN snapshot_hour SET NOT NULL;
DO $$
DECLARE constraint_name text;
BEGIN
  FOR constraint_name IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'reports.wb_marketing_campaign_nms'::regclass
      AND contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE reports.wb_marketing_campaign_nms DROP CONSTRAINT IF EXISTS %I', constraint_name);
  END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_marketing_campaign_nms_snapshot_hour_key
    ON reports.wb_marketing_campaign_nms (snapshot_hour, advert_id, nm_id);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaign_nms_snapshot ON reports.wb_marketing_campaign_nms(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaign_nms_snapshot_hour ON reports.wb_marketing_campaign_nms(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaign_nms_nm_id ON reports.wb_marketing_campaign_nms(nm_id);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaign_nms_advert ON reports.wb_marketing_campaign_nms(advert_id);

-- Статистика по кампаниям по дням с детализацией по nm_id (SKU) из fullstats days[].apps[].nms[]
CREATE TABLE IF NOT EXISTS reports.wb_marketing_campaign_stats_daily_nms (
    id BIGSERIAL PRIMARY KEY,
    stat_date DATE NOT NULL,
    advert_id BIGINT NOT NULL,
    nm_id BIGINT NOT NULL,
    nm_name VARCHAR(500),
    views INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    ctr DECIMAL(12, 4),
    cpc DECIMAL(12, 4),
    orders INTEGER DEFAULT 0,
    shks INTEGER DEFAULT 0,
    sum_spend DECIMAL(12, 2) DEFAULT 0,
    atbs INTEGER DEFAULT 0,
    canceled INTEGER DEFAULT 0,
    cr DECIMAL(12, 4),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stat_date, advert_id, nm_id)
);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaign_stats_daily_nms_date ON reports.wb_marketing_campaign_stats_daily_nms(stat_date);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaign_stats_daily_nms_nm_id ON reports.wb_marketing_campaign_stats_daily_nms(nm_id);
CREATE INDEX IF NOT EXISTS idx_wb_marketing_campaign_stats_daily_nms_advert ON reports.wb_marketing_campaign_stats_daily_nms(advert_id);

CREATE OR REPLACE VIEW reports.v_wb_marketing_balance_latest_snapshot AS
SELECT *
FROM reports.wb_marketing_balance
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_marketing_balance
);

CREATE OR REPLACE VIEW reports.v_wb_marketing_budget_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_marketing_budget
    GROUP BY snapshot_date
)
SELECT b.*
FROM reports.wb_marketing_budget b
JOIN latest_hours h
  ON h.snapshot_date = b.snapshot_date
 AND h.snapshot_hour = b.snapshot_hour;

CREATE OR REPLACE VIEW reports.v_wb_marketing_budget_latest_snapshot AS
SELECT *
FROM reports.wb_marketing_budget
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_marketing_budget
);

CREATE OR REPLACE VIEW reports.v_wb_marketing_campaign_nms_latest_daily AS
WITH latest_hours AS (
    SELECT snapshot_date, MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_marketing_campaign_nms
    GROUP BY snapshot_date
)
SELECT n.*
FROM reports.wb_marketing_campaign_nms n
JOIN latest_hours h
  ON h.snapshot_date = n.snapshot_date
 AND h.snapshot_hour = n.snapshot_hour;

CREATE OR REPLACE VIEW reports.v_wb_marketing_campaign_nms_latest_snapshot AS
SELECT *
FROM reports.wb_marketing_campaign_nms
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_marketing_campaign_nms
);
