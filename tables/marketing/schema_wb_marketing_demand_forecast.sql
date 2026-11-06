CREATE SCHEMA IF NOT EXISTS marketing;

CREATE OR REPLACE FUNCTION marketing.normalize_query_text(value TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN value IS NULL THEN NULL
        ELSE trim(
            regexp_replace(
                translate(lower(value), 'ё', 'е'),
                '[^a-zа-я0-9]+',
                ' ',
                'g'
            )
        )
    END
$$;

DROP MATERIALIZED VIEW IF EXISTS marketing.mart_marketing_campaign_demand_forecast;
DROP MATERIALIZED VIEW IF EXISTS marketing.mart_marketing_query_forecast_ready;
DROP MATERIALIZED VIEW IF EXISTS marketing.mart_marketing_query_share_daily;
DROP MATERIALIZED VIEW IF EXISTS marketing.mart_marketing_query_demand_daily;

-- V2 is query x native measurement window. frequency belongs to that window,
-- not to dt. Daily values retain row references and independent NULLs.
CREATE OR REPLACE VIEW marketing.v_search_query_window_v2 AS
WITH orders_snapshots AS (
    SELECT *, max(snapshot_hour) OVER (
        PARTITION BY current_period_start, current_period_end, nm_id, text
    ) AS latest_snapshot_hour
    FROM marketing.wb_search_query_orders_text_daily
),
orders_latest AS (
    SELECT DISTINCT ON (current_period_start, current_period_end, nm_id, text, dt)
        id, current_period_start, current_period_end, nm_id, text, dt,
        frequency, orders_count, avg_position, snapshot_hour, last_synced_at
    FROM orders_snapshots
    -- A partial newer response must not inherit old days and look complete.
    WHERE snapshot_hour = latest_snapshot_hour
    ORDER BY current_period_start, current_period_end, nm_id, text, dt,
             snapshot_hour DESC, last_synced_at DESC NULLS LAST, id DESC
),
orders_windows AS (
    SELECT current_period_start, current_period_end, nm_id, text,
        count(*) AS daily_rows,
        count(*) FILTER (WHERE dt BETWEEN current_period_start AND current_period_end) AS in_window_days,
        count(orders_count) AS order_values,
        count(frequency) AS frequency_values,
        count(DISTINCT frequency) AS frequency_variants,
        min(frequency) AS frequency_min,
        max(frequency) AS frequency_max,
        min(orders_count) AS orders_min,
        sum(orders_count) AS partial_orders_sum,
        max(snapshot_hour) AS snapshot_at,
        jsonb_agg(jsonb_build_object(
            'row_id', id, 'day', dt, 'snapshot_at', snapshot_hour,
            'window_frequency_copy', frequency, 'orders', orders_count, 'avg_position', avg_position
        ) ORDER BY dt) AS daily_observations
    FROM orders_latest
    GROUP BY current_period_start, current_period_end, nm_id, text
),
texts_latest AS (
    SELECT DISTINCT ON (current_period_start, current_period_end, nm_id, text, top_order_by)
        id, current_period_start, current_period_end, nm_id, text, top_order_by,
        frequency_current, orders_current, avg_position_current,
        snapshot_hour, last_synced_at
    FROM marketing.wb_search_query_texts
    ORDER BY current_period_start, current_period_end, nm_id, text, top_order_by,
             snapshot_hour DESC, last_synced_at DESC NULLS LAST, id DESC
),
texts_windows AS (
    SELECT current_period_start, current_period_end, nm_id, text,
        count(*) AS contexts,
        count(frequency_current) AS frequency_values,
        count(DISTINCT frequency_current) AS frequency_variants,
        min(frequency_current) AS frequency_min,
        max(frequency_current) AS frequency_max,
        count(orders_current) AS order_values,
        count(DISTINCT orders_current) AS order_variants,
        min(orders_current) AS orders_min,
        max(orders_current) AS orders_max,
        count(avg_position_current) AS position_values,
        count(DISTINCT avg_position_current) AS position_variants,
        min(avg_position_current) AS position_min,
        max(avg_position_current) AS position_max,
        max(snapshot_hour) AS snapshot_at,
        jsonb_agg(jsonb_build_object(
            'row_id', id, 'top_order_by', top_order_by, 'snapshot_at', snapshot_hour,
            'frequency', frequency_current, 'orders', orders_current,
            'avg_position', avg_position_current
        ) ORDER BY top_order_by) AS text_observations
    FROM texts_latest
    GROUP BY current_period_start, current_period_end, nm_id, text
),
joined AS (
    SELECT coalesce(o.current_period_start,t.current_period_start) AS current_period_start,
        coalesce(o.current_period_end,t.current_period_end) AS current_period_end,
        coalesce(o.nm_id,t.nm_id) AS nm_id, coalesce(o.text,t.text) AS search_text,
        o.daily_rows, o.in_window_days, o.partial_orders_sum,
        o.daily_observations, t.text_observations,
        greatest(o.snapshot_at,t.snapshot_at) AS snapshot_at,
        CASE WHEN o.frequency_variants = 1 AND o.frequency_values = o.daily_rows
                  AND o.frequency_min >= 0 THEN o.frequency_max END AS order_frequency,
        CASE WHEN t.frequency_variants = 1 AND t.frequency_values = t.contexts
                  AND t.frequency_min >= 0 THEN t.frequency_max END AS text_frequency,
        coalesce(o.frequency_variants > 1 OR o.frequency_min < 0
            OR (o.frequency_values > 0 AND o.frequency_values < o.daily_rows),false)
            OR coalesce(t.frequency_variants > 1 OR t.frequency_min < 0
            OR (t.frequency_values > 0 AND t.frequency_values < t.contexts),false) AS frequency_conflict,
        CASE WHEN o.current_period_start <= o.current_period_end
                  AND o.daily_rows = o.current_period_end - o.current_period_start + 1
                  AND o.in_window_days = o.daily_rows AND o.order_values = o.daily_rows
                  AND o.orders_min >= 0 THEN o.partial_orders_sum END AS daily_orders,
        CASE WHEN t.order_variants = 1 AND t.order_values = t.contexts
                  AND t.orders_min >= 0 THEN t.orders_max END AS text_orders,
        coalesce(t.order_variants > 1 OR t.orders_min < 0
            OR (t.order_values > 0 AND t.order_values < t.contexts),false)
            OR coalesce(o.orders_min < 0,false) AS orders_conflict,
        CASE WHEN t.position_variants = 1 AND t.position_values = t.contexts
                  AND t.position_min > 0 THEN t.position_max END AS text_position,
        coalesce(t.position_variants > 1 OR t.position_min <= 0
            OR (t.position_values > 0 AND t.position_values < t.contexts),false) AS position_conflict
    FROM orders_windows o FULL JOIN texts_windows t
      ON t.current_period_start=o.current_period_start
     AND t.current_period_end=o.current_period_end AND t.nm_id=o.nm_id AND t.text=o.text
),
resolved AS (
    SELECT *, current_period_end - current_period_start + 1 AS expected_days,
        CASE WHEN current_period_start > current_period_end THEN 'invalid_window'
             WHEN frequency_conflict OR (order_frequency IS NOT NULL AND text_frequency IS NOT NULL
                 AND order_frequency <> text_frequency) THEN 'conflicting_or_invalid_values'
             WHEN coalesce(order_frequency,text_frequency) IS NULL THEN 'missing'
             ELSE 'native_window_value' END AS frequency_status,
        CASE WHEN current_period_start > current_period_end THEN 'invalid_window'
             WHEN orders_conflict OR (daily_orders IS NOT NULL AND text_orders IS NOT NULL
                 AND daily_orders <> text_orders)
                 OR (in_window_days = daily_rows AND partial_orders_sum > text_orders)
                 THEN 'conflicting_or_invalid_values'
             WHEN coalesce(daily_orders,text_orders) IS NULL THEN 'missing_or_partial_days'
             ELSE 'native_window_value' END AS orders_status,
        CASE WHEN current_period_start > current_period_end THEN 'invalid_window'
             WHEN position_conflict THEN 'conflicting_or_invalid_values'
             WHEN text_position IS NULL THEN 'missing_no_daily_weights'
             ELSE 'native_window_value' END AS avg_position_status
    FROM joined
)
SELECT 2::integer AS version, current_period_start, current_period_end, nm_id, search_text,
    CASE WHEN frequency_status='native_window_value' THEN coalesce(order_frequency,text_frequency) END AS frequency,
    frequency_status,
    CASE WHEN frequency_status <> 'native_window_value' THEN 'unresolved'
         WHEN order_frequency IS NOT NULL THEN 'orders_text_native_window'
         ELSE 'search_texts_native_window' END AS frequency_source,
    CASE WHEN orders_status='native_window_value' THEN coalesce(daily_orders,text_orders) END AS orders_count,
    orders_status,
    CASE WHEN orders_status <> 'native_window_value' THEN 'unresolved'
         WHEN daily_orders IS NOT NULL THEN 'complete_native_days'
         ELSE 'search_texts_native_window' END AS orders_source,
    CASE WHEN avg_position_status='native_window_value' THEN text_position END AS avg_position,
    avg_position_status, coalesce(daily_rows,0) AS daily_rows,
    coalesce(in_window_days,0) AS in_window_days, expected_days, partial_orders_sum,
    coalesce(daily_observations,'[]'::jsonb) AS daily_observations,
    coalesce(text_observations,'[]'::jsonb) AS text_observations,
    snapshot_at, 'not_evaluated'::text AS lineage_status
FROM resolved;

CREATE MATERIALIZED VIEW marketing.mart_marketing_query_demand_daily AS
-- Compatibility projection for the existing trailing-seven-day forecast.
-- Other windows remain accessible in v_search_query_window_v2, never merged.
SELECT current_period_end AS snapshot_date, nm_id, search_text,
    marketing.normalize_query_text(search_text) AS normalized_search_text,
    frequency, orders_count, avg_position, frequency_source,
    current_period_start, current_period_end
FROM marketing.v_search_query_window_v2
WHERE current_period_start = current_period_end - 6
WITH NO DATA;

CREATE UNIQUE INDEX idx_mart_marketing_query_demand_daily_key
    ON marketing.mart_marketing_query_demand_daily (snapshot_date, nm_id, search_text);
CREATE INDEX idx_mart_marketing_query_demand_daily_nm_date
    ON marketing.mart_marketing_query_demand_daily (nm_id, snapshot_date);
CREATE INDEX idx_mart_marketing_query_demand_daily_normalized
    ON marketing.mart_marketing_query_demand_daily (nm_id, normalized_search_text);

CREATE MATERIALIZED VIEW marketing.mart_marketing_query_share_daily AS
WITH demand_snapshots AS (
    SELECT DISTINCT snapshot_date
    FROM marketing.mart_marketing_query_demand_daily
),
marketing_query_7d AS (
    SELECT
        d.snapshot_date,
        q.advert_id,
        q.nm_id,
        q.norm_query,
        marketing.normalize_query_text(q.norm_query) AS normalized_norm_query,
        MAX(q.payment_type) FILTER (WHERE q.payment_type <> 'unknown') AS payment_type,
        MAX(q.campaign_name) AS campaign_name,
        SUM(COALESCE(q.views, 0)) AS ad_views,
        SUM(COALESCE(q.clicks, 0)) AS ad_clicks,
        SUM(COALESCE(q.orders, 0)) AS ad_orders,
        ROUND(SUM(COALESCE(q.spend, 0)), 2) AS ad_spend,
        AVG(q.avg_pos) AS avg_pos,
        CASE
            WHEN SUM(COALESCE(q.orders, 0)) > 0 THEN 'winner'
            WHEN SUM(COALESCE(q.spend, 0)) > 0 AND SUM(COALESCE(q.orders, 0)) = 0 AND SUM(COALESCE(q.clicks, 0)) > 0 THEN 'traffic_only'
            WHEN SUM(COALESCE(q.spend, 0)) > 0 AND SUM(COALESCE(q.orders, 0)) = 0 THEN 'waste'
            ELSE 'thin_data'
        END AS query_quality_band_7d
    FROM demand_snapshots d
    JOIN marketing.mart_marketing_query_daily q
        ON q.stat_date BETWEEN d.snapshot_date - INTERVAL '6 day' AND d.snapshot_date
    GROUP BY d.snapshot_date, q.advert_id, q.nm_id, q.norm_query
)
SELECT
    q.snapshot_date,
    q.advert_id,
    q.nm_id,
    q.norm_query,
    q.normalized_norm_query,
    q.payment_type,
    q.campaign_name,
    q.query_quality_band_7d,
    q.ad_views,
    q.ad_clicks,
    q.ad_orders,
    q.ad_spend,
    q.avg_pos,
    demand.query_frequency,
    demand.query_orders_total,
    demand.search_text,
    demand.frequency_source,
    CASE
        WHEN demand.query_frequency > 0 THEN ROUND(q.ad_views * 1.0 / demand.query_frequency, 4)
        ELSE NULL
    END AS ad_view_share,
    CASE
        WHEN q.ad_views > 0 THEN ROUND(q.ad_orders * 1000.0 / q.ad_views, 4)
        ELSE NULL
    END AS orders_per_1000_ad_views,
    CASE
        WHEN q.ad_views > 0 THEN ROUND(q.ad_clicks * 1.0 / q.ad_views, 4)
        ELSE NULL
    END AS observed_ctr,
    CASE
        WHEN q.ad_clicks > 0 THEN ROUND(q.ad_orders * 1.0 / q.ad_clicks, 4)
        ELSE NULL
    END AS cr_click_to_order,
    CASE
        WHEN q.ad_views > 0 THEN ROUND(q.ad_spend * 1000.0 / q.ad_views, 4)
        ELSE NULL
    END AS effective_cpm,
    CASE
        WHEN q.ad_clicks > 0 THEN ROUND(q.ad_spend * 1.0 / q.ad_clicks, 4)
        ELSE NULL
    END AS effective_cpc,
    CASE
        WHEN demand.frequency_source = 'normalized_query_ambiguous' THEN 'demand_unresolved'
        WHEN demand.search_text IS NULL THEN 'demand_unresolved'
        WHEN demand.query_frequency IS NULL THEN 'frequency_missing_or_conflicting'
        WHEN demand.query_frequency = 0 THEN 'frequency_zero'
        ELSE 'resolved'
    END AS share_resolution_status
FROM marketing_query_7d q
LEFT JOIN (
    SELECT
        snapshot_date,
        nm_id,
        normalized_search_text,
        CASE WHEN count(*) = 1 THEN min(search_text) END AS search_text,
        CASE WHEN count(*) = 1 THEN max(frequency) END AS query_frequency,
        CASE WHEN count(*) = 1 THEN max(orders_count) END AS query_orders_total,
        CASE WHEN count(*) = 1 THEN min(frequency_source)
             ELSE 'normalized_query_ambiguous' END AS frequency_source
    FROM marketing.mart_marketing_query_demand_daily
    GROUP BY snapshot_date, nm_id, normalized_search_text
) demand
    ON demand.snapshot_date = q.snapshot_date
   AND demand.nm_id = q.nm_id
   AND demand.normalized_search_text = q.normalized_norm_query
WITH NO DATA;

CREATE UNIQUE INDEX idx_mart_marketing_query_share_daily_key
    ON marketing.mart_marketing_query_share_daily (snapshot_date, advert_id, nm_id, norm_query);
CREATE INDEX idx_mart_marketing_query_share_daily_advert
    ON marketing.mart_marketing_query_share_daily (advert_id, snapshot_date);
CREATE INDEX idx_mart_marketing_query_share_daily_resolution
    ON marketing.mart_marketing_query_share_daily (share_resolution_status);
CREATE INDEX idx_mart_marketing_query_share_daily_normalized
    ON marketing.mart_marketing_query_share_daily (nm_id, normalized_norm_query);

CREATE MATERIALIZED VIEW marketing.mart_marketing_query_forecast_ready AS
SELECT
    snapshot_date,
    advert_id,
    nm_id,
    norm_query,
    payment_type,
    campaign_name,
    query_quality_band_7d,
    share_resolution_status,
    search_text,
    query_frequency,
    query_orders_total,
    ad_views,
    ad_clicks,
    ad_orders,
    ad_spend,
    avg_pos,
    ad_view_share,
    orders_per_1000_ad_views,
    observed_ctr,
    cr_click_to_order,
    effective_cpm,
    effective_cpc,
    CASE
        WHEN share_resolution_status = 'resolved' AND query_quality_band_7d IN ('winner', 'brand_defense') THEN 0.85
        WHEN share_resolution_status = 'resolved' AND query_quality_band_7d IN ('traffic_only', 'thin_data') THEN 0.50
        WHEN share_resolution_status = 'resolved' THEN 0.70
        ELSE 0.00
    END AS marginal_quality_coef,
    CASE
        WHEN share_resolution_status = 'resolved' AND ad_view_share IS NOT NULL THEN LEAST(ad_view_share * 1.10, 0.90)
        ELSE NULL
    END AS target_view_share_10pct,
    CASE
        WHEN share_resolution_status = 'resolved' AND ad_view_share IS NOT NULL THEN LEAST(ad_view_share * 1.15, 0.90)
        ELSE NULL
    END AS target_view_share_15pct,
    CASE
        WHEN share_resolution_status = 'resolved' AND query_frequency IS NOT NULL AND ad_view_share IS NOT NULL
            THEN ROUND(GREATEST(query_frequency * LEAST(ad_view_share * 1.10, 0.90) - ad_views, 0), 4)
        ELSE 0
    END AS extra_views_10pct,
    CASE
        WHEN share_resolution_status = 'resolved' AND query_frequency IS NOT NULL AND ad_view_share IS NOT NULL
            THEN ROUND(GREATEST(query_frequency * LEAST(ad_view_share * 1.15, 0.90) - ad_views, 0), 4)
        ELSE 0
    END AS extra_views_15pct,
    CASE
        WHEN COALESCE(payment_type, 'unknown') = 'cpc' THEN 'clicks_to_orders_to_spend'
        ELSE 'views_to_orders_to_budget'
    END AS forecast_method,
    CASE
        WHEN share_resolution_status = 'resolved' AND query_quality_band_7d = 'winner' THEN 'high'
        WHEN share_resolution_status = 'resolved' THEN 'medium'
        ELSE 'low'
    END AS confidence,
    CASE
        WHEN share_resolution_status = 'demand_unresolved' THEN 'investigate_match'
        WHEN share_resolution_status IN ('frequency_zero', 'frequency_missing_or_conflicting') THEN 'investigate_demand'
        WHEN query_quality_band_7d = 'winner' THEN 'scale_query'
        WHEN query_quality_band_7d IN ('traffic_only', 'waste') THEN 'hold'
        ELSE 'observe'
    END AS action_hint,
    CASE
        WHEN share_resolution_status = 'resolved' AND COALESCE(payment_type, 'unknown') = 'cpc'
            THEN ROUND(
                (GREATEST(query_frequency * LEAST(ad_view_share * 1.10, 0.90) - ad_views, 0) * COALESCE(observed_ctr, 0))
                * COALESCE(cr_click_to_order, 0)
                * CASE
                    WHEN query_quality_band_7d IN ('winner', 'brand_defense') THEN 0.85
                    WHEN query_quality_band_7d IN ('traffic_only', 'thin_data') THEN 0.50
                    ELSE 0.70
                END,
                4
            )
        WHEN share_resolution_status = 'resolved'
            THEN ROUND(
                COALESCE(orders_per_1000_ad_views, 0)
                * GREATEST(query_frequency * LEAST(ad_view_share * 1.10, 0.90) - ad_views, 0)
                / 1000.0
                * CASE
                    WHEN query_quality_band_7d IN ('winner', 'brand_defense') THEN 0.85
                    WHEN query_quality_band_7d IN ('traffic_only', 'thin_data') THEN 0.50
                    ELSE 0.70
                END,
                4
            )
        ELSE 0
    END AS extra_orders_10pct,
    CASE
        WHEN share_resolution_status = 'resolved' AND COALESCE(payment_type, 'unknown') = 'cpc'
            THEN ROUND(
                (GREATEST(query_frequency * LEAST(ad_view_share * 1.15, 0.90) - ad_views, 0) * COALESCE(observed_ctr, 0))
                * COALESCE(cr_click_to_order, 0)
                * CASE
                    WHEN query_quality_band_7d IN ('winner', 'brand_defense') THEN 0.85
                    WHEN query_quality_band_7d IN ('traffic_only', 'thin_data') THEN 0.50
                    ELSE 0.70
                END,
                4
            )
        WHEN share_resolution_status = 'resolved'
            THEN ROUND(
                COALESCE(orders_per_1000_ad_views, 0)
                * GREATEST(query_frequency * LEAST(ad_view_share * 1.15, 0.90) - ad_views, 0)
                / 1000.0
                * CASE
                    WHEN query_quality_band_7d IN ('winner', 'brand_defense') THEN 0.85
                    WHEN query_quality_band_7d IN ('traffic_only', 'thin_data') THEN 0.50
                    ELSE 0.70
                END,
                4
            )
        ELSE 0
    END AS extra_orders_15pct,
    CASE
        WHEN share_resolution_status = 'resolved' AND COALESCE(payment_type, 'unknown') = 'cpc'
            THEN ROUND(
                (GREATEST(query_frequency * LEAST(ad_view_share * 1.10, 0.90) - ad_views, 0) * COALESCE(observed_ctr, 0))
                * COALESCE(effective_cpc, 0),
                4
            )
        WHEN share_resolution_status = 'resolved'
            THEN ROUND(
                COALESCE(effective_cpm, 0)
                * GREATEST(query_frequency * LEAST(ad_view_share * 1.10, 0.90) - ad_views, 0)
                / 1000.0,
                4
            )
        ELSE 0
    END AS extra_spend_10pct,
    CASE
        WHEN share_resolution_status = 'resolved' AND COALESCE(payment_type, 'unknown') = 'cpc'
            THEN ROUND(
                (GREATEST(query_frequency * LEAST(ad_view_share * 1.15, 0.90) - ad_views, 0) * COALESCE(observed_ctr, 0))
                * COALESCE(effective_cpc, 0),
                4
            )
        WHEN share_resolution_status = 'resolved'
            THEN ROUND(
                COALESCE(effective_cpm, 0)
                * GREATEST(query_frequency * LEAST(ad_view_share * 1.15, 0.90) - ad_views, 0)
                / 1000.0,
                4
            )
        ELSE 0
    END AS extra_spend_15pct
FROM marketing.mart_marketing_query_share_daily
WITH NO DATA;

CREATE UNIQUE INDEX idx_mart_marketing_query_forecast_ready_key
    ON marketing.mart_marketing_query_forecast_ready (snapshot_date, advert_id, nm_id, norm_query);
CREATE INDEX idx_mart_marketing_query_forecast_ready_advert
    ON marketing.mart_marketing_query_forecast_ready (advert_id, snapshot_date);
CREATE INDEX idx_mart_marketing_query_forecast_ready_action
    ON marketing.mart_marketing_query_forecast_ready (action_hint, confidence);

CREATE MATERIALIZED VIEW marketing.mart_marketing_campaign_demand_forecast AS
WITH top_growth_queries AS (
    SELECT
        snapshot_date,
        advert_id,
        norm_query,
        extra_views_15pct,
        extra_orders_15pct,
        ROW_NUMBER() OVER (
            PARTITION BY snapshot_date, advert_id
            ORDER BY extra_orders_15pct DESC, extra_views_15pct DESC, norm_query
        ) AS rn
    FROM marketing.mart_marketing_query_forecast_ready
    WHERE action_hint = 'scale_query'
),
top_growth_summary AS (
    SELECT
        snapshot_date,
        advert_id,
        STRING_AGG(
            norm_query || ' (+' || ROUND(extra_orders_15pct, 2)::text || ' orders)',
            '; ' ORDER BY rn
        ) AS growth_destination_summary
    FROM top_growth_queries
    WHERE rn <= 3
    GROUP BY snapshot_date, advert_id
),
campaign_base AS (
    SELECT
        snapshot_date,
        advert_id,
        MAX(campaign_name) AS campaign_name,
        MAX(payment_type) FILTER (WHERE payment_type <> 'unknown') AS payment_type,
        COUNT(*) FILTER (WHERE action_hint = 'scale_query') AS eligible_queries_count,
        COUNT(*) FILTER (WHERE share_resolution_status = 'demand_unresolved') AS demand_unresolved_queries_count,
        SUM(COALESCE(query_frequency, 0)) FILTER (WHERE share_resolution_status = 'resolved') AS baseline_query_demand,
        SUM(COALESCE(ad_views, 0)) FILTER (WHERE share_resolution_status = 'resolved') AS baseline_ad_views,
        ROUND(SUM(COALESCE(extra_views_10pct, 0)), 4) AS extra_views_10pct,
        ROUND(SUM(COALESCE(extra_views_15pct, 0)), 4) AS extra_views_15pct,
        ROUND(SUM(COALESCE(extra_orders_10pct, 0)), 4) AS extra_orders_10pct,
        ROUND(SUM(COALESCE(extra_orders_15pct, 0)), 4) AS extra_orders_15pct,
        ROUND(SUM(COALESCE(extra_spend_10pct, 0)), 4) AS extra_spend_10pct,
        ROUND(SUM(COALESCE(extra_spend_15pct, 0)), 4) AS extra_spend_15pct
    FROM marketing.mart_marketing_query_forecast_ready
    GROUP BY snapshot_date, advert_id
)
SELECT
    base.snapshot_date,
    base.advert_id,
    base.campaign_name,
    base.payment_type,
    base.eligible_queries_count,
    base.demand_unresolved_queries_count,
    base.baseline_query_demand,
    base.baseline_ad_views,
    CASE
        WHEN base.baseline_query_demand > 0
            THEN ROUND(
                base.baseline_ad_views * 1.0 / NULLIF(base.baseline_query_demand, 0),
                4
            )
        ELSE NULL
    END AS baseline_view_share,
    base.extra_views_10pct,
    base.extra_views_15pct,
    base.extra_orders_10pct,
    base.extra_orders_15pct,
    base.extra_spend_10pct,
    base.extra_spend_15pct,
    COALESCE(
        summary.growth_destination_summary,
        'Нет подтверждённых query для масштабирования'
    ) AS growth_destination_summary,
    CASE
        WHEN base.eligible_queries_count > 0
             AND base.extra_orders_15pct > 0 THEN 'scale_limited'
        WHEN base.demand_unresolved_queries_count > 0
             AND base.eligible_queries_count = 0 THEN 'investigate'
        ELSE 'hold'
    END AS decision_hint
FROM campaign_base base
LEFT JOIN top_growth_summary summary
    ON summary.snapshot_date = base.snapshot_date
   AND summary.advert_id = base.advert_id
WITH NO DATA;

CREATE UNIQUE INDEX idx_mart_marketing_campaign_demand_forecast_key
    ON marketing.mart_marketing_campaign_demand_forecast (snapshot_date, advert_id);
CREATE INDEX idx_mart_marketing_campaign_demand_forecast_decision
    ON marketing.mart_marketing_campaign_demand_forecast (decision_hint);
