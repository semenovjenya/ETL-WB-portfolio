-- tariffs WB (API common-api: commission, box, pallet, return, acceptance/coefficients).
-- Один срез в день по snapshot_date, история накапливается.
CREATE SCHEMA IF NOT EXISTS reports;

-- Комиссия WB по родительским категориям (GET /api/v1/tariffs/commission)
CREATE TABLE IF NOT EXISTS reports.wb_tariffs_commission (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    report_json JSONB NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- tariffs на остаток (короба) (GET /api/v1/tariffs/box)
CREATE TABLE IF NOT EXISTS reports.wb_tariffs_box (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    response_json JSONB NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- tariffs на остаток (паллеты) (GET /api/v1/tariffs/pallet)
CREATE TABLE IF NOT EXISTS reports.wb_tariffs_pallet (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    response_json JSONB NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Стоимость возврата продавцу (GET /api/v1/tariffs/return)
CREATE TABLE IF NOT EXISTS reports.wb_tariffs_return (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    response_json JSONB NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- tariffs на поставку (коэффициенты приёмки) (GET /api/tariffs/v1/acceptance/coefficients)
CREATE TABLE IF NOT EXISTS reports.wb_tariffs_acceptance (
    id BIGSERIAL PRIMARY KEY,
    snapshot_hour TIMESTAMP WITH TIME ZONE,
    snapshot_date DATE NOT NULL,
    data_json JSONB NOT NULL,
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE reports.wb_tariffs_commission ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
ALTER TABLE reports.wb_tariffs_box ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
ALTER TABLE reports.wb_tariffs_pallet ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
ALTER TABLE reports.wb_tariffs_return ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;
ALTER TABLE reports.wb_tariffs_acceptance ADD COLUMN IF NOT EXISTS snapshot_hour TIMESTAMP WITH TIME ZONE;

UPDATE reports.wb_tariffs_commission SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp) WHERE snapshot_hour IS NULL;
UPDATE reports.wb_tariffs_box SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp) WHERE snapshot_hour IS NULL;
UPDATE reports.wb_tariffs_pallet SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp) WHERE snapshot_hour IS NULL;
UPDATE reports.wb_tariffs_return SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp) WHERE snapshot_hour IS NULL;
UPDATE reports.wb_tariffs_acceptance SET snapshot_hour = timezone('Europe/Moscow', snapshot_date::timestamp) WHERE snapshot_hour IS NULL;

ALTER TABLE reports.wb_tariffs_commission ALTER COLUMN snapshot_hour SET NOT NULL;
ALTER TABLE reports.wb_tariffs_box ALTER COLUMN snapshot_hour SET NOT NULL;
ALTER TABLE reports.wb_tariffs_pallet ALTER COLUMN snapshot_hour SET NOT NULL;
ALTER TABLE reports.wb_tariffs_return ALTER COLUMN snapshot_hour SET NOT NULL;
ALTER TABLE reports.wb_tariffs_acceptance ALTER COLUMN snapshot_hour SET NOT NULL;

DO $$
DECLARE table_name text;
DECLARE constraint_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'wb_tariffs_commission',
    'wb_tariffs_box',
    'wb_tariffs_pallet',
    'wb_tariffs_return',
    'wb_tariffs_acceptance'
  ]
  LOOP
    FOR constraint_name IN
      EXECUTE format(
        'SELECT conname FROM pg_constraint WHERE conrelid = %L::regclass AND contype = ''u''',
        'reports.' || table_name
      )
    LOOP
      EXECUTE format('ALTER TABLE reports.%I DROP CONSTRAINT IF EXISTS %I', table_name, constraint_name);
    END LOOP;
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_tariffs_commission_snapshot_hour_key ON reports.wb_tariffs_commission(snapshot_hour);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_tariffs_box_snapshot_hour_key ON reports.wb_tariffs_box(snapshot_hour);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_tariffs_pallet_snapshot_hour_key ON reports.wb_tariffs_pallet(snapshot_hour);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_tariffs_return_snapshot_hour_key ON reports.wb_tariffs_return(snapshot_hour);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wb_tariffs_acceptance_snapshot_hour_key ON reports.wb_tariffs_acceptance(snapshot_hour);

CREATE INDEX IF NOT EXISTS idx_wb_tariffs_commission_snapshot ON reports.wb_tariffs_commission(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_tariffs_box_snapshot ON reports.wb_tariffs_box(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_tariffs_pallet_snapshot ON reports.wb_tariffs_pallet(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_tariffs_return_snapshot ON reports.wb_tariffs_return(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_tariffs_acceptance_snapshot ON reports.wb_tariffs_acceptance(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_wb_tariffs_commission_snapshot_hour ON reports.wb_tariffs_commission(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_tariffs_box_snapshot_hour ON reports.wb_tariffs_box(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_tariffs_pallet_snapshot_hour ON reports.wb_tariffs_pallet(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_tariffs_return_snapshot_hour ON reports.wb_tariffs_return(snapshot_hour);
CREATE INDEX IF NOT EXISTS idx_wb_tariffs_acceptance_snapshot_hour ON reports.wb_tariffs_acceptance(snapshot_hour);

COMMENT ON TABLE reports.wb_tariffs_commission IS 'Комиссия WB по категориям (common-api tariffs/commission).';
COMMENT ON TABLE reports.wb_tariffs_box IS 'tariffs на остаток (короба) по складам (common-api tariffs/box).';
COMMENT ON TABLE reports.wb_tariffs_pallet IS 'tariffs на остаток (паллеты) по складам (common-api tariffs/pallet).';
COMMENT ON TABLE reports.wb_tariffs_return IS 'Стоимость возврата продавцу по складам (common-api tariffs/return).';
COMMENT ON TABLE reports.wb_tariffs_acceptance IS 'Коэффициенты приёмки на поставку по складам (common-api acceptance/coefficients).';

CREATE OR REPLACE FUNCTION reports.parse_wb_numeric(value_text TEXT)
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

COMMENT ON FUNCTION reports.parse_wb_numeric(TEXT) IS
'Преобразует строковые числа WB вида ''1 046'', ''0,07'' или ''-'' в numeric.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_commission AS
SELECT
    t.snapshot_date,
    (item->>'parentID')::BIGINT                              AS parent_id,
    NULLIF(item->>'parentName', '')                          AS parent_name,
    (item->>'subjectID')::BIGINT                             AS subject_id,
    NULLIF(item->>'subjectName', '')                         AS subject_name,
    reports.parse_wb_numeric(item->>'kgvpBooking')           AS kgvp_booking,
    reports.parse_wb_numeric(item->>'kgvpMarketplace')       AS kgvp_marketplace,
    reports.parse_wb_numeric(item->>'kgvpPickup')            AS kgvp_pickup,
    reports.parse_wb_numeric(item->>'kgvpSupplier')          AS kgvp_supplier,
    reports.parse_wb_numeric(item->>'kgvpSupplierExpress')   AS kgvp_supplier_express,
    reports.parse_wb_numeric(item->>'paidStorageKgvp')       AS paid_storage_kgvp,
    t.snapshot_hour
FROM reports.wb_tariffs_commission t
CROSS JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(t.report_json) = 'array' THEN t.report_json
        ELSE '[]'::jsonb
    END
) AS item;

COMMENT ON VIEW reports.v_wb_tariffs_commission IS
'Нормализованные тарифы комиссии WB по subject_id/subject_name из JSON-срезов wb_tariffs_commission.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_commission_latest AS
SELECT *
FROM reports.v_wb_tariffs_commission
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_tariffs_commission
);

COMMENT ON VIEW reports.v_wb_tariffs_commission_latest IS
'Последний доступный срез комиссии WB по категориям.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_box AS
SELECT
    t.snapshot_date,
    NULLIF(t.response_json->>'dtNextBox', '')::DATE                  AS dt_next_box,
    NULLIF(t.response_json->>'dtTillMax', '')::DATE                  AS dt_till_max,
    NULLIF(item->>'warehouseName', '')                               AS warehouse_name,
    NULLIF(item->>'geoName', '')                                     AS geo_name,
    reports.parse_wb_numeric(item->>'boxDeliveryBase')               AS box_delivery_base,
    reports.parse_wb_numeric(item->>'boxDeliveryLiter')              AS box_delivery_liter,
    reports.parse_wb_numeric(item->>'boxDeliveryCoefExpr')           AS box_delivery_coef_expr,
    reports.parse_wb_numeric(item->>'boxDeliveryMarketplaceBase')    AS box_delivery_marketplace_base,
    reports.parse_wb_numeric(item->>'boxDeliveryMarketplaceLiter')   AS box_delivery_marketplace_liter,
    reports.parse_wb_numeric(item->>'boxDeliveryMarketplaceCoefExpr') AS box_delivery_marketplace_coef_expr,
    reports.parse_wb_numeric(item->>'boxStorageBase')                AS box_storage_base,
    reports.parse_wb_numeric(item->>'boxStorageLiter')               AS box_storage_liter,
    reports.parse_wb_numeric(item->>'boxStorageCoefExpr')            AS box_storage_coef_expr,
    t.snapshot_hour
FROM reports.wb_tariffs_box t
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(t.response_json->'warehouseList', '[]'::jsonb)
) AS item;

COMMENT ON VIEW reports.v_wb_tariffs_box IS
'Нормализованные box-тарифы WB по складам из JSON-срезов wb_tariffs_box.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_box_latest AS
SELECT *
FROM reports.v_wb_tariffs_box
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_tariffs_box
);

COMMENT ON VIEW reports.v_wb_tariffs_box_latest IS
'Последний доступный срез box-тарифов WB по складам.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_pallet AS
SELECT
    t.snapshot_date,
    NULLIF(t.response_json->>'dtNextPallet', '')::DATE               AS dt_next_pallet,
    NULLIF(t.response_json->>'dtTillMax', '')::DATE                  AS dt_till_max,
    NULLIF(item->>'warehouseName', '')                               AS warehouse_name,
    reports.parse_wb_numeric(item->>'palletDeliveryValueBase')       AS pallet_delivery_value_base,
    reports.parse_wb_numeric(item->>'palletDeliveryValueLiter')      AS pallet_delivery_value_liter,
    reports.parse_wb_numeric(item->>'palletDeliveryExpr')            AS pallet_delivery_expr,
    reports.parse_wb_numeric(item->>'palletStorageValueExpr')        AS pallet_storage_value_expr,
    reports.parse_wb_numeric(item->>'palletStorageExpr')             AS pallet_storage_expr,
    t.snapshot_hour
FROM reports.wb_tariffs_pallet t
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(t.response_json->'warehouseList', '[]'::jsonb)
) AS item;

COMMENT ON VIEW reports.v_wb_tariffs_pallet IS
'Нормализованные pallet-тарифы WB по складам из JSON-срезов wb_tariffs_pallet.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_pallet_latest AS
SELECT *
FROM reports.v_wb_tariffs_pallet
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_tariffs_pallet
);

COMMENT ON VIEW reports.v_wb_tariffs_pallet_latest IS
'Последний доступный срез pallet-тарифов WB по складам.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_return AS
SELECT
    t.snapshot_date,
    NULLIF(t.response_json->>'dtNextDeliveryDumpKgt', '')::DATE      AS dt_next_delivery_dump_kgt,
    NULLIF(t.response_json->>'dtNextDeliveryDumpSrg', '')::DATE      AS dt_next_delivery_dump_srg,
    NULLIF(t.response_json->>'dtNextDeliveryDumpSup', '')::DATE      AS dt_next_delivery_dump_sup,
    NULLIF(item->>'warehouseName', '')                               AS warehouse_name,
    reports.parse_wb_numeric(item->>'deliveryDumpKgtOfficeBase')     AS delivery_dump_kgt_office_base,
    reports.parse_wb_numeric(item->>'deliveryDumpKgtOfficeLiter')    AS delivery_dump_kgt_office_liter,
    reports.parse_wb_numeric(item->>'deliveryDumpKgtReturnExpr')     AS delivery_dump_kgt_return_expr,
    reports.parse_wb_numeric(item->>'deliveryDumpSrgOfficeExpr')     AS delivery_dump_srg_office_expr,
    reports.parse_wb_numeric(item->>'deliveryDumpSrgReturnExpr')     AS delivery_dump_srg_return_expr,
    reports.parse_wb_numeric(item->>'deliveryDumpSupCourierBase')    AS delivery_dump_sup_courier_base,
    reports.parse_wb_numeric(item->>'deliveryDumpSupCourierLiter')   AS delivery_dump_sup_courier_liter,
    reports.parse_wb_numeric(item->>'deliveryDumpSupOfficeBase')     AS delivery_dump_sup_office_base,
    reports.parse_wb_numeric(item->>'deliveryDumpSupOfficeLiter')    AS delivery_dump_sup_office_liter,
    reports.parse_wb_numeric(item->>'deliveryDumpSupReturnExpr')     AS delivery_dump_sup_return_expr,
    t.snapshot_hour
FROM reports.wb_tariffs_return t
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(t.response_json->'warehouseList', '[]'::jsonb)
) AS item;

COMMENT ON VIEW reports.v_wb_tariffs_return IS
'Нормализованные тарифы возврата продавцу по складам из JSON-срезов wb_tariffs_return.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_return_latest AS
SELECT *
FROM reports.v_wb_tariffs_return
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_tariffs_return
);

COMMENT ON VIEW reports.v_wb_tariffs_return_latest IS
'Последний доступный срез тарифов возврата продавцу.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_acceptance AS
SELECT
    t.snapshot_date,
    NULLIF(item->>'date', '')::TIMESTAMPTZ                           AS tariff_datetime,
    (item->>'warehouseID')::BIGINT                                   AS warehouse_id,
    NULLIF(item->>'warehouseName', '')                               AS warehouse_name,
    (item->>'boxTypeID')::INT                                        AS box_type_id,
    (item->>'allowUnload')::BOOLEAN                                  AS allow_unload,
    (item->>'isSortingCenter')::BOOLEAN                              AS is_sorting_center,
    reports.parse_wb_numeric(item->>'coefficient')                   AS coefficient,
    reports.parse_wb_numeric(item->>'storageCoef')                   AS storage_coef,
    reports.parse_wb_numeric(item->>'deliveryCoef')                  AS delivery_coef,
    reports.parse_wb_numeric(item->>'deliveryBaseLiter')             AS delivery_base_liter,
    reports.parse_wb_numeric(item->>'deliveryAdditionalLiter')       AS delivery_additional_liter,
    reports.parse_wb_numeric(item->>'storageBaseLiter')              AS storage_base_liter,
    reports.parse_wb_numeric(item->>'storageAdditionalLiter')        AS storage_additional_liter,
    t.snapshot_hour
FROM reports.wb_tariffs_acceptance t
CROSS JOIN LATERAL jsonb_array_elements(
    CASE
        WHEN jsonb_typeof(t.data_json) = 'array' THEN t.data_json
        ELSE '[]'::jsonb
    END
) AS item;

COMMENT ON VIEW reports.v_wb_tariffs_acceptance IS
'Нормализованные коэффициенты приёмки WB по складам и типу короба.';

CREATE OR REPLACE VIEW reports.v_wb_tariffs_acceptance_latest AS
SELECT *
FROM reports.v_wb_tariffs_acceptance
WHERE snapshot_hour = (
    SELECT MAX(snapshot_hour)
    FROM reports.wb_tariffs_acceptance
);

COMMENT ON VIEW reports.v_wb_tariffs_acceptance_latest IS
'Последний доступный срез коэффициентов приёмки WB.';
