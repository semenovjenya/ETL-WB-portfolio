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
       AND c.relname = 'mart_ai_sales_planning';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.mart_ai_sales_planning CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.mart_ai_sales_planning CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.mart_ai_sales_planning AS
SELECT * FROM analytics_ai.mart_ai_sales_planning;
