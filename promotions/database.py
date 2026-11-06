"""Модуль для работы с PostgreSQL для календаря акций calendar/promotions."""
import json
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional, Any

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


class PromotionsDatabase:
    """БД для календаря акций WB."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (календарь акций)")
        except psycopg2.Error as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            raise

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к БД закрыто")

    def truncate_promotions_and_progress(self) -> None:
        """Очистить таблицы акций, details, номенклатур и прогресса (для полной перезаливки)."""
        try:
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_calendar_promotions_nomenclatures RESTART IDENTITY CASCADE")
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_calendar_promotions_details RESTART IDENTITY CASCADE")
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_calendar_promotions RESTART IDENTITY CASCADE")
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_calendar_promotions_progress RESTART IDENTITY CASCADE")
            logger.info("Таблицы wb_calendar_promotions, wb_calendar_promotions_details, wb_calendar_promotions_nomenclatures и progress очищены")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при очистке таблиц акций: {e}")
            raise

    def create_tables(self) -> None:
        try:
            execute_ddl_bundle(self.cursor, "schema_calendar_promotions.sql")
            logger.info("Таблицы календаря акций созданы или уже существуют")
        except FileNotFoundError:
            logger.warning("Файл schema_calendar_promotions.sql не найден")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise

    def get_last_end_date_time(self) -> Optional[datetime]:
        """Последняя сохранённая граница периода выгрузки."""
        try:
            execute_sql(self.cursor, 
                """
                SELECT end_date_time_to
                FROM reports.wb_calendar_promotions_progress
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            row = self.cursor.fetchone()
            return row[0] if row else None
        except psycopg2.Error as e:
            logger.error(f"Ошибка при чтении прогресса акций: {e}")
            return None

    def get_latest_snapshot_date(self) -> Optional[date]:
        """Последняя доступная snapshot_date по таблице акций."""
        try:
            execute_sql(self.cursor, "SELECT MAX(snapshot_date) FROM reports.wb_calendar_promotions")
            row = self.cursor.fetchone()
            return row[0] if row and row[0] else None
        except psycopg2.Error as e:
            logger.error(f"Ошибка при чтении snapshot_date акций: {e}")
            return None

    def get_promotion_ids(
        self,
        snapshot_date: Optional[date] = None,
    ) -> List[int]:
        """Список promotion_id за конкретную snapshot_date."""
        try:
            if snapshot_date is None:
                snapshot_date = self.get_latest_snapshot_date()
            if snapshot_date is None:
                return []
            execute_sql(self.cursor, 
                """
                SELECT DISTINCT promotion_id
                FROM reports.wb_calendar_promotions
                WHERE snapshot_date = %s
                ORDER BY promotion_id
                """,
                (snapshot_date,),
            )
            return [r[0] for r in self.cursor.fetchall()]
        except psycopg2.Error as e:
            logger.error(f"Ошибка при чтении promotion_id: {e}")
            return []

    def save_progress(self, end_date_time_to: datetime) -> None:
        try:
            execute_sql(self.cursor, 
                """
                INSERT INTO reports.wb_calendar_promotions_progress (end_date_time_to, updated_at)
                VALUES (%s, CURRENT_TIMESTAMP)
                """,
                (end_date_time_to,),
            )
            logger.info(f"Прогресс акций сохранён: endDateTime={end_date_time_to}")
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
        s = str(value).strip().replace("Z", "+00:00")
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                if "%z" in fmt and "+00:00" in s:
                    from datetime import timezone
                    dt = datetime.strptime(s.replace("+00:00", ""), "%Y-%m-%dT%H:%M:%S")
                    return dt.replace(tzinfo=timezone.utc)
                return datetime.strptime(s.split(".")[0], fmt)
            except ValueError:
                continue
        return None

    def normalize_row(self, item: Dict[str, Any]) -> Dict[str, Any]:
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        return {
            "promotion_id": get_("id"),
            "name": get_("name"),
            "start_date_time": self.parse_datetime(get_("startDateTime", "start_date_time")),
            "end_date_time": self.parse_datetime(get_("endDateTime", "end_date_time")),
            "type": get_("type"),
        }

    def upsert_promotions(self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime) -> int:
        if not rows:
            return 0
        normalized = [self.normalize_row(r) for r in rows]
        valid = [r for r in normalized if r.get("promotion_id") is not None]
        if not valid:
            return 0
        for r in valid:
            r["snapshot_date"] = snapshot_date

        query = """
            INSERT INTO reports.wb_calendar_promotions (
                snapshot_date, promotion_id, name, start_date_time, end_date_time, type, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(promotion_id)s, %(name)s, %(start_date_time)s, %(end_date_time)s, %(type)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (promotion_id, snapshot_date) DO UPDATE SET
                name = EXCLUDED.name,
                start_date_time = EXCLUDED.start_date_time,
                end_date_time = EXCLUDED.end_date_time,
                type = EXCLUDED.type,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, valid)
            logger.info(f"В БД записано/обновлено строк акций за срез {snapshot_date}: {len(valid)}")
            return len(valid)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке акций: {e}")
            raise

    def normalize_row_details(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Нормализация строки из GET /api/v1/calendar/promotions/details (все поля + полный JSON)."""
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        promotion_id = get_("id")
        if promotion_id is None:
            return {}
        advantages = get_("advantages")
        if isinstance(advantages, list):
            advantages = json.dumps(advantages, ensure_ascii=False)
        else:
            advantages = None
        ranging = get_("ranging")
        if isinstance(ranging, list):
            ranging = json.dumps(ranging, ensure_ascii=False)
        else:
            ranging = None
        try:
            details_json = json.dumps(item, ensure_ascii=False)
        except (TypeError, ValueError):
            details_json = None
        return {
            "promotion_id": promotion_id,
            "name": get_("name"),
            "description": get_("description"),
            "advantages": advantages,
            "start_date_time": self.parse_datetime(get_("startDateTime", "start_date_time")),
            "end_date_time": self.parse_datetime(get_("endDateTime", "end_date_time")),
            "in_promo_action_leftovers": get_("inPromoActionLeftovers", "in_promo_action_leftovers"),
            "in_promo_action_total": get_("inPromoActionTotal", "in_promo_action_total"),
            "not_in_promo_action_leftovers": get_("notInPromoActionLeftovers", "not_in_promo_action_leftovers"),
            "not_in_promo_action_total": get_("notInPromoActionTotal", "not_in_promo_action_total"),
            "participation_percentage": get_("participationPercentage", "participation_percentage"),
            "type": get_("type"),
            "exception_products_count": get_("exceptionProductsCount", "exception_products_count"),
            "ranging": ranging,
            "details_json": details_json,
        }

    def upsert_promotion_details(
        self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: Optional[datetime] = None
    ) -> int:
        """Вставка/обновление подробностей акций (details) за срез."""
        if not rows:
            return 0
        for r in rows:
            r["snapshot_date"] = snapshot_date
        query = """
            INSERT INTO reports.wb_calendar_promotions_details (
                snapshot_date, promotion_id, name, description, advantages,
                start_date_time, end_date_time, in_promo_action_leftovers, in_promo_action_total,
                not_in_promo_action_leftovers, not_in_promo_action_total, participation_percentage,
                type, exception_products_count, ranging, details_json, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(promotion_id)s, %(name)s, %(description)s, %(advantages)s::jsonb,
                %(start_date_time)s, %(end_date_time)s, %(in_promo_action_leftovers)s, %(in_promo_action_total)s,
                %(not_in_promo_action_leftovers)s, %(not_in_promo_action_total)s, %(participation_percentage)s,
                %(type)s, %(exception_products_count)s, %(ranging)s::jsonb, %(details_json)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (snapshot_date, promotion_id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                advantages = EXCLUDED.advantages,
                start_date_time = EXCLUDED.start_date_time,
                end_date_time = EXCLUDED.end_date_time,
                in_promo_action_leftovers = EXCLUDED.in_promo_action_leftovers,
                in_promo_action_total = EXCLUDED.in_promo_action_total,
                not_in_promo_action_leftovers = EXCLUDED.not_in_promo_action_leftovers,
                not_in_promo_action_total = EXCLUDED.not_in_promo_action_total,
                participation_percentage = EXCLUDED.participation_percentage,
                type = EXCLUDED.type,
                exception_products_count = EXCLUDED.exception_products_count,
                ranging = EXCLUDED.ranging,
                details_json = EXCLUDED.details_json,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"В БД записано/обновлено подробностей акций (details) за срез {snapshot_date}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке details акций: {e}")
            raise

    def normalize_row_nomenclature(self, item: Dict[str, Any], promotion_id: int, in_action: bool) -> Dict[str, Any]:
        """Нормализация строки из GET /api/v1/calendar/promotions/nomenclatures (id = nm_id)."""
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        nm_id = get_("id")
        if nm_id is None:
            return {}
        return {
            "promotion_id": promotion_id,
            "nm_id": nm_id,
            "in_action": in_action,
            "price": get_("price"),
            "currency_code": get_("currencyCode", "currency_code"),
            "plan_price": get_("planPrice", "plan_price"),
            "discount": get_("discount"),
            "plan_discount": get_("planDiscount", "plan_discount"),
        }

    def upsert_promotion_nomenclatures(
        self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: Optional[datetime] = None
    ) -> int:
        """Вставка/обновление номенклатур (SKU) по акциям за срез."""
        if not rows:
            return 0
        for r in rows:
            r["snapshot_date"] = snapshot_date
        query = """
            INSERT INTO reports.wb_calendar_promotions_nomenclatures (
                snapshot_date, promotion_id, nm_id, in_action, price, currency_code,
                plan_price, discount, plan_discount, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(promotion_id)s, %(nm_id)s, %(in_action)s, %(price)s, %(currency_code)s,
                %(plan_price)s, %(discount)s, %(plan_discount)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (snapshot_date, promotion_id, nm_id) DO UPDATE SET
                in_action = EXCLUDED.in_action,
                price = EXCLUDED.price,
                currency_code = EXCLUDED.currency_code,
                plan_price = EXCLUDED.plan_price,
                discount = EXCLUDED.discount,
                plan_discount = EXCLUDED.plan_discount,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"В БД записано/обновлено номенклатур (SKU) по акциям за срез {snapshot_date}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке номенклатур акций: {e}")
            raise
