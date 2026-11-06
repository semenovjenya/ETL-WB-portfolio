-- =============================================================================
-- 1pager AI view
--
-- Source: reports.mart_ai_sales_planning
-- Grain: one row per nm_id per report_date
-- Output: full accumulated history by completed report_date
--
-- Filters:
--   * excludes the current incomplete Moscow report_date
--   * stock_qty > 0, or recent sales/orders activity, or open supply
--   * sold-out but recently active SKUs are kept in the export
--
-- Notes:
--   * report_date is preserved so consumers can query any completed historical day
--   * current Moscow day is excluded because it may be incomplete
--   * sku is vendor_code from the base mart
--   * supply_qty is pending_supply_qty from open supplies
-- =============================================================================

CREATE OR REPLACE VIEW reports.v_1pager_ai_daily AS
WITH latest_complete_report_date AS (
    SELECT MAX(m.report_date) AS report_date
    FROM reports.mart_ai_sales_planning m
    WHERE m.report_date < timezone('Europe/Moscow', now())::date
),
orders_daily_actual AS (
    SELECT
        o.date_ord::date                                        AS report_date,
        o.nm_id,
        COUNT(*) FILTER (WHERE COALESCE(o.is_cancel, false) = false)
                                                               AS actual_orders_1d
    FROM reports.v_wb_supplier_orders_latest_daily o
    WHERE o.nm_id IS NOT NULL
      AND o.date_ord IS NOT NULL
    GROUP BY o.date_ord::date, o.nm_id
),
sales_daily_actual AS (
    SELECT
        s.date_ord::date                                        AS report_date,
        s.nm_id,
        COUNT(*)                                                AS actual_sales_1d
    FROM reports.v_wb_supplier_sales_latest_daily s
    WHERE s.nm_id IS NOT NULL
      AND s.date_ord IS NOT NULL
    GROUP BY s.date_ord::date, s.nm_id
),
product_titles AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        title AS product_name
    FROM reports.wb_sales_funnel_products_daily
    WHERE nm_id IS NOT NULL
      AND title IS NOT NULL
      AND title <> ''
    ORDER BY nm_id, report_date DESC
),
eligible_marketing_campaigns AS (
    SELECT
        snapshot_date,
        external_id,
        name,
        campaign_type,
        status,
        payment_type
    FROM reports.v_wb_marketing_campaigns_latest_daily
    WHERE status = 9
       OR (
            status = 11
            AND COALESCE(change_time, updated_at, deleted_at, started_at, created_at)
                >= snapshot_date - INTERVAL '30 days'
       )
),
marketing_campaign_details AS (
    SELECT
        cnm.snapshot_date                                       AS report_date,
        cnm.nm_id,
        COUNT(DISTINCT cnm.advert_id)                           AS marketing_campaign_count,
        STRING_AGG(DISTINCT cnm.advert_id::text, ', ')          AS marketing_advert_ids,
        STRING_AGG(DISTINCT c.name, ' | ')
            FILTER (WHERE c.name IS NOT NULL AND c.name <> '')  AS marketing_campaign_names,
        STRING_AGG(DISTINCT c.campaign_type, ', ')
            FILTER (WHERE c.campaign_type IS NOT NULL AND c.campaign_type <> '')
                                                               AS marketing_campaign_types,
        STRING_AGG(DISTINCT c.status::text, ', ')
            FILTER (WHERE c.status IS NOT NULL)                 AS marketing_campaign_statuses,
        STRING_AGG(DISTINCT c.payment_type, ', ')
            FILTER (WHERE c.payment_type IS NOT NULL AND c.payment_type <> '')
                                                               AS marketing_payment_types,
        SUM(COALESCE(cnm.bid_search_kopecks, 0))                AS marketing_bid_search_kopecks,
        SUM(COALESCE(cnm.bid_recommendations_kopecks, 0))       AS marketing_bid_recommendations_kopecks
    FROM reports.v_wb_marketing_campaign_nms_latest_daily cnm
    JOIN eligible_marketing_campaigns c
        ON c.snapshot_date = cnm.snapshot_date
       AND c.external_id = cnm.advert_id
    GROUP BY cnm.snapshot_date, cnm.nm_id
),
marketing_stats_daily AS (
    SELECT
        stat_date                                               AS report_date,
        nm_id,
        SUM(COALESCE(views, 0))                                 AS marketing_views,
        SUM(COALESCE(clicks, 0))                                AS marketing_clicks,
        SUM(COALESCE(orders, 0))                                AS marketing_orders,
        SUM(COALESCE(atbs, 0))                                  AS marketing_atbs,
        SUM(COALESCE(canceled, 0))                              AS marketing_canceled,
        ROUND(SUM(COALESCE(sum_spend, 0))::numeric, 2)          AS marketing_spend,
        ROUND(
            SUM(COALESCE(clicks, 0))::numeric
            / NULLIF(SUM(COALESCE(views, 0)), 0) * 100,
        2)                                                      AS marketing_ctr,
        ROUND(
            SUM(COALESCE(sum_spend, 0))::numeric
            / NULLIF(SUM(COALESCE(clicks, 0)), 0),
        2)                                                      AS marketing_cpc,
        ROUND(
            SUM(COALESCE(orders, 0))::numeric
            / NULLIF(SUM(COALESCE(clicks, 0)), 0) * 100,
        2)                                                      AS marketing_cr
    FROM reports.wb_marketing_campaign_stats_daily_nms s
    JOIN eligible_marketing_campaigns c
        ON c.snapshot_date = s.stat_date
       AND c.external_id = s.advert_id
    GROUP BY stat_date, nm_id
),
open_supplies_daily AS (
    SELECT
        s.snapshot_date                                          AS report_date,
        sg.nm_id,
        COALESCE(SUM(sg.quantity), 0)                            AS open_supply_qty,
        STRING_AGG(DISTINCT s.status_id::text, ', ' ORDER BY s.status_id::text)
            FILTER (WHERE s.status_id IS NOT NULL)               AS supply_status_ids,
        MIN(s.supply_date)                                       AS planned_supply_date
    FROM reports.v_wb_supplies_goods_latest_daily sg
    JOIN reports.v_wb_supplies_latest_daily s
        ON s.snapshot_date = sg.snapshot_date
       AND s.supply_id = sg.supply_id
    WHERE sg.nm_id IS NOT NULL
      AND s.fact_date IS NULL
    GROUP BY s.snapshot_date, sg.nm_id
),
latest_supply_goods_snapshot AS (
    SELECT
        sg.nm_id,
        COALESCE(SUM(sg.quantity), 0)                            AS latest_supply_goods_qty
    FROM reports.v_wb_supplies_goods_latest_daily sg
    WHERE sg.snapshot_date = (
        SELECT MAX(snapshot_date)
        FROM reports.v_wb_supplies_goods_latest_daily
    )
      AND sg.nm_id IS NOT NULL
    GROUP BY sg.nm_id
),
-- -----------------------------------------------------------------------
-- Блок промо: последний снимок details на каждую акцию.
-- Джойн по датам: акция активна на report_date если
--   start_date_time::date <= report_date <= end_date_time::date
-- Данные агрегируются по всем активным на дату акциям (уровень аккаунта,
-- не nm_id — для автоакций список nm_id в API недоступен).
-- promo_nomenclatures_latest: последний снимок участия SKU на уровне nm_id
-- (только для regular-акций, для автоакций API возвращает 422).
-- -----------------------------------------------------------------------
promo_details_latest AS (
    SELECT
        promotion_id,
        name                        AS promo_name,
        type                        AS promo_type,
        start_date_time::date       AS promo_start,
        end_date_time::date         AS promo_end,
        participation_percentage,
        in_promo_action_total,
        not_in_promo_action_total,
        exception_products_count,
        ranging
    FROM reports.v_wb_calendar_promotions_details_latest_snapshot
),
promo_nomenclatures_latest AS (
    SELECT
        promotion_id,
        nm_id,
        in_action,
        plan_discount
    FROM reports.v_wb_calendar_promotions_nomenclatures_latest_snapshot
),
enriched AS (
    SELECT
        m.report_date,
        m.nm_id                                                AS id,
        m.vendor_code                                          AS sku,
        pt.product_name,
        m.stock_qty,
        COALESCE(oda.actual_orders_1d, 0)                      AS orders_1d,
        COALESCE(sda.actual_sales_1d, 0)                       AS sales_1d,
        COALESCE(m.revenue_net, 0)                             AS revenue_net_1d,
        COALESCE(m.ppvz_for_pay, 0)                            AS ppvz_1d,
        SUM(COALESCE(oda.actual_orders_1d, 0)) OVER (
            PARTITION BY m.nm_id
            ORDER BY m.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS orders_7d,
        SUM(COALESCE(sda.actual_sales_1d, 0)) OVER (
            PARTITION BY m.nm_id
            ORDER BY m.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS sales_7d,
        SUM(COALESCE(oda.actual_orders_1d, 0)) OVER (
            PARTITION BY m.nm_id
            ORDER BY m.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS orders_14d,
        SUM(COALESCE(sda.actual_sales_1d, 0)) OVER (
            PARTITION BY m.nm_id
            ORDER BY m.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS sales_14d,
        SUM(COALESCE(oda.actual_orders_1d, 0)) OVER (
            PARTITION BY m.nm_id
            ORDER BY m.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS orders_21d,
        SUM(COALESCE(sda.actual_sales_1d, 0)) OVER (
            PARTITION BY m.nm_id
            ORDER BY m.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS sales_21d,
        SUM(COALESCE(oda.actual_orders_1d, 0)) OVER (
            PARTITION BY m.nm_id
            ORDER BY m.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS orders_31d,
        SUM(COALESCE(sda.actual_sales_1d, 0)) OVER (
            PARTITION BY m.nm_id
            ORDER BY m.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS sales_31d,
        ROUND(
            SUM(COALESCE(sda.actual_sales_1d, 0)::numeric) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
            ) / 7.0,
        4)                                                     AS avg_sales_7d,
        ROUND(
            SUM(COALESCE(sda.actual_sales_1d, 0)::numeric) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
            ) / 14.0,
        4)                                                     AS avg_sales_14d,
        ROUND(
            SUM(COALESCE(sda.actual_sales_1d, 0)::numeric) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
            ) / 21.0,
        4)                                                     AS avg_sales_21d,
        ROUND(
            SUM(COALESCE(sda.actual_sales_1d, 0)::numeric) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
            ) / 31.0,
        4)                                                     AS avg_sales_31d,
        ROUND(
            SUM(COALESCE(m.revenue_net, 0)) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
            )::numeric,
        2)                                                     AS revenue_net_7d,
        ROUND(
            SUM(COALESCE(m.revenue_net, 0)) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
            )::numeric,
        2)                                                     AS revenue_net_14d,
        ROUND(
            SUM(COALESCE(m.revenue_net, 0)) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
            )::numeric,
        2)                                                     AS revenue_net_21d,
        ROUND(
            SUM(COALESCE(m.revenue_net, 0)) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
            )::numeric,
        2)                                                     AS revenue_net_31d,
        ROUND(
            SUM(COALESCE(m.ppvz_for_pay, 0)) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
            )::numeric,
        2)                                                     AS ppvz_7d,
        ROUND(
            SUM(COALESCE(m.ppvz_for_pay, 0)) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
            )::numeric,
        2)                                                     AS ppvz_14d,
        ROUND(
            SUM(COALESCE(m.ppvz_for_pay, 0)) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
            )::numeric,
        2)                                                     AS ppvz_21d,
        ROUND(
            SUM(COALESCE(m.ppvz_for_pay, 0)) OVER (
                PARTITION BY m.nm_id
                ORDER BY m.report_date
                RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
            )::numeric,
        2)                                                     AS ppvz_31d,
        m.price_raw                                            AS price_before_discount,
        m.price_final                                          AS price_after_discount,
        m.discount_pct,
        m.spp_pct,
        m.price_with_spp,
        m.stock_turnover_weekly                                AS stock_turnover,
        m.is_promo_period                                      AS in_promo,
        m.has_active_campaign                                  AS in_marketing_campaigns,
        mcd.marketing_campaign_count,
        mcd.marketing_advert_ids,
        mcd.marketing_campaign_names,
        mcd.marketing_campaign_types,
        mcd.marketing_campaign_statuses,
        mcd.marketing_payment_types,
        mcd.marketing_bid_search_kopecks,
        mcd.marketing_bid_recommendations_kopecks,
        msd.marketing_views,
        msd.marketing_clicks,
        msd.marketing_orders,
        msd.marketing_atbs,
        msd.marketing_canceled,
        msd.marketing_spend,
        msd.marketing_ctr,
        msd.marketing_cpc,
        msd.marketing_cr,
        m.last_supply_date,
        COALESCE(m.pending_supply_qty, 0)                      AS supply_qty,
        COALESCE(osd.open_supply_qty, lsg.latest_supply_goods_qty, 0)
                                                               AS open_supply_qty,
        osd.supply_status_ids,
        osd.planned_supply_date,
        COALESCE(lsg.latest_supply_goods_qty, 0)               AS latest_supply_goods_qty,
        m.open_count                                           AS impressions,
        m.open_to_cart_pct                                     AS cart_conversion_pct,
        m.cart_to_order_pct                                    AS cart_to_order_conversion_pct,
        SUM(m.buyout_count_day) OVER (
            PARTITION BY m.nm_id
            ORDER BY m.report_date
            RANGE BETWEEN INTERVAL '44 days' PRECEDING AND CURRENT ROW
        )                                                      AS sales_45d,
        p7.price_final                                         AS price_before_spp_7d_ago,
        p7.price_with_spp                                      AS price_after_spp_7d_ago,
        p14.price_final                                        AS price_before_spp_14d_ago,
        p14.price_with_spp                                     AS price_after_spp_14d_ago,
        p21.price_final                                        AS price_before_spp_21d_ago,
        p21.price_with_spp                                     AS price_after_spp_21d_ago,
        p31.price_final                                        AS price_before_spp_31d_ago,
        p31.price_with_spp                                     AS price_after_spp_31d_ago,
        promo.promo_names,
        promo.promo_types,
        promo.promo_first_start_date,
        promo.promo_nearest_end_date,
        promo.promo_boost_max,
        promo_nm.promo_nm_in_action,
        promo_nm.promo_gap_min,
        promo_nm.promo_eligible_names
    FROM reports.mart_ai_sales_planning m
    CROSS JOIN latest_complete_report_date lcd
    LEFT JOIN product_titles pt
        ON pt.nm_id = m.nm_id
    LEFT JOIN orders_daily_actual oda
        ON oda.report_date = m.report_date
       AND oda.nm_id = m.nm_id
    LEFT JOIN sales_daily_actual sda
        ON sda.report_date = m.report_date
       AND sda.nm_id = m.nm_id
    LEFT JOIN marketing_campaign_details mcd
        ON mcd.report_date = m.report_date
       AND mcd.nm_id = m.nm_id
    LEFT JOIN marketing_stats_daily msd
        ON msd.report_date = m.report_date
       AND msd.nm_id = m.nm_id
    LEFT JOIN open_supplies_daily osd
        ON osd.report_date = m.report_date
       AND osd.nm_id = m.nm_id
    LEFT JOIN latest_supply_goods_snapshot lsg
        ON lsg.nm_id = m.nm_id
    LEFT JOIN reports.mart_ai_sales_planning p7
        ON p7.nm_id = m.nm_id
       AND p7.report_date = m.report_date - 7
    LEFT JOIN reports.mart_ai_sales_planning p14
        ON p14.nm_id = m.nm_id
       AND p14.report_date = m.report_date - 14
    LEFT JOIN reports.mart_ai_sales_planning p21
        ON p21.nm_id = m.nm_id
       AND p21.report_date = m.report_date - 21
    LEFT JOIN reports.mart_ai_sales_planning p31
        ON p31.nm_id = m.nm_id
       AND p31.report_date = m.report_date - 31
    LEFT JOIN LATERAL (
        SELECT
            STRING_AGG(promo_name, ' | ' ORDER BY promo_name)          AS promo_names,
            STRING_AGG(DISTINCT promo_type, ', ')                       AS promo_types,
            MIN(promo_start)                                            AS promo_first_start_date,
            MIN(promo_end)                                              AS promo_nearest_end_date,
            MAX((
                SELECT MAX((el->>'boost')::numeric)
                FROM jsonb_array_elements(ranging) el
            ))                                                          AS promo_boost_max
        FROM promo_details_latest
        WHERE promo_start <= m.report_date
          AND promo_end   >= m.report_date
    ) promo ON true
    -- -----------------------------------------------------------------------
    -- SKU-уровень: участие nm_id в regular-акциях и gap до условия.
    -- gap = plan_discount - discount_pct:
    --   <= 0 → SKU уже выполняет условие (скидка достаточна)
    --   >  0 → нужно увеличить скидку на gap% для участия
    -- -----------------------------------------------------------------------
    LEFT JOIN LATERAL (
        SELECT
            BOOL_OR(n.in_action)                                        AS promo_nm_in_action,
            MIN(n.plan_discount - m.discount_pct)                       AS promo_gap_min,
            STRING_AGG(p.promo_name, ' | ' ORDER BY p.promo_name)
                FILTER (WHERE n.plan_discount - m.discount_pct <= 0)    AS promo_eligible_names
        FROM promo_nomenclatures_latest n
        JOIN promo_details_latest p ON p.promotion_id = n.promotion_id
        WHERE n.nm_id = m.nm_id
          AND p.promo_start <= m.report_date
          AND p.promo_end   >= m.report_date
    ) promo_nm ON true
    WHERE lcd.report_date IS NOT NULL
      AND m.report_date <= lcd.report_date
),
enriched_7d AS (
    SELECT
        e.*,
        SUM(COALESCE(e.marketing_views, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_views_7d,
        SUM(COALESCE(e.marketing_clicks, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_clicks_7d,
        SUM(COALESCE(e.marketing_views, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_views_14d,
        SUM(COALESCE(e.marketing_clicks, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_clicks_14d,
        SUM(COALESCE(e.marketing_views, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_views_21d,
        SUM(COALESCE(e.marketing_clicks, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_clicks_21d,
        SUM(COALESCE(e.marketing_views, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_views_31d,
        SUM(COALESCE(e.marketing_clicks, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_clicks_31d,
        SUM(COALESCE(e.marketing_orders, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_orders_7d,
        SUM(COALESCE(e.marketing_orders, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_orders_14d,
        SUM(COALESCE(e.marketing_orders, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_orders_21d,
        SUM(COALESCE(e.marketing_orders, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_orders_31d,
        SUM(COALESCE(e.marketing_atbs, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_atbs_7d,
        SUM(COALESCE(e.marketing_atbs, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_atbs_14d,
        SUM(COALESCE(e.marketing_atbs, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_atbs_21d,
        SUM(COALESCE(e.marketing_atbs, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_atbs_31d,
        SUM(COALESCE(e.marketing_canceled, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_canceled_7d,
        SUM(COALESCE(e.marketing_canceled, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_canceled_14d,
        SUM(COALESCE(e.marketing_canceled, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_canceled_21d,
        SUM(COALESCE(e.marketing_canceled, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )                                                      AS marketing_canceled_31d,
        ROUND(SUM(COALESCE(e.marketing_spend, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )::numeric, 2)                                         AS marketing_spend_7d
        ,
        ROUND(SUM(COALESCE(e.marketing_spend, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        )::numeric, 2)                                         AS marketing_spend_14d,
        ROUND(SUM(COALESCE(e.marketing_spend, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        )::numeric, 2)                                         AS marketing_spend_21d,
        ROUND(SUM(COALESCE(e.marketing_spend, 0)) OVER (
            PARTITION BY e.id
            ORDER BY e.report_date
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        )::numeric, 2)                                         AS marketing_spend_31d
    FROM enriched e
)
SELECT
    e.report_date,
    e.id,
    COALESCE(e.sku, '')                                        AS sku,
    COALESCE(e.product_name, '')                               AS product_name,
    COALESCE(e.stock_qty, 0)                                   AS qty_on_stock,
    COALESCE(e.last_supply_date, e.report_date - 45)           AS last_supply_date,
    (
        e.report_date - COALESCE(e.last_supply_date, e.report_date - 45)
    )                                                          AS days_on_stock,
    COALESCE(e.orders_1d, 0)                                   AS orders_1d,
    COALESCE(e.sales_1d, 0)                                    AS sales_1d,
    COALESCE(e.revenue_net_1d, 0)                              AS revenue_net_1d,
    COALESCE(e.ppvz_1d, 0)                                     AS ppvz_1d,
    COALESCE(ROUND(e.price_before_discount::numeric, 2), 0)    AS price_before_discount,
    COALESCE(ROUND(e.price_after_discount::numeric, 2), 0)     AS price_after_discount,
    COALESCE(ROUND(e.discount_pct::numeric, 2), 0)             AS discount_pct,
    COALESCE(ROUND(e.spp_pct::numeric, 2), 0)                  AS spp_pct,
    COALESCE(ROUND(e.price_with_spp::numeric, 2), 0)           AS price_with_spp,
    COALESCE(ROUND(e.stock_turnover::numeric, 4), 0)           AS stock_turnover,
    COALESCE(e.in_promo, false)                                AS in_promo,
    COALESCE(
        CASE
            WHEN COALESCE(e.in_promo, false)
                 AND e.promo_first_start_date IS NOT NULL
                THEN e.report_date - e.promo_first_start_date + 1
            ELSE 0
        END,
        0
    )                                                          AS days_in_promo,
    (
        COALESCE(e.in_marketing_campaigns, false)
        OR COALESCE(e.marketing_campaign_count, 0) > 0
    )                                                          AS in_marketing_campaigns,
    COALESCE(e.marketing_campaign_count, 0)                    AS marketing_campaign_count,
    COALESCE(e.marketing_advert_ids, '')                       AS marketing_advert_ids,
    COALESCE(e.marketing_campaign_names, '')                   AS marketing_campaign_names,
    COALESCE(e.marketing_campaign_types, '')                   AS marketing_campaign_types,
    COALESCE(e.marketing_campaign_statuses, '')                AS marketing_campaign_statuses,
    COALESCE(e.marketing_payment_types, '')                    AS marketing_payment_types,
    COALESCE(e.marketing_bid_search_kopecks, 0)                AS marketing_bid_search_kopecks,
    COALESCE(e.marketing_bid_recommendations_kopecks, 0)
                                                               AS marketing_bid_recommendations_kopecks,
    COALESCE(e.marketing_views, 0)                             AS marketing_views,
    COALESCE(e.marketing_clicks, 0)                            AS marketing_clicks,
    COALESCE(e.marketing_orders, 0)                            AS marketing_orders,
    COALESCE(e.marketing_atbs, 0)                              AS marketing_atbs,
    COALESCE(e.marketing_canceled, 0)                          AS marketing_canceled,
    COALESCE(e.marketing_spend, 0)                             AS marketing_spend,
    COALESCE(e.marketing_ctr, 0)                               AS marketing_ctr,
    COALESCE(e.marketing_cpc, 0)                               AS marketing_cpc,
    COALESCE(e.marketing_cr, 0)                                AS marketing_cr,
    COALESCE(e.orders_7d, 0)                                   AS orders_7d,
    COALESCE(e.sales_7d, 0)                                    AS sales_7d,
    COALESCE(e.avg_sales_7d, 0)                                AS avg_sales_7d,
    COALESCE(e.revenue_net_7d, 0)                              AS revenue_net_7d,
    COALESCE(e.ppvz_7d, 0)                                     AS ppvz_7d,
    COALESCE(e.marketing_views_7d, 0)                          AS marketing_views_7d,
    COALESCE(e.marketing_clicks_7d, 0)                         AS marketing_clicks_7d,
    COALESCE(e.marketing_orders_7d, 0)                         AS marketing_orders_7d,
    COALESCE(e.marketing_atbs_7d, 0)                           AS marketing_atbs_7d,
    COALESCE(e.marketing_canceled_7d, 0)                       AS marketing_canceled_7d,
    COALESCE(e.marketing_spend_7d, 0)                          AS marketing_spend_7d,
    COALESCE(
        ROUND(
            e.marketing_clicks_7d::numeric
            / NULLIF(e.marketing_views_7d, 0) * 100,
        2),
        0
    )                                                          AS marketing_ctr_7d,
    COALESCE(
        ROUND(
            e.marketing_spend_7d::numeric
            / NULLIF(e.marketing_clicks_7d, 0),
        2),
        0
    )                                                          AS marketing_cpc_7d,
    COALESCE(
        ROUND(
            e.marketing_orders_7d::numeric
            / NULLIF(e.marketing_clicks_7d, 0) * 100,
        2),
        0
    )                                                          AS marketing_cr_7d,
    COALESCE(
        CASE
            WHEN e.last_supply_date IS NULL THEN 0::numeric
            ELSE ROUND(
                (e.price_after_discount - e.price_before_spp_7d_ago)
                / NULLIF(e.price_before_spp_7d_ago, 0) * 100,
            2)
        END,
        0
    )                                                          AS price_change_before_spp_7d_pct,
    COALESCE(
        CASE
            WHEN e.last_supply_date IS NULL THEN 0::numeric
            ELSE ROUND(
                (e.price_with_spp - e.price_after_spp_7d_ago)
                / NULLIF(e.price_after_spp_7d_ago, 0) * 100,
            2)
        END,
        0
    )                                                          AS price_change_after_spp_7d_pct,
    COALESCE(e.orders_14d, 0)                                  AS orders_14d,
    COALESCE(e.sales_14d, 0)                                   AS sales_14d,
    COALESCE(e.avg_sales_14d, 0)                               AS avg_sales_14d,
    COALESCE(e.revenue_net_14d, 0)                             AS revenue_net_14d,
    COALESCE(e.ppvz_14d, 0)                                    AS ppvz_14d,
    COALESCE(e.marketing_views_14d, 0)                         AS marketing_views_14d,
    COALESCE(e.marketing_clicks_14d, 0)                        AS marketing_clicks_14d,
    COALESCE(e.marketing_orders_14d, 0)                        AS marketing_orders_14d,
    COALESCE(e.marketing_atbs_14d, 0)                          AS marketing_atbs_14d,
    COALESCE(e.marketing_canceled_14d, 0)                      AS marketing_canceled_14d,
    COALESCE(e.marketing_spend_14d, 0)                         AS marketing_spend_14d,
    COALESCE(
        ROUND(
            e.marketing_clicks_14d::numeric
            / NULLIF(e.marketing_views_14d, 0) * 100,
        2),
        0
    )                                                          AS marketing_ctr_14d,
    COALESCE(
        ROUND(
            e.marketing_spend_14d::numeric
            / NULLIF(e.marketing_clicks_14d, 0),
        2),
        0
    )                                                          AS marketing_cpc_14d,
    COALESCE(
        ROUND(
            e.marketing_orders_14d::numeric
            / NULLIF(e.marketing_clicks_14d, 0) * 100,
        2),
        0
    )                                                          AS marketing_cr_14d,
    COALESCE(
        CASE
            WHEN e.last_supply_date IS NULL THEN 0::numeric
            ELSE ROUND(
                (e.price_after_discount - e.price_before_spp_14d_ago)
                / NULLIF(e.price_before_spp_14d_ago, 0) * 100,
            2)
        END,
        0
    )                                                          AS price_change_before_spp_14d_pct,
    COALESCE(
        CASE
            WHEN e.last_supply_date IS NULL THEN 0::numeric
            ELSE ROUND(
                (e.price_with_spp - e.price_after_spp_14d_ago)
                / NULLIF(e.price_after_spp_14d_ago, 0) * 100,
            2)
        END,
        0
    )                                                          AS price_change_after_spp_14d_pct,
    COALESCE(e.orders_21d, 0)                                  AS orders_21d,
    COALESCE(e.sales_21d, 0)                                   AS sales_21d,
    COALESCE(e.avg_sales_21d, 0)                               AS avg_sales_21d,
    COALESCE(e.revenue_net_21d, 0)                             AS revenue_net_21d,
    COALESCE(e.ppvz_21d, 0)                                    AS ppvz_21d,
    COALESCE(e.marketing_views_21d, 0)                         AS marketing_views_21d,
    COALESCE(e.marketing_clicks_21d, 0)                        AS marketing_clicks_21d,
    COALESCE(e.marketing_orders_21d, 0)                        AS marketing_orders_21d,
    COALESCE(e.marketing_atbs_21d, 0)                          AS marketing_atbs_21d,
    COALESCE(e.marketing_canceled_21d, 0)                      AS marketing_canceled_21d,
    COALESCE(e.marketing_spend_21d, 0)                         AS marketing_spend_21d,
    COALESCE(
        ROUND(
            e.marketing_clicks_21d::numeric
            / NULLIF(e.marketing_views_21d, 0) * 100,
        2),
        0
    )                                                          AS marketing_ctr_21d,
    COALESCE(
        ROUND(
            e.marketing_spend_21d::numeric
            / NULLIF(e.marketing_clicks_21d, 0),
        2),
        0
    )                                                          AS marketing_cpc_21d,
    COALESCE(
        ROUND(
            e.marketing_orders_21d::numeric
            / NULLIF(e.marketing_clicks_21d, 0) * 100,
        2),
        0
    )                                                          AS marketing_cr_21d,
    COALESCE(
        CASE
            WHEN e.last_supply_date IS NULL THEN 0::numeric
            ELSE ROUND(
                (e.price_after_discount - e.price_before_spp_21d_ago)
                / NULLIF(e.price_before_spp_21d_ago, 0) * 100,
            2)
        END,
        0
    )                                                          AS price_change_before_spp_21d_pct,
    COALESCE(
        CASE
            WHEN e.last_supply_date IS NULL THEN 0::numeric
            ELSE ROUND(
                (e.price_with_spp - e.price_after_spp_21d_ago)
                / NULLIF(e.price_after_spp_21d_ago, 0) * 100,
            2)
        END,
        0
    )                                                          AS price_change_after_spp_21d_pct,
    COALESCE(e.orders_31d, 0)                                  AS orders_31d,
    COALESCE(e.sales_31d, 0)                                   AS sales_31d,
    COALESCE(e.avg_sales_31d, 0)                               AS avg_sales_31d,
    COALESCE(e.revenue_net_31d, 0)                             AS revenue_net_31d,
    COALESCE(e.ppvz_31d, 0)                                    AS ppvz_31d,
    COALESCE(e.marketing_views_31d, 0)                         AS marketing_views_31d,
    COALESCE(e.marketing_clicks_31d, 0)                        AS marketing_clicks_31d,
    COALESCE(e.marketing_orders_31d, 0)                        AS marketing_orders_31d,
    COALESCE(e.marketing_atbs_31d, 0)                          AS marketing_atbs_31d,
    COALESCE(e.marketing_canceled_31d, 0)                      AS marketing_canceled_31d,
    COALESCE(e.marketing_spend_31d, 0)                         AS marketing_spend_31d,
    COALESCE(
        ROUND(
            e.marketing_clicks_31d::numeric
            / NULLIF(e.marketing_views_31d, 0) * 100,
        2),
        0
    )                                                          AS marketing_ctr_31d,
    COALESCE(
        ROUND(
            e.marketing_spend_31d::numeric
            / NULLIF(e.marketing_clicks_31d, 0),
        2),
        0
    )                                                          AS marketing_cpc_31d,
    COALESCE(
        ROUND(
            e.marketing_orders_31d::numeric
            / NULLIF(e.marketing_clicks_31d, 0) * 100,
        2),
        0
    )                                                          AS marketing_cr_31d,
    COALESCE(e.supply_qty, 0)                                  AS supply_qty,
    COALESCE(
        CASE
            WHEN e.last_supply_date IS NULL THEN 0::numeric
            ELSE ROUND(
                (e.price_after_discount - e.price_before_spp_31d_ago)
                / NULLIF(e.price_before_spp_31d_ago, 0) * 100,
            2)
        END,
        0
    )                                                          AS price_change_before_spp_31d_pct,
    COALESCE(
        CASE
            WHEN e.last_supply_date IS NULL THEN 0::numeric
            ELSE ROUND(
                (e.price_with_spp - e.price_after_spp_31d_ago)
                / NULLIF(e.price_after_spp_31d_ago, 0) * 100,
            2)
        END,
        0
    )                                                          AS price_change_after_spp_31d_pct,
    COALESCE(e.impressions, 0)                                 AS impressions,
    COALESCE(ROUND(e.cart_conversion_pct::numeric, 2), 0)      AS cart_conversion_pct,
    COALESCE(ROUND(e.cart_to_order_conversion_pct::numeric, 2), 0)
                                                               AS cart_to_order_conversion_pct,
    -- ------------------------------------------------------------------
    -- Блок промо (уровень аккаунта: все акции, активные на report_date)
    -- ------------------------------------------------------------------
    COALESCE(e.promo_names, '')                                AS promo_names,
    COALESCE(e.promo_types, '')                                AS promo_types,
    COALESCE(e.promo_nearest_end_date, DATE '1970-01-01')      AS promo_nearest_end_date,
    COALESCE(e.promo_boost_max, 0)                             AS promo_boost_max,
    -- ------------------------------------------------------------------
    -- Блок промо (уровень SKU: только regular-акции с nm_id в nomenclatures)
    -- ------------------------------------------------------------------
    COALESCE(e.promo_nm_in_action, false)                      AS promo_nm_in_action,
    ROUND(COALESCE(e.promo_gap_min, 0)::numeric, 1)            AS promo_gap_min,
    COALESCE(e.promo_eligible_names, '')                       AS promo_eligible_names,
    COALESCE(e.open_supply_qty, 0)                             AS open_supply_qty,
    COALESCE(e.supply_status_ids, '')                          AS supply_status_ids,
    e.planned_supply_date                                      AS planned_supply_date
FROM enriched_7d e
WHERE COALESCE(e.stock_qty, 0) > 0
   OR COALESCE(e.sales_1d, 0) > 0
   OR COALESCE(e.orders_1d, 0) > 0
   OR COALESCE(e.sales_7d, 0) > 0
   OR COALESCE(e.supply_qty, 0) > 0
   OR COALESCE(e.latest_supply_goods_qty, 0) > 0
ORDER BY e.report_date DESC, e.sales_31d DESC, e.id;

COMMENT ON VIEW reports.v_1pager_ai_daily IS
'1pager AI slice from mart_ai_sales_planning with accumulated history by completed report_date only. The current Moscow day is excluded because it may be incomplete. Keeps SKUs with stock, recent sales/orders activity, or open supply. When supply history is absent, last_supply_date falls back to report_date minus 45 days. Promo block: account-level promotions active on report_date joined from wb_calendar_promotions_details (latest snapshot per promotion_id). Columns promo_in_total / promo_not_in_total show SKU participation counts at the account level; promo_boost_max is the maximum boost factor across all active promotions.';
