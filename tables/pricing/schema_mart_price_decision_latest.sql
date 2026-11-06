CREATE SCHEMA IF NOT EXISTS pricing;

DROP MATERIALIZED VIEW IF EXISTS pricing.mart_price_decision_latest;

CREATE MATERIALIZED VIEW pricing.mart_price_decision_latest AS
WITH latest_price_snapshot AS (
    SELECT
        p.snapshot_date,
        p.nm_id,
        NULLIF(p.vendor_code, '') AS vendor_code,
        COALESCE(p.club_discounted_price, p.discounted_price, p.price) AS price_current
    FROM pricing.v_wb_supplier_prices_latest_snapshot p
    WHERE p.nm_id IS NOT NULL
      AND COALESCE(p.club_discounted_price, p.discounted_price, p.price) IS NOT NULL
      AND COALESCE(p.club_discounted_price, p.discounted_price, p.price) > 0
),
latest_mart_date AS (
    SELECT MAX(report_date) AS report_date
    FROM analytics_ai.mart_ai_sales_planning
),
latest_sales_date AS (
    SELECT MAX(report_date) AS report_date
    FROM sales.wb_sales_funnel_products_daily
),
mart_latest AS (
    SELECT
        m.report_date,
        m.nm_id,
        NULLIF(m.vendor_code, '') AS vendor_code,
        NULLIF(m.brand_name, '') AS brand_name,
        NULLIF(m.subject_name, '') AS subject_name,
        COALESCE(m.stock_qty, 0) AS stock_qty,
        m.price_elasticity_point,
        m.elasticity_rolling_4w
    FROM analytics_ai.mart_ai_sales_planning m
    JOIN latest_mart_date d
      ON d.report_date = m.report_date
    WHERE m.nm_id IS NOT NULL
      AND COALESCE(m.stock_qty, 0) > 0
),
sales_7d AS (
    SELECT
        s.nm_id,
        ROUND(SUM(COALESCE(s.order_count, 0))::numeric, 4) AS baseline_orders_7d,
        ROUND(SUM(COALESCE(s.order_sum, 0))::numeric, 2) AS baseline_revenue_gross_7d,
        ROUND(SUM(COALESCE(s.buyout_count, 0))::numeric, 4) AS baseline_buyouts_7d
    FROM sales.wb_sales_funnel_products_daily s
    JOIN latest_sales_date d
      ON s.report_date BETWEEN d.report_date - INTERVAL '6 day' AND d.report_date
    WHERE s.nm_id IS NOT NULL
    GROUP BY s.nm_id
),
active_calc_scenarios AS (
    SELECT DISTINCT ON (s.nm_id)
        s.scenario_id,
        s.nm_id,
        s.updated_at
    FROM finance.wb_profit_calculator_scenarios s
    WHERE s.nm_id IS NOT NULL
      AND s.is_active = TRUE
    ORDER BY s.nm_id, s.updated_at DESC, s.scenario_id DESC
),
calc_current AS (
    SELECT
        r.scenario_id,
        r.nm_id,
        NULLIF(r.vendor_code, '') AS vendor_code,
        NULLIF(r.brand_name, '') AS brand_name,
        NULLIF(r.subject_name, '') AS subject_name,
        r.sales_model,
        r.price_after_discount_rub,
        r.net_profit_rub AS net_profit_rub_current,
        r.margin_pct AS margin_pct_current,
        r.cost_price_rub,
        r.ad_percent,
        r.tax_percent,
        r.kvv_pct,
        r.expected_outbound_per_buyout_rub,
        r.expected_return_logistics_rub,
        r.storage_total_rub,
        r.other_expenses_rub,
        r.calculation_status
    FROM active_calc_scenarios s
    JOIN finance.wb_profit_calculator_results r
      ON r.scenario_id = s.scenario_id
),
latest_marketing_stat_date AS (
    SELECT MAX(stat_date) AS stat_date
    FROM marketing.wb_marketing_campaign_stats_daily_nms
),
marketing_nm_advert_7d AS (
    SELECT
        s.nm_id,
        s.advert_id,
        ROUND(SUM(COALESCE(s.sum_spend, 0))::numeric, 2) AS spend_7d
    FROM marketing.wb_marketing_campaign_stats_daily_nms s
    JOIN latest_marketing_stat_date d
      ON s.stat_date BETWEEN d.stat_date - INTERVAL '6 day' AND d.stat_date
    WHERE s.nm_id IS NOT NULL
    GROUP BY s.nm_id, s.advert_id
),
latest_marketing_forecast_date AS (
    SELECT MAX(snapshot_date) AS snapshot_date
    FROM marketing.mart_marketing_forecast_ready
),
marketing_forecast_latest AS (
    SELECT
        m.snapshot_date,
        m.advert_id,
        m.winner_query_share_7d,
        m.waste_query_share_7d,
        m.marginal_quality_coef,
        m.safe_growth_pct,
        m.confidence,
        m.decision_hint
    FROM marketing.mart_marketing_forecast_ready m
    JOIN latest_marketing_forecast_date d
      ON d.snapshot_date = m.snapshot_date
),
marketing_joined AS (
    SELECT
        a.nm_id,
        a.advert_id,
        a.spend_7d,
        f.winner_query_share_7d,
        f.waste_query_share_7d,
        f.marginal_quality_coef,
        f.safe_growth_pct,
        f.confidence,
        f.decision_hint
    FROM marketing_nm_advert_7d a
    LEFT JOIN marketing_forecast_latest f
      ON f.advert_id = a.advert_id
),
marketing_dominant AS (
    SELECT
        ranked.nm_id,
        ranked.confidence AS marketing_confidence,
        ranked.decision_hint AS marketing_decision_hint
    FROM (
        SELECT
            j.*,
            ROW_NUMBER() OVER (
                PARTITION BY j.nm_id
                ORDER BY j.spend_7d DESC, j.advert_id
            ) AS rn
        FROM marketing_joined j
    ) ranked
    WHERE ranked.rn = 1
),
marketing_weighted AS (
    SELECT
        j.nm_id,
        ROUND(SUM(j.spend_7d)::numeric, 2) AS baseline_adv_spend_7d,
        CASE
            WHEN SUM(j.spend_7d) > 0 THEN ROUND(SUM(j.winner_query_share_7d * j.spend_7d)::numeric / SUM(j.spend_7d), 4)
            ELSE NULL
        END AS marketing_winner_query_share_7d,
        CASE
            WHEN SUM(j.spend_7d) > 0 THEN ROUND(SUM(j.waste_query_share_7d * j.spend_7d)::numeric / SUM(j.spend_7d), 4)
            ELSE NULL
        END AS marketing_waste_query_share_7d,
        CASE
            WHEN SUM(j.spend_7d) > 0 THEN ROUND(SUM(j.marginal_quality_coef * j.spend_7d)::numeric / SUM(j.spend_7d), 4)
            ELSE NULL
        END AS marketing_marginal_quality_coef,
        CASE
            WHEN SUM(j.spend_7d) > 0 THEN ROUND(SUM(j.safe_growth_pct * j.spend_7d)::numeric / SUM(j.spend_7d), 4)
            ELSE NULL
        END AS marketing_safe_growth_pct
    FROM marketing_joined j
    GROUP BY j.nm_id
),
price_ai_latest AS (
    SELECT
        a.run_date AS price_ai_run_date,
        a.source_nm_id AS nm_id,
        COALESCE(a.competitor_count, 0) AS competitor_count,
        a.competitor_price_min,
        a.competitor_price_median,
        a.competitor_price_max
    FROM analytics_ai.v_wb_price_ai_analysis_latest a
),
base AS (
    SELECT
        p.snapshot_date,
        p.nm_id,
        COALESCE(m.vendor_code, p.vendor_code, c.vendor_code) AS vendor_code,
        COALESCE(m.brand_name, c.brand_name) AS brand_name,
        COALESCE(m.subject_name, c.subject_name) AS subject_name,
        p.price_current,
        m.stock_qty,
        COALESCE(s7.baseline_orders_7d, 0) AS baseline_orders_7d,
        COALESCE(s7.baseline_revenue_gross_7d, 0) AS baseline_revenue_gross_7d,
        COALESCE(s7.baseline_revenue_gross_7d, 0) AS baseline_revenue_net_7d,
        COALESCE(s7.baseline_buyouts_7d, 0) AS baseline_buyouts_7d,
        COALESCE(mw.baseline_adv_spend_7d, 0) AS baseline_adv_spend_7d,
        CASE
            WHEN m.elasticity_rolling_4w BETWEEN -5.0 AND -0.3 THEN m.elasticity_rolling_4w
            WHEN m.price_elasticity_point BETWEEN -5.0 AND -0.3 THEN m.price_elasticity_point
            ELSE -2.0
        END AS elasticity_to_apply,
        CASE
            WHEN m.elasticity_rolling_4w BETWEEN -5.0 AND -0.3 THEN 'rolling_4w'
            WHEN m.price_elasticity_point BETWEEN -5.0 AND -0.3 THEN 'point'
            ELSE 'fallback_default'
        END AS elasticity_source,
        md.marketing_decision_hint,
        COALESCE(mw.marketing_safe_growth_pct, 0.10) AS marketing_safe_growth_pct,
        COALESCE(mw.marketing_marginal_quality_coef, 0.70) AS marketing_marginal_quality_coef,
        mw.marketing_winner_query_share_7d,
        mw.marketing_waste_query_share_7d,
        COALESCE(md.marketing_confidence, 'low') AS marketing_confidence,
        CASE
            WHEN mw.nm_id IS NOT NULL THEN TRUE
            ELSE FALSE
        END AS has_marketing_signal,
        ai.competitor_count,
        ai.competitor_price_min,
        ai.competitor_price_median,
        ai.competitor_price_max,
        ai.price_ai_run_date,
        CASE
            WHEN ai.price_ai_run_date IS NOT NULL
             AND ai.price_ai_run_date >= p.snapshot_date - 7 THEN TRUE
            ELSE FALSE
        END AS price_ai_is_fresh,
        c.scenario_id,
        c.sales_model,
        c.price_after_discount_rub,
        c.net_profit_rub_current,
        c.margin_pct_current,
        c.cost_price_rub,
        c.ad_percent,
        c.tax_percent,
        c.kvv_pct,
        c.expected_outbound_per_buyout_rub,
        c.expected_return_logistics_rub,
        c.storage_total_rub,
        c.other_expenses_rub
    FROM latest_price_snapshot p
    JOIN mart_latest m
      ON m.nm_id = p.nm_id
    LEFT JOIN sales_7d s7
      ON s7.nm_id = p.nm_id
    JOIN calc_current c
      ON c.nm_id = p.nm_id
     AND c.calculation_status = 'ok'
    LEFT JOIN marketing_weighted mw
      ON mw.nm_id = p.nm_id
    LEFT JOIN marketing_dominant md
      ON md.nm_id = p.nm_id
    LEFT JOIN price_ai_latest ai
      ON ai.nm_id = p.nm_id
),
bounded AS (
    SELECT
        b.*,
        GREATEST(5, (ROUND(b.price_current * 0.85 / 5.0) * 5)::int) AS candidate_price_min,
        GREATEST(5, (ROUND(b.price_current * (1 + COALESCE(b.marketing_safe_growth_pct, 0.10)) / 5.0) * 5)::int) AS candidate_price_growth_cap,
        CASE
            WHEN b.price_ai_is_fresh
             AND COALESCE(b.competitor_count, 0) >= 3
             AND b.competitor_price_max IS NOT NULL
             AND b.competitor_price_max > 0
            THEN TRUE
            ELSE FALSE
        END AS market_ceiling_enabled,
        CASE
            WHEN b.price_ai_is_fresh
             AND COALESCE(b.competitor_count, 0) >= 3
             AND b.competitor_price_max IS NOT NULL
             AND b.competitor_price_max > 0
            THEN (FLOOR(b.competitor_price_max / 5.0) * 5)::int
            ELSE NULL
        END AS market_ceiling_price,
        5::int AS candidate_step_rub
    FROM base b
),
candidate_bounds AS (
    SELECT
        b.*,
        CASE
            WHEN b.market_ceiling_enabled THEN LEAST(b.candidate_price_growth_cap, b.market_ceiling_price)
            ELSE b.candidate_price_growth_cap
        END AS candidate_price_max,
        ROUND(COALESCE(b.baseline_orders_7d, 0) * COALESCE(b.net_profit_rub_current, 0), 2) AS current_net_profit_7d
    FROM bounded b
),
candidate_grid AS (
    SELECT
        b.nm_id,
        gs::numeric(12, 2) AS candidate_price
    FROM candidate_bounds b
    CROSS JOIN LATERAL generate_series(b.candidate_price_min, b.candidate_price_max, b.candidate_step_rub) gs
),
candidate_eval AS (
    SELECT
        b.nm_id,
        g.candidate_price,
        ROUND(
            b.baseline_orders_7d
            * POWER(g.candidate_price / NULLIF(b.price_current, 0), b.elasticity_to_apply),
            4
        ) AS expected_orders_7d,
        ROUND(g.candidate_price * COALESCE(b.kvv_pct, 0) / 100.0, 2) AS expected_kvv_rub,
        ROUND(g.candidate_price * COALESCE(b.ad_percent, 0) / 100.0, 2) AS expected_ad_rub,
        ROUND(g.candidate_price * COALESCE(b.tax_percent, 0) / 100.0, 2) AS expected_tax_rub,
        ROUND(
            g.candidate_price
            - ROUND(g.candidate_price * COALESCE(b.kvv_pct, 0) / 100.0, 2)
            - COALESCE(b.expected_outbound_per_buyout_rub, 0)
            - COALESCE(b.expected_return_logistics_rub, 0)
            - COALESCE(b.storage_total_rub, 0)
            - COALESCE(b.cost_price_rub, 0)
            - ROUND(g.candidate_price * COALESCE(b.ad_percent, 0) / 100.0, 2)
            - COALESCE(b.other_expenses_rub, 0)
            - ROUND(g.candidate_price * COALESCE(b.tax_percent, 0) / 100.0, 2),
            2
        ) AS expected_net_profit_per_unit,
        ROUND(
            ROUND(
                g.candidate_price
                - ROUND(g.candidate_price * COALESCE(b.kvv_pct, 0) / 100.0, 2)
                - COALESCE(b.expected_outbound_per_buyout_rub, 0)
                - COALESCE(b.expected_return_logistics_rub, 0)
                - COALESCE(b.storage_total_rub, 0)
                - COALESCE(b.cost_price_rub, 0)
                - ROUND(g.candidate_price * COALESCE(b.ad_percent, 0) / 100.0, 2)
                - COALESCE(b.other_expenses_rub, 0)
                - ROUND(g.candidate_price * COALESCE(b.tax_percent, 0) / 100.0, 2),
                2
            ) / NULLIF(g.candidate_price, 0) * 100,
            2
        ) AS expected_margin_pct,
        ROUND(
            ROUND(
                b.baseline_orders_7d
                * POWER(g.candidate_price / NULLIF(b.price_current, 0), b.elasticity_to_apply),
                4
            ) *
            ROUND(
                g.candidate_price
                - ROUND(g.candidate_price * COALESCE(b.kvv_pct, 0) / 100.0, 2)
                - COALESCE(b.expected_outbound_per_buyout_rub, 0)
                - COALESCE(b.expected_return_logistics_rub, 0)
                - COALESCE(b.storage_total_rub, 0)
                - COALESCE(b.cost_price_rub, 0)
                - ROUND(g.candidate_price * COALESCE(b.ad_percent, 0) / 100.0, 2)
                - COALESCE(b.other_expenses_rub, 0)
                - ROUND(g.candidate_price * COALESCE(b.tax_percent, 0) / 100.0, 2),
                2
            ),
            2
        ) AS expected_net_profit_7d,
        CASE
            WHEN COALESCE(b.baseline_adv_spend_7d, 0) = 0 THEN 0::numeric
            WHEN ROUND(
                b.baseline_orders_7d
                * POWER(g.candidate_price / NULLIF(b.price_current, 0), b.elasticity_to_apply),
                4
            ) * g.candidate_price > 0
            THEN ROUND(
                b.baseline_adv_spend_7d
                / NULLIF(
                    ROUND(
                        b.baseline_orders_7d
                        * POWER(g.candidate_price / NULLIF(b.price_current, 0), b.elasticity_to_apply),
                        4
                    ) * g.candidate_price,
                    0
                ),
                4
            )
            ELSE NULL
        END AS expected_drr
    FROM candidate_bounds b
    JOIN candidate_grid g
      ON g.nm_id = b.nm_id
),
candidate_scored AS (
    SELECT
        e.*,
        (e.expected_margin_pct >= 30) AS passes_margin_guardrail,
        (COALESCE(e.expected_drr, 0) <= 0.12) AS passes_drr_guardrail,
        ((e.expected_margin_pct >= 30) AND (COALESCE(e.expected_drr, 0) <= 0.12)) AS passes_all_guardrails
    FROM candidate_eval e
),
candidate_summary AS (
    SELECT
        s.nm_id,
        COUNT(*) AS candidate_count,
        COUNT(*) FILTER (WHERE s.passes_margin_guardrail) AS margin_pass_count,
        COUNT(*) FILTER (WHERE s.passes_drr_guardrail) AS drr_pass_count,
        COUNT(*) FILTER (WHERE s.passes_all_guardrails) AS pass_count
    FROM candidate_scored s
    GROUP BY s.nm_id
),
best_candidate AS (
    SELECT
        ranked.nm_id,
        ranked.candidate_price,
        ranked.expected_orders_7d,
        ranked.expected_net_profit_7d,
        ranked.expected_margin_pct
    FROM (
        SELECT
            s.*,
            ROW_NUMBER() OVER (
                PARTITION BY s.nm_id
                ORDER BY s.expected_net_profit_7d DESC, ABS(s.candidate_price - b.price_current), s.candidate_price DESC
            ) AS rn
        FROM candidate_scored s
        JOIN candidate_bounds b
          ON b.nm_id = s.nm_id
        WHERE s.passes_all_guardrails
    ) ranked
    WHERE ranked.rn = 1
)
SELECT
    b.snapshot_date,
    b.nm_id,
    b.vendor_code,
    b.brand_name,
    b.subject_name,
    b.price_current,
    b.stock_qty,
    b.baseline_orders_7d,
    b.baseline_revenue_gross_7d,
    b.baseline_revenue_net_7d,
    b.baseline_buyouts_7d,
    b.baseline_adv_spend_7d,
    b.elasticity_to_apply,
    b.elasticity_source,
    b.marketing_decision_hint,
    b.marketing_safe_growth_pct,
    b.marketing_marginal_quality_coef,
    b.marketing_winner_query_share_7d,
    b.marketing_waste_query_share_7d,
    b.marketing_confidence,
    b.competitor_count,
    b.competitor_price_min,
    b.competitor_price_median,
    b.competitor_price_max,
    b.price_ai_run_date,
    b.scenario_id,
    b.sales_model,
    b.price_after_discount_rub,
    b.net_profit_rub_current,
    b.margin_pct_current,
    b.cost_price_rub,
    b.ad_percent,
    b.tax_percent,
    b.expected_outbound_per_buyout_rub,
    b.expected_return_logistics_rub,
    b.storage_total_rub,
    b.other_expenses_rub,
    b.candidate_price_min,
    b.candidate_price_max,
    b.candidate_step_rub,
    CASE
        WHEN b.baseline_orders_7d <= 0 THEN b.price_current
        WHEN COALESCE(s.candidate_count, 0) = 0 THEN b.price_current
        WHEN COALESCE(s.pass_count, 0) = 0 THEN b.price_current
        ELSE c.candidate_price
    END AS recommended_price,
    ROUND(
        CASE
            WHEN b.baseline_orders_7d <= 0 THEN b.price_current
            WHEN COALESCE(s.candidate_count, 0) = 0 THEN b.price_current
            WHEN COALESCE(s.pass_count, 0) = 0 THEN b.price_current
            ELSE c.candidate_price
        END - b.price_current,
        2
    ) AS recommended_price_delta_abs,
    ROUND(
        (
            CASE
                WHEN b.baseline_orders_7d <= 0 THEN b.price_current
                WHEN COALESCE(s.candidate_count, 0) = 0 THEN b.price_current
                WHEN COALESCE(s.pass_count, 0) = 0 THEN b.price_current
                ELSE c.candidate_price
            END - b.price_current
        ) / NULLIF(b.price_current, 0) * 100,
        2
    ) AS recommended_price_delta_pct,
    CASE
        WHEN b.baseline_orders_7d <= 0 THEN b.baseline_orders_7d
        WHEN COALESCE(s.candidate_count, 0) = 0 THEN b.baseline_orders_7d
        WHEN COALESCE(s.pass_count, 0) = 0 THEN b.baseline_orders_7d
        ELSE c.expected_orders_7d
    END AS expected_orders_7d,
    CASE
        WHEN b.baseline_orders_7d <= 0 THEN b.current_net_profit_7d
        WHEN COALESCE(s.candidate_count, 0) = 0 THEN b.current_net_profit_7d
        WHEN COALESCE(s.pass_count, 0) = 0 THEN b.current_net_profit_7d
        ELSE c.expected_net_profit_7d
    END AS expected_net_profit_7d,
    CASE
        WHEN b.baseline_orders_7d <= 0 THEN b.margin_pct_current
        WHEN COALESCE(s.candidate_count, 0) = 0 THEN b.margin_pct_current
        WHEN COALESCE(s.pass_count, 0) = 0 THEN b.margin_pct_current
        ELSE c.expected_margin_pct
    END AS expected_margin_pct,
    CASE
        WHEN b.baseline_orders_7d <= 0 THEN 'hold'
        WHEN COALESCE(s.candidate_count, 0) = 0 THEN 'no_candidate'
        WHEN COALESCE(s.pass_count, 0) = 0 THEN 'hold'
        WHEN c.candidate_price > b.price_current THEN 'raise'
        WHEN c.candidate_price < b.price_current THEN 'lower'
        ELSE 'hold'
    END AS decision_status,
    CASE
        WHEN b.elasticity_source <> 'fallback_default'
         AND b.baseline_orders_7d >= 10
         AND COALESCE(b.marketing_confidence, 'low') IN ('high', 'medium')
        THEN 'high'
        WHEN b.elasticity_source <> 'fallback_default'
         AND b.baseline_orders_7d >= 3
        THEN 'medium'
        ELSE 'low'
    END AS decision_confidence,
    CASE
        WHEN b.baseline_orders_7d <= 0 THEN 'insufficient_demand'
        WHEN COALESCE(s.candidate_count, 0) = 0 AND b.market_ceiling_enabled THEN 'market_ceiling'
        WHEN COALESCE(s.candidate_count, 0) = 0 THEN 'guardrail_margin'
        WHEN COALESCE(s.pass_count, 0) = 0 AND COALESCE(s.margin_pass_count, 0) = 0 THEN 'guardrail_margin'
        WHEN COALESCE(s.pass_count, 0) = 0 AND COALESCE(s.drr_pass_count, 0) = 0 THEN 'guardrail_drr'
        WHEN COALESCE(s.pass_count, 0) = 0 THEN 'guardrail_margin'
        WHEN b.market_ceiling_enabled
         AND c.candidate_price = b.candidate_price_max
         AND b.candidate_price_max < b.candidate_price_growth_cap
        THEN 'market_ceiling'
        WHEN b.price_ai_run_date IS NOT NULL
         AND NOT b.price_ai_is_fresh
        THEN 'stale_price_ai'
        WHEN NOT b.has_marketing_signal THEN 'missing_marketing_signal'
        WHEN b.elasticity_source = 'fallback_default' THEN 'elasticity_fallback'
        ELSE 'gp_maximization'
    END AS decision_reason_code,
    b.market_ceiling_enabled,
    b.current_net_profit_7d
FROM candidate_bounds b
LEFT JOIN candidate_summary s
  ON s.nm_id = b.nm_id
LEFT JOIN best_candidate c
  ON c.nm_id = b.nm_id
WITH NO DATA;

CREATE UNIQUE INDEX idx_mart_price_decision_latest_nm_id
    ON pricing.mart_price_decision_latest (nm_id);

CREATE INDEX idx_mart_price_decision_latest_status
    ON pricing.mart_price_decision_latest (decision_status, decision_confidence);

COMMENT ON MATERIALIZED VIEW pricing.mart_price_decision_latest IS
'Latest-snapshot price decision mart for repricing. One row per nm_id with recommendation, economic guardrails, and marketing context. Baseline demand/revenue is sourced from sales.wb_sales_funnel_products_daily; marketing is contextual only.';
