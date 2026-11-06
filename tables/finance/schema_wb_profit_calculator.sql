CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'analytics_ai'
       AND c.relname = 'wb_profit_calculator_scenarios';
    IF _relkind IN ('r', 'p')
       AND to_regclass('finance.wb_profit_calculator_scenarios') IS NULL THEN
        EXECUTE 'ALTER TABLE analytics_ai.wb_profit_calculator_scenarios SET SCHEMA finance';
    END IF;

    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_profit_calculator_scenarios';
    IF _relkind IN ('r', 'p')
       AND to_regclass('finance.wb_profit_calculator_scenarios') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_profit_calculator_scenarios SET SCHEMA finance';
    END IF;
END $$;

DO $$
DECLARE
    _relkind "char";
BEGIN
    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'analytics_ai'
       AND c.relname = 'wb_profit_calculator_results';
    IF _relkind IN ('r', 'p')
       AND to_regclass('finance.wb_profit_calculator_results') IS NULL THEN
        EXECUTE 'ALTER TABLE analytics_ai.wb_profit_calculator_results SET SCHEMA finance';
    END IF;

    SELECT c.relkind
      INTO _relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'reports'
       AND c.relname = 'wb_profit_calculator_results';
    IF _relkind IN ('r', 'p')
       AND to_regclass('finance.wb_profit_calculator_results') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_profit_calculator_results SET SCHEMA finance';
    END IF;
END $$;

DROP VIEW IF EXISTS analytics_ai.v_wb_profit_calculator_results_source CASCADE;
DROP FUNCTION IF EXISTS analytics_ai.refresh_wb_profit_calculator_results() CASCADE;
DROP FUNCTION IF EXISTS analytics_ai.sync_wb_profit_calculator_scenarios_from_stocks() CASCADE;
DROP FUNCTION IF EXISTS analytics_ai.seed_wb_profit_calculator_scenarios(INTEGER) CASCADE;
DROP FUNCTION IF EXISTS analytics_ai.set_wb_profit_calc_updated_at() CASCADE;

-- =============================================================================
-- Аналог WB Profit Calculator на стороне БД
--
-- Источник логики:
--   https://seller.wildberries.ru/instructions/ru/ru/material/profit-calculator
--
-- Что делаем:
--   1) Храним сценарии расчёта в таблице finance.wb_profit_calculator_scenarios
--   2) Считаем результат в finance.v_wb_profit_calculator_results_source
--   3) Материализуем результат в таблицу finance.wb_profit_calculator_results
--
-- Важно:
--   Это DB-аналог калькулятора WB, а не копия их закрытого backend-движка 1:1.
--   Формулы логистики/хранения строятся по публичным тарифам WB:
--   base + max(volume_liters - 1, 0) * extra_liter_rate
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS finance;
CREATE TABLE IF NOT EXISTS finance.wb_profit_calculator_scenarios (
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
    weight_brutto_kg NUMERIC(12, 3),
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

COMMENT ON TABLE finance.wb_profit_calculator_scenarios IS
'Сценарии DB-аналога калькулятора юнит-экономики WB. Часть полей можно заполнить вручную, часть подтягивается по nm_id.';

ALTER TABLE finance.wb_profit_calculator_scenarios
    ADD COLUMN IF NOT EXISTS price_after_discount_rub NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS weight_brutto_kg NUMERIC(12, 3);

CREATE INDEX IF NOT EXISTS idx_wb_profit_calc_scenarios_nm_id
    ON finance.wb_profit_calculator_scenarios (nm_id);

CREATE INDEX IF NOT EXISTS idx_wb_profit_calc_scenarios_active
    ON finance.wb_profit_calculator_scenarios (is_active);

CREATE OR REPLACE FUNCTION finance.set_wb_profit_calc_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_wb_profit_calc_updated_at
    ON finance.wb_profit_calculator_scenarios;

CREATE TRIGGER trg_wb_profit_calc_updated_at
BEFORE UPDATE ON finance.wb_profit_calculator_scenarios
FOR EACH ROW
EXECUTE FUNCTION finance.set_wb_profit_calc_updated_at();

UPDATE finance.wb_profit_calculator_scenarios calc
SET cost_price_rub = pc.cost_price_rub
FROM finance.wb_product_costs pc
WHERE calc.nm_id = pc.nm_id
  AND COALESCE(calc.cost_price_rub, 0) = 0
  AND pc.cost_price_rub > 0;

CREATE OR REPLACE FUNCTION finance.parse_wb_numeric(value_text TEXT)
RETURNS NUMERIC
LANGUAGE sql
IMMUTABLE
RETURNS NULL ON NULL INPUT
AS $$
    SELECT CASE
        WHEN btrim(value_text) IN ('', '-', '—') THEN NULL
        ELSE NULLIF(
            regexp_replace(
                replace(btrim(value_text), ',', '.'),
                '[^0-9.\-]+',
                '',
                'g'
            ),
            ''
        )::numeric
    END
$$;

DROP VIEW IF EXISTS finance.v_wb_profit_calculator_results_source CASCADE;

CREATE VIEW finance.v_wb_profit_calculator_results_source AS
WITH price_latest AS (
    SELECT DISTINCT ON (p.nm_id)
        p.nm_id,
        p.vendor_code,
        p.price AS price_list,
        p.discounted_price,
        p.club_discounted_price,
        COALESCE(p.discounted_price, p.price) AS price_current
    FROM pricing.wb_supplier_prices p
    WHERE p.nm_id IS NOT NULL
    ORDER BY
        p.nm_id,
        p.snapshot_date DESC,
        p.last_synced_at DESC NULLS LAST,
        p.id DESC
),

meta_funnel AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        subject_id,
        subject_name,
        brand_name,
        vendor_code
    FROM sales.wb_sales_funnel_products_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, report_date DESC, id DESC
),

meta_finance AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        subject_name,
        brand_name
    FROM finance.wb_report_detail_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, COALESCE(sale_dt::date, date_to) DESC, rrd_id DESC
),

latest_stock_date AS (
    SELECT MAX(snapshot_date) AS snapshot_date
    FROM supply.wb_supplier_stocks
),

stock_warehouse_latest AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        warehouse_name
    FROM supply.wb_supplier_stocks s
    JOIN latest_stock_date d
      ON d.snapshot_date = s.snapshot_date
    WHERE s.nm_id IS NOT NULL
      AND warehouse_name IS NOT NULL
    ORDER BY nm_id, quantity DESC, warehouse_name
),

product_costs_latest AS (
    SELECT
        pc.nm_id,
        pc.cost_price_rub
    FROM finance.wb_product_costs pc
),

latest_tariffs_commission_payload AS (
    SELECT t.report_json
    FROM pricing.wb_tariffs_commission t
    ORDER BY
        t.snapshot_date DESC,
        t.last_synced_at DESC NULLS LAST,
        t.id DESC
    LIMIT 1
),

tariffs_commission_latest AS (
    SELECT DISTINCT ON (
        (item->>'subjectID')::BIGINT,
        NULLIF(item->>'subjectName', '')
    )
        (item->>'parentID')::BIGINT                            AS parent_id,
        NULLIF(item->>'parentName', '')                        AS parent_name,
        (item->>'subjectID')::BIGINT                           AS subject_id,
        NULLIF(item->>'subjectName', '')                       AS subject_name,
        finance.parse_wb_numeric(item->>'kgvpBooking')         AS kgvp_booking,
        finance.parse_wb_numeric(item->>'kgvpMarketplace')     AS kgvp_marketplace,
        finance.parse_wb_numeric(item->>'kgvpPickup')          AS kgvp_pickup,
        finance.parse_wb_numeric(item->>'kgvpSupplier')        AS kgvp_supplier,
        finance.parse_wb_numeric(item->>'kgvpSupplierExpress') AS kgvp_supplier_express,
        finance.parse_wb_numeric(item->>'paidStorageKgvp')     AS paid_storage_kgvp
    FROM latest_tariffs_commission_payload t
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(t.report_json) = 'array' THEN t.report_json
            ELSE '[]'::jsonb
        END
    ) AS item
    ORDER BY
        (item->>'subjectID')::BIGINT,
        NULLIF(item->>'subjectName', '')
),

latest_tariffs_box_payload AS (
    SELECT t.response_json
    FROM pricing.wb_tariffs_box t
    ORDER BY
        t.snapshot_date DESC,
        t.last_synced_at DESC NULLS LAST,
        t.id DESC
    LIMIT 1
),

tariffs_box_latest AS (
    SELECT DISTINCT ON (NULLIF(item->>'warehouseName', ''))
        NULLIF(item->>'warehouseName', '')                         AS warehouse_name,
        finance.parse_wb_numeric(item->>'boxDeliveryBase')         AS box_delivery_base,
        finance.parse_wb_numeric(item->>'boxDeliveryLiter')        AS box_delivery_liter,
        finance.parse_wb_numeric(item->>'boxStorageBase')          AS box_storage_base,
        finance.parse_wb_numeric(item->>'boxStorageLiter')         AS box_storage_liter
    FROM latest_tariffs_box_payload t
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(t.response_json->'warehouseList', '[]'::jsonb)
    ) AS item
    ORDER BY NULLIF(item->>'warehouseName', '')
),

latest_tariffs_pallet_payload AS (
    SELECT t.response_json
    FROM pricing.wb_tariffs_pallet t
    ORDER BY
        t.snapshot_date DESC,
        t.last_synced_at DESC NULLS LAST,
        t.id DESC
    LIMIT 1
),

tariffs_pallet_latest AS (
    SELECT DISTINCT ON (NULLIF(item->>'warehouseName', ''))
        NULLIF(item->>'warehouseName', '')                           AS warehouse_name,
        finance.parse_wb_numeric(item->>'palletDeliveryValueBase')   AS pallet_delivery_value_base,
        finance.parse_wb_numeric(item->>'palletDeliveryValueLiter')  AS pallet_delivery_value_liter,
        finance.parse_wb_numeric(item->>'palletStorageValueExpr')    AS pallet_storage_value_expr
    FROM latest_tariffs_pallet_payload t
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(t.response_json->'warehouseList', '[]'::jsonb)
    ) AS item
    ORDER BY NULLIF(item->>'warehouseName', '')
),

latest_tariffs_return_payload AS (
    SELECT t.response_json
    FROM pricing.wb_tariffs_return t
    ORDER BY
        t.snapshot_date DESC,
        t.last_synced_at DESC NULLS LAST,
        t.id DESC
    LIMIT 1
),

tariffs_return_latest AS (
    SELECT DISTINCT ON (NULLIF(item->>'warehouseName', ''))
        NULLIF(item->>'warehouseName', '')                              AS warehouse_name,
        finance.parse_wb_numeric(item->>'deliveryDumpSupOfficeBase')    AS delivery_dump_sup_office_base,
        finance.parse_wb_numeric(item->>'deliveryDumpSupOfficeLiter')   AS delivery_dump_sup_office_liter
    FROM latest_tariffs_return_payload t
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(t.response_json->'warehouseList', '[]'::jsonb)
    ) AS item
    ORDER BY NULLIF(item->>'warehouseName', '')
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
        s.weight_brutto_kg,
        CASE
            WHEN s.length_cm IS NOT NULL
             AND s.width_cm IS NOT NULL
             AND s.height_cm IS NOT NULL
            THEN ROUND(s.length_cm * s.width_cm * s.height_cm / 1000.0, 3)
        END                                                                 AS volume_liters,
        COALESCE(
            s.buyout_pct,
            100
        )                                                                   AS buyout_pct_resolved,
        COALESCE(
            NULLIF(s.turnover_days, 0),
            31
        )                                                                   AS turnover_days_resolved,
        COALESCE(
            NULLIF(s.cost_price_rub, 0),
            pc.cost_price_rub,
            0
        )                                                                   AS cost_price_rub,
        s.ad_percent,
        s.other_expenses_rub,
        s.tax_percent,
        s.kvv_pct_override,
        s.comment_text
    FROM finance.wb_profit_calculator_scenarios s
    LEFT JOIN price_latest pl ON pl.nm_id = s.nm_id
    LEFT JOIN meta_funnel mf ON mf.nm_id = s.nm_id
    LEFT JOIN meta_finance mfi ON mfi.nm_id = s.nm_id
    LEFT JOIN stock_warehouse_latest sw ON sw.nm_id = s.nm_id
    LEFT JOIN product_costs_latest pc
      ON pc.nm_id = s.nm_id
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
    LEFT JOIN tariffs_commission_latest tc
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
    LEFT JOIN tariffs_box_latest bx
      ON bx.warehouse_name = t.warehouse_name
    LEFT JOIN tariffs_pallet_latest pl
      ON pl.warehouse_name = t.warehouse_name
    LEFT JOIN tariffs_return_latest rt
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
    weight_brutto_kg,
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

COMMENT ON VIEW finance.v_wb_profit_calculator_results_source IS
'Расчётный слой DB-аналога калькулятора WB: кВВ, логистика, хранение, возвраты, реклама, налог и итоговая прибыль.';

DROP TABLE IF EXISTS finance.wb_profit_calculator_results;

CREATE TABLE finance.wb_profit_calculator_results AS
SELECT *
FROM finance.v_wb_profit_calculator_results_source
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_profit_calc_results_scenario_id
    ON finance.wb_profit_calculator_results (scenario_id);

COMMENT ON TABLE finance.wb_profit_calculator_results IS
'Физический результат DB-аналога WB Profit Calculator. Пересобирается функцией finance.refresh_wb_profit_calculator_results().';

CREATE OR REPLACE FUNCTION finance.refresh_wb_profit_calculator_results()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_rows BIGINT;
BEGIN
    TRUNCATE TABLE finance.wb_profit_calculator_results;

    INSERT INTO finance.wb_profit_calculator_results
    SELECT *
    FROM finance.v_wb_profit_calculator_results_source;

    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    RETURN inserted_rows;
END;
$$;

COMMENT ON FUNCTION finance.refresh_wb_profit_calculator_results() IS
'Полностью пересобирает finance.wb_profit_calculator_results из расчётного view.';

CREATE OR REPLACE FUNCTION finance.sync_wb_profit_calculator_scenarios_from_sku_ai_analysis()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    changed_rows BIGINT := 0;
    affected_rows BIGINT := 0;
BEGIN
    WITH latest_snapshot AS (
        SELECT MAX(snapshot_date) AS snapshot_date
        FROM analytics_ai.wb_sku_ai_analysis
    ),
    latest_product_costs AS (
        SELECT
            pc.nm_id,
            pc.cost_price_rub
        FROM finance.wb_product_costs pc
    ),
    latest_sku AS (
        SELECT DISTINCT ON (s.nm_id)
            s.nm_id,
            COALESCE(NULLIF(s.vendor_code, ''), 'nm_' || s.nm_id::TEXT)     AS scenario_name,
            s.subject_name,
            NULLIF(s.warehouse_names->>0, '')                                AS warehouse_name,
            s.price                                                          AS price_before_wb_discount,
            COALESCE(s.club_discounted_price, s.discounted_price, s.price)   AS price_after_discount_rub,
            s.length_cm,
            s.width_cm,
            s.height_cm,
            s.weight_brutto_kg
        FROM analytics_ai.wb_sku_ai_analysis s
        JOIN latest_snapshot d
          ON d.snapshot_date = s.snapshot_date
        WHERE s.nm_id IS NOT NULL
          AND GREATEST(COALESCE(s.total_quantity_full, 0), COALESCE(s.total_quantity, 0)) > 0
        ORDER BY
            s.nm_id,
            (s.length_cm IS NOT NULL AND s.width_cm IS NOT NULL AND s.height_cm IS NOT NULL) DESC,
            COALESCE(s.total_quantity_full, 0) DESC,
            COALESCE(s.total_quantity, 0) DESC,
            s.barcode
    )
    UPDATE finance.wb_profit_calculator_scenarios calc
    SET is_active = FALSE
    WHERE calc.is_active = TRUE
      AND NOT EXISTS (
          SELECT 1
          FROM latest_sku src
          WHERE src.nm_id = calc.nm_id
      );

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    changed_rows := changed_rows + affected_rows;

    WITH latest_snapshot AS (
        SELECT MAX(snapshot_date) AS snapshot_date
        FROM analytics_ai.wb_sku_ai_analysis
    ),
    latest_product_costs AS (
        SELECT
            pc.nm_id,
            pc.cost_price_rub
        FROM finance.wb_product_costs pc
    ),
    latest_sku AS (
        SELECT DISTINCT ON (s.nm_id)
            s.nm_id,
            COALESCE(NULLIF(s.vendor_code, ''), 'nm_' || s.nm_id::TEXT)     AS scenario_name,
            s.subject_name,
            NULLIF(s.warehouse_names->>0, '')                                AS warehouse_name,
            s.price                                                          AS price_before_wb_discount,
            COALESCE(s.club_discounted_price, s.discounted_price, s.price)   AS price_after_discount_rub,
            s.length_cm,
            s.width_cm,
            s.height_cm,
            s.weight_brutto_kg
        FROM analytics_ai.wb_sku_ai_analysis s
        JOIN latest_snapshot d
          ON d.snapshot_date = s.snapshot_date
        WHERE s.nm_id IS NOT NULL
          AND GREATEST(COALESCE(s.total_quantity_full, 0), COALESCE(s.total_quantity, 0)) > 0
        ORDER BY
            s.nm_id,
            (s.length_cm IS NOT NULL AND s.width_cm IS NOT NULL AND s.height_cm IS NOT NULL) DESC,
            COALESCE(s.total_quantity_full, 0) DESC,
            COALESCE(s.total_quantity, 0) DESC,
            s.barcode
    )
    UPDATE finance.wb_profit_calculator_scenarios calc
    SET
        scenario_name = COALESCE(calc.scenario_name, src.scenario_name),
        subject_name = COALESCE(calc.subject_name, src.subject_name),
        warehouse_name = COALESCE(calc.warehouse_name, src.warehouse_name),
        price_before_wb_discount = COALESCE(calc.price_before_wb_discount, src.price_before_wb_discount),
        price_after_discount_rub = COALESCE(calc.price_after_discount_rub, src.price_after_discount_rub),
        length_cm = COALESCE(calc.length_cm, src.length_cm),
        width_cm = COALESCE(calc.width_cm, src.width_cm),
        height_cm = COALESCE(calc.height_cm, src.height_cm),
        weight_brutto_kg = COALESCE(calc.weight_brutto_kg, src.weight_brutto_kg),
        cost_price_rub = CASE
            WHEN COALESCE(calc.cost_price_rub, 0) = 0 THEN COALESCE(pc.cost_price_rub, calc.cost_price_rub)
            ELSE calc.cost_price_rub
        END,
        is_active = TRUE
    FROM latest_sku src
    LEFT JOIN latest_product_costs pc
      ON pc.nm_id = src.nm_id
    WHERE calc.nm_id = src.nm_id;

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    changed_rows := changed_rows + affected_rows;

    WITH latest_snapshot AS (
        SELECT MAX(snapshot_date) AS snapshot_date
        FROM analytics_ai.wb_sku_ai_analysis
    ),
    latest_sku AS (
        SELECT DISTINCT ON (s.nm_id)
            s.nm_id,
            COALESCE(NULLIF(s.vendor_code, ''), 'nm_' || s.nm_id::TEXT)     AS scenario_name,
            s.subject_name,
            NULLIF(s.warehouse_names->>0, '')                                AS warehouse_name,
            s.price                                                          AS price_before_wb_discount,
            COALESCE(s.club_discounted_price, s.discounted_price, s.price)   AS price_after_discount_rub,
            s.length_cm,
            s.width_cm,
            s.height_cm,
            s.weight_brutto_kg
        FROM analytics_ai.wb_sku_ai_analysis s
        JOIN latest_snapshot d
          ON d.snapshot_date = s.snapshot_date
        WHERE s.nm_id IS NOT NULL
          AND GREATEST(COALESCE(s.total_quantity_full, 0), COALESCE(s.total_quantity, 0)) > 0
        ORDER BY
            s.nm_id,
            (s.length_cm IS NOT NULL AND s.width_cm IS NOT NULL AND s.height_cm IS NOT NULL) DESC,
            COALESCE(s.total_quantity_full, 0) DESC,
            COALESCE(s.total_quantity, 0) DESC,
            s.barcode
    )
    INSERT INTO finance.wb_profit_calculator_scenarios (
        scenario_name,
        nm_id,
        subject_name,
        sales_model,
        warehouse_name,
        price_before_wb_discount,
        price_after_discount_rub,
        length_cm,
        width_cm,
        height_cm,
        weight_brutto_kg,
        cost_price_rub,
        comment_text
    )
    SELECT
        src.scenario_name,
        src.nm_id,
        src.subject_name,
        'fbw_box',
        src.warehouse_name,
        src.price_before_wb_discount,
        src.price_after_discount_rub,
        src.length_cm,
        src.width_cm,
        src.height_cm,
        src.weight_brutto_kg,
        COALESCE(pc.cost_price_rub, 0),
        'Автосценарий из analytics_ai.wb_sku_ai_analysis. Проверьте warehouse_name, cost_price_rub и при необходимости скорректируйте габариты.'
    FROM latest_sku src
    LEFT JOIN latest_product_costs pc
      ON pc.nm_id = src.nm_id
    WHERE NOT EXISTS (
        SELECT 1
        FROM finance.wb_profit_calculator_scenarios calc
        WHERE calc.nm_id = src.nm_id
          AND calc.is_active = TRUE
    )
    ORDER BY src.nm_id;

    GET DIAGNOSTICS affected_rows = ROW_COUNT;
    changed_rows := changed_rows + affected_rows;

    RETURN changed_rows;
END;
$$;

COMMENT ON FUNCTION finance.sync_wb_profit_calculator_scenarios_from_sku_ai_analysis() IS
'Синхронизирует сценарии калькулятора из последнего snapshot analytics_ai.wb_sku_ai_analysis: активирует/деактивирует nm_id по наличию в текущем срезе и автозаполняет warehouse_name, цены, габариты и weight_brutto_kg.';

CREATE OR REPLACE FUNCTION finance.sync_wb_profit_calculator_scenarios_from_stocks()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_rows BIGINT;
BEGIN
    WITH latest_stock_date AS (
        SELECT MAX(snapshot_date) AS snapshot_date
        FROM supply.wb_supplier_stocks
    ),
    latest_product_costs AS (
        SELECT
            pc.nm_id,
            pc.cost_price_rub
        FROM finance.wb_product_costs pc
    ),
    in_stock_nm_ids AS (
        SELECT DISTINCT s.nm_id
        FROM supply.wb_supplier_stocks s
        JOIN latest_stock_date d
          ON d.snapshot_date = s.snapshot_date
        WHERE s.nm_id IS NOT NULL
          AND COALESCE(s.quantity_full, s.quantity, 0) > 0
    )
    UPDATE finance.wb_profit_calculator_scenarios s
    SET is_active = FALSE
    WHERE s.is_active = TRUE
      AND NOT EXISTS (
          SELECT 1
          FROM in_stock_nm_ids st
          WHERE st.nm_id = s.nm_id
      );

    WITH latest_product_costs AS (
        SELECT
            pc.nm_id,
            pc.cost_price_rub
        FROM finance.wb_product_costs pc
    ),
    in_stock_nm_ids AS (
        SELECT DISTINCT s.nm_id
        FROM supply.wb_supplier_stocks s
        JOIN (
            SELECT MAX(snapshot_date) AS snapshot_date
            FROM supply.wb_supplier_stocks
        ) d
          ON d.snapshot_date = s.snapshot_date
        WHERE s.nm_id IS NOT NULL
          AND COALESCE(s.quantity_full, s.quantity, 0) > 0
    )
    UPDATE finance.wb_profit_calculator_scenarios s
    SET
        cost_price_rub = CASE
            WHEN COALESCE(s.cost_price_rub, 0) = 0 THEN COALESCE(pc.cost_price_rub, s.cost_price_rub)
            ELSE s.cost_price_rub
        END,
        is_active = TRUE
    FROM in_stock_nm_ids st
    LEFT JOIN latest_product_costs pc
      ON pc.nm_id = st.nm_id
    WHERE s.nm_id = st.nm_id
      AND s.is_active = TRUE;

    WITH latest_stock_date AS (
        SELECT MAX(snapshot_date) AS snapshot_date
        FROM supply.wb_supplier_stocks
    ),
    latest_product_costs AS (
        SELECT
            pc.nm_id,
            pc.cost_price_rub
        FROM finance.wb_product_costs pc
    ),
    in_stock_nm_ids AS (
        SELECT DISTINCT s.nm_id
        FROM supply.wb_supplier_stocks s
        JOIN latest_stock_date d
          ON d.snapshot_date = s.snapshot_date
        WHERE s.nm_id IS NOT NULL
          AND COALESCE(s.quantity_full, s.quantity, 0) > 0
    )
    INSERT INTO finance.wb_profit_calculator_scenarios (
        scenario_name,
        nm_id,
        subject_name,
        sales_model,
        price_before_wb_discount,
        price_after_discount_rub,
        cost_price_rub,
        comment_text
    )
    SELECT
        COALESCE(NULLIF(u.vendor_code, ''), 'nm_' || u.nm_id::TEXT),
        u.nm_id,
        u.subject_name,
        'fbw_box',
        u.price_list,
        u.price_current,
        COALESCE(pc.cost_price_rub, 0),
        'Автосценарий по товарам с остатками. Заполните warehouse_name, length_cm, width_cm, height_cm, cost_price_rub.'
    FROM analytics_ai.wb_unit_economics u
    JOIN in_stock_nm_ids st
      ON st.nm_id = u.nm_id
    LEFT JOIN latest_product_costs pc
      ON pc.nm_id = u.nm_id
    WHERE NOT EXISTS (
        SELECT 1
        FROM finance.wb_profit_calculator_scenarios s
        WHERE s.nm_id = u.nm_id
          AND s.is_active = TRUE
    )
    ORDER BY u.sold_units_90d DESC NULLS LAST, u.nm_id;

    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    RETURN inserted_rows;
END;
$$;

COMMENT ON FUNCTION finance.sync_wb_profit_calculator_scenarios_from_stocks() IS
'Синхронизирует активные сценарии калькулятора со списком nm_id из последнего среза supply.wb_supplier_stocks, где quantity или quantity_full > 0: лишние сценарии деактивируются, недостающие добавляются.';

CREATE OR REPLACE FUNCTION finance.seed_wb_profit_calculator_scenarios(limit_rows INTEGER DEFAULT 50)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_rows BIGINT;
BEGIN
    INSERT INTO finance.wb_profit_calculator_scenarios (
        scenario_name,
        nm_id,
        subject_name,
        sales_model,
        price_before_wb_discount,
        price_after_discount_rub,
        cost_price_rub,
        comment_text
    )
    SELECT
        COALESCE(NULLIF(u.vendor_code, ''), 'nm_' || u.nm_id::TEXT),
        u.nm_id,
        u.subject_name,
        'fbw_box',
        u.price_list,
        u.price_current,
        COALESCE(pc.cost_price_rub, 0),
        'Автосценарий. Заполните warehouse_name, length_cm, width_cm, height_cm, cost_price_rub.'
    FROM analytics_ai.wb_unit_economics u
    LEFT JOIN finance.wb_product_costs pc
      ON pc.nm_id = u.nm_id
    WHERE NOT EXISTS (
        SELECT 1
        FROM finance.wb_profit_calculator_scenarios s
        WHERE s.nm_id = u.nm_id
    )
    ORDER BY u.sold_units_90d DESC NULLS LAST, u.nm_id
    LIMIT GREATEST(limit_rows, 0);

    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    RETURN inserted_rows;
END;
$$;

COMMENT ON FUNCTION finance.seed_wb_profit_calculator_scenarios(INTEGER) IS
'Создаёт стартовые сценарии калькулятора по текущим товарам. Габариты, склад и себестоимость нужно дозаполнить вручную.';
