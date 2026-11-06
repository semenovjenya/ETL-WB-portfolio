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
       AND c.relname = 'wb_calendar_promotions';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_calendar_promotions CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_calendar_promotions CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_calendar_promotions AS
SELECT * FROM marketing.wb_calendar_promotions;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_calendar_promotions_progress';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_calendar_promotions_progress CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_calendar_promotions_progress CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_calendar_promotions_progress AS
SELECT * FROM marketing.wb_calendar_promotions_progress;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_calendar_promotions_details';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_calendar_promotions_details CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_calendar_promotions_details CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_calendar_promotions_details AS
SELECT * FROM marketing.wb_calendar_promotions_details;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_calendar_promotions_nomenclatures';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_calendar_promotions_nomenclatures CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_calendar_promotions_nomenclatures CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_calendar_promotions_nomenclatures AS
SELECT * FROM marketing.wb_calendar_promotions_nomenclatures;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_calendar_promotions_latest_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_calendar_promotions_latest_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_calendar_promotions_latest_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_latest_daily AS
SELECT * FROM marketing.v_wb_calendar_promotions_latest_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_calendar_promotions_latest_snapshot';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_calendar_promotions_latest_snapshot CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_calendar_promotions_latest_snapshot CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_latest_snapshot AS
SELECT * FROM marketing.v_wb_calendar_promotions_latest_snapshot;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_calendar_promotions_details_latest_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_calendar_promotions_details_latest_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_calendar_promotions_details_latest_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_details_latest_daily AS
SELECT * FROM marketing.v_wb_calendar_promotions_details_latest_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_calendar_promotions_details_latest_snapshot';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_calendar_promotions_details_latest_snapshot CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_calendar_promotions_details_latest_snapshot CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_details_latest_snapshot AS
SELECT * FROM marketing.v_wb_calendar_promotions_details_latest_snapshot;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_calendar_promotions_nomenclatures_latest_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_calendar_promotions_nomenclatures_latest_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_calendar_promotions_nomenclatures_latest_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_nomenclatures_latest_daily AS
SELECT * FROM marketing.v_wb_calendar_promotions_nomenclatures_latest_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_calendar_promotions_nomenclatures_latest_snapshot';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_calendar_promotions_nomenclatures_latest_snapshot CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_calendar_promotions_nomenclatures_latest_snapshot CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_calendar_promotions_nomenclatures_latest_snapshot AS
SELECT * FROM marketing.v_wb_calendar_promotions_nomenclatures_latest_snapshot;
