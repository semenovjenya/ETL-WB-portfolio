CREATE SCHEMA IF NOT EXISTS analytics_ai;
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
       AND c.relname = 'mart_ai_sales_planning';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW analytics_ai.mart_ai_sales_planning CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW analytics_ai.mart_ai_sales_planning CASCADE';
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
     WHERE n.nspname = 'reports'
       AND c.relname = 'mart_ai_sales_planning';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW reports.mart_ai_sales_planning CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW reports.mart_ai_sales_planning CASCADE';
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
       AND c.relname = 'v_1pager_daily_source';
    IF _relkind = 'm' THEN
        EXECUTE 'DROP MATERIALIZED VIEW analytics_ai.v_1pager_daily_source CASCADE';
    ELSIF _relkind = 'v' THEN
        EXECUTE 'DROP VIEW analytics_ai.v_1pager_daily_source CASCADE';
    END IF;
END $$;

-- =============================================================================
-- Daily source view for 1pager AI / ML: analytics_ai.v_1pager_daily_source
--
-- Зерно: одна строка = один nm_id на одну дату (report_date).
-- Гранулярность — день; каждая строка несёт недельный контекст
-- (week_start, rolling-суммы, лаги по неделям).
--
-- Блоки в порядке зависимостей:
--   [0] Идентификаторы и период
--   [1] prices и скидки           ← funnel order_sum/order_count (carry-forward)
--                                  + wb_supplier_sales для discount/SPP
--   [2] Воронка спроса           ← wb_sales_funnel_products_daily
--   [3] Конверсии воронки        ← рассчитываются из блока 2
--   [4] Эластичность спроса      ← блоки 1 + 3 + LAG-7д
--   [5] stocks                  ← wb_supplier_stocks (carry-forward)
--   [6] Оборачиваемость запасов  ← блоки 2 + 5
--   [7] Финансы                  ← wb_report_detail_daily
--   [8] ML-фичи (лаги, rolling)  ← все предыдущие блоки
--   [9] Целевые переменные       ← LEAD-7д (постфактум для обучения)
--   [A] Сезонность               ← wb_calendar_promotions + calendar
--   [B] supplies и пополнение    ← wb_supplies + wb_supplies_goods
--   [C] marketing                ← wb_marketing_campaign_stats_daily_nms
--   [D] Возвраты                 ← wb_report_detail_daily (doc_type = Возврат)
--   [G+] Расширенная прибыльность ← производные от блоков 1 + 7
--
-- Обновление: CREATE OR REPLACE VIEW в составе daily 1pager bundle
--             после загрузки всех исходных таблиц.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS analytics_ai;

CREATE VIEW analytics_ai.v_1pager_daily_source AS
WITH

-- ─────────────────────────────────────────────────────────────────
-- [A0] Границы дат для плотного календаря.
--      Нижняя граница по возможности остаётся как в funnel, чтобы не
--      раздувать историю. Верхняя граница берётся из самого свежего
--      дневного источника, поэтому витрина может жить дальше funnel.
-- ─────────────────────────────────────────────────────────────────
source_date_ranges AS (
    SELECT
        'wb_sales_funnel_products_daily'::text                AS source_name,
        MIN(report_date)                                      AS min_date,
        MAX(report_date)                                      AS max_date
    FROM sales.wb_sales_funnel_products_daily

    UNION ALL

    SELECT
        'wb_stocks_sales_daily',
        MIN(snapshot_date),
        MAX(snapshot_date)
    FROM analytics_ai.wb_stocks_sales_daily

    UNION ALL

    SELECT
        'wb_supplier_stocks',
        MIN(snapshot_date),
        MAX(snapshot_date)
    FROM supply.v_wb_supplier_stocks_latest_daily

    UNION ALL

    SELECT
        'wb_supplier_sales',
        MIN(date_ord::date),
        MAX(date_ord::date)
    FROM sales.v_wb_supplier_sales_latest_daily
    WHERE date_ord IS NOT NULL

    UNION ALL

    SELECT
        'wb_supplier_orders',
        MIN(date_ord::date),
        MAX(date_ord::date)
    FROM sales.v_wb_supplier_orders_latest_daily
    WHERE date_ord IS NOT NULL

    UNION ALL

    SELECT
        'wb_report_detail_daily',
        MIN(COALESCE(sale_dt::date, date_to)),
        MAX(COALESCE(sale_dt::date, date_to))
    FROM finance.wb_report_detail_daily

    UNION ALL

    SELECT
        'wb_marketing_campaign_stats_daily_nms',
        MIN(stat_date),
        MAX(stat_date)
    FROM marketing.wb_marketing_campaign_stats_daily_nms
),

date_bounds AS (
    SELECT
        COALESCE(
            MAX(min_date) FILTER (
                WHERE source_name = 'wb_sales_funnel_products_daily'
            ),
            MIN(min_date),
            CURRENT_DATE
        )                                                     AS min_report_date,
        COALESCE(MAX(max_date), CURRENT_DATE)                 AS max_report_date
    FROM source_date_ranges
),

-- ─────────────────────────────────────────────────────────────────
-- [A1] Плотный календарь дат — один ряд на каждый день периода.
--      Верхняя граница определяется по самому «живому» источнику.
-- ─────────────────────────────────────────────────────────────────
calendar AS (
    SELECT d::date AS report_date
    FROM date_bounds db
    CROSS JOIN generate_series(
        db.min_report_date,
        db.max_report_date,
        INTERVAL '1 day'
    ) gs(d)
),

-- ─────────────────────────────────────────────────────────────────
-- [A2] Универсум SKU: объединяем все источники, которые могут дать nm_id,
--      чтобы в спайн попадали товары с остатками/продажами/маркетингом
--      даже если funnel за последний день ещё не доехал.
-- ─────────────────────────────────────────────────────────────────
product_ids_raw AS (
    SELECT nm_id
    FROM sales.wb_sales_funnel_products_daily
    WHERE nm_id IS NOT NULL

    UNION ALL

    SELECT nm_id
    FROM analytics_ai.wb_stocks_sales_daily
    WHERE nm_id IS NOT NULL

    UNION ALL

    SELECT nm_id
    FROM supply.v_wb_supplier_stocks_latest_daily
    WHERE nm_id IS NOT NULL

    UNION ALL

    SELECT nm_id
    FROM sales.v_wb_supplier_sales_latest_daily
    WHERE nm_id IS NOT NULL

    UNION ALL

    SELECT nm_id
    FROM sales.v_wb_supplier_orders_latest_daily
    WHERE nm_id IS NOT NULL

    UNION ALL

    SELECT nm_id
    FROM finance.wb_report_detail_daily
    WHERE nm_id IS NOT NULL

    UNION ALL

    SELECT nm_id
    FROM supply.v_wb_supplies_goods_latest_daily
    WHERE nm_id IS NOT NULL

    UNION ALL

    SELECT nm_id
    FROM marketing.wb_marketing_campaign_stats_daily_nms
    WHERE nm_id IS NOT NULL
),

product_ids AS (
    SELECT DISTINCT nm_id
    FROM product_ids_raw
),

product_meta_funnel AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        vendor_code,
        brand_name,
        subject_name
    FROM sales.wb_sales_funnel_products_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, report_date DESC, id DESC
),

product_meta_finance AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        brand_name,
        subject_name
    FROM finance.wb_report_detail_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, COALESCE(sale_dt::date, date_to) DESC, rrd_id DESC
),

product_meta_supplies AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        vendor_code
    FROM supply.v_wb_supplies_goods_latest_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, snapshot_date DESC, id DESC
),

-- ─────────────────────────────────────────────────────────────────
-- [A3] Список уникальных артикулов с последними известными метаданными.
--      Метаданные берём из funnel, а если их нет — дотягиваем из finance
--      и supplies.
-- ─────────────────────────────────────────────────────────────────
products AS (
    SELECT
        p.nm_id,
        COALESCE(
            NULLIF(f.vendor_code, ''),
            NULLIF(s.vendor_code, ''),
            ''
        )                                                     AS vendor_code,
        COALESCE(
            NULLIF(f.brand_name, ''),
            NULLIF(fin.brand_name, ''),
            ''
        )                                                     AS brand_name,
        COALESCE(
            NULLIF(f.subject_name, ''),
            NULLIF(fin.subject_name, ''),
            ''
        )                                                     AS subject_name
    FROM product_ids p
    LEFT JOIN product_meta_funnel   f   ON f.nm_id = p.nm_id
    LEFT JOIN product_meta_finance  fin ON fin.nm_id = p.nm_id
    LEFT JOIN product_meta_supplies s   ON s.nm_id = p.nm_id
),

-- ─────────────────────────────────────────────────────────────────
-- [A4] Плотный spine: каждый nm_id × каждый день периода.
-- ─────────────────────────────────────────────────────────────────
spine AS (
    SELECT
        c.report_date,
        p.nm_id,
        p.vendor_code,
        p.brand_name,
        p.subject_name
    FROM calendar c
    CROSS JOIN products p
),

-- ─────────────────────────────────────────────────────────────────
-- [A] Скидка продавца и СПП из фактических продаж
--     Источник: wb_supplier_sales
-- ─────────────────────────────────────────────────────────────────
discounts_daily AS (
    SELECT
        date_ord::date                                          AS report_date,
        nm_id,
        ROUND(AVG(total_price)::numeric, 2)                    AS price_shelf,
        ROUND(AVG(discount_percent)::numeric, 2)               AS discount_pct,
        ROUND(AVG(spp)::numeric, 2)                            AS spp_pct
    FROM sales.v_wb_supplier_sales_latest_daily
    WHERE nm_id IS NOT NULL
      AND date_ord IS NOT NULL
    GROUP BY date_ord::date, nm_id
),

-- ─────────────────────────────────────────────────────────────────
-- [B] Воронка по дням — основной «хребет» дат и артикулов.
--     Источник: wb_sales_funnel_products_daily
-- ─────────────────────────────────────────────────────────────────
funnel_data AS (
    SELECT
        report_date,
        nm_id,
        vendor_code,
        brand_name,
        subject_name,
        COALESCE(open_count, 0)                                AS open_count,
        COALESCE(cart_count, 0)                                AS cart_count,
        COALESCE(order_count, 0)                               AS order_count_day,
        COALESCE(buyout_count, 0)                              AS buyout_count_day,
        COALESCE(order_sum, 0)                                 AS order_sum_day,
        COALESCE(buyout_sum, 0)                                AS buyout_sum_day,
        COALESCE(add_to_wishlist_count, 0)                     AS wishlist_count,
        COALESCE(add_to_cart_conversion, 0)                    AS open_to_cart_pct,
        COALESCE(cart_to_order_conversion, 0)                  AS cart_to_order_pct,
        COALESCE(buyout_percent, 0)                            AS order_to_buyout_pct,
        CASE
            WHEN COALESCE(order_count, 0) > 0
            THEN ROUND(order_sum::numeric / order_count, 2)
        END                                                    AS price_from_funnel
    FROM sales.wb_sales_funnel_products_daily
    WHERE nm_id IS NOT NULL
),

-- ─────────────────────────────────────────────────────────────────
-- [C] Отмены за день
--     Источник: wb_supplier_orders (is_cancel = true)
-- ─────────────────────────────────────────────────────────────────
cancels_daily AS (
    SELECT
        date_ord::date                                          AS report_date,
        nm_id,
        COUNT(*)                                               AS cancel_count_day
    FROM sales.v_wb_supplier_orders_latest_daily
    WHERE nm_id IS NOT NULL
      AND date_ord IS NOT NULL
      AND is_cancel = true
    GROUP BY date_ord::date, nm_id
),

-- ─────────────────────────────────────────────────────────────────
-- [D] stocks за день — исторический daily-слой + актуальный clean daily.
--     Источники:
--       * analytics_ai.wb_stocks_sales_daily      — historical daily
--       * supply.v_wb_supplier_stocks_latest_daily — current clean daily
--     На совпадающих датах приоритет у supplier daily.
-- ─────────────────────────────────────────────────────────────────
stocks_daily_raw AS (
    SELECT
        snapshot_date                                          AS report_date,
        nm_id,
        SUM(stock_quantity)                                    AS stock_qty,
        SUM(stock_quantity_full)                               AS stock_qty_full,
        0::bigint                                              AS in_way_to_client,
        0::bigint                                              AS in_way_from_client,
        1                                                      AS source_priority
    FROM analytics_ai.wb_stocks_sales_daily
    WHERE nm_id IS NOT NULL
    GROUP BY snapshot_date, nm_id

    UNION ALL

    SELECT
        snapshot_date                                          AS report_date,
        nm_id,
        SUM(quantity)                                          AS stock_qty,
        SUM(quantity_full)                                     AS stock_qty_full,
        SUM(in_way_to_client)                                  AS in_way_to_client,
        SUM(in_way_from_client)                                AS in_way_from_client,
        2                                                      AS source_priority
    FROM supply.v_wb_supplier_stocks_latest_daily
    WHERE nm_id IS NOT NULL
    GROUP BY snapshot_date, nm_id
),
stocks_daily AS (
    SELECT
        report_date,
        nm_id,
        stock_qty,
        stock_qty_full,
        in_way_to_client,
        in_way_from_client
    FROM (
        SELECT
            s.*,
            ROW_NUMBER() OVER (
                PARTITION BY s.report_date, s.nm_id
                ORDER BY s.source_priority DESC
            ) AS rn
        FROM stocks_daily_raw s
    ) ranked
    WHERE rn = 1
),

-- ─────────────────────────────────────────────────────────────────
-- [E] Финансовые показатели за день
--     Источник: wb_report_detail_daily (sale_dt)
--     Только строки-продажи (не возвраты) — фильтруем doc_type_name.
-- ─────────────────────────────────────────────────────────────────
finance_daily AS (
    SELECT
        sale_dt::date                                          AS report_date,
        nm_id,
        SUM(retail_amount)                                     AS revenue_gross,
        SUM(retail_price_withdisc_rub * quantity)              AS revenue_net,
        SUM(ppvz_for_pay)                                      AS ppvz_for_pay,
        ROUND(AVG(commission_percent)::numeric, 2)             AS commission_pct,
        SUM(delivery_rub)                                      AS delivery_cost,
        SUM(storage_fee)                                       AS storage_fee,
        SUM(penalty)                                           AS penalty,
        SUM(quantity)                                          AS fin_quantity
    FROM finance.wb_report_detail_daily
    WHERE nm_id IS NOT NULL
      AND sale_dt IS NOT NULL
      AND (doc_type_name NOT ILIKE '%возврат%' OR doc_type_name IS NULL)
    GROUP BY sale_dt::date, nm_id
),

finance_freshness AS (
    SELECT
        MAX(COALESCE(sale_dt::date, date_to))                  AS max_finance_date
    FROM finance.wb_report_detail_daily
),

-- ─────────────────────────────────────────────────────────────────
-- [F] Исторический рейтинг пока не подтверждён
--     Источник: wb_sales_funnel_products_daily
--     product.* metadata is not dated by report_date. Backfill also rewrites
--     last_synced_at; neither date proves observed historical rating. Keep
--     unknown until observation receipts/lineage exist, never fill with zero.
--     Native current metadata is retained in the source for a separate reader.
-- ─────────────────────────────────────────────────────────────────
ratings_history_unverified AS (
    SELECT DISTINCT ON (nm_id)
        nm_id,
        NULL::DECIMAL(5, 2) AS product_rating,
        NULL::DECIMAL(5, 2) AS feedback_rating
    FROM sales.wb_sales_funnel_products_daily
    WHERE nm_id IS NOT NULL
    ORDER BY nm_id, report_date DESC
),

-- ─────────────────────────────────────────────────────────────────
-- [NEW-1] Акции: флаг акционного периода + дней до следующей акции
--     Источник: wb_calendar_promotions
--     promo_dates — дедупликация уникальных дат начала/конца акций.
--     promos_per_day — одна строка на дату календаря.
-- ─────────────────────────────────────────────────────────────────
promo_dates AS (
    SELECT DISTINCT
        start_date_time::date AS promo_start,
        end_date_time::date   AS promo_end
    FROM marketing.v_wb_calendar_promotions_latest_daily
    WHERE start_date_time IS NOT NULL
      AND end_date_time   IS NOT NULL
),

promos_per_day AS (
    SELECT
        c.report_date,
        BOOL_OR(c.report_date BETWEEN pd.promo_start AND pd.promo_end) AS is_promo_period,
        MIN(pd.promo_start - c.report_date)
            FILTER (WHERE pd.promo_start > c.report_date)              AS days_to_next_promo
    FROM calendar c
    CROSS JOIN promo_dates pd
    GROUP BY c.report_date
),

-- ─────────────────────────────────────────────────────────────────
-- [NEW-2] supplies: дата последней выполненной поставки по nm_id
--     Источник: wb_supplies_goods JOIN wb_supplies
--     supply_daily — одна строка на (nm_id, supply_date) для завершённых
--     поставок (fact_date IS NOT NULL). В base join-ится по report_date,
--     на дни без поставки даёт NULL → carry-forward даёт last_supply_date.
-- ─────────────────────────────────────────────────────────────────
supply_daily AS (
    SELECT
        sg.nm_id,
        s.supply_date                                          AS report_date,
        s.supply_date                                          AS supply_date_val
    FROM supply.v_wb_supplies_goods_latest_daily sg
    JOIN supply.v_wb_supplies_latest_daily s ON s.supply_id = sg.supply_id
    WHERE sg.nm_id IS NOT NULL
      AND s.supply_date IS NOT NULL
      AND s.fact_date IS NOT NULL
    GROUP BY sg.nm_id, s.supply_date
),

-- ─────────────────────────────────────────────────────────────────
-- [NEW-3] Ожидаемое количество в незакрытых поставках (статическая
--     метрика per nm_id; используем последний снапшот каждой поставки).
-- ─────────────────────────────────────────────────────────────────
supply_pending AS (
    SELECT
        sg.nm_id,
        COALESCE(SUM(sg.quantity), 0)                          AS pending_supply_qty
    FROM supply.v_wb_supplies_goods_latest_daily sg
    JOIN (
        SELECT DISTINCT ON (supply_id)
            supply_id,
            fact_date
        FROM supply.v_wb_supplies_latest_daily
        ORDER BY supply_id, snapshot_date DESC
    ) latest ON latest.supply_id = sg.supply_id
    WHERE sg.nm_id IS NOT NULL
      AND latest.fact_date IS NULL
    GROUP BY sg.nm_id
),

-- ─────────────────────────────────────────────────────────────────
-- [NEW-4] Средний интервал между поставками (статическая per nm_id).
-- ─────────────────────────────────────────────────────────────────
supply_intervals AS (
    SELECT
        nm_id,
        ROUND(AVG(gap_days)::numeric, 1)                       AS avg_supply_interval_days
    FROM (
        SELECT
            nm_id,
            supply_date - LAG(supply_date)
                OVER (PARTITION BY nm_id ORDER BY supply_date) AS gap_days
        FROM (
            SELECT DISTINCT sg.nm_id, s.supply_date
            FROM supply.v_wb_supplies_goods_latest_daily sg
            JOIN supply.v_wb_supplies_latest_daily s ON s.supply_id = sg.supply_id
            WHERE sg.nm_id IS NOT NULL
              AND s.supply_date IS NOT NULL
        ) uniq
    ) gaps
    WHERE gap_days IS NOT NULL
    GROUP BY nm_id
),

-- ─────────────────────────────────────────────────────────────────
-- [NEW-5] Рекламная статистика по nm_id за день
--     Источник: wb_marketing_campaign_stats_daily_nms
-- ─────────────────────────────────────────────────────────────────
adv_daily_nm AS (
    SELECT
        stat_date                                              AS report_date,
        nm_id,
        ROUND(SUM(sum_spend)::numeric, 2)                      AS adv_spend_day,
        SUM(orders)                                            AS adv_orders_day,
        1                                                      AS has_active_campaign
    FROM marketing.wb_marketing_campaign_stats_daily_nms
    WHERE nm_id IS NOT NULL
    GROUP BY stat_date, nm_id
),

-- ─────────────────────────────────────────────────────────────────
-- [NEW-6] Возвраты по nm_id за день
--     Источник: wb_report_detail_daily (строки с типом «Возврат»)
-- ─────────────────────────────────────────────────────────────────
returns_daily AS (
    SELECT
        sale_dt::date                                          AS report_date,
        nm_id,
        SUM(ABS(quantity))                                     AS return_count_day,
        ROUND(
            SUM(ABS(retail_price_withdisc_rub * quantity))::numeric,
        2)                                                     AS return_sum_day
    FROM finance.wb_report_detail_daily
    WHERE nm_id IS NOT NULL
      AND sale_dt IS NOT NULL
      AND doc_type_name ILIKE '%возврат%'
    GROUP BY sale_dt::date, nm_id
),

-- ─────────────────────────────────────────────────────────────────
-- [G] Базовый JOIN: spine × все источники.
--     Дни без записи в источнике дают NULL (не 0) — carry-forward
--     применяется в следующих CTE.
--     Воронка: 0 в дни без записи (нет трафика / заказов).
--     Финансы: NULL в дни без финансового отчёта, чтобы не маскировать
--              отсутствие источника под "нулевые продажи".
--     prices/скидки/остатки/supply_date_val: NULL → carry-forward ниже.
-- ─────────────────────────────────────────────────────────────────
base AS (
    SELECT
        -- [Блок 0] Идентификаторы и период
        s.report_date,
        DATE_TRUNC('week', s.report_date)::date                AS week_start,
        s.nm_id,
        s.vendor_code,
        s.brand_name,
        s.subject_name,

        -- [Блок 1] prices (carry-forward в base_filled)
        d.price_shelf                                          AS price_shelf_raw,
        f.price_from_funnel,
        d.discount_pct,
        d.spp_pct,

        -- [Блок 2] Воронка спроса (0 в дни без записи)
        COALESCE(f.open_count, 0)                              AS open_count,
        COALESCE(f.cart_count, 0)                              AS cart_count,
        COALESCE(f.order_count_day, 0)                         AS order_count_day,
        COALESCE(f.buyout_count_day, 0)                        AS buyout_count_day,
        COALESCE(f.order_sum_day, 0)                           AS order_sum_day,
        COALESCE(f.buyout_sum_day, 0)                          AS buyout_sum_day,
        COALESCE(c.cancel_count_day, 0)                        AS cancel_count_day,
        COALESCE(f.wishlist_count, 0)                          AS wishlist_count,

        -- [Блок 3] Конверсии воронки (0 в дни без трафика)
        COALESCE(f.open_to_cart_pct, 0)                        AS open_to_cart_pct,
        COALESCE(f.cart_to_order_pct, 0)                       AS cart_to_order_pct,
        COALESCE(f.order_to_buyout_pct, 0)                     AS order_to_buyout_pct,
        ROUND(
            COALESCE(c.cancel_count_day, 0)::numeric
            / NULLIF(COALESCE(f.order_count_day, 0), 0) * 100,
        2)                                                     AS cancel_rate_pct,

        -- [Блок 5] stocks (NULL если нет снапшота — carry-forward ниже)
        s2.stock_qty,
        s2.stock_qty_full,
        s2.in_way_to_client,
        s2.in_way_from_client,

        -- [Блок 7] Финансы:
        -- * report_date > max_finance_date => источник ещё не догружен, ставим NULL
        -- * report_date <= max_finance_date и строки нет => считаем нулевым днём без транзакций
        CASE
            WHEN fin.nm_id IS NULL
                 AND (ff.max_finance_date IS NULL OR s.report_date > ff.max_finance_date) THEN NULL
            ELSE COALESCE(fin.revenue_gross, 0)
        END                                                    AS revenue_gross,
        CASE
            WHEN fin.nm_id IS NULL
                 AND (ff.max_finance_date IS NULL OR s.report_date > ff.max_finance_date) THEN NULL
            ELSE COALESCE(fin.revenue_net, 0)
        END                                                    AS revenue_net,
        CASE
            WHEN fin.nm_id IS NULL
                 AND (ff.max_finance_date IS NULL OR s.report_date > ff.max_finance_date) THEN NULL
            ELSE COALESCE(fin.ppvz_for_pay, 0)
        END                                                    AS ppvz_for_pay,
        CASE
            WHEN fin.nm_id IS NULL
                 AND (ff.max_finance_date IS NULL OR s.report_date > ff.max_finance_date) THEN NULL
            ELSE COALESCE(fin.commission_pct, 0)
        END                                                    AS commission_pct,
        CASE
            WHEN fin.nm_id IS NULL
                 AND (ff.max_finance_date IS NULL OR s.report_date > ff.max_finance_date) THEN NULL
            ELSE COALESCE(fin.delivery_cost, 0)
        END                                                    AS delivery_cost,
        CASE
            WHEN fin.nm_id IS NULL
                 AND (ff.max_finance_date IS NULL OR s.report_date > ff.max_finance_date) THEN NULL
            ELSE COALESCE(fin.storage_fee, 0)
        END                                                    AS storage_fee,
        CASE
            WHEN fin.nm_id IS NULL
                 AND (ff.max_finance_date IS NULL OR s.report_date > ff.max_finance_date) THEN NULL
            ELSE COALESCE(fin.penalty, 0)
        END                                                    AS penalty,
        CASE
            WHEN fin.nm_id IS NOT NULL THEN ROUND(
                (COALESCE(fin.ppvz_for_pay, 0)
                 - COALESCE(fin.delivery_cost, 0)
                 - COALESCE(fin.storage_fee, 0))
                / NULLIF(fin.fin_quantity, 0),
            2)
        END                                                    AS net_profit_per_unit,

        -- [Блок 8] Рейтинги
        r.product_rating                                      AS product_rating,
        r.feedback_rating                                     AS feedback_rating,

        -- [Блок A] Сезонность — акции
        COALESCE(pp.is_promo_period, false)                    AS is_promo_period,
        pp.days_to_next_promo,

        -- [Блок B] supplies
        -- supply_date_val: NULL если не было поставки в этот день → carry-forward
        sd.supply_date_val,
        COALESCE(spe.pending_supply_qty, 0)                    AS pending_supply_qty,
        si.avg_supply_interval_days,

        -- [Блок C] Реклама (0 в дни без кампаний)
        COALESCE(adv.adv_spend_day, 0)                         AS adv_spend_day,
        COALESCE(adv.adv_orders_day, 0)                        AS adv_orders_day,
        COALESCE(adv.has_active_campaign, 0)                   AS has_active_campaign,

        -- [Блок D] Возвраты (0 в дни без возвратов)
        COALESCE(ret.return_count_day, 0)                      AS return_count_day,
        COALESCE(ret.return_sum_day, 0)                        AS return_sum_day

    FROM spine s
    LEFT JOIN funnel_data       f   ON f.report_date   = s.report_date AND f.nm_id   = s.nm_id
    LEFT JOIN discounts_daily   d   ON d.report_date   = s.report_date AND d.nm_id   = s.nm_id
    LEFT JOIN cancels_daily     c   ON c.report_date   = s.report_date AND c.nm_id   = s.nm_id
    LEFT JOIN stocks_daily      s2  ON s2.report_date  = s.report_date AND s2.nm_id  = s.nm_id
    LEFT JOIN finance_daily     fin ON fin.report_date = s.report_date AND fin.nm_id = s.nm_id
    CROSS JOIN finance_freshness ff
    LEFT JOIN ratings_history_unverified r   ON r.nm_id = s.nm_id
    LEFT JOIN promos_per_day    pp  ON pp.report_date  = s.report_date
    LEFT JOIN supply_daily      sd  ON sd.report_date  = s.report_date AND sd.nm_id  = s.nm_id
    LEFT JOIN supply_pending    spe ON spe.nm_id = s.nm_id
    LEFT JOIN supply_intervals  si  ON si.nm_id  = s.nm_id
    LEFT JOIN adv_daily_nm      adv ON adv.report_date = s.report_date AND adv.nm_id = s.nm_id
    LEFT JOIN returns_daily     ret ON ret.report_date = s.report_date AND ret.nm_id = s.nm_id
),

-- ─────────────────────────────────────────────────────────────────
-- [G2] Вычисляем группы для carry-forward всех «медленно меняющихся»
--      полей: цена, скидки, остатки, in_way, last_supply_date.
-- ─────────────────────────────────────────────────────────────────
base_filled AS (
    SELECT
        *,
        SUM(CASE WHEN price_shelf_raw IS NOT NULL THEN 1 ELSE 0 END)
            OVER (PARTITION BY nm_id ORDER BY report_date)     AS price_grp,
        SUM(CASE WHEN price_from_funnel IS NOT NULL THEN 1 ELSE 0 END)
            OVER (PARTITION BY nm_id ORDER BY report_date)     AS price_funnel_grp,
        SUM(CASE WHEN discount_pct IS NOT NULL THEN 1 ELSE 0 END)
            OVER (PARTITION BY nm_id ORDER BY report_date)     AS discount_grp,
        SUM(CASE WHEN spp_pct IS NOT NULL THEN 1 ELSE 0 END)
            OVER (PARTITION BY nm_id ORDER BY report_date)     AS spp_grp,
        SUM(CASE WHEN stock_qty IS NOT NULL THEN 1 ELSE 0 END)
            OVER (PARTITION BY nm_id ORDER BY report_date)     AS stock_grp_fwd,
        SUM(CASE WHEN in_way_to_client IS NOT NULL THEN 1 ELSE 0 END)
            OVER (PARTITION BY nm_id ORDER BY report_date)     AS in_way_grp,
        -- Группа для carry-forward даты последней поставки
        SUM(CASE WHEN supply_date_val IS NOT NULL THEN 1 ELSE 0 END)
            OVER (PARTITION BY nm_id ORDER BY report_date)     AS supply_grp
    FROM base
),

-- ─────────────────────────────────────────────────────────────────
-- [H] Применяем carry-forward для всех медленно меняющихся полей
-- ─────────────────────────────────────────────────────────────────
base_with_price AS (
    SELECT
        report_date, week_start, nm_id, vendor_code, brand_name, subject_name,
        -- Carry-forward полочной цены
        COALESCE(
            MAX(price_shelf_raw) OVER (PARTITION BY nm_id, price_grp),
            0
        )                                                      AS price_raw,
        -- Carry-forward цены покупателя из воронки (справочно)
        COALESCE(
            MAX(price_from_funnel) OVER (PARTITION BY nm_id, price_funnel_grp),
            0
        )                                                      AS price_sale,
        -- Carry-forward скидок
        COALESCE(
            MAX(discount_pct) OVER (PARTITION BY nm_id, discount_grp),
            0
        )                                                      AS discount_pct,
        COALESCE(
            MAX(spp_pct) OVER (PARTITION BY nm_id, spp_grp),
            0
        )                                                      AS spp_pct,
        open_count, cart_count,
        order_count_day, buyout_count_day,
        order_sum_day, buyout_sum_day,
        cancel_count_day, wishlist_count,
        open_to_cart_pct, cart_to_order_pct,
        order_to_buyout_pct, cancel_rate_pct,
        -- Carry-forward остатков
        COALESCE(
            MAX(stock_qty) OVER (PARTITION BY nm_id, stock_grp_fwd),
            0
        )                                                      AS stock_qty,
        COALESCE(
            MAX(stock_qty_full) OVER (PARTITION BY nm_id, stock_grp_fwd),
            0
        )                                                      AS stock_qty_full,
        COALESCE(
            MAX(in_way_to_client) OVER (PARTITION BY nm_id, in_way_grp),
            0
        )                                                      AS in_way_to_client,
        COALESCE(
            MAX(in_way_from_client) OVER (PARTITION BY nm_id, in_way_grp),
            0
        )                                                      AS in_way_from_client,
        -- Carry-forward даты последней поставки (NULL до первой поставки)
        MAX(supply_date_val) OVER (PARTITION BY nm_id, supply_grp)
                                                               AS last_supply_date,
        revenue_gross, revenue_net, ppvz_for_pay,
        commission_pct, delivery_cost, storage_fee, penalty,
        net_profit_per_unit,
        product_rating, feedback_rating,
        -- Блок A: сезонность / акции
        is_promo_period,
        days_to_next_promo,
        -- Блок B: поставки
        pending_supply_qty,
        avg_supply_interval_days,
        -- Блок C: реклама
        adv_spend_day,
        adv_orders_day,
        has_active_campaign,
        -- Блок D: возвраты
        return_count_day,
        return_sum_day
    FROM base_filled
),

-- ─────────────────────────────────────────────────────────────────
-- [I] Финальный базовый JOIN: считаем price_final и price_with_spp
-- ─────────────────────────────────────────────────────────────────
base_final AS (
    SELECT
        *,
        ROUND(
            price_raw * (1.0 - discount_pct / 100.0),
        2)                                                     AS price_final,
        ROUND(
            price_raw
            * (1.0 - discount_pct / 100.0)
            * (1.0 - spp_pct     / 100.0),
        2)                                                     AS price_with_spp
    FROM base_with_price
),

-- ─────────────────────────────────────────────────────────────────
-- [J] Первый слой оконных функций:
--     rolling-суммы за 7/28 дней, простые LAG-7д, return_rate_30d
-- ─────────────────────────────────────────────────────────────────
windowed_1 AS (
    SELECT
        *,

        -- Блок 1: цена неделю назад
        CASE
            WHEN report_date - LAG(report_date, 7) OVER w = 7
            THEN LAG(price_final, 7) OVER w
        END                                                    AS price_final_prev_week,

        -- Блок 4: заказы неделю назад
        CASE
            WHEN report_date - LAG(report_date, 7) OVER w = 7
            THEN LAG(order_count_day, 7) OVER w
        END                                                    AS order_count_prev_week,

        -- Блок 5: средний остаток за 7 дней
        ROUND(
            AVG(stock_qty::numeric)
                OVER (w RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW),
        2)                                                     AS stock_week_avg,

        -- Блок 6: скользящие суммы выкупов за 7 / 28 дней
        SUM(buyout_count_day)
            OVER (w RANGE BETWEEN INTERVAL '6 days' PRECEDING
                               AND CURRENT ROW)                AS sales_7d_sum,

        ROUND(
            SUM(buyout_count_day::numeric)
                OVER (w RANGE BETWEEN INTERVAL '27 days' PRECEDING
                                   AND CURRENT ROW) / 28.0,
        4)                                                     AS sales_28d_avg_per_day,

        -- Блок 8: rolling-средние/std продаж за 28 дней
        ROUND(
            AVG(buyout_count_day::numeric)
                OVER (w RANGE BETWEEN INTERVAL '27 days' PRECEDING
                                   AND CURRENT ROW),
        4)                                                     AS sales_rolling_4w_avg,

        ROUND(
            STDDEV(buyout_count_day::numeric)
                OVER (w RANGE BETWEEN INTERVAL '27 days' PRECEDING
                                   AND CURRENT ROW),
        4)                                                     AS sales_rolling_4w_std,

        -- Блок 8: видимость
        CASE
            WHEN report_date - LAG(report_date, 7) OVER w = 7
            THEN LAG(open_count, 7) OVER w
        END                                                    AS open_count_lag_1w,

        SUM(open_count)
            OVER (w RANGE BETWEEN INTERVAL '6 days' PRECEDING
                               AND CURRENT ROW)                AS open_count_rolling_7d,

        -- Блок D: процент возвратов за 30 дней
        ROUND(
            SUM(return_count_day::numeric)
                OVER (w RANGE BETWEEN INTERVAL '29 days' PRECEDING AND CURRENT ROW)
            / NULLIF(
                SUM(buyout_count_day::numeric)
                    OVER (w RANGE BETWEEN INTERVAL '29 days' PRECEDING AND CURRENT ROW),
            0) * 100,
        2)                                                     AS return_rate_30d

    FROM base_final
    WINDOW w AS (PARTITION BY nm_id ORDER BY report_date)
),

-- ─────────────────────────────────────────────────────────────────
-- [K] Второй слой оконных функций:
--     лаги rolling-сумм, LEAD-7д для целевых переменных,
--     производные эластичности, YoY изменение спроса
-- ─────────────────────────────────────────────────────────────────
windowed_2 AS (
    SELECT
        *,

        -- Блок 8: лаги sales_7d_sum на 1/2/4 недели
        CASE
            WHEN report_date - LAG(report_date, 7)
                     OVER (PARTITION BY nm_id ORDER BY report_date) = 7
            THEN LAG(sales_7d_sum, 7)
                     OVER (PARTITION BY nm_id ORDER BY report_date)
        END                                                    AS sales_lag_1w,

        CASE
            WHEN report_date - LAG(report_date, 14)
                     OVER (PARTITION BY nm_id ORDER BY report_date) = 14
            THEN LAG(sales_7d_sum, 14)
                     OVER (PARTITION BY nm_id ORDER BY report_date)
        END                                                    AS sales_lag_2w,

        CASE
            WHEN report_date - LAG(report_date, 28)
                     OVER (PARTITION BY nm_id ORDER BY report_date) = 28
            THEN LAG(sales_7d_sum, 28)
                     OVER (PARTITION BY nm_id ORDER BY report_date)
        END                                                    AS sales_lag_4w,

        -- Блок 9: целевые переменные (постфактум, для обучения ML)
        SUM(order_count_day)
            OVER (PARTITION BY nm_id ORDER BY report_date
                  RANGE BETWEEN INTERVAL '1 day'  FOLLOWING
                            AND INTERVAL '7 days' FOLLOWING)  AS target_orders_next_7d,

        SUM(buyout_count_day)
            OVER (PARTITION BY nm_id ORDER BY report_date
                  RANGE BETWEEN INTERVAL '1 day'  FOLLOWING
                            AND INTERVAL '7 days' FOLLOWING)  AS target_buyouts_next_7d,

        -- Блок 1: процент изменения цены
        ROUND(
            (price_final - price_final_prev_week)
            / NULLIF(price_final_prev_week, 0) * 100,
        2)                                                     AS price_change_pct,

        -- Блок 4: процент изменения спроса
        ROUND(
            (order_count_day - order_count_prev_week)::numeric
            / NULLIF(order_count_prev_week, 0) * 100,
        2)                                                     AS order_change_pct,

        -- Блок 4: точечная эластичность (ΔQ% / ΔP%)
        ROUND(
            (   (order_count_day - order_count_prev_week)::numeric
                / NULLIF(order_count_prev_week, 0) * 100    )
            / NULLIF(
                (price_final - price_final_prev_week)
                / NULLIF(price_final_prev_week, 0) * 100,
            0),
        4)                                                     AS price_elasticity_point,

        -- Блок A: изменение заказов год-к-году (52 недели = 364 дня)
        CASE
            WHEN report_date - LAG(report_date, 364)
                     OVER (PARTITION BY nm_id ORDER BY report_date) = 364
            THEN ROUND(
                (order_count_day - LAG(order_count_day, 364)
                     OVER (PARTITION BY nm_id ORDER BY report_date))::numeric
                / NULLIF(
                    LAG(order_count_day, 364)
                        OVER (PARTITION BY nm_id ORDER BY report_date),
                0) * 100,
            2)
        END                                                    AS yoy_orders_change_pct

    FROM windowed_1
)

-- ─────────────────────────────────────────────────────────────────
-- ИТОГОВЫЙ SELECT: все блоки в логическом порядке.
-- ─────────────────────────────────────────────────────────────────
SELECT
    -- ── [Блок 0] Идентификаторы и период ────────────────────────
    report_date,
    week_start,
    nm_id,
    vendor_code,
    brand_name,
    subject_name,

    -- ── [Блок 1] prices и скидки ───────────────────────────────────
    price_raw,
    discount_pct,
    spp_pct,
    price_final,
    price_with_spp,
    price_sale,
    price_final_prev_week,
    price_change_pct,

    -- ── [Блок 2] Воронка спроса (дневные абсолюты) ───────────────
    open_count,
    cart_count,
    order_count_day,
    order_sum_day,
    buyout_count_day,
    buyout_sum_day,
    cancel_count_day,
    wishlist_count,

    -- ── [Блок 3] Конверсии воронки ───────────────────────────────
    open_to_cart_pct,
    cart_to_order_pct,
    order_to_buyout_pct,
    (
        open_to_cart_pct < 0 OR open_to_cart_pct > 100
        OR cart_to_order_pct < 0 OR cart_to_order_pct > 100
        OR order_to_buyout_pct < 0 OR order_to_buyout_pct > 100
    )                                                          AS is_conversion_anomaly,
    cancel_rate_pct,

    -- ── [Блок 4] Эластичность спроса ────────────────────────────
    order_count_prev_week,
    order_change_pct,
    price_elasticity_point,
    ROUND(
        AVG(price_elasticity_point)
            OVER (PARTITION BY nm_id ORDER BY report_date
                  RANGE BETWEEN INTERVAL '27 days' PRECEDING AND CURRENT ROW),
    4)                                                         AS elasticity_rolling_4w,

    -- ── [Блок 5] stocks ─────────────────────────────────────────
    stock_qty,
    stock_qty_full,
    in_way_to_client,
    in_way_from_client,
    stock_week_avg,

    -- ── [Блок 6] Оборачиваемость запасов ────────────────────────
    buyout_count_day                                           AS sales_per_day,
    sales_7d_sum,
    sales_28d_avg_per_day,
    ROUND(
        stock_qty::numeric / NULLIF(sales_28d_avg_per_day, 0),
    1)                                                         AS days_of_stock,
    ROUND(
        sales_7d_sum::numeric / NULLIF(stock_week_avg, 0),
    4)                                                         AS stock_turnover_weekly,
    CASE
        WHEN sales_28d_avg_per_day IS NULL
             OR sales_28d_avg_per_day = 0               THEN 'no_sales'
        WHEN stock_qty::numeric / sales_28d_avg_per_day < 14 THEN 'critical'
        WHEN stock_qty::numeric / sales_28d_avg_per_day < 30 THEN 'warning'
        ELSE 'ok'
    END                                                        AS reorder_flag,

    -- ── [Блок 7] Финансы ─────────────────────────────────────────
    revenue_gross,
    revenue_net,
    ppvz_for_pay,
    commission_pct,
    delivery_cost,
    storage_fee,
    penalty,
    net_profit_per_unit,

    -- ── [Блок 8] ML-фичи: исторические признаки ─────────────────
    sales_lag_1w,
    sales_lag_2w,
    sales_lag_4w,
    sales_rolling_4w_avg,
    sales_rolling_4w_std,
    product_rating,
    feedback_rating,
    open_count_lag_1w,
    open_count_rolling_7d,

    -- ── [Блок 9] Целевые переменные (постфактум) ─────────────────
    target_orders_next_7d,
    target_buyouts_next_7d,

    -- ── [Блок A] Сезонность ──────────────────────────────────────
    EXTRACT(week  FROM report_date)::int                       AS week_of_year,
    EXTRACT(month FROM report_date)::int                       AS month_num,
    (EXTRACT(isodow FROM report_date) >= 6)::boolean           AS is_weekend,
    is_promo_period,
    days_to_next_promo,
    yoy_orders_change_pct,

    -- ── [Блок B] supplies и пополнение ───────────────────────────
    last_supply_date,
    (report_date - last_supply_date)                           AS days_since_last_supply,
    pending_supply_qty,
    avg_supply_interval_days,
    -- Рекомендуемый объём пополнения: горизонт 30 дней + страховой запас 14 дней
    -- формула: потребность_60д - текущий_остаток - ожидаемые_поступления
    GREATEST(0,
        ROUND(
            COALESCE(sales_28d_avg_per_day, 0) * 44
            - stock_qty
            - pending_supply_qty,
        0)
    )                                                          AS reorder_qty_recommended,

    -- ── [Блок C] marketing ───────────────────────────────────────
    adv_spend_day,
    adv_orders_day,
    (has_active_campaign = 1)::boolean                         AS has_active_campaign,
    ROUND(
        adv_spend_day / NULLIF(adv_orders_day, 0),
    2)                                                         AS adv_cpo,
    ROUND(
        revenue_net / NULLIF(adv_spend_day, 0),
    2)                                                         AS adv_roas,

    -- ── [Блок D] Возвраты ────────────────────────────────────────
    return_count_day,
    return_sum_day,
    (buyout_count_day - return_count_day)                      AS net_sales_day,
    return_rate_30d,

    -- ── [Блок G+] Расширенная прибыльность ───────────────────────
    ROUND(
        net_profit_per_unit / NULLIF(price_final, 0) * 100,
    2)                                                         AS margin_pct,
    ROUND(
        (1.0 - ppvz_for_pay / NULLIF(revenue_net, 0)) * 100,
    2)                                                         AS effective_commission_pct

FROM windowed_2;

COMMENT ON VIEW analytics_ai.v_1pager_daily_source IS
'Daily source view for 1pager AI / ML. Зерно: nm_id + report_date (день).
Содержит 14 логических блоков: цены → воронка → конверсии → эластичность →
остатки → оборачиваемость → финансы → ML-фичи → целевые переменные →
сезонность (A) → поставки (B) → маркетинг (C) → возвраты (D) → прибыльность (G+).
Пересобирается вместе с daily 1pager bundle без materialized mart.';
