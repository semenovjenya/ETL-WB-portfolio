"""Модуль для работы с PostgreSQL для воронки продаж (sales-funnel/products)."""
import json
import logging
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Set
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


def _get_any(obj: Dict, *keys: str, default: Any = None) -> Any:
    if obj is None:
        return default
    for k in keys:
        if k in obj:
            return obj[k]
    return default


def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


class SalesFunnelDatabase:
    """БД для воронки продаж WB (products)."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (воронка продаж)")
        except psycopg2.Error as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            raise

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к БД закрыто")

    def get_active_nm_ids(self, days: int = 90) -> List[int]:
        """
        Артикулы (nm_id), у которых есть остатки или продажи за последние days дней.
        Данные из reports.wb_supplier_stocks и reports.wb_supplier_sales.
        """
        cutoff = date.today() - timedelta(days=days)
        result = []
        try:
            # stocks: хотя бы один срез за период
            execute_sql(self.cursor, 
                """
                SELECT DISTINCT nm_id FROM reports.wb_supplier_stocks
                WHERE snapshot_date >= %s AND nm_id IS NOT NULL
                """,
                (cutoff,),
            )
            result.extend(row[0] for row in self.cursor.fetchall())
        except psycopg2.Error as e:
            logger.warning(f"Таблица остатков недоступна или пуста: {e}")
        try:
            # sales: заказ или срез за период
            execute_sql(self.cursor, 
                """
                SELECT DISTINCT nm_id FROM reports.wb_supplier_sales
                WHERE (snapshot_date >= %s OR (date_ord IS NOT NULL AND date_ord::date >= %s))
                  AND nm_id IS NOT NULL
                """,
                (cutoff, cutoff),
            )
            result.extend(row[0] for row in self.cursor.fetchall())
        except psycopg2.Error as e:
            logger.warning(f"Таблица продаж недоступна или пуста: {e}")
        result = sorted(set(result))
        logger.info(f"Активных nm_id (остатки или продажи за {days} дней): {len(result)}")
        return result

    def truncate_funnel_and_progress(self) -> None:
        """Очистить таблицы воронки и прогресса."""
        try:
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_sales_funnel_products RESTART IDENTITY CASCADE")
            execute_sql(self.cursor, "TRUNCATE TABLE reports.wb_sales_funnel_progress RESTART IDENTITY CASCADE")
            logger.info("Таблицы wb_sales_funnel_products и wb_sales_funnel_progress очищены")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при очистке таблиц воронки: {e}")
            raise

    def create_tables(self) -> None:
        try:
            execute_ddl_bundle(self.cursor, "schema_sales_funnel.sql")
            logger.info("Таблицы воронки продаж созданы или уже существуют")
            try:
                execute_sql(self.cursor, 
                    "ALTER TABLE reports.wb_sales_funnel_products ADD COLUMN IF NOT EXISTS api_response JSONB"
                )
            except psycopg2.Error:
                pass
            execute_ddl_bundle(self.cursor, "schema_sales_funnel_daily.sql")
            logger.info("Таблица воронки по дням создана или уже существует")
            execute_ddl_bundle(self.cursor, "schema_sales_funnel_weekly.sql")
            logger.info("Таблица воронки по неделям создана или уже существует")
        except FileNotFoundError:
            logger.warning("Файл schema_sales_funnel.sql не найден")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise

    def ensure_daily_table_only(self) -> None:
        """Создаёт только схему reports и таблицу wb_sales_funnel_products_daily (для скрипта 90d daily)."""
        try:
            execute_ddl_bundle(self.cursor, "schema_sales_funnel_daily.sql")
            logger.info("Таблица reports.wb_sales_funnel_products_daily создана или уже существует")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при создании таблицы воронки по дням: {e}")
            raise

    def get_last_daily_report_date(self) -> Optional[date]:
        """Вернуть последнюю дату, уже загруженную в reports.wb_sales_funnel_products_daily."""
        try:
            execute_sql(self.cursor, 
                "SELECT MAX(report_date) FROM reports.wb_sales_funnel_products_daily"
            )
            result = self.cursor.fetchone()
            last_date = result[0] if result else None
            logger.info("Последняя дата в wb_sales_funnel_products_daily: %s", last_date)
            return last_date
        except psycopg2.Error as e:
            logger.warning(
                "Не удалось получить последнюю дату из reports.wb_sales_funnel_products_daily: %s",
                e,
            )
            return None

    def get_loaded_daily_report_dates(self, start_date: date, end_date: date) -> Set[date]:
        """Вернуть множество уже загруженных report_date в указанном диапазоне."""
        try:
            execute_sql(
                self.cursor,
                """
                SELECT DISTINCT report_date
                FROM reports.wb_sales_funnel_products_daily
                WHERE report_date BETWEEN %s AND %s
                """,
                (start_date, end_date),
            )
            loaded_dates = {row[0] for row in self.cursor.fetchall() if row[0] is not None}
            logger.info(
                "Загруженных дат в wb_sales_funnel_products_daily за %s – %s: %s",
                start_date,
                end_date,
                len(loaded_dates),
            )
            return loaded_dates
        except psycopg2.Error as e:
            logger.warning(
                "Не удалось получить список report_date из reports.wb_sales_funnel_products_daily: %s",
                e,
            )
            return set()

    def save_progress(self, period_start: date, period_end: date, snapshot_date: date) -> None:
        try:
            execute_sql(self.cursor, 
                """
                INSERT INTO reports.wb_sales_funnel_progress (period_start, period_end, snapshot_date, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (period_start, period_end, snapshot_date),
            )
            logger.info(f"Прогресс воронки сохранён: period {period_start}–{period_end}, snapshot {snapshot_date}")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при сохранении прогресса: {e}")
            raise

    def normalize_product_row(self, item: Dict[str, Any], period_start: date, period_end: date) -> Dict[str, Any]:
        """Из элемента data.products[] сформировать строку для wb_sales_funnel_products."""
        product = _get_any(item, "product") or {}
        statistic = _get_any(item, "statistic") or {}
        selected = _get_any(statistic, "selected") or {}
        conversions = _get_any(selected, "conversions") or {}
        stocks = _get_any(product, "stocks") or {}

        nm_id = _get_any(product, "nmId", "nm_id")
        if nm_id is None:
            return {}

        # Полный ответ API по карточке (product + statistic с selected, past, comparison)
        api_response = json.dumps(item, ensure_ascii=False) if item else None

        return {
            "period_start": period_start,
            "period_end": period_end,
            "nm_id": nm_id,
            "api_response": api_response,
            "title": _get_any(product, "title"),
            "vendor_code": _get_any(product, "vendorCode", "vendor_code"),
            "brand_name": _get_any(product, "brandName", "brand_name"),
            "subject_id": _get_any(product, "subjectId", "subject_id"),
            "subject_name": _get_any(product, "subjectName", "subject_name"),
            "product_rating": _get_any(product, "productRating", "product_rating"),
            "feedback_rating": _get_any(product, "feedbackRating", "feedback_rating"),
            "stocks_wb": _get_any(stocks, "wb"),
            "stocks_mp": _get_any(stocks, "mp"),
            "balance_sum": _get_any(stocks, "balanceSum", "balance_sum"),
            "open_count": _get_any(selected, "openCount", "open_count"),
            "cart_count": _get_any(selected, "cartCount", "cart_count"),
            "order_count": _get_any(selected, "orderCount", "order_count"),
            "order_sum": _get_any(selected, "orderSum", "order_sum"),
            "buyout_count": _get_any(selected, "buyoutCount", "buyout_count"),
            "buyout_sum": _get_any(selected, "buyoutSum", "buyout_sum"),
            "cancel_count": _get_any(selected, "cancelCount", "cancel_count"),
            "cancel_sum": _get_any(selected, "cancelSum", "cancel_sum"),
            "avg_price": _get_any(selected, "avgPrice", "avg_price"),
            "avg_orders_count_per_day": _get_any(selected, "avgOrdersCountPerDay", "avg_orders_count_per_day"),
            "share_order_percent": _get_any(selected, "shareOrderPercent", "share_order_percent"),
            "add_to_wishlist": _get_any(selected, "addToWishlist", "add_to_wishlist"),
            "localization_percent": _get_any(selected, "localizationPercent", "localization_percent"),
            "add_to_cart_percent": _get_any(conversions, "addToCartPercent", "add_to_cart_percent"),
            "cart_to_order_percent": _get_any(conversions, "cartToOrderPercent", "cart_to_order_percent"),
            "buyout_percent": _get_any(conversions, "buyoutPercent", "buyout_percent"),
            "currency": _get_any(item, "currency"),
        }

    def upsert_funnel_products(
        self,
        rows: List[Dict[str, Any]],
        snapshot_date: date,
        period_start: date,
        period_end: date,
    ) -> int:
        if not rows:
            return 0
        for r in rows:
            r["snapshot_date"] = snapshot_date
            r["period_start"] = period_start
            r["period_end"] = period_end

        query = """
            INSERT INTO reports.wb_sales_funnel_products (
                snapshot_date, period_start, period_end, nm_id, title, vendor_code, brand_name,
                subject_id, subject_name, product_rating, feedback_rating, stocks_wb, stocks_mp, balance_sum,
                open_count, cart_count, order_count, order_sum, buyout_count, buyout_sum,
                cancel_count, cancel_sum, avg_price, avg_orders_count_per_day, share_order_percent,
                add_to_wishlist, localization_percent, add_to_cart_percent, cart_to_order_percent,
                buyout_percent, currency, api_response, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(period_start)s, %(period_end)s, %(nm_id)s, %(title)s, %(vendor_code)s, %(brand_name)s,
                %(subject_id)s, %(subject_name)s, %(product_rating)s, %(feedback_rating)s, %(stocks_wb)s, %(stocks_mp)s, %(balance_sum)s,
                %(open_count)s, %(cart_count)s, %(order_count)s, %(order_sum)s, %(buyout_count)s, %(buyout_sum)s,
                %(cancel_count)s, %(cancel_sum)s, %(avg_price)s, %(avg_orders_count_per_day)s, %(share_order_percent)s,
                %(add_to_wishlist)s, %(localization_percent)s, %(add_to_cart_percent)s, %(cart_to_order_percent)s,
                %(buyout_percent)s, %(currency)s, %(api_response)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (snapshot_date, nm_id) DO UPDATE SET
                period_start = EXCLUDED.period_start,
                period_end = EXCLUDED.period_end,
                title = EXCLUDED.title,
                vendor_code = EXCLUDED.vendor_code,
                brand_name = EXCLUDED.brand_name,
                subject_id = EXCLUDED.subject_id,
                subject_name = EXCLUDED.subject_name,
                product_rating = EXCLUDED.product_rating,
                feedback_rating = EXCLUDED.feedback_rating,
                stocks_wb = EXCLUDED.stocks_wb,
                stocks_mp = EXCLUDED.stocks_mp,
                balance_sum = EXCLUDED.balance_sum,
                open_count = EXCLUDED.open_count,
                cart_count = EXCLUDED.cart_count,
                order_count = EXCLUDED.order_count,
                order_sum = EXCLUDED.order_sum,
                buyout_count = EXCLUDED.buyout_count,
                buyout_sum = EXCLUDED.buyout_sum,
                cancel_count = EXCLUDED.cancel_count,
                cancel_sum = EXCLUDED.cancel_sum,
                avg_price = EXCLUDED.avg_price,
                avg_orders_count_per_day = EXCLUDED.avg_orders_count_per_day,
                share_order_percent = EXCLUDED.share_order_percent,
                add_to_wishlist = EXCLUDED.add_to_wishlist,
                localization_percent = EXCLUDED.localization_percent,
                add_to_cart_percent = EXCLUDED.add_to_cart_percent,
                cart_to_order_percent = EXCLUDED.cart_to_order_percent,
                buyout_percent = EXCLUDED.buyout_percent,
                currency = EXCLUDED.currency,
                api_response = EXCLUDED.api_response,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"В БД записано/обновлено строк воронки за срез {snapshot_date}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке воронки: {e}")
            raise

    def _parse_date(self, value: Any) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        s = str(value).strip()[:10]
        if len(s) == 10:
            try:
                return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
            except (ValueError, IndexError):
                pass
        return None

    def normalize_product_to_daily_row(
        self,
        item: Dict[str, Any],
        report_date: date,
        currency: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Строка для wb_sales_funnel_products_daily из ответа sales-funnel/products за один день (period start=end=report_date)."""
        product = _get_any(item, "product") or {}
        statistic = _get_any(item, "statistic") or {}
        selected = _get_any(statistic, "selected") or {}
        past = _get_any(statistic, "past") or {}
        comparison = _get_any(statistic, "comparison") or {}
        conversions = _get_any(selected, "conversions") or {}
        past_conversions = _get_any(past, "conversions") or {}
        comparison_conversions = _get_any(comparison, "conversions") or {}
        selected_period = _get_any(selected, "period") or {}
        past_period = _get_any(past, "period") or {}
        selected_time_to_ready = _get_any(selected, "timeToReady", "time_to_ready") or {}
        past_time_to_ready = _get_any(past, "timeToReady", "time_to_ready") or {}
        comparison_time_to_ready = _get_any(comparison, "timeToReadyDynamic", "time_to_ready_dynamic") or {}
        selected_wb_club = _get_any(selected, "wbClub", "wb_club") or {}
        past_wb_club = _get_any(past, "wbClub", "wb_club") or {}
        comparison_wb_club = _get_any(comparison, "wbClubDynamic", "wb_club_dynamic") or {}
        stocks = _get_any(product, "stocks") or {}
        nm_id = _get_any(product, "nmId", "nm_id")
        if nm_id is None:
            return None
        cur = currency or _get_any(item, "currency")
        return {
            "report_date": report_date,
            "nm_id": nm_id,
            "title": _get_any(product, "title"),
            "vendor_code": _get_any(product, "vendorCode", "vendor_code"),
            "brand_name": _get_any(product, "brandName", "brand_name"),
            "subject_id": _get_any(product, "subjectId", "subject_id"),
            "subject_name": _get_any(product, "subjectName", "subject_name"),
            "product_tags_json": _json_dumps(_get_any(product, "tags")),
            "product_rating": _get_any(product, "productRating", "product_rating"),
            "feedback_rating": _get_any(product, "feedbackRating", "feedback_rating"),
            "stocks_wb": _get_any(stocks, "wb"),
            "stocks_mp": _get_any(stocks, "mp"),
            "balance_sum": _get_any(stocks, "balanceSum", "balance_sum"),
            "selected_period_start": self._parse_date(_get_any(selected_period, "start")),
            "selected_period_end": self._parse_date(_get_any(selected_period, "end")),
            "open_count": _get_any(selected, "openCount", "open_count"),
            "cart_count": _get_any(selected, "cartCount", "cart_count"),
            "order_count": _get_any(selected, "orderCount", "order_count"),
            "order_sum": _get_any(selected, "orderSum", "order_sum"),
            "buyout_count": _get_any(selected, "buyoutCount", "buyout_count"),
            "buyout_sum": _get_any(selected, "buyoutSum", "buyout_sum"),
            "cancel_count": _get_any(selected, "cancelCount", "cancel_count"),
            "cancel_sum": _get_any(selected, "cancelSum", "cancel_sum"),
            "avg_price": _get_any(selected, "avgPrice", "avg_price"),
            "avg_orders_count_per_day": _get_any(selected, "avgOrdersCountPerDay", "avg_orders_count_per_day"),
            "share_order_percent": _get_any(selected, "shareOrderPercent", "share_order_percent"),
            "buyout_percent": _get_any(conversions, "buyoutPercent", "buyout_percent"),
            "add_to_cart_conversion": _get_any(conversions, "addToCartPercent", "add_to_cart_percent"),
            "cart_to_order_conversion": _get_any(conversions, "cartToOrderPercent", "cart_to_order_percent"),
            "add_to_wishlist_count": _get_any(selected, "addToWishlist", "add_to_wishlist"),
            "time_to_ready_days": _get_any(selected_time_to_ready, "days"),
            "time_to_ready_hours": _get_any(selected_time_to_ready, "hours"),
            "time_to_ready_mins": _get_any(selected_time_to_ready, "mins"),
            "localization_percent": _get_any(selected, "localizationPercent", "localization_percent"),
            "selected_wb_club_order_count": _get_any(selected_wb_club, "orderCount", "order_count"),
            "selected_wb_club_order_sum": _get_any(selected_wb_club, "orderSum", "order_sum"),
            "selected_wb_club_buyout_sum": _get_any(selected_wb_club, "buyoutSum", "buyout_sum"),
            "selected_wb_club_buyout_count": _get_any(selected_wb_club, "buyoutCount", "buyout_count"),
            "selected_wb_club_cancel_sum": _get_any(selected_wb_club, "cancelSum", "cancel_sum"),
            "selected_wb_club_cancel_count": _get_any(selected_wb_club, "cancelCount", "cancel_count"),
            "selected_wb_club_avg_price": _get_any(selected_wb_club, "avgPrice", "avg_price"),
            "selected_wb_club_buyout_percent": _get_any(selected_wb_club, "buyoutPercent", "buyout_percent"),
            "selected_wb_club_avg_order_count_per_day": _get_any(selected_wb_club, "avgOrderCountPerDay", "avg_order_count_per_day"),
            "past_period_start": self._parse_date(_get_any(past_period, "start")),
            "past_period_end": self._parse_date(_get_any(past_period, "end")),
            "past_open_count": _get_any(past, "openCount", "open_count"),
            "past_cart_count": _get_any(past, "cartCount", "cart_count"),
            "past_order_count": _get_any(past, "orderCount", "order_count"),
            "past_order_sum": _get_any(past, "orderSum", "order_sum"),
            "past_buyout_count": _get_any(past, "buyoutCount", "buyout_count"),
            "past_buyout_sum": _get_any(past, "buyoutSum", "buyout_sum"),
            "past_cancel_count": _get_any(past, "cancelCount", "cancel_count"),
            "past_cancel_sum": _get_any(past, "cancelSum", "cancel_sum"),
            "past_avg_price": _get_any(past, "avgPrice", "avg_price"),
            "past_avg_orders_count_per_day": _get_any(past, "avgOrdersCountPerDay", "avg_orders_count_per_day"),
            "past_share_order_percent": _get_any(past, "shareOrderPercent", "share_order_percent"),
            "past_add_to_wishlist_count": _get_any(past, "addToWishlist", "add_to_wishlist"),
            "past_time_to_ready_days": _get_any(past_time_to_ready, "days"),
            "past_time_to_ready_hours": _get_any(past_time_to_ready, "hours"),
            "past_time_to_ready_mins": _get_any(past_time_to_ready, "mins"),
            "past_localization_percent": _get_any(past, "localizationPercent", "localization_percent"),
            "past_wb_club_order_count": _get_any(past_wb_club, "orderCount", "order_count"),
            "past_wb_club_order_sum": _get_any(past_wb_club, "orderSum", "order_sum"),
            "past_wb_club_buyout_sum": _get_any(past_wb_club, "buyoutSum", "buyout_sum"),
            "past_wb_club_buyout_count": _get_any(past_wb_club, "buyoutCount", "buyout_count"),
            "past_wb_club_cancel_sum": _get_any(past_wb_club, "cancelSum", "cancel_sum"),
            "past_wb_club_cancel_count": _get_any(past_wb_club, "cancelCount", "cancel_count"),
            "past_wb_club_avg_price": _get_any(past_wb_club, "avgPrice", "avg_price"),
            "past_wb_club_buyout_percent": _get_any(past_wb_club, "buyoutPercent", "buyout_percent"),
            "past_wb_club_avg_order_count_per_day": _get_any(past_wb_club, "avgOrderCountPerDay", "avg_order_count_per_day"),
            "past_add_to_cart_percent": _get_any(past_conversions, "addToCartPercent", "add_to_cart_percent"),
            "past_cart_to_order_percent": _get_any(past_conversions, "cartToOrderPercent", "cart_to_order_percent"),
            "past_buyout_percent": _get_any(past_conversions, "buyoutPercent", "buyout_percent"),
            "comparison_open_count_dynamic": _get_any(comparison, "openCountDynamic", "open_count_dynamic"),
            "comparison_cart_count_dynamic": _get_any(comparison, "cartCountDynamic", "cart_count_dynamic"),
            "comparison_order_count_dynamic": _get_any(comparison, "orderCountDynamic", "order_count_dynamic"),
            "comparison_order_sum_dynamic": _get_any(comparison, "orderSumDynamic", "order_sum_dynamic"),
            "comparison_buyout_count_dynamic": _get_any(comparison, "buyoutCountDynamic", "buyout_count_dynamic"),
            "comparison_buyout_sum_dynamic": _get_any(comparison, "buyoutSumDynamic", "buyout_sum_dynamic"),
            "comparison_cancel_count_dynamic": _get_any(comparison, "cancelCountDynamic", "cancel_count_dynamic"),
            "comparison_cancel_sum_dynamic": _get_any(comparison, "cancelSumDynamic", "cancel_sum_dynamic"),
            "comparison_avg_orders_count_per_day_dynamic": _get_any(comparison, "avgOrdersCountPerDayDynamic", "avg_orders_count_per_day_dynamic"),
            "comparison_avg_price_dynamic": _get_any(comparison, "avgPriceDynamic", "avg_price_dynamic"),
            "comparison_share_order_percent_dynamic": _get_any(comparison, "shareOrderPercentDynamic", "share_order_percent_dynamic"),
            "comparison_add_to_wishlist_dynamic": _get_any(comparison, "addToWishlistDynamic", "add_to_wishlist_dynamic"),
            "comparison_time_to_ready_days": _get_any(comparison_time_to_ready, "days"),
            "comparison_time_to_ready_hours": _get_any(comparison_time_to_ready, "hours"),
            "comparison_time_to_ready_mins": _get_any(comparison_time_to_ready, "mins"),
            "comparison_localization_percent_dynamic": _get_any(comparison, "localizationPercentDynamic", "localization_percent_dynamic"),
            "comparison_wb_club_order_count_dynamic": _get_any(comparison_wb_club, "orderCount", "order_count"),
            "comparison_wb_club_order_sum_dynamic": _get_any(comparison_wb_club, "orderSum", "order_sum"),
            "comparison_wb_club_buyout_sum_dynamic": _get_any(comparison_wb_club, "buyoutSum", "buyout_sum"),
            "comparison_wb_club_buyout_count_dynamic": _get_any(comparison_wb_club, "buyoutCount", "buyout_count"),
            "comparison_wb_club_cancel_sum_dynamic": _get_any(comparison_wb_club, "cancelSum", "cancel_sum"),
            "comparison_wb_club_cancel_count_dynamic": _get_any(comparison_wb_club, "cancelCount", "cancel_count"),
            "comparison_wb_club_avg_price_dynamic": _get_any(comparison_wb_club, "avgPrice", "avg_price"),
            "comparison_wb_club_buyout_percent_dynamic": _get_any(comparison_wb_club, "buyoutPercent", "buyout_percent"),
            "comparison_wb_club_avg_order_count_per_day_dynamic": _get_any(comparison_wb_club, "avgOrderCountPerDay", "avg_order_count_per_day"),
            "comparison_add_to_cart_percent": _get_any(comparison_conversions, "addToCartPercent", "add_to_cart_percent"),
            "comparison_cart_to_order_percent": _get_any(comparison_conversions, "cartToOrderPercent", "cart_to_order_percent"),
            "comparison_buyout_percent": _get_any(comparison_conversions, "buyoutPercent", "buyout_percent"),
            "currency": cur,
            "api_response": _json_dumps(item),
        }

    def normalize_daily_row(
        self,
        product: Dict[str, Any],
        history_item: Dict[str, Any],
        currency: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Строка для wb_sales_funnel_products_daily из product + history[].element (API history)."""
        nm_id = _get_any(product, "nmId", "nm_id")
        report_date = self._parse_date(_get_any(history_item, "date"))
        if nm_id is None or report_date is None:
            return None
        return {
            "report_date": report_date,
            "nm_id": nm_id,
            "title": _get_any(product, "title"),
            "vendor_code": _get_any(product, "vendorCode", "vendor_code"),
            "brand_name": _get_any(product, "brandName", "brand_name"),
            "subject_id": _get_any(product, "subjectId", "subject_id"),
            "subject_name": _get_any(product, "subjectName", "subject_name"),
            "open_count": _get_any(history_item, "openCount", "open_count"),
            "cart_count": _get_any(history_item, "cartCount", "cart_count"),
            "order_count": _get_any(history_item, "orderCount", "order_count"),
            "order_sum": _get_any(history_item, "orderSum", "order_sum"),
            "buyout_count": _get_any(history_item, "buyoutCount", "buyout_count"),
            "buyout_sum": _get_any(history_item, "buyoutSum", "buyout_sum"),
            "buyout_percent": _get_any(history_item, "buyoutPercent", "buyout_percent"),
            "add_to_cart_conversion": _get_any(history_item, "addToCartConversion", "add_to_cart_conversion"),
            "cart_to_order_conversion": _get_any(history_item, "cartToOrderConversion", "cart_to_order_conversion"),
            "add_to_wishlist_count": _get_any(history_item, "addToWishlistCount", "add_to_wishlist_count"),
            "currency": currency,
        }

    def upsert_funnel_daily(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_sales_funnel_products_daily (
                report_date, nm_id, title, vendor_code, brand_name, subject_id, subject_name,
                product_tags_json, product_rating, feedback_rating, stocks_wb, stocks_mp, balance_sum,
                selected_period_start, selected_period_end,
                open_count, cart_count, order_count, order_sum, buyout_count, buyout_sum,
                cancel_count, cancel_sum, avg_price, avg_orders_count_per_day, share_order_percent,
                buyout_percent, add_to_cart_conversion, cart_to_order_conversion, add_to_wishlist_count,
                time_to_ready_days, time_to_ready_hours, time_to_ready_mins, localization_percent,
                selected_wb_club_order_count, selected_wb_club_order_sum, selected_wb_club_buyout_sum,
                selected_wb_club_buyout_count, selected_wb_club_cancel_sum, selected_wb_club_cancel_count,
                selected_wb_club_avg_price, selected_wb_club_buyout_percent, selected_wb_club_avg_order_count_per_day,
                past_period_start, past_period_end, past_open_count, past_cart_count, past_order_count, past_order_sum,
                past_buyout_count, past_buyout_sum, past_cancel_count, past_cancel_sum, past_avg_price,
                past_avg_orders_count_per_day, past_share_order_percent, past_add_to_wishlist_count,
                past_time_to_ready_days, past_time_to_ready_hours, past_time_to_ready_mins, past_localization_percent,
                past_wb_club_order_count, past_wb_club_order_sum, past_wb_club_buyout_sum, past_wb_club_buyout_count,
                past_wb_club_cancel_sum, past_wb_club_cancel_count, past_wb_club_avg_price,
                past_wb_club_buyout_percent, past_wb_club_avg_order_count_per_day,
                past_add_to_cart_percent, past_cart_to_order_percent, past_buyout_percent,
                comparison_open_count_dynamic, comparison_cart_count_dynamic, comparison_order_count_dynamic,
                comparison_order_sum_dynamic, comparison_buyout_count_dynamic, comparison_buyout_sum_dynamic,
                comparison_cancel_count_dynamic, comparison_cancel_sum_dynamic,
                comparison_avg_orders_count_per_day_dynamic, comparison_avg_price_dynamic,
                comparison_share_order_percent_dynamic, comparison_add_to_wishlist_dynamic,
                comparison_time_to_ready_days, comparison_time_to_ready_hours, comparison_time_to_ready_mins,
                comparison_localization_percent_dynamic,
                comparison_wb_club_order_count_dynamic, comparison_wb_club_order_sum_dynamic,
                comparison_wb_club_buyout_sum_dynamic, comparison_wb_club_buyout_count_dynamic,
                comparison_wb_club_cancel_sum_dynamic, comparison_wb_club_cancel_count_dynamic,
                comparison_wb_club_avg_price_dynamic, comparison_wb_club_buyout_percent_dynamic,
                comparison_wb_club_avg_order_count_per_day_dynamic,
                comparison_add_to_cart_percent, comparison_cart_to_order_percent, comparison_buyout_percent,
                currency, api_response, last_synced_at
            ) VALUES (
                %(report_date)s, %(nm_id)s, %(title)s, %(vendor_code)s, %(brand_name)s,
                %(subject_id)s, %(subject_name)s,
                %(product_tags_json)s::jsonb, %(product_rating)s, %(feedback_rating)s, %(stocks_wb)s, %(stocks_mp)s, %(balance_sum)s,
                %(selected_period_start)s, %(selected_period_end)s,
                %(open_count)s, %(cart_count)s, %(order_count)s, %(order_sum)s, %(buyout_count)s, %(buyout_sum)s,
                %(cancel_count)s, %(cancel_sum)s, %(avg_price)s, %(avg_orders_count_per_day)s, %(share_order_percent)s,
                %(buyout_percent)s, %(add_to_cart_conversion)s, %(cart_to_order_conversion)s, %(add_to_wishlist_count)s,
                %(time_to_ready_days)s, %(time_to_ready_hours)s, %(time_to_ready_mins)s, %(localization_percent)s,
                %(selected_wb_club_order_count)s, %(selected_wb_club_order_sum)s, %(selected_wb_club_buyout_sum)s,
                %(selected_wb_club_buyout_count)s, %(selected_wb_club_cancel_sum)s, %(selected_wb_club_cancel_count)s,
                %(selected_wb_club_avg_price)s, %(selected_wb_club_buyout_percent)s, %(selected_wb_club_avg_order_count_per_day)s,
                %(past_period_start)s, %(past_period_end)s, %(past_open_count)s, %(past_cart_count)s, %(past_order_count)s, %(past_order_sum)s,
                %(past_buyout_count)s, %(past_buyout_sum)s, %(past_cancel_count)s, %(past_cancel_sum)s, %(past_avg_price)s,
                %(past_avg_orders_count_per_day)s, %(past_share_order_percent)s, %(past_add_to_wishlist_count)s,
                %(past_time_to_ready_days)s, %(past_time_to_ready_hours)s, %(past_time_to_ready_mins)s, %(past_localization_percent)s,
                %(past_wb_club_order_count)s, %(past_wb_club_order_sum)s, %(past_wb_club_buyout_sum)s, %(past_wb_club_buyout_count)s,
                %(past_wb_club_cancel_sum)s, %(past_wb_club_cancel_count)s, %(past_wb_club_avg_price)s,
                %(past_wb_club_buyout_percent)s, %(past_wb_club_avg_order_count_per_day)s,
                %(past_add_to_cart_percent)s, %(past_cart_to_order_percent)s, %(past_buyout_percent)s,
                %(comparison_open_count_dynamic)s, %(comparison_cart_count_dynamic)s, %(comparison_order_count_dynamic)s,
                %(comparison_order_sum_dynamic)s, %(comparison_buyout_count_dynamic)s, %(comparison_buyout_sum_dynamic)s,
                %(comparison_cancel_count_dynamic)s, %(comparison_cancel_sum_dynamic)s,
                %(comparison_avg_orders_count_per_day_dynamic)s, %(comparison_avg_price_dynamic)s,
                %(comparison_share_order_percent_dynamic)s, %(comparison_add_to_wishlist_dynamic)s,
                %(comparison_time_to_ready_days)s, %(comparison_time_to_ready_hours)s, %(comparison_time_to_ready_mins)s,
                %(comparison_localization_percent_dynamic)s,
                %(comparison_wb_club_order_count_dynamic)s, %(comparison_wb_club_order_sum_dynamic)s,
                %(comparison_wb_club_buyout_sum_dynamic)s, %(comparison_wb_club_buyout_count_dynamic)s,
                %(comparison_wb_club_cancel_sum_dynamic)s, %(comparison_wb_club_cancel_count_dynamic)s,
                %(comparison_wb_club_avg_price_dynamic)s, %(comparison_wb_club_buyout_percent_dynamic)s,
                %(comparison_wb_club_avg_order_count_per_day_dynamic)s,
                %(comparison_add_to_cart_percent)s, %(comparison_cart_to_order_percent)s, %(comparison_buyout_percent)s,
                %(currency)s, %(api_response)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (nm_id, report_date) DO UPDATE SET
                title = EXCLUDED.title,
                vendor_code = EXCLUDED.vendor_code,
                brand_name = EXCLUDED.brand_name,
                subject_id = EXCLUDED.subject_id,
                subject_name = EXCLUDED.subject_name,
                product_tags_json = EXCLUDED.product_tags_json,
                product_rating = EXCLUDED.product_rating,
                feedback_rating = EXCLUDED.feedback_rating,
                stocks_wb = EXCLUDED.stocks_wb,
                stocks_mp = EXCLUDED.stocks_mp,
                balance_sum = EXCLUDED.balance_sum,
                selected_period_start = EXCLUDED.selected_period_start,
                selected_period_end = EXCLUDED.selected_period_end,
                open_count = EXCLUDED.open_count,
                cart_count = EXCLUDED.cart_count,
                order_count = EXCLUDED.order_count,
                order_sum = EXCLUDED.order_sum,
                buyout_count = EXCLUDED.buyout_count,
                buyout_sum = EXCLUDED.buyout_sum,
                cancel_count = EXCLUDED.cancel_count,
                cancel_sum = EXCLUDED.cancel_sum,
                avg_price = EXCLUDED.avg_price,
                avg_orders_count_per_day = EXCLUDED.avg_orders_count_per_day,
                share_order_percent = EXCLUDED.share_order_percent,
                buyout_percent = EXCLUDED.buyout_percent,
                add_to_cart_conversion = EXCLUDED.add_to_cart_conversion,
                cart_to_order_conversion = EXCLUDED.cart_to_order_conversion,
                add_to_wishlist_count = EXCLUDED.add_to_wishlist_count,
                time_to_ready_days = EXCLUDED.time_to_ready_days,
                time_to_ready_hours = EXCLUDED.time_to_ready_hours,
                time_to_ready_mins = EXCLUDED.time_to_ready_mins,
                localization_percent = EXCLUDED.localization_percent,
                selected_wb_club_order_count = EXCLUDED.selected_wb_club_order_count,
                selected_wb_club_order_sum = EXCLUDED.selected_wb_club_order_sum,
                selected_wb_club_buyout_sum = EXCLUDED.selected_wb_club_buyout_sum,
                selected_wb_club_buyout_count = EXCLUDED.selected_wb_club_buyout_count,
                selected_wb_club_cancel_sum = EXCLUDED.selected_wb_club_cancel_sum,
                selected_wb_club_cancel_count = EXCLUDED.selected_wb_club_cancel_count,
                selected_wb_club_avg_price = EXCLUDED.selected_wb_club_avg_price,
                selected_wb_club_buyout_percent = EXCLUDED.selected_wb_club_buyout_percent,
                selected_wb_club_avg_order_count_per_day = EXCLUDED.selected_wb_club_avg_order_count_per_day,
                past_period_start = EXCLUDED.past_period_start,
                past_period_end = EXCLUDED.past_period_end,
                past_open_count = EXCLUDED.past_open_count,
                past_cart_count = EXCLUDED.past_cart_count,
                past_order_count = EXCLUDED.past_order_count,
                past_order_sum = EXCLUDED.past_order_sum,
                past_buyout_count = EXCLUDED.past_buyout_count,
                past_buyout_sum = EXCLUDED.past_buyout_sum,
                past_cancel_count = EXCLUDED.past_cancel_count,
                past_cancel_sum = EXCLUDED.past_cancel_sum,
                past_avg_price = EXCLUDED.past_avg_price,
                past_avg_orders_count_per_day = EXCLUDED.past_avg_orders_count_per_day,
                past_share_order_percent = EXCLUDED.past_share_order_percent,
                past_add_to_wishlist_count = EXCLUDED.past_add_to_wishlist_count,
                past_time_to_ready_days = EXCLUDED.past_time_to_ready_days,
                past_time_to_ready_hours = EXCLUDED.past_time_to_ready_hours,
                past_time_to_ready_mins = EXCLUDED.past_time_to_ready_mins,
                past_localization_percent = EXCLUDED.past_localization_percent,
                past_wb_club_order_count = EXCLUDED.past_wb_club_order_count,
                past_wb_club_order_sum = EXCLUDED.past_wb_club_order_sum,
                past_wb_club_buyout_sum = EXCLUDED.past_wb_club_buyout_sum,
                past_wb_club_buyout_count = EXCLUDED.past_wb_club_buyout_count,
                past_wb_club_cancel_sum = EXCLUDED.past_wb_club_cancel_sum,
                past_wb_club_cancel_count = EXCLUDED.past_wb_club_cancel_count,
                past_wb_club_avg_price = EXCLUDED.past_wb_club_avg_price,
                past_wb_club_buyout_percent = EXCLUDED.past_wb_club_buyout_percent,
                past_wb_club_avg_order_count_per_day = EXCLUDED.past_wb_club_avg_order_count_per_day,
                past_add_to_cart_percent = EXCLUDED.past_add_to_cart_percent,
                past_cart_to_order_percent = EXCLUDED.past_cart_to_order_percent,
                past_buyout_percent = EXCLUDED.past_buyout_percent,
                comparison_open_count_dynamic = EXCLUDED.comparison_open_count_dynamic,
                comparison_cart_count_dynamic = EXCLUDED.comparison_cart_count_dynamic,
                comparison_order_count_dynamic = EXCLUDED.comparison_order_count_dynamic,
                comparison_order_sum_dynamic = EXCLUDED.comparison_order_sum_dynamic,
                comparison_buyout_count_dynamic = EXCLUDED.comparison_buyout_count_dynamic,
                comparison_buyout_sum_dynamic = EXCLUDED.comparison_buyout_sum_dynamic,
                comparison_cancel_count_dynamic = EXCLUDED.comparison_cancel_count_dynamic,
                comparison_cancel_sum_dynamic = EXCLUDED.comparison_cancel_sum_dynamic,
                comparison_avg_orders_count_per_day_dynamic = EXCLUDED.comparison_avg_orders_count_per_day_dynamic,
                comparison_avg_price_dynamic = EXCLUDED.comparison_avg_price_dynamic,
                comparison_share_order_percent_dynamic = EXCLUDED.comparison_share_order_percent_dynamic,
                comparison_add_to_wishlist_dynamic = EXCLUDED.comparison_add_to_wishlist_dynamic,
                comparison_time_to_ready_days = EXCLUDED.comparison_time_to_ready_days,
                comparison_time_to_ready_hours = EXCLUDED.comparison_time_to_ready_hours,
                comparison_time_to_ready_mins = EXCLUDED.comparison_time_to_ready_mins,
                comparison_localization_percent_dynamic = EXCLUDED.comparison_localization_percent_dynamic,
                comparison_wb_club_order_count_dynamic = EXCLUDED.comparison_wb_club_order_count_dynamic,
                comparison_wb_club_order_sum_dynamic = EXCLUDED.comparison_wb_club_order_sum_dynamic,
                comparison_wb_club_buyout_sum_dynamic = EXCLUDED.comparison_wb_club_buyout_sum_dynamic,
                comparison_wb_club_buyout_count_dynamic = EXCLUDED.comparison_wb_club_buyout_count_dynamic,
                comparison_wb_club_cancel_sum_dynamic = EXCLUDED.comparison_wb_club_cancel_sum_dynamic,
                comparison_wb_club_cancel_count_dynamic = EXCLUDED.comparison_wb_club_cancel_count_dynamic,
                comparison_wb_club_avg_price_dynamic = EXCLUDED.comparison_wb_club_avg_price_dynamic,
                comparison_wb_club_buyout_percent_dynamic = EXCLUDED.comparison_wb_club_buyout_percent_dynamic,
                comparison_wb_club_avg_order_count_per_day_dynamic = EXCLUDED.comparison_wb_club_avg_order_count_per_day_dynamic,
                comparison_add_to_cart_percent = EXCLUDED.comparison_add_to_cart_percent,
                comparison_cart_to_order_percent = EXCLUDED.comparison_cart_to_order_percent,
                comparison_buyout_percent = EXCLUDED.comparison_buyout_percent,
                currency = EXCLUDED.currency,
                api_response = EXCLUDED.api_response,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"В БД записано/обновлено строк воронки по дням: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке воронки по дням: {e}")
            raise

    def normalize_weekly_row(
        self,
        product: Dict[str, Any],
        history_item: Dict[str, Any],
        currency: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Строка для wb_sales_funnel_products_weekly из product + history[].element (aggregationLevel=week)."""
        nm_id = _get_any(product, "nmId", "nm_id")
        report_week_start = self._parse_date(_get_any(history_item, "date"))
        if nm_id is None or report_week_start is None:
            return None
        return {
            "report_week_start": report_week_start,
            "nm_id": nm_id,
            "title": _get_any(product, "title"),
            "vendor_code": _get_any(product, "vendorCode", "vendor_code"),
            "brand_name": _get_any(product, "brandName", "brand_name"),
            "subject_id": _get_any(product, "subjectId", "subject_id"),
            "subject_name": _get_any(product, "subjectName", "subject_name"),
            "open_count": _get_any(history_item, "openCount", "open_count"),
            "cart_count": _get_any(history_item, "cartCount", "cart_count"),
            "order_count": _get_any(history_item, "orderCount", "order_count"),
            "order_sum": _get_any(history_item, "orderSum", "order_sum"),
            "buyout_count": _get_any(history_item, "buyoutCount", "buyout_count"),
            "buyout_sum": _get_any(history_item, "buyoutSum", "buyout_sum"),
            "buyout_percent": _get_any(history_item, "buyoutPercent", "buyout_percent"),
            "add_to_cart_conversion": _get_any(history_item, "addToCartConversion", "add_to_cart_conversion"),
            "cart_to_order_conversion": _get_any(history_item, "cartToOrderConversion", "cart_to_order_conversion"),
            "add_to_wishlist_count": _get_any(history_item, "addToWishlistCount", "add_to_wishlist_count"),
            "currency": currency,
        }

    def upsert_funnel_weekly(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_sales_funnel_products_weekly (
                report_week_start, nm_id, title, vendor_code, brand_name, subject_id, subject_name,
                open_count, cart_count, order_count, order_sum, buyout_count, buyout_sum, buyout_percent,
                add_to_cart_conversion, cart_to_order_conversion, add_to_wishlist_count, currency, last_synced_at
            ) VALUES (
                %(report_week_start)s, %(nm_id)s, %(title)s, %(vendor_code)s, %(brand_name)s,
                %(subject_id)s, %(subject_name)s,
                %(open_count)s, %(cart_count)s, %(order_count)s, %(order_sum)s,
                %(buyout_count)s, %(buyout_sum)s, %(buyout_percent)s,
                %(add_to_cart_conversion)s, %(cart_to_order_conversion)s, %(add_to_wishlist_count)s,
                %(currency)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (nm_id, report_week_start) DO UPDATE SET
                title = EXCLUDED.title,
                vendor_code = EXCLUDED.vendor_code,
                brand_name = EXCLUDED.brand_name,
                subject_id = EXCLUDED.subject_id,
                subject_name = EXCLUDED.subject_name,
                open_count = EXCLUDED.open_count,
                cart_count = EXCLUDED.cart_count,
                order_count = EXCLUDED.order_count,
                order_sum = EXCLUDED.order_sum,
                buyout_count = EXCLUDED.buyout_count,
                buyout_sum = EXCLUDED.buyout_sum,
                buyout_percent = EXCLUDED.buyout_percent,
                add_to_cart_conversion = EXCLUDED.add_to_cart_conversion,
                cart_to_order_conversion = EXCLUDED.cart_to_order_conversion,
                add_to_wishlist_count = EXCLUDED.add_to_wishlist_count,
                currency = EXCLUDED.currency,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"В БД записано/обновлено строк воронки по неделям: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке воронки по неделям: {e}")
            raise
