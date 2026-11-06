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
       AND c.relname = 'wb_search_query_api_requests';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_search_query_api_requests CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_search_query_api_requests CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_search_query_api_requests AS
SELECT * FROM marketing.wb_search_query_api_requests;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_search_query_report_overview';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_search_query_report_overview CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_search_query_report_overview CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_search_query_report_overview AS
SELECT * FROM marketing.wb_search_query_report_overview;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_search_query_report_groups';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_search_query_report_groups CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_search_query_report_groups CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_search_query_report_groups AS
SELECT * FROM marketing.wb_search_query_report_groups;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_search_query_groups';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_search_query_groups CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_search_query_groups CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_search_query_groups AS
SELECT * FROM marketing.wb_search_query_groups;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_search_query_details';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_search_query_details CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_search_query_details CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_search_query_details AS
SELECT * FROM marketing.wb_search_query_details;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_search_query_texts';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_search_query_texts CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_search_query_texts CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_search_query_texts AS
SELECT * FROM marketing.wb_search_query_texts;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_search_query_orders_total_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_search_query_orders_total_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_search_query_orders_total_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_search_query_orders_total_daily AS
SELECT * FROM marketing.wb_search_query_orders_total_daily;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_search_query_orders_text_daily';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_search_query_orders_text_daily CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_search_query_orders_text_daily CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_search_query_orders_text_daily AS
SELECT * FROM marketing.wb_search_query_orders_text_daily;
