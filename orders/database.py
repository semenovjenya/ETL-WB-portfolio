"""Модуль для работы с PostgreSQL для заказов supplier/orders."""
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional, Any
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


class OrdersDatabase:
    """БД для заказов WB."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (заказы)")
        except psycopg2.Error as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            raise

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к БД закрыто")

    def truncate_orders_and_progress(self) -> None:
        """Очистить таблицы заказов и прогресса (для полной перезаливки)."""
        try:
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_supplier_orders RESTART IDENTITY CASCADE")
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_supplier_orders_progress RESTART IDENTITY CASCADE")
            logger.info("Таблицы reports.wb_supplier_orders и wb_supplier_orders_progress очищены")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при очистке таблиц заказов: {e}")
            raise

    def create_tables(self) -> None:
        try:
            execute_ddl_bundle(self.cursor, "schema_supplier_orders.sql")
            logger.info("Таблицы заказов созданы или уже существуют")
        except FileNotFoundError:
            logger.warning("Файл schema_supplier_orders.sql не найден")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise

    def get_last_change_date_from(self) -> Optional[datetime]:
        try:
            execute_sql(self.cursor, 
                """
                SELECT last_change_date_from
                FROM reports.wb_supplier_orders_progress
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            row = self.cursor.fetchone()
            return row[0] if row else None
        except psycopg2.Error as e:
            logger.error(f"Ошибка при чтении прогресса заказов: {e}")
            return None

    def save_progress(self, last_change_date_from: datetime) -> None:
        try:
            execute_sql(self.cursor, 
                """
                INSERT INTO reports.wb_supplier_orders_progress (last_change_date_from, updated_at)
                VALUES (%s, CURRENT_TIMESTAMP)
                """,
                (last_change_date_from,),
            )
            logger.info(f"Прогресс заказов сохранён: dateFrom={last_change_date_from}")
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
        s = str(value).strip().replace("Z", "")
        if "." in s:
            s = s.split(".")[0]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    def normalize_row(self, item: Dict[str, Any]) -> Dict[str, Any]:
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        return {
            "date_ord": self.parse_datetime(get_("date", "date_ord")),
            "last_change_date": self.parse_datetime(get_("lastChangeDate", "last_change_date")),
            "warehouse_name": get_("warehouseName", "warehouse_name"),
            "warehouse_type": get_("warehouseType", "warehouse_type"),
            "country_name": get_("countryName", "country_name"),
            "oblast_okrug_name": get_("oblastOkrugName", "oblast_okrug_name"),
            "region_name": get_("regionName", "region_name"),
            "supplier_article": get_("supplierArticle", "supplier_article"),
            "nm_id": get_("nmId", "nm_id"),
            "barcode": get_("barcode"),
            "category": get_("category"),
            "subject": get_("subject"),
            "brand": get_("brand"),
            "tech_size": get_("techSize", "tech_size"),
            "income_id": get_("incomeID", "income_id"),
            "is_supply": get_("isSupply", "is_supply"),
            "is_realization": get_("isRealization", "is_realization"),
            "total_price": get_("totalPrice", "total_price"),
            "discount_percent": get_("discountPercent", "discount_percent"),
            "spp": get_("spp"),
            "finished_price": get_("finishedPrice", "finished_price"),
            "price_with_disc": get_("priceWithDisc", "price_with_disc"),
            "is_cancel": get_("isCancel", "is_cancel"),
            "cancel_date": self.parse_datetime(get_("cancelDate", "cancel_date")),
            "sticker": get_("sticker"),
            "g_number": get_("gNumber", "g_number"),
            "srid": str(get_("srid", default="") or "").strip() or None,
        }

    def upsert_orders(self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime) -> int:
        if not rows:
            return 0
        normalized = [self.normalize_row(r) for r in rows]
        valid = [r for r in normalized if r.get("srid")]
        if not valid:
            return 0
        for r in valid:
            r["snapshot_date"] = snapshot_date

        query = """
            INSERT INTO reports.wb_supplier_orders (
                snapshot_date, date_ord, last_change_date, warehouse_name, warehouse_type,
                country_name, oblast_okrug_name, region_name, supplier_article, nm_id, barcode,
                category, subject, brand, tech_size, income_id, is_supply, is_realization,
                total_price, discount_percent, spp, finished_price, price_with_disc,
                is_cancel, cancel_date, sticker, g_number, srid, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(date_ord)s, %(last_change_date)s, %(warehouse_name)s, %(warehouse_type)s,
                %(country_name)s, %(oblast_okrug_name)s, %(region_name)s, %(supplier_article)s, %(nm_id)s, %(barcode)s,
                %(category)s, %(subject)s, %(brand)s, %(tech_size)s, %(income_id)s, %(is_supply)s, %(is_realization)s,
                %(total_price)s, %(discount_percent)s, %(spp)s, %(finished_price)s, %(price_with_disc)s,
                %(is_cancel)s, %(cancel_date)s, %(sticker)s, %(g_number)s, %(srid)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (srid, snapshot_date) DO UPDATE SET
                date_ord = EXCLUDED.date_ord,
                last_change_date = EXCLUDED.last_change_date,
                warehouse_name = EXCLUDED.warehouse_name,
                warehouse_type = EXCLUDED.warehouse_type,
                country_name = EXCLUDED.country_name,
                oblast_okrug_name = EXCLUDED.oblast_okrug_name,
                region_name = EXCLUDED.region_name,
                supplier_article = EXCLUDED.supplier_article,
                nm_id = EXCLUDED.nm_id,
                barcode = EXCLUDED.barcode,
                category = EXCLUDED.category,
                subject = EXCLUDED.subject,
                brand = EXCLUDED.brand,
                tech_size = EXCLUDED.tech_size,
                income_id = EXCLUDED.income_id,
                is_supply = EXCLUDED.is_supply,
                is_realization = EXCLUDED.is_realization,
                total_price = EXCLUDED.total_price,
                discount_percent = EXCLUDED.discount_percent,
                spp = EXCLUDED.spp,
                finished_price = EXCLUDED.finished_price,
                price_with_disc = EXCLUDED.price_with_disc,
                is_cancel = EXCLUDED.is_cancel,
                cancel_date = EXCLUDED.cancel_date,
                sticker = EXCLUDED.sticker,
                g_number = EXCLUDED.g_number,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, valid)
            logger.info(
                "В БД записано/обновлено строк заказов за дневной срез %s: %s",
                snapshot_date,
                len(valid),
            )
            return len(valid)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке заказов: {e}")
            raise
