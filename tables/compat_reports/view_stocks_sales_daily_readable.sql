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
       AND c.relname = 'v_stocks_sales_daily_readable';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_stocks_sales_daily_readable CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_stocks_sales_daily_readable CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_stocks_sales_daily_readable AS
SELECT * FROM analytics_ai.v_stocks_sales_daily_readable;
