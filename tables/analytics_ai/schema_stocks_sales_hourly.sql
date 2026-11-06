CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE SCHEMA IF NOT EXISTS reports;

DO $$
BEGIN
    IF to_regclass('reports.wb_stocks_sales_hourly') IS NOT NULL AND to_regclass('analytics_ai.wb_stocks_sales_hourly') IS NULL THEN
        EXECUTE 'ALTER TABLE reports.wb_stocks_sales_hourly SET SCHEMA analytics_ai';
    END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS analytics_ai;
CREATE TABLE IF NOT EXISTS analytics_ai.wb_stocks_sales_hourly (
    snapshot_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    snapshot_date DATE NOT NULL,
    nm_id BIGINT NOT NULL,
    warehouse_name VARCHAR(255) NOT NULL,
    stock_quantity INTEGER DEFAULT 0,
    stock_quantity_full INTEGER DEFAULT 0,
    sales_count INTEGER DEFAULT 0,
    sales_amount DECIMAL(12, 2) DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (snapshot_hour, nm_id, warehouse_name)
);

CREATE INDEX IF NOT EXISTS idx_wb_stocks_sales_hourly_hour ON analytics_ai.wb_stocks_sales_hourly(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_stocks_sales_hourly_date ON analytics_ai.wb_stocks_sales_hourly(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_stocks_sales_hourly_nm_id ON analytics_ai.wb_stocks_sales_hourly(nm_id);

CREATE OR REPLACE VIEW analytics_ai.v_stocks_sales_hourly AS
SELECT
    s.snapshot_hour,
    s.snapshot_date,
    s.nm_id,
    s.warehouse_name,
    s.stock_quantity,
    s.stock_quantity_full,
    COALESCE(p.sales_count, 0) AS sales_count,
    COALESCE(p.sales_amount, 0) AS sales_amount
FROM (
    SELECT
        snapshot_hour,
        snapshot_date,
        nm_id,
        warehouse_name,
        SUM(quantity) AS stock_quantity,
        SUM(quantity_full) AS stock_quantity_full
    FROM supply.wb_supplier_stocks
    WHERE nm_id IS NOT NULL
    GROUP BY snapshot_hour, snapshot_date, nm_id, warehouse_name
) s
LEFT JOIN (
    SELECT
        snapshot_hour,
        snapshot_date,
        nm_id,
        warehouse_name,
        COUNT(*) FILTER (WHERE date_ord::date = snapshot_date) AS sales_count,
        SUM(CASE WHEN date_ord::date = snapshot_date THEN COALESCE(for_pay, 0) ELSE 0 END) AS sales_amount
    FROM sales.wb_supplier_sales
    WHERE nm_id IS NOT NULL AND date_ord IS NOT NULL
    GROUP BY snapshot_hour, snapshot_date, nm_id, warehouse_name
) p ON s.snapshot_hour = p.snapshot_hour
   AND s.snapshot_date = p.snapshot_date
   AND s.nm_id = p.nm_id
   AND s.warehouse_name = p.warehouse_name;

COMMENT ON TABLE analytics_ai.wb_stocks_sales_hourly IS
'Hourly-сводка: остатки и продажи по nm_id и складу на конкретный snapshot_hour.';
