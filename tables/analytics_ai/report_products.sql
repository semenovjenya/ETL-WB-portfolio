CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

CREATE SCHEMA IF NOT EXISTS analytics_ai;

-- =============================================================================
-- Отчёт по товарам на основе витрины mart_ai_sales_planning
--
-- Одна строка = один товар (nm_id) на последнюю дату витрины.
-- Сводка: идентификация, цена, воронка, продажи, остатки, финансы, возвраты.
--
-- Примеры:
--   SELECT * FROM analytics_ai.v_report_products ORDER BY buyout_sum_day DESC;
--   SELECT * FROM analytics_ai.v_report_products WHERE subject_name = '...';
--   SELECT * FROM analytics_ai.v_report_products WHERE reorder_flag IN ('critical','warning');
-- =============================================================================

CREATE OR REPLACE VIEW analytics_ai.v_report_products AS
WITH latest AS (
    SELECT MAX(report_date) AS report_date
    FROM analytics_ai.mart_ai_sales_planning
)
SELECT
    m.report_date,
    m.nm_id,
    m.vendor_code,
    m.brand_name,
    m.subject_name,

    -- Цена
    m.price_final,
    m.discount_pct,
    m.spp_pct,

    -- Воронка за день
    m.open_count,
    m.cart_count,
    m.order_count_day,
    m.order_sum_day,
    m.buyout_count_day,
    m.buyout_sum_day,
    m.open_to_cart_pct,
    m.cart_to_order_pct,
    m.order_to_buyout_pct,
    m.cancel_rate_pct,

    -- sales (неделя / месяц)
    m.sales_7d_sum,
    m.sales_28d_avg_per_day,

    -- stocks и пополнение
    m.stock_qty,
    m.days_of_stock,
    m.reorder_flag,
    m.reorder_qty_recommended,

    -- Финансы
    m.revenue_net,
    m.ppvz_for_pay,
    m.margin_pct,
    m.net_profit_per_unit,

    -- Возвраты
    m.return_count_day,
    m.return_rate_30d,
    m.net_sales_day,

    -- Реклама
    m.adv_spend_day,
    m.adv_orders_day,
    m.has_active_campaign,
    m.adv_roas,

    -- Рейтинг
    m.product_rating,
    m.feedback_rating
FROM analytics_ai.mart_ai_sales_planning m
CROSS JOIN latest l
WHERE m.report_date = l.report_date;

COMMENT ON VIEW analytics_ai.v_report_products IS
'Сводка по товарам на последнюю дату витрины: одна строка = один nm_id. Цена, воронка, продажи, остатки, финансы, возвраты, реклама.';
