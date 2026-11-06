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
       AND c.relname = 'wb_profit_calculator_scenarios';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_profit_calculator_scenarios CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_profit_calculator_scenarios CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_profit_calculator_scenarios AS
SELECT * FROM finance.wb_profit_calculator_scenarios;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_profit_calculator_results_source';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_profit_calculator_results_source CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_profit_calculator_results_source CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_profit_calculator_results_source AS
SELECT * FROM finance.v_wb_profit_calculator_results_source;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_profit_calculator_results';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_profit_calculator_results CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_profit_calculator_results CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_profit_calculator_results AS
SELECT * FROM finance.wb_profit_calculator_results;

DROP FUNCTION IF EXISTS reports.refresh_wb_profit_calculator_results() CASCADE;
CREATE OR REPLACE FUNCTION reports.refresh_wb_profit_calculator_results()
RETURNS BIGINT
LANGUAGE sql
AS $$
    SELECT finance.refresh_wb_profit_calculator_results()
$$;

DROP FUNCTION IF EXISTS reports.sync_wb_profit_calculator_scenarios_from_stocks() CASCADE;
CREATE OR REPLACE FUNCTION reports.sync_wb_profit_calculator_scenarios_from_stocks()
RETURNS BIGINT
LANGUAGE sql
AS $$
    SELECT finance.sync_wb_profit_calculator_scenarios_from_stocks()
$$;

DROP FUNCTION IF EXISTS reports.sync_wb_profit_calculator_scenarios_from_sku_ai_analysis() CASCADE;
CREATE OR REPLACE FUNCTION reports.sync_wb_profit_calculator_scenarios_from_sku_ai_analysis()
RETURNS BIGINT
LANGUAGE sql
AS $$
    SELECT finance.sync_wb_profit_calculator_scenarios_from_sku_ai_analysis()
$$;

DROP FUNCTION IF EXISTS reports.seed_wb_profit_calculator_scenarios(INTEGER) CASCADE;
CREATE OR REPLACE FUNCTION reports.seed_wb_profit_calculator_scenarios(limit_rows INTEGER DEFAULT 50)
RETURNS BIGINT
LANGUAGE sql
AS $$
    SELECT finance.seed_wb_profit_calculator_scenarios(limit_rows)
$$;
