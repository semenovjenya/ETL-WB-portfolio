-- =============================================================================
-- Тестовые запросы для витрины reports.mart_ai_sales_planning
--
-- Запускать после первого REFRESH MATERIALIZED VIEW.
-- Каждый блок проверяет один аспект корректности расчётов.
-- =============================================================================


-- ─────────────────────────────────────────────────────────────────
-- [T0] Общая проверка: количество строк, диапазон дат, артикулов
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*)                            AS total_rows,
    COUNT(DISTINCT nm_id)               AS unique_nm_ids,
    MIN(report_date)                    AS date_min,
    MAX(report_date)                    AS date_max,
    COUNT(DISTINCT week_start)          AS total_weeks
FROM reports.mart_ai_sales_planning;


-- ─────────────────────────────────────────────────────────────────
-- [T1] Проверка цен: price_final должна быть <= price_base
--      и >= 0; не должно быть строк где price_base > 0,
--      но price_final = 0 из-за избыточных скидок
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE price_final > price_base)        AS price_final_over_base_cnt,
    COUNT(*) FILTER (WHERE price_base > 0 AND price_final <= 0) AS zero_final_price_cnt,
    COUNT(*) FILTER (WHERE price_change_pct > 200)          AS extreme_price_change_cnt,
    ROUND(AVG(price_final) FILTER (WHERE price_final > 0), 2)   AS avg_price_final,
    MIN(price_final) FILTER (WHERE price_final > 0)         AS min_price_final,
    MAX(price_final)                                        AS max_price_final
FROM reports.mart_ai_sales_planning;
-- Ожидание: price_final_over_base_cnt = 0,
--           extreme_price_change_cnt минимально (единичные акции).


-- ─────────────────────────────────────────────────────────────────
-- [T2] Проверка эластичности
--      Ожидание для нормальных товаров: price_elasticity_point < 0
--      (рост цены → снижение спроса).
--      Допустимо ~10–20% строк с положительной эластичностью
--      (акции с ростом продаж при росте цены — это нормально).
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE price_elasticity_point IS NOT NULL)  AS rows_with_elasticity,
    COUNT(*) FILTER (WHERE price_elasticity_point < 0)          AS negative_elasticity_cnt,
    COUNT(*) FILTER (WHERE price_elasticity_point > 0)          AS positive_elasticity_cnt,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE price_elasticity_point < 0)
        / NULLIF(COUNT(*) FILTER (WHERE price_elasticity_point IS NOT NULL), 0),
    1) AS pct_negative_elasticity,
    ROUND(AVG(price_elasticity_point) FILTER (WHERE price_elasticity_point IS NOT NULL), 4) AS avg_elasticity,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_elasticity_point)
          FILTER (WHERE price_elasticity_point IS NOT NULL)::numeric, 4)                    AS median_elasticity,
    -- Выбросы: |эластичность| > 50 — скорее всего шум (малые знаменатели)
    COUNT(*) FILTER (WHERE ABS(price_elasticity_point) > 50)    AS extreme_elasticity_cnt
FROM reports.mart_ai_sales_planning;


-- ─────────────────────────────────────────────────────────────────
-- [T2b] Топ-10 артикулов по средней эластичности (осмысленные значения)
-- ─────────────────────────────────────────────────────────────────
SELECT
    nm_id,
    MAX(vendor_code)                                            AS vendor_code,
    MAX(brand_name)                                            AS brand_name,
    COUNT(*) FILTER (WHERE price_elasticity_point IS NOT NULL) AS elasticity_days,
    ROUND(AVG(price_elasticity_point)
          FILTER (WHERE price_elasticity_point BETWEEN -50 AND 50), 4) AS avg_elasticity_clean,
    ROUND(AVG(elasticity_rolling_4w)
          FILTER (WHERE elasticity_rolling_4w IS NOT NULL), 4)         AS avg_elasticity_4w
FROM reports.mart_ai_sales_planning
GROUP BY nm_id
HAVING COUNT(*) FILTER (WHERE price_elasticity_point IS NOT NULL) >= 7
ORDER BY ABS(AVG(price_elasticity_point) FILTER (WHERE price_elasticity_point BETWEEN -50 AND 50)) DESC
LIMIT 10;


-- ─────────────────────────────────────────────────────────────────
-- [T3] Проверка оборачиваемости
--      days_of_stock должен быть > 0, если есть остаток и продажи.
--      stock_turnover_weekly должен быть <= 7 (нельзя продать больше,
--      чем среднее количество в наличии, за неделю, более чем
--      в несколько раз — иначе ошибка в данных об остатках).
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE stock_qty > 0 AND sales_28d_avg_per_day > 0)     AS rows_with_turnover,
    COUNT(*) FILTER (WHERE days_of_stock IS NOT NULL AND days_of_stock <= 0) AS zero_or_neg_dos_cnt,
    ROUND(AVG(days_of_stock)
          FILTER (WHERE days_of_stock IS NOT NULL AND days_of_stock > 0), 1) AS avg_days_of_stock,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_of_stock)
          FILTER (WHERE days_of_stock > 0)::numeric, 1)                      AS median_days_of_stock,
    COUNT(*) FILTER (WHERE stock_turnover_weekly > 10)                       AS extreme_turnover_cnt,
    -- Распределение флагов на последнюю дату
    COUNT(*) FILTER (
        WHERE reorder_flag = 'critical'
          AND report_date = (SELECT MAX(report_date) FROM reports.mart_ai_sales_planning)
    )                                                                        AS critical_today,
    COUNT(*) FILTER (
        WHERE reorder_flag = 'warning'
          AND report_date = (SELECT MAX(report_date) FROM reports.mart_ai_sales_planning)
    )                                                                        AS warning_today,
    COUNT(*) FILTER (
        WHERE reorder_flag = 'ok'
          AND report_date = (SELECT MAX(report_date) FROM reports.mart_ai_sales_planning)
    )                                                                        AS ok_today
FROM reports.mart_ai_sales_planning;


-- ─────────────────────────────────────────────────────────────────
-- [T3b] Топ-10 артикулов с критическими остатками (последняя дата)
-- ─────────────────────────────────────────────────────────────────
SELECT
    nm_id,
    vendor_code,
    brand_name,
    subject_name,
    report_date,
    stock_qty,
    sales_28d_avg_per_day,
    ROUND(days_of_stock, 0)             AS days_of_stock,
    reorder_flag
FROM reports.mart_ai_sales_planning
WHERE reorder_flag = 'critical'
  AND report_date = (SELECT MAX(report_date) FROM reports.mart_ai_sales_planning)
  AND sales_28d_avg_per_day > 0
ORDER BY days_of_stock ASC
LIMIT 10;


-- ─────────────────────────────────────────────────────────────────
-- [T4] Проверка ML-фичей: лаги не должны быть NULL
--      для строк, у которых достаточно истории (>28 дней)
-- ─────────────────────────────────────────────────────────────────
WITH nm_history AS (
    SELECT
        nm_id,
        COUNT(*) AS history_days
    FROM reports.mart_ai_sales_planning
    GROUP BY nm_id
    HAVING COUNT(*) > 28
)
SELECT
    COUNT(*)                                                    AS rows_with_28d_history,
    COUNT(*) FILTER (WHERE m.sales_lag_1w IS NULL)             AS null_lag_1w,
    COUNT(*) FILTER (WHERE m.sales_lag_2w IS NULL)             AS null_lag_2w,
    COUNT(*) FILTER (WHERE m.sales_lag_4w IS NULL)             AS null_lag_4w,
    COUNT(*) FILTER (WHERE m.sales_rolling_4w_avg IS NULL)     AS null_rolling_avg,
    COUNT(*) FILTER (WHERE m.target_orders_next_7d IS NULL)    AS null_target_orders,
    COUNT(*) FILTER (WHERE m.target_buyouts_next_7d IS NULL)   AS null_target_buyouts
FROM reports.mart_ai_sales_planning m
JOIN nm_history h ON h.nm_id = m.nm_id
WHERE m.report_date >= (
    SELECT MIN(report_date) + INTERVAL '28 days'
    FROM reports.mart_ai_sales_planning
);
-- Ожидание: null_lag_1w/2w/4w = 0 для записей с историей > 28 дней.
--           null_target_* > 0 только для последних 7 дней (нет будущего).


-- ─────────────────────────────────────────────────────────────────
-- [T5] Проверка финансовых метрик:
--      net_profit_per_unit не должен быть аномально отрицательным
--      (порог: < -5000 скорее всего ошибка данных).
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE net_profit_per_unit IS NOT NULL)        AS rows_with_profit,
    ROUND(AVG(net_profit_per_unit)
          FILTER (WHERE net_profit_per_unit IS NOT NULL), 2)       AS avg_net_profit,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY net_profit_per_unit)
          FILTER (WHERE net_profit_per_unit IS NOT NULL)::numeric, 2) AS median_net_profit,
    COUNT(*) FILTER (WHERE net_profit_per_unit < -5000)            AS extreme_negative_profit_cnt,
    ROUND(SUM(revenue_net)::numeric, 0)                            AS total_revenue_net,
    ROUND(SUM(ppvz_for_pay)::numeric, 0)                          AS total_ppvz_for_pay
FROM reports.mart_ai_sales_planning;


-- ─────────────────────────────────────────────────────────────────
-- [T6] Сводка по последней неделе — итоговый санити-чек
--      (сравните с данными из личного кабинета WB)
-- ─────────────────────────────────────────────────────────────────
SELECT
    week_start,
    COUNT(DISTINCT nm_id)               AS unique_articles,
    SUM(order_count_day)                AS total_orders,
    SUM(buyout_count_day)               AS total_buyouts,
    SUM(cancel_count_day)               AS total_cancels,
    ROUND(SUM(revenue_net)::numeric, 0) AS total_revenue_net,
    ROUND(AVG(order_to_buyout_pct), 1)  AS avg_buyout_pct,
    ROUND(AVG(days_of_stock)
          FILTER (WHERE days_of_stock > 0), 0)  AS avg_days_of_stock
FROM reports.mart_ai_sales_planning
WHERE week_start >= (
    SELECT MAX(week_start) - INTERVAL '4 weeks'
    FROM reports.mart_ai_sales_planning
)
GROUP BY week_start
ORDER BY week_start DESC;


-- ─────────────────────────────────────────────────────────────────
-- [T7] Проверка сезонности и акций
--      is_promo_period должен быть true только для дат в пределах акции.
--      days_to_next_promo должен быть > 0 и < 365.
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE is_promo_period = true)              AS promo_days_count,
    COUNT(*) FILTER (WHERE is_promo_period = false)             AS non_promo_days_count,
    COUNT(*) FILTER (WHERE days_to_next_promo IS NOT NULL
                       AND days_to_next_promo <= 0)             AS invalid_days_to_promo,
    COUNT(*) FILTER (WHERE days_to_next_promo > 365)            AS far_promo_cnt,
    COUNT(*) FILTER (WHERE yoy_orders_change_pct IS NOT NULL)   AS rows_with_yoy,
    ROUND(AVG(yoy_orders_change_pct)
          FILTER (WHERE yoy_orders_change_pct IS NOT NULL
                    AND ABS(yoy_orders_change_pct) < 500), 2)   AS avg_yoy_pct,
    COUNT(*) FILTER (WHERE is_weekend = true
                       AND report_date = (SELECT MAX(report_date) FROM reports.mart_ai_sales_planning))
                                                                AS weekend_check_last_date
FROM reports.mart_ai_sales_planning;
-- Ожидание: invalid_days_to_promo = 0;
--           rows_with_yoy > 0 только если есть данные старше 364 дней.


-- ─────────────────────────────────────────────────────────────────
-- [T8] Проверка блока поставок
--      last_supply_date не должна быть в будущем.
--      days_since_last_supply >= 0 для строк с last_supply_date.
--      reorder_qty_recommended >= 0 всегда.
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE last_supply_date IS NOT NULL)        AS rows_with_supply_date,
    COUNT(*) FILTER (WHERE last_supply_date > report_date)      AS future_supply_date_cnt,
    COUNT(*) FILTER (WHERE days_since_last_supply < 0)          AS negative_days_since_supply,
    COUNT(*) FILTER (WHERE pending_supply_qty < 0)              AS negative_pending_qty,
    COUNT(*) FILTER (WHERE reorder_qty_recommended < 0)         AS negative_reorder_cnt,
    ROUND(AVG(days_since_last_supply)
          FILTER (WHERE days_since_last_supply IS NOT NULL), 1) AS avg_days_since_supply,
    ROUND(AVG(avg_supply_interval_days)
          FILTER (WHERE avg_supply_interval_days IS NOT NULL), 1) AS avg_supply_interval,
    -- Топ-5 артикулов по рекомендуемому пополнению (последняя дата)
    COUNT(*) FILTER (
        WHERE reorder_qty_recommended > 0
          AND report_date = (SELECT MAX(report_date) FROM reports.mart_ai_sales_planning)
    )                                                           AS nm_need_reorder_today
FROM reports.mart_ai_sales_planning;
-- Ожидание: future_supply_date_cnt = 0;
--           negative_days_since_supply = 0; negative_reorder_cnt = 0.


-- ─────────────────────────────────────────────────────────────────
-- [T8b] Топ-10 артикулов с наибольшим рекомендуемым пополнением
-- ─────────────────────────────────────────────────────────────────
SELECT
    nm_id,
    vendor_code,
    brand_name,
    subject_name,
    report_date,
    stock_qty,
    pending_supply_qty,
    sales_28d_avg_per_day,
    ROUND(days_of_stock, 0)                                     AS days_of_stock,
    reorder_qty_recommended,
    last_supply_date,
    days_since_last_supply
FROM reports.mart_ai_sales_planning
WHERE report_date = (SELECT MAX(report_date) FROM reports.mart_ai_sales_planning)
  AND reorder_qty_recommended > 0
  AND sales_28d_avg_per_day > 0
ORDER BY reorder_qty_recommended DESC
LIMIT 10;


-- ─────────────────────────────────────────────────────────────────
-- [T9] Проверка блока маркетинга
--      adv_spend_day >= 0; adv_cpo > 0 если есть spend и orders.
--      adv_roas > 0 если есть revenue_net и spend.
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE adv_spend_day > 0)                  AS rows_with_adv_spend,
    COUNT(*) FILTER (WHERE has_active_campaign = true)         AS rows_with_campaign,
    COUNT(*) FILTER (WHERE adv_spend_day < 0)                  AS negative_adv_spend,
    COUNT(*) FILTER (WHERE adv_cpo IS NOT NULL AND adv_cpo <= 0) AS zero_or_neg_cpo,
    ROUND(AVG(adv_cpo)   FILTER (WHERE adv_cpo   > 0), 2)      AS avg_cpo,
    ROUND(AVG(adv_roas)  FILTER (WHERE adv_roas  > 0), 2)      AS avg_roas,
    ROUND(SUM(adv_spend_day)::numeric, 0)                       AS total_adv_spend,
    ROUND(SUM(adv_orders_day)::numeric, 0)                      AS total_adv_orders
FROM reports.mart_ai_sales_planning;
-- Ожидание: negative_adv_spend = 0; zero_or_neg_cpo = 0.


-- ─────────────────────────────────────────────────────────────────
-- [T10] Проверка блока возвратов
--       return_count_day >= 0; net_sales_day = buyout - return.
--       return_rate_30d в диапазоне [0, 100].
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE return_count_day > 0)               AS rows_with_returns,
    COUNT(*) FILTER (WHERE return_count_day < 0)               AS negative_return_cnt,
    COUNT(*) FILTER (WHERE net_sales_day <> buyout_count_day - return_count_day) AS net_sales_mismatch,
    COUNT(*) FILTER (WHERE return_rate_30d IS NOT NULL
                       AND (return_rate_30d < 0 OR return_rate_30d > 100))
                                                               AS invalid_return_rate,
    ROUND(AVG(return_rate_30d)
          FILTER (WHERE return_rate_30d IS NOT NULL), 2)       AS avg_return_rate_30d,
    ROUND(SUM(return_count_day)::numeric, 0)                    AS total_returns,
    ROUND(SUM(return_sum_day)::numeric, 0)                      AS total_return_sum
FROM reports.mart_ai_sales_planning;
-- Ожидание: negative_return_cnt = 0; net_sales_mismatch = 0;
--           invalid_return_rate = 0.


-- ─────────────────────────────────────────────────────────────────
-- [T10b] Проверка флага аномалий конверсий
--        Флаг должен поднимать строки, где funnel-конверсии выходят за [0, 100].
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE is_conversion_anomaly = true)       AS anomaly_rows_total,
    COUNT(*) FILTER (
        WHERE is_conversion_anomaly = true
          AND report_date = (SELECT MAX(report_date) FROM reports.mart_ai_sales_planning)
    )                                                          AS anomaly_rows_last_date,
    COUNT(*) FILTER (
        WHERE is_conversion_anomaly = true
          AND cart_to_order_pct > 100
    )                                                          AS cart_to_order_gt_100_rows,
    COUNT(*) FILTER (
        WHERE is_conversion_anomaly = true
          AND open_to_cart_pct > 100
    )                                                          AS open_to_cart_gt_100_rows,
    COUNT(*) FILTER (
        WHERE is_conversion_anomaly = true
          AND order_to_buyout_pct > 100
    )                                                          AS order_to_buyout_gt_100_rows
FROM reports.mart_ai_sales_planning;


-- ─────────────────────────────────────────────────────────────────
-- [T11] Проверка расширенной прибыльности
--       margin_pct в диапазоне [-100, 100] для нормальных товаров.
--       effective_commission_pct > 0 если есть выручка.
-- ─────────────────────────────────────────────────────────────────
SELECT
    COUNT(*) FILTER (WHERE margin_pct IS NOT NULL)             AS rows_with_margin,
    COUNT(*) FILTER (WHERE margin_pct > 100 OR margin_pct < -100) AS extreme_margin_cnt,
    ROUND(AVG(margin_pct)
          FILTER (WHERE margin_pct IS NOT NULL
                    AND margin_pct BETWEEN -100 AND 100), 2)   AS avg_margin_pct,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY margin_pct)
          FILTER (WHERE margin_pct IS NOT NULL
                    AND margin_pct BETWEEN -100 AND 100)::numeric, 2)
                                                               AS median_margin_pct,
    COUNT(*) FILTER (WHERE effective_commission_pct IS NOT NULL) AS rows_with_eff_commission,
    ROUND(AVG(effective_commission_pct)
          FILTER (WHERE effective_commission_pct IS NOT NULL
                    AND effective_commission_pct BETWEEN 0 AND 100), 2)
                                                               AS avg_effective_commission_pct
FROM reports.mart_ai_sales_planning;
-- Ожидание: extreme_margin_cnt минимально (единичные аномалии данных);
--           avg_effective_commission_pct типично 15–35% для WB.
