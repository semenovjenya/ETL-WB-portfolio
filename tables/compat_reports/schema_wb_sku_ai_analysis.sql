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
       AND c.relname = 'wb_sku_ai_analysis';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_sku_ai_analysis CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_sku_ai_analysis CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_sku_ai_analysis AS
SELECT * FROM analytics_ai.wb_sku_ai_analysis;
