-- Удаление таблиц воронки, которые не используются (оставляем только wb_sales_funnel_products_daily).
-- Выполнить вручную в БД: psql ... -f drop_sales_funnel_extra_tables.sql

DROP TABLE IF EXISTS reports.wb_sales_funnel_products_weekly CASCADE;
DROP TABLE IF EXISTS reports.wb_sales_funnel_progress CASCADE;
DROP TABLE IF EXISTS reports.wb_sales_funnel_products CASCADE;
