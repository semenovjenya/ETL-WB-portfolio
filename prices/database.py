"""Модуль для работы с PostgreSQL для цен и скидок (list/goods/filter)."""
import json
import logging
import os
from datetime import date, datetime
from typing import Dict, List, Optional, Any
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


class PricesDatabase:
    """Класс для работы с БД цен и скидок WB."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (цены)")
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
            execute_ddl_bundle(self.cursor, "schema_supplier_prices.sql")
            logger.info("Таблицы цен созданы или уже существуют")
        except FileNotFoundError:
            logger.warning(
                "Файл schema_supplier_prices.sql не найден, создание таблиц пропущено"
            )
        except psycopg2.Error as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise

    @staticmethod
    def _get_any(item: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in item:
                return item[k]
        return default

    def normalize_row(self, item: Dict[str, Any], snapshot_date: date, snapshot_hour: datetime) -> Dict[str, Any]:
        """Преобразует элемент listGoods в строку для wb_supplier_prices."""
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        sizes = get_("sizes", default=[])
        price_val = None
        discounted_price_val = None
        club_discounted_price_val = None
        if sizes and isinstance(sizes, list) and len(sizes) > 0:
            first = sizes[0]
            if isinstance(first, dict):
                price_val = get_("price", default=None) or self._get_any(first, "price", default=None)
                discounted_price_val = self._get_any(first, "discountedPrice", "discounted_price", default=None)
                club_discounted_price_val = self._get_any(first, "clubDiscountedPrice", "club_discounted_price", default=None)
        if price_val is None:
            price_val = get_("price", default=None)
        if discounted_price_val is None:
            discounted_price_val = get_("discountedPrice", "discounted_price", default=None)
        if club_discounted_price_val is None:
            club_discounted_price_val = get_("clubDiscountedPrice", "club_discounted_price", default=None)

        return {
            "snapshot_date": snapshot_date,
            "nm_id": get_("nmID", "nm_id"),
            "vendor_code": get_("vendorCode", "vendor_code"),
            "currency_iso_code": get_("currencyIsoCode4217", "currency_iso_code"),
            "discount": get_("discount", default=None),
            "club_discount": get_("clubDiscount", "club_discount", default=None),
            "editable_size_price": get_("editableSizePrice", "editable_size_price", default=None),
            "is_bad_turnover": get_("isBadTurnover", "is_bad_turnover", default=None),
            "price": price_val,
            "discounted_price": discounted_price_val,
            "club_discounted_price": club_discounted_price_val,
            "sizes_json": json.dumps(sizes) if sizes else None,
        }

    def upsert_prices(self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime) -> int:
        """Вставка/обновление цен на дневную дату среза."""
        if not rows:
            return 0
        normalized = [self.normalize_row(r, snapshot_date, snapshot_hour) for r in rows]
        valid = [r for r in normalized if r.get("nm_id") is not None]
        if not valid:
            return 0

        query = """
            INSERT INTO reports.wb_supplier_prices (
                snapshot_date, nm_id, vendor_code, currency_iso_code,
                discount, club_discount, editable_size_price, is_bad_turnover,
                price, discounted_price, club_discounted_price, sizes_json, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(nm_id)s, %(vendor_code)s, %(currency_iso_code)s,
                %(discount)s, %(club_discount)s, %(editable_size_price)s, %(is_bad_turnover)s,
                %(price)s, %(discounted_price)s, %(club_discounted_price)s, %(sizes_json)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (nm_id, snapshot_date) DO UPDATE SET
                vendor_code = EXCLUDED.vendor_code,
                currency_iso_code = EXCLUDED.currency_iso_code,
                discount = EXCLUDED.discount,
                club_discount = EXCLUDED.club_discount,
                editable_size_price = EXCLUDED.editable_size_price,
                is_bad_turnover = EXCLUDED.is_bad_turnover,
                price = EXCLUDED.price,
                discounted_price = EXCLUDED.discounted_price,
                club_discounted_price = EXCLUDED.club_discounted_price,
                sizes_json = EXCLUDED.sizes_json,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, valid)
            logger.info(
                "В БД записано/обновлено строк цен за дневной срез %s: %s",
                snapshot_date,
                len(valid),
            )
            return len(valid)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке цен: {e}")
            raise
