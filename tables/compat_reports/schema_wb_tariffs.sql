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
       AND c.relname = 'wb_tariffs_commission';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_tariffs_commission CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_tariffs_commission CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_tariffs_commission AS
SELECT * FROM pricing.wb_tariffs_commission;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_tariffs_box';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_tariffs_box CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_tariffs_box CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_tariffs_box AS
SELECT * FROM pricing.wb_tariffs_box;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_tariffs_pallet';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_tariffs_pallet CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_tariffs_pallet CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_tariffs_pallet AS
SELECT * FROM pricing.wb_tariffs_pallet;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_tariffs_return';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_tariffs_return CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_tariffs_return CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_tariffs_return AS
SELECT * FROM pricing.wb_tariffs_return;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_tariffs_acceptance';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.wb_tariffs_acceptance CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.wb_tariffs_acceptance CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.wb_tariffs_acceptance AS
SELECT * FROM pricing.wb_tariffs_acceptance;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_commission';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_commission CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_commission CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_commission AS
SELECT * FROM pricing.v_wb_tariffs_commission;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_commission_latest';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_commission_latest CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_commission_latest CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_commission_latest AS
SELECT * FROM pricing.v_wb_tariffs_commission_latest;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_box';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_box CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_box CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_box AS
SELECT * FROM pricing.v_wb_tariffs_box;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_box_latest';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_box_latest CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_box_latest CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_box_latest AS
SELECT * FROM pricing.v_wb_tariffs_box_latest;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_pallet';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_pallet CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_pallet CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_pallet AS
SELECT * FROM pricing.v_wb_tariffs_pallet;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_pallet_latest';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_pallet_latest CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_pallet_latest CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_pallet_latest AS
SELECT * FROM pricing.v_wb_tariffs_pallet_latest;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_return';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_return CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_return CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_return AS
SELECT * FROM pricing.v_wb_tariffs_return;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_return_latest';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_return_latest CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_return_latest CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_return_latest AS
SELECT * FROM pricing.v_wb_tariffs_return_latest;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_acceptance';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_acceptance CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_acceptance CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_acceptance AS
SELECT * FROM pricing.v_wb_tariffs_acceptance;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'v_wb_tariffs_acceptance_latest';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.v_wb_tariffs_acceptance_latest CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.v_wb_tariffs_acceptance_latest CASCADE';
    END IF;
END $$;
CREATE OR REPLACE VIEW reports.v_wb_tariffs_acceptance_latest AS
SELECT * FROM pricing.v_wb_tariffs_acceptance_latest;
