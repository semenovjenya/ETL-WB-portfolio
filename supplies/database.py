"""Модуль для работы с PostgreSQL для поставок WB (supplies)."""
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional, Any
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


class SuppliesDatabase:
    """БД для поставок WB."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (поставки)")
        except psycopg2.Error as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            raise

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к БД закрыто")

    def truncate_supplies_and_progress(self) -> None:
        """Очистить таблицы поставок и прогресса (для полной перезаливки)."""
        try:
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_supplies_goods RESTART IDENTITY CASCADE")
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_supplies RESTART IDENTITY CASCADE")
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_supplies_progress RESTART IDENTITY CASCADE")
            logger.info("Таблицы reports.wb_supplies, wb_supplies_goods и wb_supplies_progress очищены")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при очистке таблиц поставок: {e}")
            raise

    def create_tables(self) -> None:
        try:
            execute_ddl_bundle(self.cursor, "schema_wb_supplies.sql")
            logger.info("Таблицы поставок созданы или уже существуют")
        except FileNotFoundError:
            logger.warning("Файл schema_wb_supplies.sql не найден")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise

    def get_last_create_date_from(self) -> Optional[datetime]:
        try:
            execute_sql(self.cursor, 
                """
                SELECT last_create_date
                FROM reports.wb_supplies_progress
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            row = self.cursor.fetchone()
            return row[0] if row else None
        except psycopg2.Error as e:
            logger.error(f"Ошибка при чтении прогресса поставок: {e}")
            return None

    def save_progress(self, last_create_date: datetime) -> None:
        try:
            execute_sql(self.cursor, 
                """
                INSERT INTO reports.wb_supplies_progress (last_create_date, updated_at)
                VALUES (%s, CURRENT_TIMESTAMP)
                """,
                (last_create_date,),
            )
            logger.info(f"Прогресс поставок сохранён: last_create_date={last_create_date}")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при сохранении прогресса: {e}")
            raise

    @staticmethod
    def _get_any(item: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in item:
                return item[k]
        return default

    def parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        s = str(value).strip()
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            pass
        if s.endswith("Z"):
            s = s[:-1]
        if "." in s:
            main, frac = s.split(".", 1)
            tz_pos = max(frac.find("+"), frac.find("-"))
            if tz_pos != -1:
                s = main + frac[tz_pos:]
            else:
                s = main
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    def parse_date(self, value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        dt = self.parse_datetime(value)
        return dt.date() if dt else None

    def normalize_supply_row(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Нормализация строки из POST /supplies или GET /supplies/{ID}."""
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        return {
            "supply_id": get_("supplyID", "supply_id"),
            "preorder_id": get_("preorderID", "preorder_id"),
            "create_date": self.parse_datetime(get_("createDate", "create_date")),
            "supply_date": self.parse_date(get_("supplyDate", "supply_date")),
            "fact_date": self.parse_datetime(get_("factDate", "fact_date")),
            "updated_date": self.parse_datetime(get_("updatedDate", "updated_date")),
            "status_id": get_("statusID", "status_id"),
            "phone": get_("phone"),
            "box_type_id": get_("boxTypeID", "box_type_id"),
            "warehouse_id": get_("warehouseID", "warehouse_id"),
            "warehouse_name": get_("warehouseName", "warehouse_name"),
            "actual_warehouse_id": get_("actualWarehouseID", "actual_warehouse_id"),
            "actual_warehouse_name": get_("actualWarehouseName", "actual_warehouse_name"),
            "transit_warehouse_id": get_("transitWarehouseID", "transit_warehouse_id"),
            "transit_warehouse_name": get_("transitWarehouseName", "transit_warehouse_name"),
            "acceptance_cost": get_("acceptanceCost", "acceptance_cost"),
            "paid_acceptance_coefficient": get_("paidAcceptanceCoefficient", "paid_acceptance_coefficient"),
            "reject_reason": get_("rejectReason", "reject_reason"),
            "supplier_assign_name": get_("supplierAssignName", "supplier_assign_name"),
            "storage_coef": str(get_("storageCoef", "storage_coef") or "") or None,
            "delivery_coef": str(get_("deliveryCoef", "delivery_coef") or "") or None,
            "quantity": get_("quantity"),
            "ready_for_sale_quantity": get_("readyForSaleQuantity", "ready_for_sale_quantity"),
            "accepted_quantity": get_("acceptedQuantity", "accepted_quantity"),
            "unloading_quantity": get_("unloadingQuantity", "unloading_quantity"),
            "depersonalized_quantity": get_("depersonalizedQuantity", "depersonalized_quantity"),
        }

    def normalize_goods_row(self, supply_id: int, item: Dict[str, Any]) -> Dict[str, Any]:
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        return {
            "supply_id": supply_id,
            "barcode": get_("barcode"),
            "vendor_code": get_("vendorCode", "vendor_code"),
            "nm_id": get_("nmID", "nm_id"),
            "need_kiz": get_("needKiz", "need_kiz"),
            "tnved": get_("tnved"),
            "tech_size": get_("techSize", "tech_size"),
            "color": get_("color"),
            "supplier_box_amount": get_("supplierBoxAmount", "supplier_box_amount"),
            "quantity": get_("quantity"),
            "ready_for_sale_quantity": get_("readyForSaleQuantity", "ready_for_sale_quantity"),
            "unloading_quantity": get_("unloadingQuantity", "unloading_quantity"),
            "accepted_quantity": get_("acceptedQuantity", "accepted_quantity"),
        }

    def upsert_supplies_batch(self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime) -> int:
        """Пакетная вставка списка поставок: по supply_id и по preorder_id (два partial unique индекса)."""
        if not rows:
            return 0
        normalized = [self.normalize_supply_row(r) for r in rows]
        valid = [r for r in normalized if r.get("supply_id") is not None or r.get("preorder_id") is not None]
        for r in valid:
            r["snapshot_date"] = snapshot_date

        ins = """
            INSERT INTO reports.wb_supplies (
                snapshot_date, supply_id, preorder_id, create_date, supply_date, fact_date,
                updated_date, status_id, phone, box_type_id, warehouse_id, warehouse_name,
                actual_warehouse_id, actual_warehouse_name, transit_warehouse_id, transit_warehouse_name,
                acceptance_cost, paid_acceptance_coefficient, reject_reason, supplier_assign_name,
                storage_coef, delivery_coef, quantity, ready_for_sale_quantity, accepted_quantity,
                unloading_quantity, depersonalized_quantity, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(supply_id)s, %(preorder_id)s, %(create_date)s, %(supply_date)s, %(fact_date)s,
                %(updated_date)s, %(status_id)s, %(phone)s, %(box_type_id)s, %(warehouse_id)s, %(warehouse_name)s,
                %(actual_warehouse_id)s, %(actual_warehouse_name)s, %(transit_warehouse_id)s, %(transit_warehouse_name)s,
                %(acceptance_cost)s, %(paid_acceptance_coefficient)s, %(reject_reason)s, %(supplier_assign_name)s,
                %(storage_coef)s, %(delivery_coef)s, %(quantity)s, %(ready_for_sale_quantity)s, %(accepted_quantity)s,
                %(unloading_quantity)s, %(depersonalized_quantity)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (snapshot_date, supply_id) WHERE supply_id IS NOT NULL DO UPDATE SET
                create_date = EXCLUDED.create_date, supply_date = EXCLUDED.supply_date, fact_date = EXCLUDED.fact_date,
                updated_date = EXCLUDED.updated_date, status_id = EXCLUDED.status_id, phone = EXCLUDED.phone,
                box_type_id = EXCLUDED.box_type_id, warehouse_id = EXCLUDED.warehouse_id, warehouse_name = EXCLUDED.warehouse_name,
                actual_warehouse_id = EXCLUDED.actual_warehouse_id, actual_warehouse_name = EXCLUDED.actual_warehouse_name,
                transit_warehouse_id = EXCLUDED.transit_warehouse_id, transit_warehouse_name = EXCLUDED.transit_warehouse_name,
                acceptance_cost = EXCLUDED.acceptance_cost, paid_acceptance_coefficient = EXCLUDED.paid_acceptance_coefficient,
                reject_reason = EXCLUDED.reject_reason, supplier_assign_name = EXCLUDED.supplier_assign_name,
                storage_coef = EXCLUDED.storage_coef, delivery_coef = EXCLUDED.delivery_coef,
                quantity = EXCLUDED.quantity, ready_for_sale_quantity = EXCLUDED.ready_for_sale_quantity,
                accepted_quantity = EXCLUDED.accepted_quantity, unloading_quantity = EXCLUDED.unloading_quantity,
                depersonalized_quantity = EXCLUDED.depersonalized_quantity, last_synced_at = CURRENT_TIMESTAMP
        """
        with_supply_id = [r for r in valid if r.get("supply_id") is not None]
        with_preorder_only = [r for r in valid if r.get("supply_id") is None and r.get("preorder_id") is not None]

        try:
            if with_supply_id:
                executemany_sql(self.cursor, ins, with_supply_id)
            if with_preorder_only:
                ins_preorder = """
                    INSERT INTO reports.wb_supplies (
                        snapshot_date, supply_id, preorder_id, create_date, supply_date, fact_date,
                        updated_date, status_id, phone, box_type_id, warehouse_id, warehouse_name,
                        actual_warehouse_id, actual_warehouse_name, transit_warehouse_id, transit_warehouse_name,
                        acceptance_cost, paid_acceptance_coefficient, reject_reason, supplier_assign_name,
                        storage_coef, delivery_coef, quantity, ready_for_sale_quantity, accepted_quantity,
                        unloading_quantity, depersonalized_quantity, last_synced_at
                    ) VALUES (
                        %(snapshot_date)s, %(supply_id)s, %(preorder_id)s, %(create_date)s, %(supply_date)s, %(fact_date)s,
                        %(updated_date)s, %(status_id)s, %(phone)s, %(box_type_id)s, %(warehouse_id)s, %(warehouse_name)s,
                        %(actual_warehouse_id)s, %(actual_warehouse_name)s, %(transit_warehouse_id)s, %(transit_warehouse_name)s,
                        %(acceptance_cost)s, %(paid_acceptance_coefficient)s, %(reject_reason)s, %(supplier_assign_name)s,
                        %(storage_coef)s, %(delivery_coef)s, %(quantity)s, %(ready_for_sale_quantity)s, %(accepted_quantity)s,
                        %(unloading_quantity)s, %(depersonalized_quantity)s, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (snapshot_date, preorder_id) WHERE supply_id IS NULL DO UPDATE SET
                        create_date = EXCLUDED.create_date, supply_date = EXCLUDED.supply_date, fact_date = EXCLUDED.fact_date,
                        updated_date = EXCLUDED.updated_date, status_id = EXCLUDED.status_id, phone = EXCLUDED.phone,
                        box_type_id = EXCLUDED.box_type_id, warehouse_id = EXCLUDED.warehouse_id, warehouse_name = EXCLUDED.warehouse_name,
                        actual_warehouse_id = EXCLUDED.actual_warehouse_id, actual_warehouse_name = EXCLUDED.actual_warehouse_name,
                        transit_warehouse_id = EXCLUDED.transit_warehouse_id, transit_warehouse_name = EXCLUDED.transit_warehouse_name,
                        acceptance_cost = EXCLUDED.acceptance_cost, paid_acceptance_coefficient = EXCLUDED.paid_acceptance_coefficient,
                        reject_reason = EXCLUDED.reject_reason, supplier_assign_name = EXCLUDED.supplier_assign_name,
                        storage_coef = EXCLUDED.storage_coef, delivery_coef = EXCLUDED.delivery_coef,
                        quantity = EXCLUDED.quantity, ready_for_sale_quantity = EXCLUDED.ready_for_sale_quantity,
                        accepted_quantity = EXCLUDED.accepted_quantity, unloading_quantity = EXCLUDED.unloading_quantity,
                        depersonalized_quantity = EXCLUDED.depersonalized_quantity, last_synced_at = CURRENT_TIMESTAMP
                """
                executemany_sql(self.cursor, ins_preorder, with_preorder_only)
            logger.info(
                "В БД записано/обновлено поставок за срез %s: %s",
                snapshot_date,
                len(valid),
            )
            return len(valid)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке поставок: {e}")
            raise

    def upsert_supply(self, row: Dict[str, Any], snapshot_date: date, snapshot_hour: datetime) -> None:
        """Вставка/обновление одной поставки (детали из GET /supplies/{ID})."""
        r = self.normalize_supply_row(row)
        r["snapshot_date"] = snapshot_date
        if r.get("supply_id") is None and r.get("preorder_id") is None:
            return
        cols = "snapshot_date, supply_id, preorder_id, create_date, supply_date, fact_date, updated_date, status_id, phone, box_type_id, warehouse_id, warehouse_name, actual_warehouse_id, actual_warehouse_name, transit_warehouse_id, transit_warehouse_name, acceptance_cost, paid_acceptance_coefficient, reject_reason, supplier_assign_name, storage_coef, delivery_coef, quantity, ready_for_sale_quantity, accepted_quantity, unloading_quantity, depersonalized_quantity"
        vals = "%(snapshot_date)s, %(supply_id)s, %(preorder_id)s, %(create_date)s, %(supply_date)s, %(fact_date)s, %(updated_date)s, %(status_id)s, %(phone)s, %(box_type_id)s, %(warehouse_id)s, %(warehouse_name)s, %(actual_warehouse_id)s, %(actual_warehouse_name)s, %(transit_warehouse_id)s, %(transit_warehouse_name)s, %(acceptance_cost)s, %(paid_acceptance_coefficient)s, %(reject_reason)s, %(supplier_assign_name)s, %(storage_coef)s, %(delivery_coef)s, %(quantity)s, %(ready_for_sale_quantity)s, %(accepted_quantity)s, %(unloading_quantity)s, %(depersonalized_quantity)s"
        upd = "create_date=EXCLUDED.create_date, supply_date=EXCLUDED.supply_date, fact_date=EXCLUDED.fact_date, updated_date=EXCLUDED.updated_date, status_id=EXCLUDED.status_id, phone=EXCLUDED.phone, box_type_id=EXCLUDED.box_type_id, warehouse_id=EXCLUDED.warehouse_id, warehouse_name=EXCLUDED.warehouse_name, actual_warehouse_id=EXCLUDED.actual_warehouse_id, actual_warehouse_name=EXCLUDED.actual_warehouse_name, transit_warehouse_id=EXCLUDED.transit_warehouse_id, transit_warehouse_name=EXCLUDED.transit_warehouse_name, acceptance_cost=EXCLUDED.acceptance_cost, paid_acceptance_coefficient=EXCLUDED.paid_acceptance_coefficient, reject_reason=EXCLUDED.reject_reason, supplier_assign_name=EXCLUDED.supplier_assign_name, storage_coef=EXCLUDED.storage_coef, delivery_coef=EXCLUDED.delivery_coef, quantity=EXCLUDED.quantity, ready_for_sale_quantity=EXCLUDED.ready_for_sale_quantity, accepted_quantity=EXCLUDED.accepted_quantity, unloading_quantity=EXCLUDED.unloading_quantity, depersonalized_quantity=EXCLUDED.depersonalized_quantity, last_synced_at=CURRENT_TIMESTAMP"
        if r.get("supply_id") is not None:
            execute_sql(self.cursor, 
                f"INSERT INTO reports.wb_supplies ({cols}, last_synced_at) VALUES ({vals}, CURRENT_TIMESTAMP) ON CONFLICT (snapshot_date, supply_id) WHERE supply_id IS NOT NULL DO UPDATE SET {upd}",
                r,
            )
        else:
            execute_sql(self.cursor, 
                f"INSERT INTO reports.wb_supplies ({cols}, last_synced_at) VALUES ({vals}, CURRENT_TIMESTAMP) ON CONFLICT (snapshot_date, preorder_id) WHERE supply_id IS NULL DO UPDATE SET {upd}",
                r,
            )

    def upsert_goods(self, supply_id: int, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime) -> int:
        if not rows or supply_id is None:
            return 0
        normalized = [self.normalize_goods_row(supply_id, r) for r in rows]
        for r in normalized:
            r["snapshot_date"] = snapshot_date
        query = """
            INSERT INTO reports.wb_supplies_goods (
                snapshot_date, supply_id, barcode, vendor_code, nm_id, need_kiz, tnved, tech_size, color,
                supplier_box_amount, quantity, ready_for_sale_quantity, unloading_quantity, accepted_quantity, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(supply_id)s, %(barcode)s, %(vendor_code)s, %(nm_id)s, %(need_kiz)s, %(tnved)s, %(tech_size)s, %(color)s,
                %(supplier_box_amount)s, %(quantity)s, %(ready_for_sale_quantity)s, %(unloading_quantity)s, %(accepted_quantity)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (supply_id, barcode, snapshot_date) DO UPDATE SET
                vendor_code = EXCLUDED.vendor_code, nm_id = EXCLUDED.nm_id, need_kiz = EXCLUDED.need_kiz,
                tnved = EXCLUDED.tnved, tech_size = EXCLUDED.tech_size, color = EXCLUDED.color,
                supplier_box_amount = EXCLUDED.supplier_box_amount, quantity = EXCLUDED.quantity,
                ready_for_sale_quantity = EXCLUDED.ready_for_sale_quantity,
                unloading_quantity = EXCLUDED.unloading_quantity, accepted_quantity = EXCLUDED.accepted_quantity,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, normalized)
            logger.info(f"В БД записано товаров поставки {supply_id}: {len(normalized)}")
            return len(normalized)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке товаров поставки: {e}")
            raise
