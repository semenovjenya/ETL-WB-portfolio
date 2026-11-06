CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

CREATE SCHEMA IF NOT EXISTS analytics_ai;

-- =============================================================================
-- Quality report for analytics_ai.mart_ai_sales_planning on the latest available date
-- =============================================================================

-- [Q0] Latest mart date and source freshness
WITH latest AS (
    SELECT MAX(report_date) AS report_date
    FROM analytics_ai.mart_ai_sales_planning
)
SELECT
    l.report_date AS mart_latest_date,
    (SELECT COUNT(*) FROM analytics_ai.mart_ai_sales_planning m WHERE m.report_date = l.report_date) AS mart_rows,
    (SELECT MAX(report_date) FROM sales.wb_sales_funnel_products_daily) AS funnel_daily_max_date,
    (SELECT MAX(date_ord::date) FROM sales.wb_supplier_sales) AS supplier_sales_max_date,
    (SELECT MAX(snapshot_date) FROM supply.wb_supplier_stocks) AS supplier_stocks_max_date,
    (SELECT MAX(COALESCE(sale_dt::date, date_to)) FROM finance.wb_report_detail_daily) AS report_detail_max_date,
    (SELECT MAX(snapshot_date) FROM supply.wb_supplies) AS supplies_snapshot_max_date,
    (SELECT MAX(stat_date) FROM marketing.wb_marketing_campaign_stats_daily_nms) AS marketing_stats_max_date
FROM latest l;


-- [Q1] Coverage of critical blocks on the latest mart date
WITH latest AS (
    SELECT MAX(report_date) AS report_date
    FROM analytics_ai.mart_ai_sales_planning
)
SELECT
    COUNT(*) AS latest_rows,
    COUNT(*) FILTER (WHERE COALESCE(TRIM(brand_name), '') = '') AS blank_brand_rows,
    COUNT(*) FILTER (WHERE price_raw = 0) AS zero_price_rows,
    COUNT(*) FILTER (WHERE price_raw = 0 AND price_sale > 0) AS zero_price_with_price_sale_rows,
    COUNT(*) FILTER (WHERE revenue_net IS NOT NULL) AS finance_present_rows,
    COUNT(*) FILTER (
        WHERE revenue_gross IS NULL
          AND revenue_net IS NULL
          AND ppvz_for_pay IS NULL
          AND commission_pct IS NULL
          AND delivery_cost IS NULL
          AND storage_fee IS NULL
          AND penalty IS NULL
    ) AS finance_missing_rows,
    COUNT(*) FILTER (WHERE net_profit_per_unit IS NOT NULL) AS net_profit_present_rows,
    -- Non-null is value presence, not verified observation provenance.
    COUNT(*) FILTER (WHERE product_rating IS NOT NULL OR feedback_rating IS NOT NULL) AS ratings_present_rows,
    COUNT(*) FILTER (WHERE product_rating IS NULL AND feedback_rating IS NULL) AS ratings_missing_rows,
    COUNT(*) FILTER (WHERE (product_rating IS NULL) <> (feedback_rating IS NULL)) AS ratings_partial_rows,
    COUNT(*) FILTER (WHERE product_rating = 0 AND feedback_rating = 0) AS ratings_zero_rows,
    COUNT(product_rating) AS product_rating_present_rows,
    COUNT(*) FILTER (WHERE product_rating IS NULL) AS product_rating_missing_rows,
    COUNT(*) FILTER (WHERE product_rating = 0) AS product_rating_zero_rows,
    COUNT(feedback_rating) AS feedback_rating_present_rows,
    COUNT(*) FILTER (WHERE feedback_rating IS NULL) AS feedback_rating_missing_rows,
    COUNT(*) FILTER (WHERE feedback_rating = 0) AS feedback_rating_zero_rows,
    COUNT(*) FILTER (WHERE last_supply_date IS NOT NULL) AS supply_history_rows,
    COUNT(*) FILTER (WHERE pending_supply_qty > 0) AS pending_supply_rows,
    COUNT(*) FILTER (WHERE has_active_campaign) AS active_campaign_rows,
    COUNT(*) FILTER (WHERE is_conversion_anomaly) AS conversion_anomaly_rows
FROM analytics_ai.mart_ai_sales_planning
WHERE report_date = (SELECT report_date FROM latest);


-- [Q2] Anomaly counters on the latest mart date
WITH latest AS (
    SELECT MAX(report_date) AS report_date
    FROM analytics_ai.mart_ai_sales_planning
)
SELECT
    COUNT(*) FILTER (WHERE is_conversion_anomaly) AS conversion_anomaly_rows,
    COUNT(*) FILTER (WHERE cart_to_order_pct > 100) AS cart_to_order_gt_100_rows,
    COUNT(*) FILTER (WHERE open_to_cart_pct > 100) AS open_to_cart_gt_100_rows,
    COUNT(*) FILTER (WHERE order_to_buyout_pct > 100) AS order_to_buyout_gt_100_rows,
    COUNT(*) FILTER (WHERE price_final > price_raw) AS price_final_gt_price_raw_rows,
    COUNT(*) FILTER (WHERE price_with_spp > price_final) AS price_with_spp_gt_price_final_rows,
    COUNT(*) FILTER (WHERE buyout_count_day > 0 AND revenue_net IS NULL) AS buyouts_without_finance_rows,
    COUNT(*) FILTER (WHERE pending_supply_qty > 0 AND last_supply_date IS NULL) AS pending_without_supply_history_rows,
    COUNT(*) FILTER (WHERE reorder_flag IN ('critical', 'warning') AND last_supply_date IS NULL) AS critical_or_warning_without_supply_history_rows
FROM analytics_ai.mart_ai_sales_planning
WHERE report_date = (SELECT report_date FROM latest);


-- [Q3] Details for latest-date conversion anomalies
WITH latest AS (
    SELECT MAX(report_date) AS report_date
    FROM analytics_ai.mart_ai_sales_planning
)
SELECT
    report_date,
    nm_id,
    vendor_code,
    open_count,
    cart_count,
    order_count_day,
    buyout_count_day,
    open_to_cart_pct,
    cart_to_order_pct,
    order_to_buyout_pct
FROM analytics_ai.mart_ai_sales_planning
WHERE report_date = (SELECT report_date FROM latest)
  AND (
      open_to_cart_pct > 100
      OR cart_to_order_pct > 100
      OR order_to_buyout_pct > 100
  )
ORDER BY cart_to_order_pct DESC, open_to_cart_pct DESC, order_to_buyout_pct DESC;


-- [Q4] Details for latest-date rows with missing finance but observed buyouts
WITH latest AS (
    SELECT MAX(report_date) AS report_date
    FROM analytics_ai.mart_ai_sales_planning
)
SELECT
    report_date,
    nm_id,
    vendor_code,
    buyout_count_day,
    buyout_sum_day,
    revenue_net,
    ppvz_for_pay,
    net_profit_per_unit
FROM analytics_ai.mart_ai_sales_planning
WHERE report_date = (SELECT report_date FROM latest)
  AND buyout_count_day > 0
  AND revenue_net IS NULL
ORDER BY buyout_count_day DESC, buyout_sum_day DESC;
