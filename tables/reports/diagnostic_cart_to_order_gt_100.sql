-- =============================================================================
-- Diagnostic: cart_to_order_pct > 100 in mart_ai_sales_planning
-- =============================================================================

-- [D0] Latest mart rows with cart_to_order_pct > 100
WITH latest AS (
    SELECT MAX(report_date) AS report_date
    FROM reports.mart_ai_sales_planning
)
SELECT
    m.report_date,
    m.nm_id,
    m.vendor_code,
    m.cart_count,
    m.order_count_day,
    m.cart_to_order_pct,
    s.cart_count AS src_cart_count,
    s.order_count AS src_order_count,
    s.cart_to_order_conversion AS src_cart_to_order_pct,
    ROUND(s.order_count::numeric / NULLIF(s.cart_count, 0) * 100, 2) AS ratio_from_counts_pct
FROM reports.mart_ai_sales_planning m
LEFT JOIN reports.wb_sales_funnel_products_daily s
    ON s.report_date = m.report_date
   AND s.nm_id = m.nm_id
WHERE m.report_date = (SELECT report_date FROM latest)
  AND m.cart_to_order_pct > 100
ORDER BY m.cart_to_order_pct DESC;


-- [D1] Full raw source row for the anomaly observed on 2026-03-07
SELECT
    report_date,
    nm_id,
    vendor_code,
    brand_name,
    subject_name,
    open_count,
    cart_count,
    order_count,
    order_sum,
    buyout_count,
    buyout_sum,
    add_to_cart_conversion,
    cart_to_order_conversion,
    buyout_percent
FROM reports.wb_sales_funnel_products_daily
WHERE report_date = DATE '2026-03-07'
  AND nm_id = 175638539;


-- [D2] Sanity check: all source rows on the latest mart date where source conversion > 100
WITH latest AS (
    SELECT MAX(report_date) AS report_date
    FROM reports.mart_ai_sales_planning
)
SELECT
    s.report_date,
    s.nm_id,
    s.vendor_code,
    s.cart_count,
    s.order_count,
    s.cart_to_order_conversion,
    ROUND(s.order_count::numeric / NULLIF(s.cart_count, 0) * 100, 2) AS ratio_from_counts_pct
FROM reports.wb_sales_funnel_products_daily s
WHERE s.report_date = (SELECT report_date FROM latest)
  AND s.cart_to_order_conversion > 100
ORDER BY s.cart_to_order_conversion DESC;
