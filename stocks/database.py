"""Модуль для работы с PostgreSQL для остатков supplier/stocks."""
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional, Any
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


class StocksDatabase:
    """Класс для работы с БД остатков на складах WB."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (остатки)")
        except psycopg2.Error as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            raise

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к БД закрыто")

    def create_tables(self) -> None:
        try:
            execute_ddl_bundle(self.cursor, "schema_supplier_stocks.sql")
            logger.info("Таблицы остатков созданы или уже существуют")
        except FileNotFoundError:
            logger.warning(
                "Файл schema_supplier_stocks.sql не найден, создание таблиц пропущено"
            )
        except psycopg2.Error as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise

    def get_last_change_date_from(self) -> Optional[datetime]:
        """Последнее значение dateFrom для пагинации (из прогресса)."""
        try:
            execute_sql(self.cursor, 
                """
                SELECT last_change_date_from
                FROM reports.wb_supplier_stocks_progress
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            row = self.cursor.fetchone()
            return row[0] if row else None
        except psycopg2.Error as e:
            logger.error(f"Ошибка при чтении прогресса остатков: {e}")
            return None

    def save_progress(self, last_change_date_from: datetime) -> None:
        try:
            execute_sql(self.cursor, 
                """
                INSERT INTO reports.wb_supplier_stocks_progress (last_change_date_from, updated_at)
                VALUES (%s, CURRENT_TIMESTAMP)
                """,
                (last_change_date_from,),
            )
            logger.info(f"Прогресс остатков сохранён: dateFrom={last_change_date_from}")
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
        logger.warning(f"Не удалось распарсить дату: {value}")
        return None

    def normalize_row(self, item: Dict[str, Any]) -> Dict[str, Any]:
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        last_change = self.parse_datetime(
            get_("lastChangeDate", "last_change_date", default=None)
        )
        return {
            "last_change_date": last_change,
            "warehouse_name": get_("warehouseName", "warehouse_name", default=""),
            "supplier_article": get_("supplierArticle", "supplier_article"),
            "nm_id": get_("nmId", "nm_id"),
            "barcode": str(get_("barcode", default="")),
            "quantity": get_("quantity", default=0),
            "in_way_to_client": get_("inWayToClient", "in_way_to_client", default=0),
            "in_way_from_client": get_("inWayFromClient", "in_way_from_client", default=0),
            "quantity_full": get_("quantityFull", "quantity_full", default=0),
            "category": get_("category"),
            "subject": get_("subject"),
            "brand": get_("brand"),
            "tech_size": get_("techSize", "tech_size"),
            "price": get_("Price", "price"),
            "discount": get_("Discount", "discount"),
            "is_supply": get_("isSupply", "is_supply"),
            "is_realization": get_("isRealization", "is_realization"),
            "sc_code": get_("SCCode", "sc_code"),
        }

    def upsert_stocks(self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime) -> int:
        """Вставка/обновление остатков на дневной срез."""
        if not rows:
            return 0
        normalized = [self.normalize_row(r) for r in rows]
        valid = [r for r in normalized if r.get("barcode") is not None and r.get("warehouse_name") is not None]
        if not valid:
            return 0
        for r in valid:
            r["snapshot_date"] = snapshot_date

        query = """
            INSERT INTO reports.wb_supplier_stocks (
                snapshot_date, last_change_date, warehouse_name, supplier_article, nm_id, barcode,
                quantity, in_way_to_client, in_way_from_client, quantity_full,
                category, subject, brand, tech_size, price, discount,
                is_supply, is_realization, sc_code, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(last_change_date)s, %(warehouse_name)s, %(supplier_article)s, %(nm_id)s, %(barcode)s,
                %(quantity)s, %(in_way_to_client)s, %(in_way_from_client)s, %(quantity_full)s,
                %(category)s, %(subject)s, %(brand)s, %(tech_size)s, %(price)s, %(discount)s,
                %(is_supply)s, %(is_realization)s, %(sc_code)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (barcode, warehouse_name, snapshot_date) DO UPDATE SET
                last_change_date = EXCLUDED.last_change_date,
                supplier_article = EXCLUDED.supplier_article,
                nm_id = EXCLUDED.nm_id,
                quantity = EXCLUDED.quantity,
                in_way_to_client = EXCLUDED.in_way_to_client,
                in_way_from_client = EXCLUDED.in_way_from_client,
                quantity_full = EXCLUDED.quantity_full,
                category = EXCLUDED.category,
                subject = EXCLUDED.subject,
                brand = EXCLUDED.brand,
                tech_size = EXCLUDED.tech_size,
                price = EXCLUDED.price,
                discount = EXCLUDED.discount,
                is_supply = EXCLUDED.is_supply,
                is_realization = EXCLUDED.is_realization,
                sc_code = EXCLUDED.sc_code,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, valid)
            logger.info(
                "В БД записано/обновлено строк остатков за дневной срез %s: %s",
                snapshot_date,
                len(valid),
            )
            return len(valid)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке остатков: {e}")
            raise
