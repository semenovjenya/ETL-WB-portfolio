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
       AND c.relname = 'wb_sales_funnel_products';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_sales_funnel_products CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_sales_funnel_products CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_sales_funnel_products AS
SELECT * FROM sales.wb_sales_funnel_products;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_sales_funnel_progress';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_sales_funnel_progress CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_sales_funnel_progress CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_sales_funnel_progress AS
SELECT * FROM sales.wb_sales_funnel_progress;
