-- =============================================================================
-- Отчёт по остаткам и пополнению на основе витрины mart_ai_sales_planning
--
-- Представление: один срез на последнюю доступную дату витрины (report_date).
-- Одна строка = один nm_id. Используйте для списков пополнения и мониторинга запасов.
--
-- Примеры:
--   -- все товары с критическим/предупреждающим уровнем:
--   SELECT * FROM reports.v_report_stocks_reorder
--   WHERE reorder_flag IN ('critical', 'warning')
--   ORDER BY days_of_stock ASC NULLS FIRST;
--
--   -- по категории:
--   SELECT * FROM reports.v_report_stocks_reorder
--   WHERE subject_name = '...'
--   ORDER BY reorder_qty_recommended DESC;
--
--   -- только товары на пополнение (критичные и предупреждение):
--   SELECT * FROM reports.v_report_stocks_reorder_alert
--   ORDER BY days_of_stock ASC NULLS FIRST, reorder_qty_recommended DESC;
-- =============================================================================

CREATE OR REPLACE VIEW reports.v_report_stocks_reorder AS
WITH latest AS (
    SELECT MAX(report_date) AS report_date
    FROM reports.mart_ai_sales_planning
)
SELECT
    m.report_date,
    m.nm_id,
    m.vendor_code,
    m.brand_name,
    m.subject_name,

    -- stocks
    m.stock_qty,
    m.stock_qty_full,
    m.in_way_to_client,
    m.in_way_from_client,
    m.stock_week_avg,

    -- sales (контекст)
    m.sales_7d_sum,
    m.sales_28d_avg_per_day,

    -- Оборачиваемость и запасы
    m.days_of_stock,
    m.stock_turnover_weekly,
    m.reorder_flag,

    -- Рекомендация по пополнению
    m.reorder_qty_recommended,

    -- supplies
    m.last_supply_date,
    m.days_since_last_supply,
    m.pending_supply_qty,
    m.avg_supply_interval_days
FROM reports.mart_ai_sales_planning m
CROSS JOIN latest l
WHERE m.report_date = l.report_date;

COMMENT ON VIEW reports.v_report_stocks_reorder IS
'Срез по остаткам и пополнению на последнюю дату витрины mart_ai_sales_planning. Одна строка = один nm_id. reorder_flag: no_sales | critical (<14 дн.) | warning (<30 дн.) | ok.';

-- Список товаров, требующих внимания (критический и предупреждающий уровень запаса)
CREATE OR REPLACE VIEW reports.v_report_stocks_reorder_alert AS
SELECT *
FROM reports.v_report_stocks_reorder
WHERE reorder_flag IN ('critical', 'warning');

COMMENT ON VIEW reports.v_report_stocks_reorder_alert IS
'Товары с reorder_flag critical или warning — для быстрого списка на пополнение.';
