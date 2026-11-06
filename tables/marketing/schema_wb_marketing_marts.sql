CREATE SCHEMA IF NOT EXISTS marketing;

DROP MATERIALIZED VIEW IF EXISTS marketing.mart_marketing_forecast_ready;
DROP MATERIALIZED VIEW IF EXISTS marketing.mart_marketing_query_bands;
DROP MATERIALIZED VIEW IF EXISTS marketing.mart_marketing_campaign_daily;
DROP MATERIALIZED VIEW IF EXISTS marketing.mart_marketing_query_daily;

CREATE MATERIALIZED VIEW marketing.mart_marketing_query_daily AS
WITH latest_campaigns AS (
    SELECT DISTINCT ON (external_id)
        external_id AS advert_id,
        name AS campaign_name,
        status AS campaign_status,
        COALESCE(
            NULLIF(LOWER(payment_type), ''),
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM marketing.wb_marketing_normquery_bids bids
                    WHERE bids.advert_id = c.external_id
                ) THEN 'cpm'
                WHEN EXISTS (
                    SELECT 1
                    FROM marketing.wb_marketing_campaign_nms nms
                    WHERE nms.advert_id = c.external_id
                      AND COALESCE(nms.bid_search_kopecks, 0) + COALESCE(nms.bid_recommendations_kopecks, 0) > 0
                ) THEN 'cpc'
                ELSE 'unknown'
            END
        ) AS payment_type,
        brand
    FROM marketing.wb_marketing_campaigns c
    ORDER BY external_id, snapshot_hour DESC
),
latest_campaign_nms AS (
    SELECT DISTINCT ON (advert_id, nm_id)
        advert_id,
        nm_id,
        subject_name
    FROM marketing.wb_marketing_campaign_nms
    ORDER BY advert_id, nm_id, snapshot_hour DESC
),
latest_query_bids AS (
    SELECT DISTINCT ON (advert_id, nm_id, norm_query)
        advert_id,
        nm_id,
        norm_query,
        bid AS current_cluster_bid
    FROM marketing.wb_marketing_normquery_bids
    ORDER BY advert_id, nm_id, norm_query, snapshot_hour DESC
),
latest_query_clusters AS (
    SELECT DISTINCT ON (advert_id, nm_id, norm_query)
        advert_id,
        nm_id,
        norm_query,
        is_active AS is_active_cluster
    FROM marketing.wb_marketing_normquery_clusters
    WHERE is_active = TRUE
    ORDER BY advert_id, nm_id, norm_query, snapshot_hour DESC
),
latest_query_minus AS (
    SELECT DISTINCT ON (advert_id, nm_id, norm_query)
        advert_id,
        nm_id,
        norm_query,
        TRUE AS is_minus_phrase
    FROM marketing.wb_marketing_normquery_minus
    ORDER BY advert_id, nm_id, norm_query, snapshot_hour DESC
)
SELECT
    stats.stat_date,
    stats.advert_id,
    campaigns.campaign_name,
    campaigns.payment_type,
    campaigns.campaign_status,
    stats.nm_id,
    COALESCE(nms.subject_name, '') AS subject_name,
    stats.norm_query,
    COALESCE(bids.current_cluster_bid, 0) AS current_cluster_bid,
    COALESCE(clusters.is_active_cluster, FALSE) AS is_active_cluster,
    COALESCE(minus.is_minus_phrase, FALSE) AS is_minus_phrase,
    COALESCE(stats.views, 0) AS views,
    COALESCE(stats.clicks, 0) AS clicks,
    COALESCE(stats.orders, 0) AS orders,
    COALESCE(stats.spend, 0)::numeric(14, 2) AS spend,
    stats.ctr,
    stats.cpc,
    stats.cpm,
    stats.avg_pos,
    CASE
        WHEN COALESCE(stats.views, 0) > 0 THEN ROUND(COALESCE(stats.orders, 0) * 1000.0 / stats.views, 4)
        ELSE NULL
    END AS orders_per_1000_views,
    CASE
        WHEN COALESCE(stats.clicks, 0) > 0 THEN ROUND(COALESCE(stats.orders, 0) * 1.0 / stats.clicks, 4)
        ELSE NULL
    END AS cr_click_to_order,
    CASE
        WHEN COALESCE(stats.views, 0) > 0 THEN ROUND(COALESCE(stats.spend, 0) * 1000.0 / stats.views, 4)
        ELSE NULL
    END AS effective_cpm,
    CASE
        WHEN COALESCE(stats.clicks, 0) > 0 THEN ROUND(COALESCE(stats.spend, 0) * 1.0 / stats.clicks, 4)
        ELSE NULL
    END AS effective_cpc,
    CASE
        WHEN COALESCE(stats.orders, 0) > 0 THEN ROUND(COALESCE(stats.spend, 0) * 1.0 / stats.orders, 4)
        ELSE NULL
    END AS cpa,
    CASE
        WHEN COALESCE(stats.orders, 0) > 0 THEN 'winner'
        WHEN campaigns.brand IS NOT NULL
         AND campaigns.brand <> ''
         AND POSITION(LOWER(campaigns.brand) IN LOWER(stats.norm_query)) > 0 THEN 'brand_defense'
        WHEN COALESCE(stats.spend, 0) > 0 AND COALESCE(stats.orders, 0) = 0 AND COALESCE(stats.clicks, 0) > 0 THEN 'traffic_only'
        WHEN COALESCE(stats.spend, 0) > 0 AND COALESCE(stats.orders, 0) = 0 THEN 'waste'
        ELSE 'thin_data'
    END AS query_quality_band
FROM marketing.wb_marketing_normquery_stats_daily stats
LEFT JOIN latest_campaigns campaigns
    ON campaigns.advert_id = stats.advert_id
LEFT JOIN latest_campaign_nms nms
    ON nms.advert_id = stats.advert_id
   AND nms.nm_id = stats.nm_id
LEFT JOIN latest_query_bids bids
    ON bids.advert_id = stats.advert_id
   AND bids.nm_id = stats.nm_id
   AND bids.norm_query = stats.norm_query
LEFT JOIN latest_query_clusters clusters
    ON clusters.advert_id = stats.advert_id
   AND clusters.nm_id = stats.nm_id
   AND clusters.norm_query = stats.norm_query
LEFT JOIN latest_query_minus minus
    ON minus.advert_id = stats.advert_id
   AND minus.nm_id = stats.nm_id
   AND minus.norm_query = stats.norm_query
WITH NO DATA;

CREATE UNIQUE INDEX idx_mart_marketing_query_daily_key
    ON marketing.mart_marketing_query_daily (stat_date, advert_id, nm_id, norm_query);
CREATE INDEX idx_mart_marketing_query_daily_advert_date
    ON marketing.mart_marketing_query_daily (advert_id, stat_date);
CREATE INDEX idx_mart_marketing_query_daily_band
    ON marketing.mart_marketing_query_daily (query_quality_band);

CREATE MATERIALIZED VIEW marketing.mart_marketing_campaign_daily AS
WITH query_agg AS (
    SELECT
        stat_date,
        advert_id,
        SUM(views) AS query_views,
        SUM(clicks) AS query_clicks,
        SUM(orders) AS query_orders,
        ROUND(SUM(spend), 2) AS query_spend,
        AVG(CASE WHEN query_quality_band = 'winner' THEN 1.0 ELSE 0.0 END) AS winner_query_share,
        AVG(CASE WHEN query_quality_band IN ('waste', 'traffic_only') THEN 1.0 ELSE 0.0 END) AS waste_query_share,
        MAX(payment_type) FILTER (WHERE payment_type <> 'unknown') AS payment_type
    FROM marketing.mart_marketing_query_daily
    GROUP BY stat_date, advert_id
),
latest_budget AS (
    SELECT DISTINCT ON (advert_id)
        advert_id,
        total AS budget_total
    FROM marketing.wb_marketing_budget
    ORDER BY advert_id, snapshot_hour DESC
),
latest_campaigns AS (
    SELECT DISTINCT ON (external_id)
        external_id AS advert_id,
        name AS campaign_name,
        status AS campaign_status,
        COALESCE(
            NULLIF(LOWER(payment_type), ''),
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM marketing.wb_marketing_normquery_bids bids
                    WHERE bids.advert_id = c.external_id
                ) THEN 'cpm'
                WHEN EXISTS (
                    SELECT 1
                    FROM marketing.wb_marketing_campaign_nms nms
                    WHERE nms.advert_id = c.external_id
                      AND COALESCE(nms.bid_search_kopecks, 0) + COALESCE(nms.bid_recommendations_kopecks, 0) > 0
                ) THEN 'cpc'
                ELSE 'unknown'
            END
        ) AS payment_type
    FROM marketing.wb_marketing_campaigns c
    ORDER BY external_id, snapshot_hour DESC
)
SELECT
    stats.stat_date,
    stats.advert_id,
    campaigns.campaign_name,
    COALESCE(query_agg.payment_type, campaigns.payment_type, 'unknown') AS payment_type,
    campaigns.campaign_status,
    COALESCE(stats.views, 0) AS views,
    COALESCE(stats.clicks, 0) AS clicks,
    COALESCE(stats.orders, 0) AS orders,
    COALESCE(stats.sum_spend, 0)::numeric(14, 2) AS spend,
    stats.ctr,
    stats.cpc,
    stats.cr,
    CASE
        WHEN COALESCE(stats.orders, 0) > 0 THEN ROUND(COALESCE(stats.sum_spend, 0) * 1.0 / stats.orders, 4)
        ELSE NULL
    END AS cpa,
    COALESCE(query_agg.query_views, 0) AS query_views,
    COALESCE(query_agg.query_clicks, 0) AS query_clicks,
    COALESCE(query_agg.query_orders, 0) AS query_orders,
    COALESCE(query_agg.query_spend, 0)::numeric(14, 2) AS query_spend,
    ROUND(COALESCE(query_agg.winner_query_share, 0), 4) AS winner_query_share,
    ROUND(COALESCE(query_agg.waste_query_share, 0), 4) AS waste_query_share,
    COALESCE(budget.budget_total, 0)::numeric(14, 2) AS budget_total,
    CASE
        WHEN COALESCE(stats.orders, 0) > 0
         AND COALESCE(query_agg.winner_query_share, 0) >= 0.5
         AND COALESCE(query_agg.waste_query_share, 0) <= 0.25 THEN TRUE
        ELSE FALSE
    END AS is_scale_candidate,
    CASE
        WHEN COALESCE(stats.sum_spend, 0) > 0
         AND COALESCE(stats.orders, 0) = 0
         AND COALESCE(query_agg.waste_query_share, 0) >= 0.5 THEN TRUE
        ELSE FALSE
    END AS is_cut_candidate
FROM marketing.wb_marketing_campaign_stats_daily stats
LEFT JOIN query_agg
    ON query_agg.stat_date = stats.stat_date
   AND query_agg.advert_id = stats.advert_id
LEFT JOIN latest_budget budget
    ON budget.advert_id = stats.advert_id
LEFT JOIN latest_campaigns campaigns
    ON campaigns.advert_id = stats.advert_id
WITH NO DATA;

CREATE UNIQUE INDEX idx_mart_marketing_campaign_daily_key
    ON marketing.mart_marketing_campaign_daily (stat_date, advert_id);
CREATE INDEX idx_mart_marketing_campaign_daily_advert
    ON marketing.mart_marketing_campaign_daily (advert_id, stat_date);
CREATE INDEX idx_mart_marketing_campaign_daily_scale
    ON marketing.mart_marketing_campaign_daily (is_scale_candidate, is_cut_candidate);

CREATE MATERIALIZED VIEW marketing.mart_marketing_query_bands AS
WITH anchor AS (
    SELECT COALESCE(
        (SELECT MAX(snapshot_date) FROM marketing.wb_marketing_campaigns),
        CURRENT_DATE
    ) AS snapshot_date
),
windowed AS (
    SELECT
        anchor.snapshot_date,
        q.advert_id,
        q.nm_id,
        q.norm_query,
        MAX(q.campaign_name) AS campaign_name,
        MAX(q.payment_type) AS payment_type,
        MAX(q.query_quality_band) FILTER (WHERE q.query_quality_band = 'brand_defense') AS brand_band,
        SUM(q.views) AS views_7d,
        SUM(q.clicks) AS clicks_7d,
        SUM(q.orders) AS orders_7d,
        ROUND(SUM(q.spend), 2) AS spend_7d,
        AVG(q.avg_pos) AS avg_pos_7d
    FROM marketing.mart_marketing_query_daily q
    CROSS JOIN anchor
    WHERE q.stat_date BETWEEN anchor.snapshot_date - INTERVAL '6 day' AND anchor.snapshot_date
    GROUP BY anchor.snapshot_date, q.advert_id, q.nm_id, q.norm_query
)
SELECT
    snapshot_date::date AS snapshot_date,
    advert_id,
    nm_id,
    norm_query,
    campaign_name,
    payment_type,
    COALESCE(views_7d, 0) AS views_7d,
    COALESCE(clicks_7d, 0) AS clicks_7d,
    COALESCE(orders_7d, 0) AS orders_7d,
    COALESCE(spend_7d, 0)::numeric(14, 2) AS spend_7d,
    ROUND(avg_pos_7d::numeric, 2) AS avg_pos_7d,
    CASE
        WHEN COALESCE(views_7d, 0) > 0 THEN ROUND(COALESCE(orders_7d, 0) * 1000.0 / views_7d, 4)
        ELSE NULL
    END AS orders_per_1000_views_7d,
    CASE
        WHEN COALESCE(views_7d, 0) > 0 THEN ROUND(COALESCE(spend_7d, 0) * 1000.0 / views_7d, 4)
        ELSE NULL
    END AS effective_cpm_7d,
    CASE
        WHEN COALESCE(clicks_7d, 0) > 0 THEN ROUND(COALESCE(spend_7d, 0) * 1.0 / clicks_7d, 4)
        ELSE NULL
    END AS effective_cpc_7d,
    CASE
        WHEN COALESCE(orders_7d, 0) > 0 THEN ROUND(COALESCE(spend_7d, 0) * 1.0 / orders_7d, 4)
        ELSE NULL
    END AS cpa_7d,
    CASE
        WHEN brand_band IS NOT NULL THEN 'brand_defense'
        WHEN COALESCE(orders_7d, 0) > 0 AND COALESCE(spend_7d, 0) > 0 THEN 'winner'
        WHEN COALESCE(spend_7d, 0) > 0 AND COALESCE(orders_7d, 0) = 0 AND COALESCE(clicks_7d, 0) > 0 THEN 'traffic_only'
        WHEN COALESCE(spend_7d, 0) > 0 AND COALESCE(orders_7d, 0) = 0 THEN 'waste'
        ELSE 'thin_data'
    END AS query_band
FROM windowed
WITH NO DATA;

CREATE UNIQUE INDEX idx_mart_marketing_query_bands_key
    ON marketing.mart_marketing_query_bands (snapshot_date, advert_id, nm_id, norm_query);
CREATE INDEX idx_mart_marketing_query_bands_advert
    ON marketing.mart_marketing_query_bands (advert_id, snapshot_date);
CREATE INDEX idx_mart_marketing_query_bands_band
    ON marketing.mart_marketing_query_bands (query_band);

CREATE MATERIALIZED VIEW marketing.mart_marketing_forecast_ready AS
WITH anchor AS (
    SELECT COALESCE(
        (SELECT MAX(snapshot_date) FROM marketing.mart_marketing_query_bands),
        CURRENT_DATE
    ) AS snapshot_date
),
campaign_window AS (
    SELECT
        anchor.snapshot_date,
        c.advert_id,
        MAX(c.campaign_name) AS campaign_name,
        MAX(c.payment_type) AS payment_type,
        SUM(c.views) AS baseline_views_7d,
        SUM(c.clicks) AS baseline_clicks_7d,
        SUM(c.orders) AS baseline_orders_7d,
        ROUND(SUM(c.spend), 2) AS baseline_spend_7d
    FROM marketing.mart_marketing_campaign_daily c
    CROSS JOIN anchor
    WHERE c.stat_date BETWEEN anchor.snapshot_date - INTERVAL '6 day' AND anchor.snapshot_date
    GROUP BY anchor.snapshot_date, c.advert_id
),
query_window AS (
    SELECT
        qb.snapshot_date,
        qb.advert_id,
        AVG(CASE WHEN qb.query_band = 'winner' THEN 1.0 ELSE 0.0 END) AS winner_query_share_7d,
        AVG(CASE WHEN qb.query_band IN ('waste', 'traffic_only') THEN 1.0 ELSE 0.0 END) AS waste_query_share_7d
    FROM marketing.mart_marketing_query_bands qb
    GROUP BY qb.snapshot_date, qb.advert_id
)
SELECT
    cw.snapshot_date::date AS snapshot_date,
    cw.advert_id,
    cw.campaign_name,
    CASE
        WHEN COALESCE(NULLIF(LOWER(cw.payment_type), ''), 'unknown') IN ('cpc', 'cpm')
            THEN LOWER(cw.payment_type)
        WHEN COALESCE(qw.winner_query_share_7d, 0) > 0
            THEN 'cpm'
        ELSE 'unknown'
    END AS payment_type,
    COALESCE(cw.baseline_views_7d, 0) AS baseline_views_7d,
    COALESCE(cw.baseline_clicks_7d, 0) AS baseline_clicks_7d,
    COALESCE(cw.baseline_orders_7d, 0) AS baseline_orders_7d,
    COALESCE(cw.baseline_spend_7d, 0)::numeric(14, 2) AS baseline_spend_7d,
    CASE
        WHEN COALESCE(cw.baseline_views_7d, 0) > 0 THEN ROUND(COALESCE(cw.baseline_orders_7d, 0) * 1000.0 / cw.baseline_views_7d, 4)
        ELSE NULL
    END AS orders_per_1000_views_7d,
    CASE
        WHEN COALESCE(cw.baseline_clicks_7d, 0) > 0 THEN ROUND(COALESCE(cw.baseline_orders_7d, 0) * 1.0 / cw.baseline_clicks_7d, 4)
        ELSE NULL
    END AS cr_click_to_order_7d,
    CASE
        WHEN COALESCE(cw.baseline_views_7d, 0) > 0 THEN ROUND(COALESCE(cw.baseline_spend_7d, 0) * 1000.0 / cw.baseline_views_7d, 4)
        ELSE NULL
    END AS effective_cpm_7d,
    CASE
        WHEN COALESCE(cw.baseline_clicks_7d, 0) > 0 THEN ROUND(COALESCE(cw.baseline_spend_7d, 0) * 1.0 / cw.baseline_clicks_7d, 4)
        ELSE NULL
    END AS effective_cpc_7d,
    ROUND(COALESCE(qw.winner_query_share_7d, 0), 4) AS winner_query_share_7d,
    ROUND(COALESCE(qw.waste_query_share_7d, 0), 4) AS waste_query_share_7d,
    CASE
        WHEN COALESCE(qw.winner_query_share_7d, 0) >= 0.5 AND COALESCE(qw.waste_query_share_7d, 0) <= 0.25 THEN 0.85
        WHEN COALESCE(qw.waste_query_share_7d, 0) >= 0.5 THEN 0.50
        ELSE 0.70
    END AS marginal_quality_coef,
    CASE
        WHEN COALESCE(qw.winner_query_share_7d, 0) >= 0.5 AND COALESCE(qw.waste_query_share_7d, 0) <= 0.25 THEN 0.15
        WHEN COALESCE(qw.waste_query_share_7d, 0) >= 0.5 THEN 0.00
        ELSE 0.10
    END AS safe_growth_pct,
    CASE
        WHEN COALESCE(cw.baseline_views_7d, 0) > 0 THEN ROUND(cw.baseline_views_7d * 0.10, 2)
        ELSE 0
    END AS extra_views_10pct,
    CASE
        WHEN COALESCE(cw.baseline_clicks_7d, 0) > 0 THEN ROUND(cw.baseline_clicks_7d * 0.10, 2)
        ELSE 0
    END AS extra_clicks_10pct,
    CASE
        WHEN COALESCE(cw.baseline_views_7d, 0) > 0 THEN ROUND(cw.baseline_views_7d * 0.15, 2)
        ELSE 0
    END AS extra_views_15pct,
    CASE
        WHEN COALESCE(cw.baseline_clicks_7d, 0) > 0 THEN ROUND(cw.baseline_clicks_7d * 0.15, 2)
        ELSE 0
    END AS extra_clicks_15pct,
    CASE
        WHEN COALESCE(NULLIF(LOWER(cw.payment_type), ''), 'unknown') = 'cpc'
            THEN ROUND(
                COALESCE(
                    CASE
                        WHEN COALESCE(cw.baseline_clicks_7d, 0) > 0 THEN (cw.baseline_spend_7d * 1.0 / cw.baseline_clicks_7d) * (cw.baseline_clicks_7d * 0.10)
                        ELSE 0
                    END,
                    0
                ),
                2
            )
        ELSE ROUND(
            COALESCE(
                CASE
                    WHEN COALESCE(cw.baseline_views_7d, 0) > 0 THEN (cw.baseline_spend_7d * 1000.0 / cw.baseline_views_7d) * (cw.baseline_views_7d * 0.10) / 1000.0
                    ELSE 0
                END,
                0
            ),
            2
        )
    END AS extra_spend_10pct,
    CASE
        WHEN COALESCE(NULLIF(LOWER(cw.payment_type), ''), 'unknown') = 'cpc'
            THEN ROUND(
                COALESCE(
                    CASE
                        WHEN COALESCE(cw.baseline_clicks_7d, 0) > 0 THEN (cw.baseline_spend_7d * 1.0 / cw.baseline_clicks_7d) * (cw.baseline_clicks_7d * 0.15)
                        ELSE 0
                    END,
                    0
                ),
                2
            )
        ELSE ROUND(
            COALESCE(
                CASE
                    WHEN COALESCE(cw.baseline_views_7d, 0) > 0 THEN (cw.baseline_spend_7d * 1000.0 / cw.baseline_views_7d) * (cw.baseline_views_7d * 0.15) / 1000.0
                    ELSE 0
                END,
                0
            ),
            2
        )
    END AS extra_spend_15pct,
    CASE
        WHEN COALESCE(NULLIF(LOWER(cw.payment_type), ''), 'unknown') = 'cpc'
            THEN ROUND(
                COALESCE(
                    CASE
                        WHEN COALESCE(cw.baseline_clicks_7d, 0) > 0 THEN (cw.baseline_orders_7d * 1.0 / cw.baseline_clicks_7d) * (cw.baseline_clicks_7d * 0.10)
                        ELSE 0
                    END,
                    0
                ) *
                CASE
                    WHEN COALESCE(qw.winner_query_share_7d, 0) >= 0.5 AND COALESCE(qw.waste_query_share_7d, 0) <= 0.25 THEN 0.85
                    WHEN COALESCE(qw.waste_query_share_7d, 0) >= 0.5 THEN 0.50
                    ELSE 0.70
                END,
                4
            )
        ELSE ROUND(
            COALESCE(
                CASE
                    WHEN COALESCE(cw.baseline_views_7d, 0) > 0 THEN (cw.baseline_orders_7d * 1000.0 / cw.baseline_views_7d) * (cw.baseline_views_7d * 0.10) / 1000.0
                    ELSE 0
                END,
                0
            ) *
            CASE
                WHEN COALESCE(qw.winner_query_share_7d, 0) >= 0.5 AND COALESCE(qw.waste_query_share_7d, 0) <= 0.25 THEN 0.85
                WHEN COALESCE(qw.waste_query_share_7d, 0) >= 0.5 THEN 0.50
                ELSE 0.70
            END,
            4
        )
    END AS extra_orders_10pct,
    CASE
        WHEN COALESCE(NULLIF(LOWER(cw.payment_type), ''), 'unknown') = 'cpc'
            THEN ROUND(
                COALESCE(
                    CASE
                        WHEN COALESCE(cw.baseline_clicks_7d, 0) > 0 THEN (cw.baseline_orders_7d * 1.0 / cw.baseline_clicks_7d) * (cw.baseline_clicks_7d * 0.15)
                        ELSE 0
                    END,
                    0
                ) *
                CASE
                    WHEN COALESCE(qw.winner_query_share_7d, 0) >= 0.5 AND COALESCE(qw.waste_query_share_7d, 0) <= 0.25 THEN 0.85
                    WHEN COALESCE(qw.waste_query_share_7d, 0) >= 0.5 THEN 0.50
                    ELSE 0.70
                END,
                4
            )
        ELSE ROUND(
            COALESCE(
                CASE
                    WHEN COALESCE(cw.baseline_views_7d, 0) > 0 THEN (cw.baseline_orders_7d * 1000.0 / cw.baseline_views_7d) * (cw.baseline_views_7d * 0.15) / 1000.0
                    ELSE 0
                END,
                0
            ) *
            CASE
                WHEN COALESCE(qw.winner_query_share_7d, 0) >= 0.5 AND COALESCE(qw.waste_query_share_7d, 0) <= 0.25 THEN 0.85
                WHEN COALESCE(qw.waste_query_share_7d, 0) >= 0.5 THEN 0.50
                ELSE 0.70
            END,
            4
        )
    END AS extra_orders_15pct,
    CASE
        WHEN COALESCE(NULLIF(LOWER(cw.payment_type), ''), 'unknown') = 'cpc' THEN 'clicks_to_orders_to_spend'
        WHEN COALESCE(NULLIF(LOWER(cw.payment_type), ''), 'unknown') = 'cpm' THEN 'views_to_orders_to_budget'
        ELSE 'unknown'
    END AS forecast_method,
    CASE
        WHEN COALESCE(cw.baseline_orders_7d, 0) >= 10 AND COALESCE(qw.winner_query_share_7d, 0) >= 0.5 THEN 'high'
        WHEN COALESCE(cw.baseline_orders_7d, 0) >= 3 THEN 'medium'
        ELSE 'low'
    END AS confidence,
    CASE
        WHEN (
            CASE
                WHEN COALESCE(qw.winner_query_share_7d, 0) >= 0.5 AND COALESCE(qw.waste_query_share_7d, 0) <= 0.25 THEN 0.15
                WHEN COALESCE(qw.waste_query_share_7d, 0) >= 0.5 THEN 0.00
                ELSE 0.10
            END
        ) = 0.15 THEN 'scale_limited'
        WHEN (
            CASE
                WHEN COALESCE(qw.winner_query_share_7d, 0) >= 0.5 AND COALESCE(qw.waste_query_share_7d, 0) <= 0.25 THEN 0.15
                WHEN COALESCE(qw.waste_query_share_7d, 0) >= 0.5 THEN 0.00
                ELSE 0.10
            END
        ) = 0.10 THEN 'hold_or_test'
        ELSE 'hold'
    END AS decision_hint
FROM campaign_window cw
LEFT JOIN query_window qw
    ON qw.snapshot_date = cw.snapshot_date
   AND qw.advert_id = cw.advert_id
WITH NO DATA;

CREATE UNIQUE INDEX idx_mart_marketing_forecast_ready_key
    ON marketing.mart_marketing_forecast_ready (snapshot_date, advert_id);
CREATE INDEX idx_mart_marketing_forecast_ready_decision
    ON marketing.mart_marketing_forecast_ready (decision_hint, confidence);
