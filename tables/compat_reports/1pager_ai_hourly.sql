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
       AND c.relname = 'wb_1pager_ai_hourly_target';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_1pager_ai_hourly_target CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_1pager_ai_hourly_target CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_1pager_ai_hourly_target AS
SELECT * FROM analytics_ai.wb_1pager_ai_hourly_target;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_1pager_ai_hourly_source';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_1pager_ai_hourly_source CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_1pager_ai_hourly_source CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_1pager_ai_hourly_source AS
SELECT * FROM analytics_ai.v_1pager_ai_hourly_source;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_1pager_ai_hourly';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_1pager_ai_hourly CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_1pager_ai_hourly CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_1pager_ai_hourly AS
SELECT * FROM analytics_ai.wb_1pager_ai_hourly;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_1pager_ai_hourly';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_1pager_ai_hourly CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_1pager_ai_hourly CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_1pager_ai_hourly AS
SELECT * FROM analytics_ai.v_1pager_ai_hourly;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_1pager_ai';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_1pager_ai CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_1pager_ai CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_1pager_ai AS
SELECT * FROM analytics_ai.v_1pager_ai;
