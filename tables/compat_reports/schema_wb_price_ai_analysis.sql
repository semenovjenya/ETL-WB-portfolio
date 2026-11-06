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
       AND c.relname = 'wb_price_ai_seo_keywords';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_price_ai_seo_keywords CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_price_ai_seo_keywords CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_price_ai_seo_keywords AS
SELECT * FROM analytics_ai.wb_price_ai_seo_keywords;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_price_ai_competitors_raw';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_price_ai_competitors_raw CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_price_ai_competitors_raw CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_price_ai_competitors_raw AS
SELECT * FROM analytics_ai.wb_price_ai_competitors_raw;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_price_ai_competitor_features';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_price_ai_competitor_features CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_price_ai_competitor_features CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_price_ai_competitor_features AS
SELECT * FROM analytics_ai.wb_price_ai_competitor_features;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_price_ai_competitors_filtered';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_price_ai_competitors_filtered CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_price_ai_competitors_filtered CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_price_ai_competitors_filtered AS
SELECT * FROM analytics_ai.wb_price_ai_competitors_filtered;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_price_ai_competitor_relevance';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_price_ai_competitor_relevance CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_price_ai_competitor_relevance CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_price_ai_competitor_relevance AS
SELECT * FROM analytics_ai.wb_price_ai_competitor_relevance;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_price_ai_competitor_vision';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_price_ai_competitor_vision CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_price_ai_competitor_vision CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_price_ai_competitor_vision AS
SELECT * FROM analytics_ai.wb_price_ai_competitor_vision;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_price_ai_competitor_jobs';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_price_ai_competitor_jobs CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_price_ai_competitor_jobs CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_price_ai_competitor_jobs AS
SELECT * FROM analytics_ai.wb_price_ai_competitor_jobs;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_price_ai_analysis';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_price_ai_analysis CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_price_ai_analysis CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_price_ai_analysis AS
SELECT * FROM analytics_ai.wb_price_ai_analysis;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_price_ai_analysis_latest';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_price_ai_analysis_latest CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_price_ai_analysis_latest CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_price_ai_analysis_latest AS
SELECT * FROM analytics_ai.v_wb_price_ai_analysis_latest;
