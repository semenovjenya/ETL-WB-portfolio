-- =============================================================================
-- Аналог WB Profit Calculator на стороне БД
--
-- Источник логики:
--   https://seller.wildberries.ru/instructions/ru/ru/material/profit-calculator
--
-- Что делаем:
--   1) Храним сценарии расчёта в таблице reports.wb_profit_calculator_scenarios
--   2) Считаем результат в reports.v_wb_profit_calculator_results_source
--   3) Материализуем результат в таблицу reports.wb_profit_calculator_results
--
-- Важно:
--   Это DB-аналог калькулятора WB, а не копия их закрытого backend-движка 1:1.
--   Формулы логистики/хранения строятся по публичным тарифам WB:
--   base + max(volume_liters - 1, 0) * extra_liter_rate
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.wb_profit_calculator_scenarios (
    scenario_id BIGSERIAL PRIMARY KEY,
    scenario_name VARCHAR(255) NOT NULL,
    nm_id BIGINT,
    subject_id BIGINT,
    subject_name VARCHAR(500),
    sales_model VARCHAR(30) NOT NULL DEFAULT 'fbw_box'
        CHECK (sales_model IN (
            'fbw_box',
            'fbw_pallet',
            'fbs',
            'dbs',
            'edbs',
            'pickup',
            'booking'
        )),
    warehouse_name VARCHAR(255),
    price_before_wb_discount NUMERIC(12, 2),
    price_after_discount_rub NUMERIC(12, 2),
    length_cm NUMERIC(10, 2),
    width_cm NUMERIC(10, 2),
    height_cm NUMERIC(10, 2),
    buyout_pct NUMERIC(5, 2),
    turnover_days NUMERIC(10, 2),
    cost_price_rub NUMERIC(12, 2) NOT NULL DEFAULT 0,
    ad_percent NUMERIC(5, 2) NOT NULL DEFAULT 0,
    other_expenses_rub NUMERIC(12, 2) NOT NULL DEFAULT 0,
    tax_percent NUMERIC(5, 2) NOT NULL DEFAULT 0,
    kvv_pct_override NUMERIC(5, 2),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    comment_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE reports.wb_profit_calculator_scenarios IS
'Сценарии DB-аналога калькулятора юнит-экономики WB. Часть полей можно заполнить вручную, часть подтягивается по nm_id.';

ALTER TABLE reports.wb_profit_calculator_scenarios
    ADD COLUMN IF NOT EXISTS price_after_discount_rub NUMERIC(12, 2);

CREATE INDEX IF NOT EXISTS idx_wb_profit_calc_scenarios_nm_id
    ON reports.wb_profit_calculator_scenarios (nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_profit_calc_scenarios_active
    ON reports.wb_profit_calculator_scenarios (is_active);

CREATE OR REPLACE FUNCTION reports.set_wb_profit_calc_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_wb_profit_calc_updated_at
    ON reports.wb_profit_calculator_scenarios;

CREATE TRIGGER trg_wb_profit_calc_updated_at
BEFORE UPDATE ON reports.wb_profit_calculator_scenarios
FOR EACH ROW
EXECUTE FUNCTION reports.set_wb_profit_calc_updated_at();

DROP VIEW IF EXISTS reports.v_wb_profit_calculator_results_source CASCADE;

CREATE VIEW reports.v_wb_profit_calculator_results_source AS
WITH latest_price_date AS (
    SELECT MAX(snapshot_date) AS snapshot_date
    FROM reports.v_wb_supplier_prices_latest_snapshot
),

price_latest AS (
    SELECT
        p.nm_id,
        p.vendor_code,
        p.price AS price_list,
        p.discounted_price,
        p.club_discounted_price,
        COALESCE(p.discounted_price, p.price) AS price_current
    FROM reports.v_wb_supplier_prices_latest_snapshot p
    JOIN latest_price_date d
      ON d.snapshot_date = p.snapshot_date
),

meta_funnel AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        subject_id,
        subject_name,
        brand_name,
        vendor_code
    FROM reports.wb_sales_funnel_products_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, report_date DESC, id DESC
),

meta_finance AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        subject_name,
        brand_name
    FROM reports.wb_report_detail_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, COALESCE(sale_dt::date, date_to) DESC, rrd_id DESC
),

mart_latest AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        days_of_stock,
        order_to_buyout_pct,
        return_rate_30d
    FROM reports.mart_ai_sales_planning
    ORDER BY nm_id, report_date DESC
),

stock_warehouse_latest AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        warehouse_name
    FROM reports.v_wb_supplier_stocks_latest_snapshot
    WHERE nm_id IS NOT NULL
      AND warehouse_name IS NOT NULL
    ORDER BY nm_id, snapshot_hour DESC, quantity DESC, warehouse_name
),

resolved AS (
    SELECT
        s.scenario_id,
        s.scenario_name,
        s.nm_id,
        COALESCE(s.subject_id, mf.subject_id)                              AS subject_id_resolved,
        COALESCE(NULLIF(s.subject_name, ''), NULLIF(mf.subject_name, ''), NULLIF(mfi.subject_name, '')) AS subject_name_resolved,
        COALESCE(NULLIF(pl.vendor_code, ''), NULLIF(mf.vendor_code, ''))   AS vendor_code,
        COALESCE(NULLIF(mf.brand_name, ''), NULLIF(mfi.brand_name, ''))    AS brand_name,
        s.sales_model,
        COALESCE(NULLIF(s.warehouse_name, ''), sw.warehouse_name)           AS warehouse_name,
        COALESCE(
            pl.price_list,
            s.price_before_wb_discount,
            pl.discounted_price,
            pl.club_discounted_price
        )                                                                   AS price_before_wb_discount_resolved,
        COALESCE(
            pl.price_current,
            s.price_after_discount_rub,
            s.price_before_wb_discount,
            pl.price_list,
            pl.club_discounted_price
        )                                                                   AS price_after_discount_resolved,
        s.length_cm,
        s.width_cm,
        s.height_cm,
        CASE
            WHEN s.length_cm IS NOT NULL
             AND s.width_cm IS NOT NULL
             AND s.height_cm IS NOT NULL
            THEN ROUND(s.length_cm * s.width_cm * s.height_cm / 1000.0, 3)
        END                                                                 AS volume_liters,
        COALESCE(
            s.buyout_pct,
            NULLIF(ml.order_to_buyout_pct, 0),
            CASE
                WHEN ml.return_rate_30d IS NOT NULL THEN ROUND(100 - ml.return_rate_30d, 2)
            END,
            100
        )                                                                   AS buyout_pct_resolved,
        COALESCE(
            NULLIF(ml.days_of_stock, 0),
            NULLIF(s.turnover_days, 0),
            31
        )                                                                   AS turnover_days_resolved,
        s.cost_price_rub,
        s.ad_percent,
        s.other_expenses_rub,
        s.tax_percent,
        s.kvv_pct_override,
        s.comment_text
    FROM reports.wb_profit_calculator_scenarios s
    LEFT JOIN price_latest pl ON pl.nm_id = s.nm_id
    LEFT JOIN meta_funnel mf ON mf.nm_id = s.nm_id
    LEFT JOIN meta_finance mfi ON mfi.nm_id = s.nm_id
    LEFT JOIN mart_latest ml ON ml.nm_id = s.nm_id
    LEFT JOIN stock_warehouse_latest sw ON sw.nm_id = s.nm_id
    WHERE s.is_active = TRUE
),

tariffs AS (
    SELECT
        r.*,
        tc.parent_id,
        tc.parent_name,
        tc.kgvp_booking,
        tc.kgvp_marketplace,
        tc.kgvp_pickup,
        tc.kgvp_supplier,
        tc.kgvp_supplier_express,
        tc.paid_storage_kgvp
    FROM resolved r
    LEFT JOIN reports.v_wb_tariffs_commission_latest tc
      ON tc.subject_id = r.subject_id_resolved
      OR (
          r.subject_id_resolved IS NULL
          AND tc.subject_name = r.subject_name_resolved
      )
),

joined AS (
    SELECT
        t.*,
        bx.box_delivery_base,
        bx.box_delivery_liter,
        bx.box_storage_base,
        bx.box_storage_liter,
        pl.pallet_delivery_value_base,
        pl.pallet_delivery_value_liter,
        pl.pallet_storage_value_expr,
        rt.delivery_dump_sup_office_base,
        rt.delivery_dump_sup_office_liter
    FROM tariffs t
    LEFT JOIN reports.v_wb_tariffs_box_latest bx
      ON bx.warehouse_name = t.warehouse_name
    LEFT JOIN reports.v_wb_tariffs_pallet_latest pl
      ON pl.warehouse_name = t.warehouse_name
    LEFT JOIN reports.v_wb_tariffs_return_latest rt
      ON rt.warehouse_name = t.warehouse_name
      OR (t.warehouse_name IS NULL AND rt.warehouse_name = 'Базовые тарифы')
),

calc AS (
    SELECT
        j.*,
        CASE j.sales_model
            WHEN 'fbw_box' THEN COALESCE(j.kvv_pct_override, j.paid_storage_kgvp)
            WHEN 'fbw_pallet' THEN COALESCE(j.kvv_pct_override, j.paid_storage_kgvp)
            WHEN 'fbs' THEN COALESCE(j.kvv_pct_override, j.kgvp_marketplace)
            WHEN 'dbs' THEN COALESCE(j.kvv_pct_override, j.kgvp_supplier)
            WHEN 'edbs' THEN COALESCE(j.kvv_pct_override, j.kgvp_supplier_express)
            WHEN 'pickup' THEN COALESCE(j.kvv_pct_override, j.kgvp_pickup)
            WHEN 'booking' THEN COALESCE(j.kvv_pct_override, j.kgvp_booking)
        END AS kvv_pct_resolved,
        CASE
            WHEN j.buyout_pct_resolved IS NOT NULL AND j.buyout_pct_resolved > 0
            THEN j.buyout_pct_resolved / 100.0
        END AS buyout_share,
        CASE
            WHEN j.sales_model = 'fbw_box'
             AND j.volume_liters IS NOT NULL
             AND j.box_delivery_base IS NOT NULL
            THEN ROUND(
                j.box_delivery_base + GREATEST(j.volume_liters - 1, 0) * COALESCE(j.box_delivery_liter, 0),
                2
            )
            WHEN j.sales_model = 'fbw_pallet'
             AND j.volume_liters IS NOT NULL
             AND j.pallet_delivery_value_base IS NOT NULL
            THEN ROUND(
                j.pallet_delivery_value_base + GREATEST(j.volume_liters - 1, 0) * COALESCE(j.pallet_delivery_value_liter, 0),
                2
            )
            ELSE 0
        END AS outbound_dispatch_rub,
        CASE
            WHEN j.sales_model = 'fbw_box'
             AND j.volume_liters IS NOT NULL
             AND j.box_storage_base IS NOT NULL
            THEN ROUND(
                j.box_storage_base + GREATEST(j.volume_liters - 1, 0) * COALESCE(j.box_storage_liter, 0),
                4
            )
            WHEN j.sales_model = 'fbw_pallet'
             AND j.pallet_storage_value_expr IS NOT NULL
            THEN ROUND(j.pallet_storage_value_expr, 4)
            ELSE 0
        END AS storage_per_day_rub,
        CASE
            WHEN j.sales_model IN ('fbw_box', 'fbw_pallet')
             AND j.volume_liters IS NOT NULL
             AND j.delivery_dump_sup_office_base IS NOT NULL
            THEN ROUND(
                j.delivery_dump_sup_office_base + GREATEST(j.volume_liters - 1, 0) * COALESCE(j.delivery_dump_sup_office_liter, 0),
                2
            )
            ELSE 0
        END AS return_dispatch_rub
    FROM joined j
)

SELECT
    scenario_id,
    scenario_name,
    nm_id,
    vendor_code,
    brand_name,
    subject_id_resolved                                             AS subject_id,
    subject_name_resolved                                           AS subject_name,
    parent_id,
    parent_name,
    sales_model,
    warehouse_name,
    price_before_wb_discount_resolved                               AS price_before_wb_discount,
    price_after_discount_resolved                                   AS price_after_discount_rub,
    length_cm,
    width_cm,
    height_cm,
    volume_liters,
    buyout_pct_resolved                                             AS buyout_pct,
    turnover_days_resolved                                          AS turnover_days,
    kvv_pct_resolved                                                AS kvv_pct,
    ROUND(
        price_after_discount_resolved * COALESCE(kvv_pct_resolved, 0) / 100.0,
        2
    )                                                               AS kvv_rub,
    outbound_dispatch_rub,
    return_dispatch_rub,
    storage_per_day_rub,
    ROUND(storage_per_day_rub * COALESCE(turnover_days_resolved, 0), 2) AS storage_total_rub,
    ROUND(
        CASE
            WHEN buyout_share IS NULL OR buyout_share = 0 THEN NULL
            ELSE outbound_dispatch_rub / buyout_share
        END,
        2
    )                                                               AS expected_outbound_per_buyout_rub,
    ROUND(
        CASE
            WHEN buyout_share IS NULL OR buyout_share = 0 THEN NULL
            ELSE return_dispatch_rub * (1 - buyout_share) / buyout_share
        END,
        2
    )                                                               AS expected_return_logistics_rub,
    cost_price_rub,
    ad_percent,
    ROUND(
        price_after_discount_resolved * COALESCE(ad_percent, 0) / 100.0,
        2
    )                                                               AS ad_rub,
    other_expenses_rub,
    tax_percent,
    ROUND(
        price_after_discount_resolved * COALESCE(tax_percent, 0) / 100.0,
        2
    )                                                               AS tax_rub,
    ROUND(
        price_after_discount_resolved
        - ROUND(price_after_discount_resolved * COALESCE(kvv_pct_resolved, 0) / 100.0, 2)
        - COALESCE(
            ROUND(
                CASE
                    WHEN buyout_share IS NULL OR buyout_share = 0 THEN NULL
                    ELSE outbound_dispatch_rub / buyout_share
                END,
                2
            ),
            0
        )
        - COALESCE(
            ROUND(
                CASE
                    WHEN buyout_share IS NULL OR buyout_share = 0 THEN NULL
                    ELSE return_dispatch_rub * (1 - buyout_share) / buyout_share
                END,
                2
            ),
            0
        )
        - ROUND(storage_per_day_rub * COALESCE(turnover_days_resolved, 0), 2)
        - cost_price_rub
        - ROUND(price_after_discount_resolved * COALESCE(ad_percent, 0) / 100.0, 2)
        - other_expenses_rub
        - ROUND(price_after_discount_resolved * COALESCE(tax_percent, 0) / 100.0, 2),
        2
    )                                                               AS net_profit_rub,
    ROUND(
        (
            price_after_discount_resolved
            - ROUND(price_after_discount_resolved * COALESCE(kvv_pct_resolved, 0) / 100.0, 2)
            - COALESCE(
                ROUND(
                    CASE
                        WHEN buyout_share IS NULL OR buyout_share = 0 THEN NULL
                        ELSE outbound_dispatch_rub / buyout_share
                    END,
                    2
                ),
                0
            )
            - COALESCE(
                ROUND(
                    CASE
                        WHEN buyout_share IS NULL OR buyout_share = 0 THEN NULL
                        ELSE return_dispatch_rub * (1 - buyout_share) / buyout_share
                    END,
                    2
                ),
                0
            )
            - ROUND(storage_per_day_rub * COALESCE(turnover_days_resolved, 0), 2)
            - cost_price_rub
            - ROUND(price_after_discount_resolved * COALESCE(ad_percent, 0) / 100.0, 2)
            - other_expenses_rub
            - ROUND(price_after_discount_resolved * COALESCE(tax_percent, 0) / 100.0, 2)
        ) / NULLIF(price_after_discount_resolved, 0) * 100,
        2
    )                                                               AS margin_pct,
    CASE
        WHEN price_after_discount_resolved IS NULL THEN 'missing_price'
        WHEN subject_name_resolved IS NULL AND subject_id_resolved IS NULL THEN 'missing_category'
        WHEN sales_model IN ('fbw_box', 'fbw_pallet') AND volume_liters IS NULL THEN 'missing_dimensions'
        WHEN sales_model IN ('fbw_box', 'fbw_pallet') AND warehouse_name IS NULL THEN 'missing_warehouse'
        WHEN kvv_pct_resolved IS NULL THEN 'missing_kvv'
        ELSE 'ok'
    END                                                             AS calculation_status,
    comment_text
FROM calc;

COMMENT ON VIEW reports.v_wb_profit_calculator_results_source IS
'Расчётный слой DB-аналога калькулятора WB: кВВ, логистика, хранение, возвраты, реклама, налог и итоговая прибыль.';

DROP TABLE IF EXISTS reports.wb_profit_calculator_results;

CREATE TABLE reports.wb_profit_calculator_results AS
SELECT *
FROM reports.v_wb_profit_calculator_results_source
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_profit_calc_results_scenario_id
    ON reports.wb_profit_calculator_results (scenario_id);

COMMENT ON TABLE reports.wb_profit_calculator_results IS
'Физический результат DB-аналога WB Profit Calculator. Пересобирается функцией reports.refresh_wb_profit_calculator_results().';

CREATE OR REPLACE FUNCTION reports.refresh_wb_profit_calculator_results()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_rows BIGINT;
BEGIN
    TRUNCATE TABLE reports.wb_profit_calculator_results;

    INSERT INTO reports.wb_profit_calculator_results
    SELECT *
    FROM reports.v_wb_profit_calculator_results_source;

    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    RETURN inserted_rows;
END;
$$;

COMMENT ON FUNCTION reports.refresh_wb_profit_calculator_results() IS
'Полностью пересобирает reports.wb_profit_calculator_results из расчётного view.';

CREATE OR REPLACE FUNCTION reports.sync_wb_profit_calculator_scenarios_from_stocks()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_rows BIGINT;
BEGIN
    WITH latest_mart_date AS (
        SELECT MAX(report_date) AS report_date
        FROM reports.mart_ai_sales_planning
    ),
    in_stock_nm_ids AS (
        SELECT DISTINCT m.nm_id
        FROM reports.mart_ai_sales_planning m
        JOIN latest_mart_date d
          ON d.report_date = m.report_date
        WHERE m.nm_id IS NOT NULL
          AND COALESCE(m.stock_qty, 0) > 0
    )
    UPDATE reports.wb_profit_calculator_scenarios s
    SET is_active = FALSE
    WHERE s.is_active = TRUE
      AND NOT EXISTS (
          SELECT 1
          FROM in_stock_nm_ids st
          WHERE st.nm_id = s.nm_id
      );

    WITH latest_mart_date AS (
        SELECT MAX(report_date) AS report_date
        FROM reports.mart_ai_sales_planning
    ),
    in_stock_nm_ids AS (
        SELECT DISTINCT m.nm_id
        FROM reports.mart_ai_sales_planning m
        JOIN latest_mart_date d
          ON d.report_date = m.report_date
        WHERE m.nm_id IS NOT NULL
          AND COALESCE(m.stock_qty, 0) > 0
    )
    INSERT INTO reports.wb_profit_calculator_scenarios (
        scenario_name,
        nm_id,
        subject_name,
        sales_model,
        price_before_wb_discount,
        price_after_discount_rub,
        comment_text
    )
    SELECT
        COALESCE(NULLIF(u.vendor_code, ''), 'nm_' || u.nm_id::TEXT),
        u.nm_id,
        u.subject_name,
        'fbw_box',
        u.price_list,
        u.price_current,
        'Автосценарий по товарам с остатками. Заполните warehouse_name, length_cm, width_cm, height_cm, cost_price_rub.'
    FROM reports.wb_unit_economics u
    JOIN in_stock_nm_ids st
      ON st.nm_id = u.nm_id
    WHERE NOT EXISTS (
        SELECT 1
        FROM reports.wb_profit_calculator_scenarios s
        WHERE s.nm_id = u.nm_id
          AND s.is_active = TRUE
    )
    ORDER BY u.sold_units_90d DESC NULLS LAST, u.nm_id;

    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    RETURN inserted_rows;
END;
$$;

COMMENT ON FUNCTION reports.sync_wb_profit_calculator_scenarios_from_stocks() IS
'Синхронизирует активные сценарии калькулятора со списком nm_id из последней даты reports.mart_ai_sales_planning, где stock_qty > 0 (логика 1pager AI): лишние сценарии деактивируются, недостающие добавляются.';

CREATE OR REPLACE FUNCTION reports.seed_wb_profit_calculator_scenarios(limit_rows INTEGER DEFAULT 50)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_rows BIGINT;
BEGIN
    INSERT INTO reports.wb_profit_calculator_scenarios (
        scenario_name,
        nm_id,
        subject_name,
        sales_model,
        price_before_wb_discount,
        price_after_discount_rub,
        comment_text
    )
    SELECT
        COALESCE(NULLIF(u.vendor_code, ''), 'nm_' || u.nm_id::TEXT),
        u.nm_id,
        u.subject_name,
        'fbw_box',
        u.price_list,
        u.price_current,
        'Автосценарий. Заполните warehouse_name, length_cm, width_cm, height_cm, cost_price_rub.'
    FROM reports.wb_unit_economics u
    WHERE NOT EXISTS (
        SELECT 1
        FROM reports.wb_profit_calculator_scenarios s
        WHERE s.nm_id = u.nm_id
    )
    ORDER BY u.sold_units_90d DESC NULLS LAST, u.nm_id
    LIMIT GREATEST(limit_rows, 0);

    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    RETURN inserted_rows;
END;
$$;

COMMENT ON FUNCTION reports.seed_wb_profit_calculator_scenarios(INTEGER) IS
'Создаёт стартовые сценарии калькулятора по текущим товарам. Габариты, склад и себестоимость нужно дозаполнить вручную.';
