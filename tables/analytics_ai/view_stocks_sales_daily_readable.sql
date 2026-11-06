CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

CREATE SCHEMA IF NOT EXISTS analytics_ai;

-- Удобное представление: сводка остатков/продаж + название товара, бренд, артикул поставщика.
-- Зерно: одна строка = один nm_id на одном складе на одну дату среза.
-- В представление попадают только склады с положительным остатком.
DROP VIEW IF EXISTS analytics_ai.v_stocks_sales_daily_readable;

CREATE VIEW analytics_ai.v_stocks_sales_daily_readable AS
WITH stock_rows AS (
    SELECT
        snapshot_date,
        nm_id,
        warehouse_name,
        SUM(quantity) AS stock_quantity,
        SUM(quantity_full) AS stock_quantity_full
    FROM supply.v_wb_supplier_stocks_latest_daily
    WHERE nm_id IS NOT NULL
    GROUP BY snapshot_date, nm_id, warehouse_name
    HAVING SUM(quantity) > 0
),
sales_by_nm AS (
    SELECT
        date_ord::date AS snapshot_date,
        nm_id,
        COUNT(*) AS sales_count,
        SUM(COALESCE(for_pay, 0)) AS sales_amount,
        STRING_AGG(DISTINCT warehouse_name, ', ' ORDER BY warehouse_name) AS sales_warehouses
    FROM sales.v_wb_supplier_sales_latest_daily
    WHERE nm_id IS NOT NULL AND date_ord IS NOT NULL
    GROUP BY date_ord::date, nm_id
),
prod_s AS (
    SELECT
        nm_id,
        date_ord::date AS snapshot_date,
        MAX(subject) AS subject,
        MAX(brand) AS brand,
        MAX(supplier_article) AS supplier_article
    FROM sales.v_wb_supplier_sales_latest_daily
    WHERE nm_id IS NOT NULL AND date_ord IS NOT NULL
    GROUP BY nm_id, date_ord::date
),
prod_st AS (
    SELECT
        nm_id,
        snapshot_date,
        MAX(subject) AS subject,
        MAX(brand) AS brand,
        MAX(supplier_article) AS supplier_article
    FROM supply.v_wb_supplier_stocks_latest_daily
    WHERE nm_id IS NOT NULL
    GROUP BY nm_id, snapshot_date
)
SELECT
    s.snapshot_date,
    s.nm_id,
    s.warehouse_name,
    COALESCE(prod_s.subject, prod_st.subject, '') AS subject,
    COALESCE(prod_s.brand, prod_st.brand, '') AS brand,
    COALESCE(prod_s.supplier_article, prod_st.supplier_article, '') AS supplier_article,
    s.stock_quantity,
    s.stock_quantity_full,
    COALESCE(p.sales_count, 0) AS sales_count,
    COALESCE(p.sales_amount, 0) AS sales_amount,
    COALESCE(p.sales_warehouses, '') AS sales_warehouses
FROM stock_rows s
LEFT JOIN sales_by_nm p
    ON s.snapshot_date = p.snapshot_date AND s.nm_id = p.nm_id
LEFT JOIN prod_s
    ON s.snapshot_date = prod_s.snapshot_date AND s.nm_id = prod_s.nm_id
LEFT JOIN prod_st
    ON s.snapshot_date = prod_st.snapshot_date AND s.nm_id = prod_st.nm_id
ORDER BY s.snapshot_date DESC, s.nm_id ASC, s.stock_quantity DESC, s.warehouse_name ASC;

COMMENT ON VIEW analytics_ai.v_stocks_sales_daily_readable IS 'Сводка остатки/продажи по nm_id, складу и дате среза. Только склады с положительным остатком; продажи подтягиваются агрегатом по nm_id без жёсткого джойна по складу.';
