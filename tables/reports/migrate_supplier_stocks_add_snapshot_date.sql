-- Миграция: добавить snapshot_date в существующую таблицу (если она уже создана без этой колонки).
-- Выполнить один раз вручную: psql -f tables/reports/migrate_supplier_stocks_add_snapshot_date.sql
ALTER TABLE reports.wb_supplier_stocks ADD COLUMN IF NOT EXISTS snapshot_date DATE;
UPDATE reports.wb_supplier_stocks SET snapshot_date = CURRENT_DATE WHERE snapshot_date IS NULL;
ALTER TABLE reports.wb_supplier_stocks ALTER COLUMN snapshot_date SET NOT NULL;
ALTER TABLE reports.wb_supplier_stocks DROP CONSTRAINT IF EXISTS wb_supplier_stocks_barcode_warehouse_name_key;
ALTER TABLE reports.wb_supplier_stocks DROP CONSTRAINT IF EXISTS reports_wb_supplier_stocks_barcode_warehouse_name_key;
ALTER TABLE reports.wb_supplier_stocks ADD CONSTRAINT wb_supplier_stocks_barcode_warehouse_snapshot_key UNIQUE (barcode, warehouse_name, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_supplier_stocks_snapshot_date ON reports.wb_supplier_stocks(snapshot_date);
