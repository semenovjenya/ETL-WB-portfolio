-- Заполнить/обновить reports.wb_stocks_sales_daily на последнюю дату среза остатков.
-- Запускать после загрузки остатков и продаж.
-- Для другой даты замените подзапрос на нужную дату, например '2026-03-03'.

INSERT INTO reports.wb_stocks_sales_daily (
    snapshot_date,
    nm_id,
    warehouse_name,
    stock_quantity,
    stock_quantity_full,
    sales_count,
    sales_amount,
    updated_at
)
SELECT
    snapshot_date,
    nm_id,
    warehouse_name,
    stock_quantity,
    stock_quantity_full,
    sales_count,
    sales_amount,
    CURRENT_TIMESTAMP
FROM reports.v_stocks_sales_daily
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM reports.v_wb_supplier_stocks_latest_daily)
ON CONFLICT (snapshot_date, nm_id, warehouse_name)
DO UPDATE SET
    stock_quantity = EXCLUDED.stock_quantity,
    stock_quantity_full = EXCLUDED.stock_quantity_full,
    sales_count = EXCLUDED.sales_count,
    sales_amount = EXCLUDED.sales_amount,
    updated_at = EXCLUDED.updated_at;
