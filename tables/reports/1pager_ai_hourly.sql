-- =============================================================================
-- 1pager AI hourly artifacts
--
-- Objects:
--   * reports.v_1pager_ai_hourly_source  - build source for one target snapshot_hour
--   * reports.wb_1pager_ai_hourly        - accumulated hourly table
--   * reports.v_1pager_ai_hourly         - history view over accumulated table
--   * reports.v_1pager_ai                - compatibility alias to latest snapshot_hour
--
-- The target snapshot_hour for the source view is controlled through
-- reports.wb_1pager_ai_hourly_target(target_key='build').
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_1pager_ai_hourly_target (
    target_key TEXT PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE VIEW reports.v_1pager_ai_hourly_source AS
WITH requested_target AS (
    SELECT snapshot_hour
    FROM reports.wb_1pager_ai_hourly_target
    WHERE target_key = 'build'
),
fallback_target AS (
    SELECT MAX(snapshot_hour) AS snapshot_hour
    FROM reports.wb_stocks_sales_hourly
),
target_snapshot AS (
    SELECT
        COALESCE(rt.snapshot_hour, ft.snapshot_hour)             AS snapshot_hour,
        (
            SELECT MAX(h.snapshot_date)
            FROM reports.wb_stocks_sales_hourly h
            WHERE h.snapshot_hour = COALESCE(rt.snapshot_hour, ft.snapshot_hour)
        )                                                       AS snapshot_date
    FROM fallback_target ft
    LEFT JOIN requested_target rt
      ON TRUE
),
stock_snapshot_source AS (
    SELECT
        ts.snapshot_hour                                        AS target_snapshot_hour,
        ts.snapshot_date                                        AS target_snapshot_date,
        COALESCE((
            SELECT MAX(ss.snapshot_hour)
            FROM (
                SELECT snapshot_hour
                FROM reports.wb_supplier_stocks
                WHERE snapshot_hour <= ts.snapshot_hour
                GROUP BY snapshot_hour
                HAVING SUM(COALESCE(quantity, 0)) > 0
            ) ss
        ), ts.snapshot_hour)                                    AS stock_snapshot_hour
    FROM target_snapshot ts
),
hourly_stock AS (
    SELECT
        sss.target_snapshot_hour                                AS snapshot_hour,
        sss.target_snapshot_date                                AS snapshot_date,
        h.nm_id,
        SUM(COALESCE(h.stock_quantity, 0))                      AS qty_on_stock,
        SUM(COALESCE(h.sales_count, 0))                         AS sales_1d
    FROM reports.wb_stocks_sales_hourly h
    JOIN stock_snapshot_source sss
      ON sss.stock_snapshot_hour = h.snapshot_hour
    GROUP BY sss.target_snapshot_hour, sss.target_snapshot_date, h.nm_id
),
base_daily AS (
    SELECT DISTINCT ON (b.id)
        b.*
    FROM reports.v_1pager_ai_daily b
    CROSS JOIN target_snapshot ts
    WHERE ts.snapshot_hour IS NOT NULL
      AND b.report_date <= ts.snapshot_hour::date
    ORDER BY b.id, b.report_date DESC
),
product_titles AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        title                                                   AS product_name
    FROM reports.wb_sales_funnel_products_daily
    WHERE nm_id IS NOT NULL
      AND title IS NOT NULL
      AND title <> ''
    ORDER BY nm_id, report_date DESC
),
current_prices AS (
    SELECT
        p.nm_id,
        p.vendor_code,
        p.price,
        p.discounted_price,
        p.club_discounted_price,
        p.discount,
        p.club_discount
    FROM reports.wb_supplier_prices p
    JOIN target_snapshot ts
      ON ts.snapshot_hour = p.snapshot_hour
),
orders_current AS (
    SELECT
        o.nm_id,
        COUNT(*) FILTER (WHERE COALESCE(o.is_cancel, false) = false)
                                                                 AS orders_1d
    FROM reports.wb_supplier_orders o
    JOIN target_snapshot ts
      ON ts.snapshot_hour = o.snapshot_hour
    WHERE o.nm_id IS NOT NULL
      AND o.date_ord IS NOT NULL
      AND o.date_ord::date = ts.snapshot_hour::date
    GROUP BY o.nm_id
),
supply_qty_current AS (
    SELECT
        sg.nm_id,
        COALESCE(SUM(sg.quantity), 0)                            AS supply_qty
    FROM reports.wb_supplies_goods sg
    JOIN reports.wb_supplies s
      ON s.snapshot_hour = sg.snapshot_hour
     AND s.supply_id = sg.supply_id
    JOIN target_snapshot ts
      ON ts.snapshot_hour = sg.snapshot_hour
    WHERE sg.nm_id IS NOT NULL
      AND s.fact_date IS NULL
    GROUP BY sg.nm_id
),
last_supply_history AS (
    SELECT
        sg.nm_id,
        MAX(s.supply_date)                                       AS last_supply_date
    FROM reports.v_wb_supplies_goods_latest_daily sg
    JOIN reports.v_wb_supplies_latest_daily s
      ON s.supply_id = sg.supply_id
    WHERE sg.nm_id IS NOT NULL
      AND s.supply_date IS NOT NULL
      AND s.fact_date IS NOT NULL
    GROUP BY sg.nm_id
),
eligible_marketing_campaigns_current AS (
    SELECT
        c.external_id,
        c.name,
        c.campaign_type,
        c.status,
        c.payment_type
    FROM reports.wb_marketing_campaigns c
    JOIN target_snapshot ts
      ON ts.snapshot_hour = c.snapshot_hour
    WHERE c.status = 9
       OR (
            c.status = 11
            AND COALESCE(c.change_time, c.updated_at, c.deleted_at, c.started_at, c.created_at)
                >= ts.snapshot_hour::date - INTERVAL '30 days'
       )
),
marketing_campaign_details_current AS (
    SELECT
        cnm.nm_id,
        COUNT(DISTINCT cnm.advert_id)                            AS marketing_campaign_count,
        STRING_AGG(DISTINCT cnm.advert_id::text, ', ')           AS marketing_advert_ids,
        STRING_AGG(DISTINCT c.name, ' | ')
            FILTER (WHERE c.name IS NOT NULL AND c.name <> '')   AS marketing_campaign_names,
        STRING_AGG(DISTINCT c.campaign_type, ', ')
            FILTER (WHERE c.campaign_type IS NOT NULL AND c.campaign_type <> '')
                                                                 AS marketing_campaign_types,
        STRING_AGG(DISTINCT c.status::text, ', ')
            FILTER (WHERE c.status IS NOT NULL)                  AS marketing_campaign_statuses,
        STRING_AGG(DISTINCT c.payment_type, ', ')
            FILTER (WHERE c.payment_type IS NOT NULL AND c.payment_type <> '')
                                                                 AS marketing_payment_types,
        SUM(COALESCE(cnm.bid_search_kopecks, 0))                 AS marketing_bid_search_kopecks,
        SUM(COALESCE(cnm.bid_recommendations_kopecks, 0))        AS marketing_bid_recommendations_kopecks
    FROM reports.wb_marketing_campaign_nms cnm
    JOIN target_snapshot ts
      ON ts.snapshot_hour = cnm.snapshot_hour
    JOIN eligible_marketing_campaigns_current c
      ON c.external_id = cnm.advert_id
    GROUP BY cnm.nm_id
),
promo_details_current AS (
    SELECT
        d.promotion_id,
        d.name,
        d.type,
        d.start_date_time::date                                  AS promo_start,
        d.end_date_time::date                                    AS promo_end,
        d.ranging
    FROM reports.wb_calendar_promotions_details d
    JOIN target_snapshot ts
      ON ts.snapshot_hour = d.snapshot_hour
),
promo_account_current AS (
    SELECT
        COUNT(*) > 0                                             AS in_promo,
        STRING_AGG(p.name, ' | ' ORDER BY p.name)                AS promo_names,
        STRING_AGG(DISTINCT p.type, ', ')
            FILTER (WHERE p.type IS NOT NULL AND p.type <> '')   AS promo_types,
        MIN(p.promo_start)                                       AS promo_first_start_date,
        MIN(p.promo_end)                                         AS promo_nearest_end_date,
        MAX((
            SELECT MAX((el->>'boost')::numeric)
            FROM jsonb_array_elements(COALESCE(p.ranging, '[]'::jsonb)) el
        ))                                                       AS promo_boost_max
    FROM promo_details_current p
    CROSS JOIN target_snapshot ts
    WHERE p.promo_start <= ts.snapshot_hour::date
      AND p.promo_end >= ts.snapshot_hour::date
),
promo_nomenclatures_current AS (
    SELECT
        n.promotion_id,
        n.nm_id,
        n.in_action,
        n.plan_discount
    FROM reports.wb_calendar_promotions_nomenclatures n
    JOIN target_snapshot ts
      ON ts.snapshot_hour = n.snapshot_hour
),
promo_nm_current AS (
    SELECT
        n.nm_id,
        BOOL_OR(n.in_action)                                     AS promo_nm_in_action,
        MIN(n.plan_discount - COALESCE(cp.discount, 0))          AS promo_gap_min,
        STRING_AGG(p.name, ' | ' ORDER BY p.name)
            FILTER (WHERE n.plan_discount - COALESCE(cp.discount, 0) <= 0)
                                                                 AS promo_eligible_names
    FROM promo_nomenclatures_current n
    JOIN promo_details_current p
      ON p.promotion_id = n.promotion_id
    LEFT JOIN current_prices cp
      ON cp.nm_id = n.nm_id
    CROSS JOIN target_snapshot ts
    WHERE p.promo_start <= ts.snapshot_hour::date
      AND p.promo_end >= ts.snapshot_hour::date
    GROUP BY n.nm_id
),
product_scope AS (
    SELECT nm_id
    FROM hourly_stock
    UNION
    SELECT id AS nm_id
    FROM base_daily
)
SELECT
    ts.snapshot_hour,
    ts.snapshot_date                                             AS report_date,
    ps.nm_id                                                     AS id,
    COALESCE(base.sku, cp.vendor_code, '')                       AS sku,
    COALESCE(base.product_name, pt.product_name, '')             AS product_name,
    COALESCE(hs.qty_on_stock, base.qty_on_stock, 0)              AS qty_on_stock,
    COALESCE(lsh.last_supply_date, ts.snapshot_date - 45)        AS last_supply_date,
    (
        ts.snapshot_date - COALESCE(lsh.last_supply_date, ts.snapshot_date - 45)
    )                                                            AS days_on_stock,
    COALESCE(oc.orders_1d, 0)                                    AS orders_1d,
    COALESCE(hs.sales_1d, 0)                                     AS sales_1d,
    COALESCE(ROUND(cp.price::numeric, 2), base.price_before_discount, 0)
                                                                 AS price_before_discount,
    COALESCE(ROUND(cp.discounted_price::numeric, 2), base.price_after_discount, 0)
                                                                 AS price_after_discount,
    COALESCE(ROUND(cp.discount::numeric, 2), base.discount_pct, 0)
                                                                 AS discount_pct,
    COALESCE(ROUND(cp.club_discount::numeric, 2), base.spp_pct, 0)
                                                                 AS spp_pct,
    COALESCE(ROUND(cp.club_discounted_price::numeric, 2), base.price_with_spp, 0)
                                                                 AS price_with_spp,
    COALESCE(base.stock_turnover, 0)                             AS stock_turnover,
    COALESCE(pac.in_promo, false)                                AS in_promo,
    COALESCE(
        CASE
            WHEN COALESCE(pac.in_promo, false)
                 AND pac.promo_first_start_date IS NOT NULL
                THEN ts.snapshot_date - pac.promo_first_start_date + 1
            ELSE 0
        END,
        0
    )                                                            AS days_in_promo,
    (
        COALESCE(base.in_marketing_campaigns, false)
        OR COALESCE(mcd.marketing_campaign_count, 0) > 0
    )                                                            AS in_marketing_campaigns,
    COALESCE(mcd.marketing_campaign_count, 0)                    AS marketing_campaign_count,
    COALESCE(mcd.marketing_advert_ids, '')                       AS marketing_advert_ids,
    COALESCE(mcd.marketing_campaign_names, '')                   AS marketing_campaign_names,
    COALESCE(mcd.marketing_campaign_types, '')                   AS marketing_campaign_types,
    COALESCE(mcd.marketing_campaign_statuses, '')                AS marketing_campaign_statuses,
    COALESCE(mcd.marketing_payment_types, '')                    AS marketing_payment_types,
    COALESCE(mcd.marketing_bid_search_kopecks, 0)                AS marketing_bid_search_kopecks,
    COALESCE(mcd.marketing_bid_recommendations_kopecks, 0)       AS marketing_bid_recommendations_kopecks,
    COALESCE(base.marketing_views, 0)                            AS marketing_views,
    COALESCE(base.marketing_clicks, 0)                           AS marketing_clicks,
    COALESCE(base.marketing_orders, 0)                           AS marketing_orders,
    COALESCE(base.marketing_atbs, 0)                             AS marketing_atbs,
    COALESCE(base.marketing_canceled, 0)                         AS marketing_canceled,
    COALESCE(base.marketing_spend, 0)                            AS marketing_spend,
    COALESCE(base.marketing_ctr, 0)                              AS marketing_ctr,
    COALESCE(base.marketing_cpc, 0)                              AS marketing_cpc,
    COALESCE(base.marketing_cr, 0)                               AS marketing_cr,
    COALESCE(base.sales_7d, 0)                                   AS sales_7d,
    COALESCE(base.avg_sales_7d, 0)                               AS avg_sales_7d,
    COALESCE(base.marketing_views_7d, 0)                         AS marketing_views_7d,
    COALESCE(base.marketing_clicks_7d, 0)                        AS marketing_clicks_7d,
    COALESCE(base.marketing_orders_7d, 0)                        AS marketing_orders_7d,
    COALESCE(base.marketing_atbs_7d, 0)                          AS marketing_atbs_7d,
    COALESCE(base.marketing_canceled_7d, 0)                      AS marketing_canceled_7d,
    COALESCE(base.marketing_spend_7d, 0)                         AS marketing_spend_7d,
    COALESCE(base.marketing_ctr_7d, 0)                           AS marketing_ctr_7d,
    COALESCE(base.marketing_cpc_7d, 0)                           AS marketing_cpc_7d,
    COALESCE(base.marketing_cr_7d, 0)                            AS marketing_cr_7d,
    COALESCE(base.price_change_before_spp_7d_pct, 0)             AS price_change_before_spp_7d_pct,
    COALESCE(base.price_change_after_spp_7d_pct, 0)              AS price_change_after_spp_7d_pct,
    COALESCE(base.sales_14d, 0)                                  AS sales_14d,
    COALESCE(base.avg_sales_14d, 0)                              AS avg_sales_14d,
    COALESCE(base.marketing_views_14d, 0)                        AS marketing_views_14d,
    COALESCE(base.marketing_clicks_14d, 0)                       AS marketing_clicks_14d,
    COALESCE(base.marketing_orders_14d, 0)                       AS marketing_orders_14d,
    COALESCE(base.marketing_atbs_14d, 0)                         AS marketing_atbs_14d,
    COALESCE(base.marketing_canceled_14d, 0)                     AS marketing_canceled_14d,
    COALESCE(base.marketing_spend_14d, 0)                        AS marketing_spend_14d,
    COALESCE(base.marketing_ctr_14d, 0)                          AS marketing_ctr_14d,
    COALESCE(base.marketing_cpc_14d, 0)                          AS marketing_cpc_14d,
    COALESCE(base.marketing_cr_14d, 0)                           AS marketing_cr_14d,
    COALESCE(base.price_change_before_spp_14d_pct, 0)            AS price_change_before_spp_14d_pct,
    COALESCE(base.price_change_after_spp_14d_pct, 0)             AS price_change_after_spp_14d_pct,
    COALESCE(base.sales_21d, 0)                                  AS sales_21d,
    COALESCE(base.avg_sales_21d, 0)                              AS avg_sales_21d,
    COALESCE(base.marketing_views_21d, 0)                        AS marketing_views_21d,
    COALESCE(base.marketing_clicks_21d, 0)                       AS marketing_clicks_21d,
    COALESCE(base.marketing_orders_21d, 0)                       AS marketing_orders_21d,
    COALESCE(base.marketing_atbs_21d, 0)                         AS marketing_atbs_21d,
    COALESCE(base.marketing_canceled_21d, 0)                     AS marketing_canceled_21d,
    COALESCE(base.marketing_spend_21d, 0)                        AS marketing_spend_21d,
    COALESCE(base.marketing_ctr_21d, 0)                          AS marketing_ctr_21d,
    COALESCE(base.marketing_cpc_21d, 0)                          AS marketing_cpc_21d,
    COALESCE(base.marketing_cr_21d, 0)                           AS marketing_cr_21d,
    COALESCE(base.price_change_before_spp_21d_pct, 0)            AS price_change_before_spp_21d_pct,
    COALESCE(base.price_change_after_spp_21d_pct, 0)             AS price_change_after_spp_21d_pct,
    COALESCE(base.sales_31d, 0)                                  AS sales_31d,
    COALESCE(base.avg_sales_31d, 0)                              AS avg_sales_31d,
    COALESCE(base.marketing_views_31d, 0)                        AS marketing_views_31d,
    COALESCE(base.marketing_clicks_31d, 0)                       AS marketing_clicks_31d,
    COALESCE(base.marketing_orders_31d, 0)                       AS marketing_orders_31d,
    COALESCE(base.marketing_atbs_31d, 0)                         AS marketing_atbs_31d,
    COALESCE(base.marketing_canceled_31d, 0)                     AS marketing_canceled_31d,
    COALESCE(base.marketing_spend_31d, 0)                        AS marketing_spend_31d,
    COALESCE(base.marketing_ctr_31d, 0)                          AS marketing_ctr_31d,
    COALESCE(base.marketing_cpc_31d, 0)                          AS marketing_cpc_31d,
    COALESCE(base.marketing_cr_31d, 0)                           AS marketing_cr_31d,
    COALESCE(sqc.supply_qty, 0)                                  AS supply_qty,
    COALESCE(base.price_change_before_spp_31d_pct, 0)            AS price_change_before_spp_31d_pct,
    COALESCE(base.price_change_after_spp_31d_pct, 0)             AS price_change_after_spp_31d_pct,
    COALESCE(base.impressions, 0)                                AS impressions,
    COALESCE(base.cart_conversion_pct, 0)                        AS cart_conversion_pct,
    COALESCE(base.cart_to_order_conversion_pct, 0)               AS cart_to_order_conversion_pct,
    COALESCE(pac.promo_names, '')                                AS promo_names,
    COALESCE(pac.promo_types, '')                                AS promo_types,
    COALESCE(pac.promo_nearest_end_date, DATE '1970-01-01')      AS promo_nearest_end_date,
    COALESCE(pac.promo_boost_max, 0)                             AS promo_boost_max,
    COALESCE(pnc.promo_nm_in_action, false)                      AS promo_nm_in_action,
    ROUND(COALESCE(pnc.promo_gap_min, 0)::numeric, 1)            AS promo_gap_min,
    COALESCE(pnc.promo_eligible_names, '')                       AS promo_eligible_names
FROM product_scope ps
CROSS JOIN target_snapshot ts
LEFT JOIN hourly_stock hs
  ON hs.nm_id = ps.nm_id
LEFT JOIN base_daily base
  ON base.id = ps.nm_id
LEFT JOIN product_titles pt
  ON pt.nm_id = ps.nm_id
LEFT JOIN current_prices cp
  ON cp.nm_id = ps.nm_id
LEFT JOIN orders_current oc
  ON oc.nm_id = ps.nm_id
LEFT JOIN supply_qty_current sqc
  ON sqc.nm_id = ps.nm_id
LEFT JOIN last_supply_history lsh
  ON lsh.nm_id = ps.nm_id
LEFT JOIN marketing_campaign_details_current mcd
  ON mcd.nm_id = ps.nm_id
LEFT JOIN promo_nm_current pnc
  ON pnc.nm_id = ps.nm_id
CROSS JOIN promo_account_current pac
WHERE COALESCE(hs.qty_on_stock, base.qty_on_stock, 0) > 0
ORDER BY ts.snapshot_hour DESC, COALESCE(base.sales_31d, 0) DESC, ps.nm_id;

COMMENT ON VIEW reports.v_1pager_ai_hourly_source IS
'Source view for building a single snapshot_hour of 1pager AI hourly data. Target hour is controlled by reports.wb_1pager_ai_hourly_target.';

CREATE TABLE IF NOT EXISTS reports.wb_1pager_ai_hourly AS
SELECT
    src.*,
    CURRENT_TIMESTAMP AS updated_at
FROM reports.v_1pager_ai_hourly_source src
WHERE FALSE;

ALTER TABLE reports.wb_1pager_ai_hourly
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'reports.wb_1pager_ai_hourly'::regclass
          AND conname = 'wb_1pager_ai_hourly_pkey'
    ) THEN
        ALTER TABLE reports.wb_1pager_ai_hourly
            ADD CONSTRAINT wb_1pager_ai_hourly_pkey PRIMARY KEY (snapshot_hour, id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_wb_1pager_ai_hourly_report_date
    ON reports.wb_1pager_ai_hourly (report_date);
CREATE INDEX IF NOT EXISTS idx_wb_1pager_ai_hourly_id
    ON reports.wb_1pager_ai_hourly (id);
CREATE INDEX IF NOT EXISTS idx_wb_1pager_ai_hourly_snapshot_hour
    ON reports.wb_1pager_ai_hourly (snapshot_hour);

CREATE OR REPLACE VIEW reports.v_1pager_ai_hourly AS
SELECT
    snapshot_hour,
    report_date,
    id,
    sku,
    product_name,
    qty_on_stock,
    last_supply_date,
    days_on_stock,
    orders_1d,
    sales_1d,
    price_before_discount,
    price_after_discount,
    discount_pct,
    spp_pct,
    price_with_spp,
    stock_turnover,
    in_promo,
    days_in_promo,
    in_marketing_campaigns,
    marketing_campaign_count,
    marketing_advert_ids,
    marketing_campaign_names,
    marketing_campaign_types,
    marketing_campaign_statuses,
    marketing_payment_types,
    marketing_bid_search_kopecks,
    marketing_bid_recommendations_kopecks,
    marketing_views,
    marketing_clicks,
    marketing_orders,
    marketing_atbs,
    marketing_canceled,
    marketing_spend,
    marketing_ctr,
    marketing_cpc,
    marketing_cr,
    sales_7d,
    avg_sales_7d,
    marketing_views_7d,
    marketing_clicks_7d,
    marketing_orders_7d,
    marketing_atbs_7d,
    marketing_canceled_7d,
    marketing_spend_7d,
    marketing_ctr_7d,
    marketing_cpc_7d,
    marketing_cr_7d,
    price_change_before_spp_7d_pct,
    price_change_after_spp_7d_pct,
    sales_14d,
    avg_sales_14d,
    marketing_views_14d,
    marketing_clicks_14d,
    marketing_orders_14d,
    marketing_atbs_14d,
    marketing_canceled_14d,
    marketing_spend_14d,
    marketing_ctr_14d,
    marketing_cpc_14d,
    marketing_cr_14d,
    price_change_before_spp_14d_pct,
    price_change_after_spp_14d_pct,
    sales_21d,
    avg_sales_21d,
    marketing_views_21d,
    marketing_clicks_21d,
    marketing_orders_21d,
    marketing_atbs_21d,
    marketing_canceled_21d,
    marketing_spend_21d,
    marketing_ctr_21d,
    marketing_cpc_21d,
    marketing_cr_21d,
    price_change_before_spp_21d_pct,
    price_change_after_spp_21d_pct,
    sales_31d,
    avg_sales_31d,
    marketing_views_31d,
    marketing_clicks_31d,
    marketing_orders_31d,
    marketing_atbs_31d,
    marketing_canceled_31d,
    marketing_spend_31d,
    marketing_ctr_31d,
    marketing_cpc_31d,
    marketing_cr_31d,
    supply_qty,
    price_change_before_spp_31d_pct,
    price_change_after_spp_31d_pct,
    impressions,
    cart_conversion_pct,
    cart_to_order_conversion_pct,
    promo_names,
    promo_types,
    promo_nearest_end_date,
    promo_boost_max,
    promo_nm_in_action,
    promo_gap_min,
    promo_eligible_names
FROM reports.wb_1pager_ai_hourly;

COMMENT ON VIEW reports.v_1pager_ai_hourly IS
'Accumulated hourly 1pager AI history. One row per nm_id per snapshot_hour.';

CREATE OR REPLACE VIEW reports.v_1pager_ai AS
SELECT *
FROM reports.v_1pager_ai_hourly
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_1pager_ai_hourly
);

COMMENT ON VIEW reports.v_1pager_ai IS
'Compatibility alias that points consumers to the latest snapshot_hour from accumulated hourly 1pager AI history.';
