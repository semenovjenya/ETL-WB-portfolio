-- Диагностика пропусков для nm_id=175562457
-- Запуск: psql "$PG_DSN" -f tables/reports/diagnostic_nm_175562457.sql

\echo '=== [1] Воронка: wb_sales_funnel_products_daily ==='
SELECT
    'wb_sales_funnel_products_daily'  AS source_table,
    COUNT(*)                          AS total_rows,
    MIN(report_date)                  AS first_date,
    MAX(report_date)                  AS last_date,
    COUNT(*) FILTER (WHERE order_count > 0)  AS days_with_orders
FROM reports.wb_sales_funnel_products_daily
WHERE nm_id = 175562457;

\echo ''
\echo '=== [2] sales: wb_supplier_sales ==='
SELECT
    'wb_supplier_sales'               AS source_table,
    COUNT(*)                          AS total_rows,
    MIN(date_ord::date)               AS first_date,
    MAX(date_ord::date)               AS last_date
FROM reports.wb_supplier_sales
WHERE nm_id = 175562457;

\echo ''
\echo '=== [3] Финансовый отчёт: wb_report_detail_daily ==='
SELECT
    'wb_report_detail_daily'          AS source_table,
    COUNT(*)                          AS total_rows,
    MIN(sale_dt::date)                AS first_date,
    MAX(sale_dt::date)                AS last_date,
    COUNT(*) FILTER (WHERE doc_type_name ILIKE '%возврат%') AS return_rows
FROM reports.wb_report_detail_daily
WHERE nm_id = 175562457;

\echo ''
\echo '=== [4] stocks: wb_supplier_stocks ==='
SELECT
    'wb_supplier_stocks'              AS source_table,
    COUNT(*)                          AS total_rows,
    MIN(snapshot_date)                AS first_date,
    MAX(snapshot_date)                AS last_date
FROM reports.wb_supplier_stocks
WHERE nm_id = 175562457;

\echo ''
\echo '=== [5] supplies: wb_supplies_goods + wb_supplies ==='
SELECT
    'wb_supplies_goods + wb_supplies' AS source_table,
    COUNT(*)                          AS total_rows,
    COUNT(*) FILTER (WHERE s.fact_date IS NOT NULL) AS completed_supplies,
    COUNT(*) FILTER (WHERE s.fact_date IS NULL)     AS pending_supplies
FROM reports.wb_supplies_goods sg
JOIN reports.wb_supplies s ON s.supply_id = sg.supply_id
WHERE sg.nm_id = 175562457;

\echo ''
\echo '=== [6] Реклама: wb_marketing_campaign_stats_daily_nms ==='
SELECT
    'wb_marketing_campaign_stats_daily_nms' AS source_table,
    COUNT(*)                          AS total_rows,
    MIN(stat_date)                    AS first_date,
    MAX(stat_date)                    AS last_date
FROM reports.wb_marketing_campaign_stats_daily_nms
WHERE nm_id = 175562457;

\echo ''
\echo '=== [7] Витрина: mart_ai_sales_planning для nm_id ==='
SELECT
    COUNT(*)                AS total_rows_in_mart,
    MIN(report_date)        AS mart_first_date,
    MAX(report_date)        AS mart_last_date
FROM reports.mart_ai_sales_planning
WHERE nm_id = 175562457;

\echo ''
\echo '=== [8] Строка на 2026-03-03 в витрине (target_date_exists) ==='
SELECT report_date AS target_date_exists
FROM reports.mart_ai_sales_planning
WHERE nm_id = 175562457 AND report_date = '2026-03-03';
