CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_unit_economics') IS NOT NULL AND to_regclass('analytics_ai.wb_unit_economics') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_unit_economics SET SCHEMA analytics_ai';
    END IF;
END $$;

-- =============================================================================
-- Витрина юнит-экономики WB: analytics_ai.v_wb_unit_economics
--
-- Назначение:
--   Показать текущую цену товара, текущую комиссию WB по категории
--   и оценочный профит одной продажи до себестоимости товара.
--
-- Источники:
--   - pricing.wb_supplier_prices              : текущие цены
--   - pricing.v_wb_tariffs_commission_latest : текущие тарифы комиссии WB
--   - finance.wb_report_detail_daily         : фактические удержания и payout
--   - sales.wb_sales_funnel_products_daily : subject_id / subject_name / brand / vendor_code
--
-- Принципы расчёта:
--   - price_current = club_discounted_price -> discounted_price -> price
--   - tariff_commission_pct = paid_storage_kgvp
--     Это поле лучше всего совпадает с фактическим commission_percent из report_detail.
--   - прочие расходы (логистика, хранение, приёмка, штрафы, удержания)
--     берутся как средние фактические значения на единицу за последние 90 дней.
--   - profit считается ДО себестоимости товара (COGS здесь нет).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE OR REPLACE VIEW analytics_ai.v_wb_unit_economics AS
WITH latest_price_date AS (
    SELECT MAX(snapshot_date) AS snapshot_date
    FROM pricing.v_wb_supplier_prices_latest_snapshot
),

prices AS (
    SELECT
        p.snapshot_date,
        p.nm_id,
        NULLIF(p.vendor_code, '')                               AS vendor_code,
        p.currency_iso_code,
        p.discount,
        p.club_discount,
        p.price                                                AS price_list,
        p.discounted_price,
        p.club_discounted_price,
        COALESCE(p.club_discounted_price, p.discounted_price, p.price) AS price_current
    FROM pricing.v_wb_supplier_prices_latest_snapshot p
    JOIN latest_price_date d
      ON d.snapshot_date = p.snapshot_date
    WHERE p.nm_id IS NOT NULL
),

meta_funnel AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        subject_id,
        NULLIF(subject_name, '')                               AS subject_name,
        NULLIF(brand_name, '')                                 AS brand_name,
        NULLIF(vendor_code, '')                                AS vendor_code_meta
    FROM sales.wb_sales_funnel_products_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, report_date DESC, id DESC
),

meta_finance AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        NULLIF(subject_name, '')                               AS subject_name,
        NULLIF(brand_name, '')                                 AS brand_name
    FROM finance.wb_report_detail_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, COALESCE(sale_dt::date, date_to) DESC, rrd_id DESC
),

max_finance_date AS (
    SELECT MAX(COALESCE(sale_dt::date, date_to)) AS max_finance_date
    FROM finance.wb_report_detail_daily
),

sales_90d AS (
    SELECT
        r.nm_id,
        SUM(COALESCE(r.quantity, 0))                           AS sold_units_90d,
        SUM(COALESCE(r.retail_price_withdisc_rub, 0) * COALESCE(r.quantity, 0)) AS revenue_net_90d,
        SUM(ABS(COALESCE(r.ppvz_sales_commission, 0)))         AS sales_commission_rub_90d,
        SUM(ABS(COALESCE(r.acquiring_fee, 0)))                 AS acquiring_fee_rub_90d,
        SUM(GREATEST(COALESCE(r.delivery_rub, 0), 0))          AS delivery_rub_90d,
        SUM(GREATEST(COALESCE(r.storage_fee, 0), 0))           AS storage_fee_rub_90d,
        SUM(GREATEST(COALESCE(r.acceptance, 0), 0))            AS acceptance_rub_90d,
        SUM(GREATEST(COALESCE(r.penalty, 0), 0))               AS penalty_rub_90d,
        SUM(GREATEST(COALESCE(r.deduction, 0), 0))             AS deduction_rub_90d,
        SUM(COALESCE(r.ppvz_for_pay, 0))                       AS payout_rub_90d,
        ROUND(AVG(NULLIF(r.commission_percent, 0))::NUMERIC, 2) AS commission_percent_avg_90d,
        ROUND(AVG(NULLIF(r.acquiring_percent, 0))::NUMERIC, 2) AS acquiring_percent_avg_90d
    FROM finance.wb_report_detail_daily r
    CROSS JOIN max_finance_date m
    WHERE r.nm_id IS NOT NULL
      AND COALESCE(r.quantity, 0) > 0
      AND COALESCE(r.sale_dt::date, r.date_to) IS NOT NULL
      AND m.max_finance_date IS NOT NULL
      AND COALESCE(r.sale_dt::date, r.date_to) BETWEEN m.max_finance_date - 89 AND m.max_finance_date
      AND (r.doc_type_name IS NULL OR r.doc_type_name NOT ILIKE '%возврат%')
    GROUP BY r.nm_id
),

returns_90d AS (
    SELECT
        r.nm_id,
        SUM(ABS(COALESCE(r.quantity, 0)))                      AS returned_units_90d
    FROM finance.wb_report_detail_daily r
    CROSS JOIN max_finance_date m
    WHERE r.nm_id IS NOT NULL
      AND COALESCE(r.sale_dt::date, r.date_to) IS NOT NULL
      AND m.max_finance_date IS NOT NULL
      AND COALESCE(r.sale_dt::date, r.date_to) BETWEEN m.max_finance_date - 89 AND m.max_finance_date
      AND r.doc_type_name ILIKE '%возврат%'
    GROUP BY r.nm_id
),

base AS (
    SELECT
        p.snapshot_date,
        p.nm_id,
        COALESCE(p.vendor_code, mf.vendor_code_meta)           AS vendor_code,
        COALESCE(mf.brand_name, mfi.brand_name)                AS brand_name,
        mf.subject_id,
        COALESCE(mf.subject_name, mfi.subject_name)            AS subject_name,
        tc.parent_id,
        tc.parent_name,
        p.currency_iso_code,
        p.discount                                             AS price_discount_pct,
        p.club_discount                                        AS club_discount_pct,
        p.price_list,
        p.discounted_price,
        p.club_discounted_price,
        p.price_current,
        tc.kgvp_booking,
        tc.kgvp_marketplace,
        tc.kgvp_pickup,
        tc.kgvp_supplier,
        tc.kgvp_supplier_express,
        tc.paid_storage_kgvp                                   AS tariff_commission_pct,
        ROUND(
            s.revenue_net_90d / NULLIF(s.sold_units_90d, 0),
            2
        )                                                      AS avg_revenue_per_unit_90d,
        ROUND(
            s.sales_commission_rub_90d / NULLIF(s.revenue_net_90d, 0) * 100,
            2
        )                                                      AS actual_commission_pct_90d,
        ROUND(
            s.acquiring_fee_rub_90d / NULLIF(s.revenue_net_90d, 0) * 100,
            2
        )                                                      AS actual_acquiring_pct_90d,
        COALESCE(
            tc.paid_storage_kgvp,
            ROUND(s.sales_commission_rub_90d / NULLIF(s.revenue_net_90d, 0) * 100, 2),
            s.commission_percent_avg_90d
        )                                                      AS commission_pct_to_apply,
        COALESCE(
            ROUND(s.acquiring_fee_rub_90d / NULLIF(s.revenue_net_90d, 0) * 100, 2),
            s.acquiring_percent_avg_90d,
            0
        )                                                      AS acquiring_pct_to_apply,
        s.sold_units_90d,
        COALESCE(r.returned_units_90d, 0)                      AS returned_units_90d,
        ROUND(
            COALESCE(r.returned_units_90d, 0)::NUMERIC
            / NULLIF(s.sold_units_90d, 0) * 100,
            2
        )                                                      AS return_rate_90d_pct,
        ROUND(s.delivery_rub_90d / NULLIF(s.sold_units_90d, 0), 2)   AS avg_delivery_rub_per_unit_90d,
        ROUND(s.storage_fee_rub_90d / NULLIF(s.sold_units_90d, 0), 2) AS avg_storage_rub_per_unit_90d,
        ROUND(s.acceptance_rub_90d / NULLIF(s.sold_units_90d, 0), 2) AS avg_acceptance_rub_per_unit_90d,
        ROUND(s.penalty_rub_90d / NULLIF(s.sold_units_90d, 0), 2)    AS avg_penalty_rub_per_unit_90d,
        ROUND(s.deduction_rub_90d / NULLIF(s.sold_units_90d, 0), 2)  AS avg_deduction_rub_per_unit_90d,
        ROUND(s.payout_rub_90d / NULLIF(s.sold_units_90d, 0), 2)     AS historical_payout_rub_per_unit_90d
    FROM prices p
    LEFT JOIN meta_funnel mf
      ON mf.nm_id = p.nm_id
    LEFT JOIN meta_finance mfi
      ON mfi.nm_id = p.nm_id
    LEFT JOIN pricing.v_wb_tariffs_commission_latest tc
      ON tc.subject_id = mf.subject_id
      OR (
          mf.subject_id IS NULL
          AND tc.subject_name = COALESCE(mf.subject_name, mfi.subject_name)
      )
    LEFT JOIN sales_90d s
      ON s.nm_id = p.nm_id
    LEFT JOIN returns_90d r
      ON r.nm_id = p.nm_id
)

SELECT
    snapshot_date,
    nm_id,
    vendor_code,
    brand_name,
    subject_id,
    subject_name,
    parent_id,
    parent_name,
    currency_iso_code,
    price_discount_pct,
    club_discount_pct,
    price_list,
    discounted_price,
    club_discounted_price,
    price_current,
    kgvp_booking,
    kgvp_marketplace,
    kgvp_pickup,
    kgvp_supplier,
    kgvp_supplier_express,
    tariff_commission_pct,
    actual_commission_pct_90d,
    actual_acquiring_pct_90d,
    commission_pct_to_apply,
    acquiring_pct_to_apply,
    sold_units_90d,
    returned_units_90d,
    return_rate_90d_pct,
    avg_revenue_per_unit_90d,
    avg_delivery_rub_per_unit_90d,
    avg_storage_rub_per_unit_90d,
    avg_acceptance_rub_per_unit_90d,
    avg_penalty_rub_per_unit_90d,
    avg_deduction_rub_per_unit_90d,
    historical_payout_rub_per_unit_90d,
    CASE
        WHEN commission_pct_to_apply IS NULL THEN NULL
        ELSE ROUND(
            price_current * commission_pct_to_apply / 100,
            2
        )
    END AS estimated_commission_rub,
    ROUND(
        price_current * COALESCE(acquiring_pct_to_apply, 0) / 100,
        2
    ) AS estimated_acquiring_rub,
    ROUND(
        COALESCE(avg_delivery_rub_per_unit_90d, 0)
        + COALESCE(avg_storage_rub_per_unit_90d, 0)
        + COALESCE(avg_acceptance_rub_per_unit_90d, 0)
        + COALESCE(avg_penalty_rub_per_unit_90d, 0)
        + COALESCE(avg_deduction_rub_per_unit_90d, 0),
        2
    ) AS estimated_other_costs_rub,
    CASE
        WHEN commission_pct_to_apply IS NULL THEN NULL
        ELSE ROUND(
            price_current
            - (price_current * commission_pct_to_apply / 100)
            - (price_current * COALESCE(acquiring_pct_to_apply, 0) / 100)
            - COALESCE(avg_delivery_rub_per_unit_90d, 0)
            - COALESCE(avg_storage_rub_per_unit_90d, 0)
            - COALESCE(avg_acceptance_rub_per_unit_90d, 0)
            - COALESCE(avg_penalty_rub_per_unit_90d, 0)
            - COALESCE(avg_deduction_rub_per_unit_90d, 0),
            2
        )
    END AS estimated_profit_before_cogs_rub,
    CASE
        WHEN commission_pct_to_apply IS NULL THEN NULL
        ELSE ROUND(
            (
                price_current
                - (price_current * commission_pct_to_apply / 100)
                - (price_current * COALESCE(acquiring_pct_to_apply, 0) / 100)
                - COALESCE(avg_delivery_rub_per_unit_90d, 0)
                - COALESCE(avg_storage_rub_per_unit_90d, 0)
                - COALESCE(avg_acceptance_rub_per_unit_90d, 0)
                - COALESCE(avg_penalty_rub_per_unit_90d, 0)
                - COALESCE(avg_deduction_rub_per_unit_90d, 0)
            ) / NULLIF(price_current, 0) * 100,
            2
        )
    END AS estimated_margin_before_cogs_pct
FROM base;

COMMENT ON VIEW analytics_ai.v_wb_unit_economics IS
'Текущая витрина юнит-экономики WB по nm_id: цена, комиссия WB по тарифу и оценочный профит продажи до себестоимости товара.';

CREATE TABLE IF NOT EXISTS analytics_ai.wb_unit_economics AS
SELECT *
FROM analytics_ai.v_wb_unit_economics
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_unit_economics_nm_id
    ON analytics_ai.wb_unit_economics (nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_unit_economics_snapshot_date
    ON analytics_ai.wb_unit_economics (snapshot_date);

COMMENT ON TABLE analytics_ai.wb_unit_economics IS
'Физическая витрина юнит-экономики WB. Наполняется из analytics_ai.v_wb_unit_economics функцией analytics_ai.refresh_wb_unit_economics().';

CREATE OR REPLACE FUNCTION analytics_ai.refresh_wb_unit_economics()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_rows BIGINT;
BEGIN
    TRUNCATE TABLE analytics_ai.wb_unit_economics;

    INSERT INTO analytics_ai.wb_unit_economics
    SELECT *
    FROM analytics_ai.v_wb_unit_economics;

    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    RETURN inserted_rows;
END;
$$;

COMMENT ON FUNCTION analytics_ai.refresh_wb_unit_economics() IS
'Полностью пересобирает физическую таблицу analytics_ai.wb_unit_economics из расчётного view analytics_ai.v_wb_unit_economics.';
