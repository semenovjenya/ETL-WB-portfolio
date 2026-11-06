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
       AND c.relname = 'wb_stocks_sales_hourly';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_stocks_sales_hourly CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_stocks_sales_hourly CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_stocks_sales_hourly AS
SELECT * FROM analytics_ai.wb_stocks_sales_hourly;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_stocks_sales_hourly';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_stocks_sales_hourly CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_stocks_sales_hourly CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_stocks_sales_hourly AS
SELECT * FROM analytics_ai.v_stocks_sales_hourly;
