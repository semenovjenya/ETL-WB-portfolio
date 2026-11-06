CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

-- =============================================================================
-- 1pager ML views
--
-- Source: analytics_ai.v_1pager_daily_source
-- Grain: one row per nm_id per report_date
-- Output:
--   * analytics_ai.v_1pager_ml_train - full completed history for model training
--   * analytics_ai.v_1pager_ml       - latest five completed report dates for live scoring
-- =============================================================================

DROP VIEW IF EXISTS analytics_ai.v_1pager_ml;
DROP VIEW IF EXISTS analytics_ai.v_1pager_ml_train;

CREATE VIEW analytics_ai.v_1pager_ml_train AS
WITH marketing_daily AS (
    SELECT
        stat_date                                               AS report_date,
        nm_id,
        SUM(COALESCE(views, 0))                                 AS marketing_views_day,
        SUM(COALESCE(clicks, 0))                                AS marketing_clicks_day,
        SUM(COALESCE(orders, 0))                                AS marketing_orders_day,
        SUM(COALESCE(atbs, 0))                                  AS marketing_atbs_day,
        SUM(COALESCE(canceled, 0))                              AS marketing_canceled_day,
        ROUND(SUM(COALESCE(sum_spend, 0))::numeric, 2)          AS marketing_spend_day,
        ROUND(
            SUM(COALESCE(clicks, 0))::numeric
            / NULLIF(SUM(COALESCE(views, 0)), 0) * 100,
        2)                                                      AS marketing_ctr_day,
        ROUND(
            SUM(COALESCE(sum_spend, 0))::numeric
            / NULLIF(SUM(COALESCE(clicks, 0)), 0),
        2)                                                      AS marketing_cpc_day,
        ROUND(
            SUM(COALESCE(orders, 0))::numeric
            / NULLIF(SUM(COALESCE(clicks, 0)), 0) * 100,
        2)                                                      AS marketing_cr_day
    FROM marketing.wb_marketing_campaign_stats_daily_nms
    GROUP BY stat_date, nm_id
),
base AS (
    SELECT
        m.report_date,
        m.nm_id                                                AS id,
        COALESCE(m.vendor_code, '')                            AS sku,

        CASE WHEN COALESCE(m.stock_qty, 0) > 0 THEN 1 ELSE 0 END
                                                               AS in_stock_flag,
        CASE WHEN m.target_buyouts_next_7d IS NOT NULL THEN 1 ELSE 0 END
                                                               AS target_ready_7d_flag,
        CASE WHEN SUM(m.buyout_count_day) OVER (
                     PARTITION BY m.nm_id
                     ORDER BY m.report_date
                     RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                               AND INTERVAL '14 days' FOLLOWING
                 ) IS NOT NULL THEN 1 ELSE 0 END               AS target_ready_14d_flag,
        CASE WHEN SUM(m.buyout_count_day) OVER (
                     PARTITION BY m.nm_id
                     ORDER BY m.report_date
                     RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                               AND INTERVAL '21 days' FOLLOWING
                 ) IS NOT NULL THEN 1 ELSE 0 END               AS target_ready_21d_flag,
        CASE WHEN SUM(m.buyout_count_day) OVER (
                     PARTITION BY m.nm_id
                     ORDER BY m.report_date
                     RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                               AND INTERVAL '31 days' FOLLOWING
                 ) IS NOT NULL THEN 1 ELSE 0 END               AS target_ready_31d_flag,

        COALESCE(m.stock_qty, 0)                               AS qty_on_stock,
        COALESCE(m.stock_qty_full, 0)                          AS qty_on_stock_full,
        COALESCE(m.in_way_to_client, 0)                        AS in_way_to_client,
        COALESCE(m.in_way_from_client, 0)                      AS in_way_from_client,
        COALESCE(m.stock_week_avg, 0)                          AS stock_week_avg,
        COALESCE(m.days_of_stock, 0)                           AS days_of_stock,
        COALESCE(m.stock_turnover_weekly, 0)                   AS stock_turnover_weekly,
        COALESCE(m.last_supply_date, m.report_date - 45)       AS last_supply_date,
        COALESCE(m.days_since_last_supply, 45)                 AS days_since_last_supply,
        COALESCE(m.pending_supply_qty, 0)                      AS pending_supply_qty,
        COALESCE(m.avg_supply_interval_days, 0)                AS avg_supply_interval_days,
        COALESCE(m.reorder_qty_recommended, 0)                 AS reorder_qty_recommended,

        COALESCE(m.price_raw, 0)                               AS price_before_discount,
        COALESCE(m.price_final, 0)                             AS price_after_discount,
        COALESCE(m.discount_pct, 0)                            AS discount_pct,
        COALESCE(m.spp_pct, 0)                                 AS spp_pct,
        COALESCE(m.price_with_spp, 0)                          AS price_with_spp,
        COALESCE(m.price_change_pct, 0)                        AS price_change_pct,
        COALESCE(m.revenue_gross, 0)                           AS revenue_gross,
        COALESCE(m.revenue_net, 0)                             AS revenue_net,
        COALESCE(m.ppvz_for_pay, 0)                            AS ppvz_for_pay,
        COALESCE(m.commission_pct, 0)                          AS commission_pct,
        COALESCE(m.delivery_cost, 0)                           AS delivery_cost,
        COALESCE(m.storage_fee, 0)                             AS storage_fee,
        COALESCE(m.penalty, 0)                                 AS penalty,
        COALESCE(m.net_profit_per_unit, 0)                     AS net_profit_per_unit,
        COALESCE(m.elasticity_rolling_4w, 0)                   AS elasticity_rolling_4w,

        COALESCE(m.order_count_day, 0)                         AS orders_1d,
        COALESCE(m.buyout_count_day, 0)                        AS buyouts_1d,
        COALESCE(m.sales_7d_sum, 0)                            AS buyouts_7d,
        COALESCE(m.sales_28d_avg_per_day, 0)                   AS buyouts_28d_avg_per_day,
        COALESCE(m.sales_lag_1w, 0)                            AS sales_lag_1w,
        COALESCE(m.sales_lag_2w, 0)                            AS sales_lag_2w,
        COALESCE(m.sales_lag_4w, 0)                            AS sales_lag_4w,
        COALESCE(m.sales_rolling_4w_avg, 0)                    AS sales_rolling_4w_avg,
        COALESCE(m.sales_rolling_4w_std, 0)                    AS sales_rolling_4w_std,
        COALESCE(m.order_change_pct, 0)                        AS order_change_pct,
        COALESCE(m.yoy_orders_change_pct, 0)                   AS yoy_orders_change_pct,

        COALESCE(m.open_count, 0)                              AS open_count,
        COALESCE(m.open_to_cart_pct, 0)                        AS open_to_cart_pct,
        COALESCE(m.cart_to_order_pct, 0)                       AS cart_to_order_pct,
        COALESCE(m.open_count_lag_1w, 0)                       AS open_count_lag_1w,
        COALESCE(m.open_count_rolling_7d, 0)                   AS open_count_rolling_7d,
        m.product_rating                          AS product_rating,
        m.feedback_rating                         AS feedback_rating,

        CASE WHEN COALESCE(m.is_promo_period, false) THEN 1 ELSE 0 END
                                                               AS in_promo_flag,
        COALESCE(m.days_to_next_promo, 9999)                   AS days_to_next_promo,
        COALESCE(m.week_of_year, 0)                            AS week_of_year,
        COALESCE(m.month_num, 0)                               AS month_num,
        CASE WHEN COALESCE(m.is_weekend, false) THEN 1 ELSE 0 END
                                                               AS is_weekend_flag,

        COALESCE(m.return_count_day, 0)                        AS return_count_day,
        COALESCE(m.return_sum_day, 0)                          AS return_sum_day,
        COALESCE(m.net_sales_day, 0)                           AS net_sales_day,
        COALESCE(m.return_rate_30d, 0)                         AS return_rate_30d,

        CASE WHEN COALESCE(m.has_active_campaign, false) THEN 1 ELSE 0 END
                                                               AS has_active_campaign_flag,
        COALESCE(m.adv_spend_day, 0)                           AS adv_spend_day,
        COALESCE(m.adv_orders_day, 0)                          AS adv_orders_day,
        COALESCE(m.adv_cpo, 0)                                 AS adv_cpo,
        COALESCE(m.adv_roas, 0)                                AS adv_roas,
        COALESCE(md.marketing_views_day, 0)                    AS marketing_views_day,
        COALESCE(md.marketing_clicks_day, 0)                   AS marketing_clicks_day,
        COALESCE(md.marketing_orders_day, 0)                   AS marketing_orders_day,
        COALESCE(md.marketing_atbs_day, 0)                     AS marketing_atbs_day,
        COALESCE(md.marketing_canceled_day, 0)                 AS marketing_canceled_day,
        COALESCE(md.marketing_spend_day, 0)                    AS marketing_spend_day,
        COALESCE(md.marketing_ctr_day, 0)                      AS marketing_ctr_day,
        COALESCE(md.marketing_cpc_day, 0)                      AS marketing_cpc_day,
        COALESCE(md.marketing_cr_day, 0)                       AS marketing_cr_day
    FROM analytics_ai.v_1pager_daily_source m
    LEFT JOIN marketing_daily md
        ON md.report_date = m.report_date
       AND md.nm_id = m.nm_id
),
featured AS (
    SELECT
        b.*,

        SUM(b.marketing_views_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_views_7d,
        SUM(b.marketing_views_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_views_14d,
        SUM(b.marketing_views_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_views_21d,
        SUM(b.marketing_views_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_views_31d,

        SUM(b.marketing_clicks_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_clicks_7d,
        SUM(b.marketing_clicks_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_clicks_14d,
        SUM(b.marketing_clicks_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_clicks_21d,
        SUM(b.marketing_clicks_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_clicks_31d,

        SUM(b.marketing_orders_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_orders_7d,
        SUM(b.marketing_orders_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_orders_14d,
        SUM(b.marketing_orders_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_orders_21d,
        SUM(b.marketing_orders_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_orders_31d,

        ROUND(SUM(b.marketing_spend_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )::numeric, 2)                                         AS marketing_spend_7d,
        ROUND(SUM(b.marketing_spend_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )::numeric, 2)                                         AS marketing_spend_14d,
        ROUND(SUM(b.marketing_spend_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )::numeric, 2)                                         AS marketing_spend_21d,
        ROUND(SUM(b.marketing_spend_day) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )::numeric, 2)                                         AS marketing_spend_31d,

        LEAD(b.orders_1d, 1) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
        )                                                      AS target_orders_next_1d,
        LEAD(b.buyouts_1d, 1) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
        )                                                      AS target_buyouts_next_1d,
        SUM(b.orders_1d) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                      AND INTERVAL '7 days' FOLLOWING
        )                                                      AS target_orders_next_7d,
        SUM(b.buyouts_1d) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                      AND INTERVAL '7 days' FOLLOWING
        )                                                      AS target_buyouts_next_7d,
        SUM(b.orders_1d) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                      AND INTERVAL '14 days' FOLLOWING
        )                                                      AS target_orders_next_14d,
        SUM(b.buyouts_1d) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                      AND INTERVAL '14 days' FOLLOWING
        )                                                      AS target_buyouts_next_14d,
        SUM(b.orders_1d) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                      AND INTERVAL '21 days' FOLLOWING
        )                                                      AS target_orders_next_21d,
        SUM(b.buyouts_1d) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                      AND INTERVAL '21 days' FOLLOWING
        )                                                      AS target_buyouts_next_21d,
        SUM(b.orders_1d) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                      AND INTERVAL '31 days' FOLLOWING
        )                                                      AS target_orders_next_31d,
        SUM(b.buyouts_1d) OVER (
            PARTITION BY b.id
            ORDER BY b.report_date
            RANGE BETWEEN INTERVAL '1 day' FOLLOWING
                      AND INTERVAL '31 days' FOLLOWING
        )                                                      AS target_buyouts_next_31d
    FROM base b
)
SELECT
    report_date,
    id,
    sku,
    in_stock_flag,
    target_ready_7d_flag,
    target_ready_14d_flag,
    target_ready_21d_flag,
    target_ready_31d_flag,
    qty_on_stock,
    qty_on_stock_full,
    in_way_to_client,
    in_way_from_client,
    stock_week_avg,
    days_of_stock,
    stock_turnover_weekly,
    last_supply_date,
    days_since_last_supply,
    pending_supply_qty,
    avg_supply_interval_days,
    reorder_qty_recommended,
    price_before_discount,
    price_after_discount,
    discount_pct,
    spp_pct,
    price_with_spp,
    price_change_pct,
    revenue_gross,
    revenue_net,
    ppvz_for_pay,
    commission_pct,
    delivery_cost,
    storage_fee,
    penalty,
    net_profit_per_unit,
    elasticity_rolling_4w,
    orders_1d,
    buyouts_1d,
    buyouts_7d,
    buyouts_28d_avg_per_day,
    sales_lag_1w,
    sales_lag_2w,
    sales_lag_4w,
    sales_rolling_4w_avg,
    sales_rolling_4w_std,
    order_change_pct,
    yoy_orders_change_pct,
    open_count,
    open_to_cart_pct,
    cart_to_order_pct,
    open_count_lag_1w,
    open_count_rolling_7d,
    product_rating,
    feedback_rating,
    in_promo_flag,
    days_to_next_promo,
    week_of_year,
    month_num,
    is_weekend_flag,
    return_count_day,
    return_sum_day,
    net_sales_day,
    return_rate_30d,
    has_active_campaign_flag,
    adv_spend_day,
    adv_orders_day,
    adv_cpo,
    adv_roas,
    marketing_views_day,
    marketing_clicks_day,
    marketing_orders_day,
    marketing_atbs_day,
    marketing_canceled_day,
    marketing_spend_day,
    marketing_ctr_day,
    marketing_cpc_day,
    marketing_cr_day,
    marketing_views_7d,
    marketing_views_14d,
    marketing_views_21d,
    marketing_views_31d,
    marketing_clicks_7d,
    marketing_clicks_14d,
    marketing_clicks_21d,
    marketing_clicks_31d,
    marketing_orders_7d,
    marketing_orders_14d,
    marketing_orders_21d,
    marketing_orders_31d,
    marketing_spend_7d,
    marketing_spend_14d,
    marketing_spend_21d,
    marketing_spend_31d,
    target_orders_next_1d,
    target_buyouts_next_1d,
    target_orders_next_7d,
    target_buyouts_next_7d,
    target_orders_next_14d,
    target_buyouts_next_14d,
    target_orders_next_21d,
    target_buyouts_next_21d,
    target_orders_next_31d,
    target_buyouts_next_31d
FROM featured
WHERE report_date < timezone('Europe/Moscow', now())::date
  AND (
      COALESCE(qty_on_stock, 0) > 0
      OR COALESCE(buyouts_1d, 0) > 0
      OR COALESCE(orders_1d, 0) > 0
      OR COALESCE(buyouts_7d, 0) > 0
      OR COALESCE(pending_supply_qty, 0) > 0
  )
ORDER BY report_date DESC, id;

COMMENT ON VIEW analytics_ai.v_1pager_ml_train IS
'Full completed-history ML feature layer from v_1pager_daily_source. Keeps the same feature and target logic as the serving 1pager_ml view, but without truncating to the latest five dates. Intended for model training and backtesting.';

CREATE VIEW analytics_ai.v_1pager_ml AS
WITH latest_dates AS (
    SELECT report_date
    FROM (
        SELECT DISTINCT report_date
        FROM analytics_ai.v_1pager_ml_train
        ORDER BY report_date DESC
        LIMIT 5
    ) latest
)
SELECT *
FROM analytics_ai.v_1pager_ml_train
WHERE report_date IN (SELECT report_date FROM latest_dates)
ORDER BY report_date DESC, id;

COMMENT ON VIEW analytics_ai.v_1pager_ml IS
'Live ML-ready feature base from v_1pager_ml_train. Keeps only the latest five completed report_date values for daily scoring and preserves forward-looking target columns for monitoring and offline validation.';
