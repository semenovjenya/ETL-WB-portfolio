CREATE SCHEMA IF NOT EXISTS reports;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_normquery_clusters';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_normquery_clusters CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_normquery_clusters CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_normquery_clusters AS
SELECT * FROM marketing.wb_marketing_normquery_clusters;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_normquery_bids';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_normquery_bids CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_normquery_bids CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_normquery_bids AS
SELECT * FROM marketing.wb_marketing_normquery_bids;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_normquery_minus';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_normquery_minus CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_normquery_minus CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_normquery_minus AS
SELECT * FROM marketing.wb_marketing_normquery_minus;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_normquery_stats';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_normquery_stats CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_normquery_stats CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_normquery_stats AS
SELECT * FROM marketing.wb_marketing_normquery_stats;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_normquery_stats_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_normquery_stats_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_normquery_stats_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_normquery_stats_daily AS
SELECT * FROM marketing.wb_marketing_normquery_stats_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_upd';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_upd CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_upd CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_upd AS
SELECT * FROM marketing.wb_marketing_upd;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_balance';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_balance CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_balance CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_balance AS
SELECT * FROM marketing.wb_marketing_balance;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_budget';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_budget CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_budget CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_budget AS
SELECT * FROM marketing.wb_marketing_budget;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_campaign_stats_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_campaign_stats_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_campaign_stats_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_campaign_stats_daily AS
SELECT * FROM marketing.wb_marketing_campaign_stats_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_campaign_nms';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_campaign_nms CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_campaign_nms CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_campaign_nms AS
SELECT * FROM marketing.wb_marketing_campaign_nms;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_marketing_campaign_stats_daily_nms';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_marketing_campaign_stats_daily_nms CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_marketing_campaign_stats_daily_nms CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_marketing_campaign_stats_daily_nms AS
SELECT * FROM marketing.wb_marketing_campaign_stats_daily_nms;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_marketing_balance_latest_snapshot';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_marketing_balance_latest_snapshot CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_marketing_balance_latest_snapshot CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_marketing_balance_latest_snapshot AS
SELECT * FROM marketing.v_wb_marketing_balance_latest_snapshot;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_marketing_budget_latest_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_marketing_budget_latest_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_marketing_budget_latest_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_marketing_budget_latest_daily AS
SELECT * FROM marketing.v_wb_marketing_budget_latest_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_marketing_budget_latest_snapshot';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_marketing_budget_latest_snapshot CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_marketing_budget_latest_snapshot CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_marketing_budget_latest_snapshot AS
SELECT * FROM marketing.v_wb_marketing_budget_latest_snapshot;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_marketing_campaign_nms_latest_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_marketing_campaign_nms_latest_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_marketing_campaign_nms_latest_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_marketing_campaign_nms_latest_daily AS
SELECT * FROM marketing.v_wb_marketing_campaign_nms_latest_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_marketing_campaign_nms_latest_snapshot';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_marketing_campaign_nms_latest_snapshot CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_marketing_campaign_nms_latest_snapshot CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_marketing_campaign_nms_latest_snapshot AS
SELECT * FROM marketing.v_wb_marketing_campaign_nms_latest_snapshot;
