DO $$
DECLARE
    obj record;
BEGIN
    FOR obj IN
        SELECT table_schema, table_name
        FROM information_schema.views
        WHERE table_schema = 'reports'
          AND table_name NOT ILIKE '%1pager%'
        ORDER BY table_name
    LOOP
        EXECUTE format('DROP VIEW IF EXISTS %I.%I CASCADE', obj.table_schema, obj.table_name);
    END LOOP;
END $$;
