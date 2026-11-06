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
       AND c.relname = 'wb_supplies';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_supplies CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_supplies CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_supplies AS
SELECT * FROM supply.wb_supplies;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_supplies_goods';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_supplies_goods CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_supplies_goods CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_supplies_goods AS
SELECT * FROM supply.wb_supplies_goods;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_supplies_progress';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_supplies_progress CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_supplies_progress CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_supplies_progress AS
SELECT * FROM supply.wb_supplies_progress;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_supplies_latest_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_supplies_latest_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_supplies_latest_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_supplies_latest_daily AS
SELECT * FROM supply.v_wb_supplies_latest_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_supplies_latest_snapshot';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_supplies_latest_snapshot CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_supplies_latest_snapshot CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_supplies_latest_snapshot AS
SELECT * FROM supply.v_wb_supplies_latest_snapshot;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_supplies_goods_latest_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_supplies_goods_latest_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_supplies_goods_latest_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_supplies_goods_latest_daily AS
SELECT * FROM supply.v_wb_supplies_goods_latest_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_supplies_goods_latest_snapshot';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_supplies_goods_latest_snapshot CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_supplies_goods_latest_snapshot CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_supplies_goods_latest_snapshot AS
SELECT * FROM supply.v_wb_supplies_goods_latest_snapshot;
