"""Модуль для работы с PostgreSQL для поисковых запросов WB."""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Iterable, Optional

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


def _to_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


class SearchQueriesDatabase:
    """БД для источника search-report."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (поисковые запросы)")
        except psycopg2.Error as exc:
            logger.error("Ошибка подключения к БД: %s", exc)
            raise

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к БД закрыто")

    def create_tables(self) -> None:
        try:
            execute_ddl_bundle(self.cursor, "schema_wb_search_queries.sql")
            logger.info("Таблицы поисковых запросов созданы или уже существуют")
        except FileNotFoundError:
            logger.warning("Файл schema_wb_search_queries.sql не найден")
        except psycopg2.Error as exc:
            logger.error("Ошибка при создании таблиц: %s", exc)
            raise

    def get_active_nm_ids(self, days: int = 90, limit: int = 0) -> list[int]:
        cutoff = date.today()
        if days > 0:
            from datetime import timedelta

            cutoff = date.today() - timedelta(days=days)
        result: set[int] = set()
        try:
            execute_sql(self.cursor, 
                """
                SELECT DISTINCT nm_id
                FROM reports.wb_supplier_stocks
                WHERE snapshot_date >= %s
                  AND nm_id IS NOT NULL
                """,
                (cutoff,),
            )
            result.update(int(row[0]) for row in self.cursor.fetchall())
        except psycopg2.Error as exc:
            logger.warning("Таблица остатков недоступна или пуста: %s", exc)
        try:
            execute_sql(self.cursor, 
                """
                SELECT DISTINCT nm_id
                FROM reports.wb_supplier_sales
                WHERE (
                    snapshot_date >= %s
                    OR (date_ord IS NOT NULL AND date_ord::date >= %s)
                )
                  AND nm_id IS NOT NULL
                """,
                (cutoff, cutoff),
            )
            result.update(int(row[0]) for row in self.cursor.fetchall())
        except psycopg2.Error as exc:
            logger.warning("Таблица продаж недоступна или пуста: %s", exc)
        nm_ids = sorted(result)
        if limit and limit > 0:
            nm_ids = nm_ids[:limit]
        logger.info("Активных nm_id найдено: %s", len(nm_ids))
        return nm_ids

    def upsert_api_requests(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_search_query_api_requests (
                request_key, snapshot_hour, method_name, endpoint, batch_index, offset_value,
                limit_value, current_period_start, current_period_end, past_period_start,
                past_period_end, nm_id, top_order_by, position_cluster,
                include_substituted_skus, include_search_texts,
                request_payload, response_payload, last_synced_at
            ) VALUES (
                %(request_key)s, %(snapshot_hour)s, %(method_name)s, %(endpoint)s, %(batch_index)s, %(offset_value)s,
                %(limit_value)s, %(current_period_start)s, %(current_period_end)s, %(past_period_start)s,
                %(past_period_end)s, %(nm_id)s, %(top_order_by)s, %(position_cluster)s,
                %(include_substituted_skus)s, %(include_search_texts)s,
                %(request_payload)s::jsonb, %(response_payload)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (request_key) DO UPDATE SET
                response_payload = EXCLUDED.response_payload,
                last_synced_at = CURRENT_TIMESTAMP
        """
        prepared = []
        for row in rows:
            item = dict(row)
            item["request_payload"] = _to_json(item.get("request_payload"))
            item["response_payload"] = _to_json(item.get("response_payload"))
            prepared.append(item)
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def upsert_report_overview(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_search_query_report_overview (
                request_key, snapshot_hour, current_period_start, current_period_end,
                past_period_start, past_period_end, batch_index, offset_value,
                total_products, supplier_rating_current, supplier_rating_dynamics,
                advertised_products_current, advertised_products_dynamics,
                position_average_current, position_average_dynamics,
                position_median_current, position_median_dynamics,
                cluster_first_hundred_current, cluster_first_hundred_dynamics,
                cluster_second_hundred_current, cluster_second_hundred_dynamics,
                cluster_below_current, cluster_below_dynamics,
                visibility_current, visibility_dynamics,
                open_card_current, open_card_dynamics,
                currency, api_response, last_synced_at
            ) VALUES (
                %(request_key)s, %(snapshot_hour)s, %(current_period_start)s, %(current_period_end)s,
                %(past_period_start)s, %(past_period_end)s, %(batch_index)s, %(offset_value)s,
                %(total_products)s, %(supplier_rating_current)s, %(supplier_rating_dynamics)s,
                %(advertised_products_current)s, %(advertised_products_dynamics)s,
                %(position_average_current)s, %(position_average_dynamics)s,
                %(position_median_current)s, %(position_median_dynamics)s,
                %(cluster_first_hundred_current)s, %(cluster_first_hundred_dynamics)s,
                %(cluster_second_hundred_current)s, %(cluster_second_hundred_dynamics)s,
                %(cluster_below_current)s, %(cluster_below_dynamics)s,
                %(visibility_current)s, %(visibility_dynamics)s,
                %(open_card_current)s, %(open_card_dynamics)s,
                %(currency)s, %(api_response)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (request_key) DO UPDATE SET
                total_products = EXCLUDED.total_products,
                supplier_rating_current = EXCLUDED.supplier_rating_current,
                supplier_rating_dynamics = EXCLUDED.supplier_rating_dynamics,
                advertised_products_current = EXCLUDED.advertised_products_current,
                advertised_products_dynamics = EXCLUDED.advertised_products_dynamics,
                position_average_current = EXCLUDED.position_average_current,
                position_average_dynamics = EXCLUDED.position_average_dynamics,
                position_median_current = EXCLUDED.position_median_current,
                position_median_dynamics = EXCLUDED.position_median_dynamics,
                cluster_first_hundred_current = EXCLUDED.cluster_first_hundred_current,
                cluster_first_hundred_dynamics = EXCLUDED.cluster_first_hundred_dynamics,
                cluster_second_hundred_current = EXCLUDED.cluster_second_hundred_current,
                cluster_second_hundred_dynamics = EXCLUDED.cluster_second_hundred_dynamics,
                cluster_below_current = EXCLUDED.cluster_below_current,
                cluster_below_dynamics = EXCLUDED.cluster_below_dynamics,
                visibility_current = EXCLUDED.visibility_current,
                visibility_dynamics = EXCLUDED.visibility_dynamics,
                open_card_current = EXCLUDED.open_card_current,
                open_card_dynamics = EXCLUDED.open_card_dynamics,
                currency = EXCLUDED.currency,
                api_response = EXCLUDED.api_response,
                last_synced_at = CURRENT_TIMESTAMP
        """
        prepared = []
        for row in rows:
            item = dict(row)
            item["api_response"] = _to_json(item.get("api_response"))
            prepared.append(item)
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def _upsert_group_rows(self, table_name: str, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        query = f"""
            INSERT INTO reports.{table_name} (
                request_key, snapshot_hour, current_period_start, current_period_end,
                past_period_start, past_period_end, batch_index, offset_value,
                row_index, subject_id, subject_name, brand_name, tag_id, tag_name,
                metric_avg_position_current, metric_avg_position_dynamics,
                metric_open_card_current, metric_open_card_dynamics,
                metric_add_to_cart_current, metric_add_to_cart_dynamics,
                metric_open_to_cart_current, metric_open_to_cart_dynamics,
                metric_orders_current, metric_orders_dynamics,
                metric_cart_to_order_current, metric_cart_to_order_dynamics,
                metric_visibility_current, metric_visibility_dynamics,
                currency, api_response, last_synced_at
            ) VALUES (
                %(request_key)s, %(snapshot_hour)s, %(current_period_start)s, %(current_period_end)s,
                %(past_period_start)s, %(past_period_end)s, %(batch_index)s, %(offset_value)s,
                %(row_index)s, %(subject_id)s, %(subject_name)s, %(brand_name)s, %(tag_id)s, %(tag_name)s,
                %(metric_avg_position_current)s, %(metric_avg_position_dynamics)s,
                %(metric_open_card_current)s, %(metric_open_card_dynamics)s,
                %(metric_add_to_cart_current)s, %(metric_add_to_cart_dynamics)s,
                %(metric_open_to_cart_current)s, %(metric_open_to_cart_dynamics)s,
                %(metric_orders_current)s, %(metric_orders_dynamics)s,
                %(metric_cart_to_order_current)s, %(metric_cart_to_order_dynamics)s,
                %(metric_visibility_current)s, %(metric_visibility_dynamics)s,
                %(currency)s, %(api_response)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (request_key, row_index) DO UPDATE SET
                subject_id = EXCLUDED.subject_id,
                subject_name = EXCLUDED.subject_name,
                brand_name = EXCLUDED.brand_name,
                tag_id = EXCLUDED.tag_id,
                tag_name = EXCLUDED.tag_name,
                metric_avg_position_current = EXCLUDED.metric_avg_position_current,
                metric_avg_position_dynamics = EXCLUDED.metric_avg_position_dynamics,
                metric_open_card_current = EXCLUDED.metric_open_card_current,
                metric_open_card_dynamics = EXCLUDED.metric_open_card_dynamics,
                metric_add_to_cart_current = EXCLUDED.metric_add_to_cart_current,
                metric_add_to_cart_dynamics = EXCLUDED.metric_add_to_cart_dynamics,
                metric_open_to_cart_current = EXCLUDED.metric_open_to_cart_current,
                metric_open_to_cart_dynamics = EXCLUDED.metric_open_to_cart_dynamics,
                metric_orders_current = EXCLUDED.metric_orders_current,
                metric_orders_dynamics = EXCLUDED.metric_orders_dynamics,
                metric_cart_to_order_current = EXCLUDED.metric_cart_to_order_current,
                metric_cart_to_order_dynamics = EXCLUDED.metric_cart_to_order_dynamics,
                metric_visibility_current = EXCLUDED.metric_visibility_current,
                metric_visibility_dynamics = EXCLUDED.metric_visibility_dynamics,
                currency = EXCLUDED.currency,
                api_response = EXCLUDED.api_response,
                last_synced_at = CURRENT_TIMESTAMP
        """
        prepared = []
        for row in rows:
            item = dict(row)
            item["api_response"] = _to_json(item.get("api_response"))
            prepared.append(item)
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def upsert_report_groups(self, rows: Iterable[dict[str, Any]]) -> int:
        return self._upsert_group_rows("wb_search_query_report_groups", rows)

    def upsert_groups(self, rows: Iterable[dict[str, Any]]) -> int:
        return self._upsert_group_rows("wb_search_query_groups", rows)

    def upsert_details(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_search_query_details (
                request_key, snapshot_hour, current_period_start, current_period_end,
                past_period_start, past_period_end, batch_index, offset_value,
                nm_id, name, vendor_code, subject_name, brand_name, main_photo,
                is_advertised, is_substituted_sku, is_card_rated, rating, feedback_rating,
                min_price, max_price,
                avg_position_current, avg_position_dynamics,
                open_card_current, open_card_dynamics,
                add_to_cart_current, add_to_cart_dynamics,
                open_to_cart_current, open_to_cart_dynamics,
                orders_current, orders_dynamics,
                cart_to_order_current, cart_to_order_dynamics,
                visibility_current, visibility_dynamics,
                currency, api_response, last_synced_at
            ) VALUES (
                %(request_key)s, %(snapshot_hour)s, %(current_period_start)s, %(current_period_end)s,
                %(past_period_start)s, %(past_period_end)s, %(batch_index)s, %(offset_value)s,
                %(nm_id)s, %(name)s, %(vendor_code)s, %(subject_name)s, %(brand_name)s, %(main_photo)s,
                %(is_advertised)s, %(is_substituted_sku)s, %(is_card_rated)s, %(rating)s, %(feedback_rating)s,
                %(min_price)s, %(max_price)s,
                %(avg_position_current)s, %(avg_position_dynamics)s,
                %(open_card_current)s, %(open_card_dynamics)s,
                %(add_to_cart_current)s, %(add_to_cart_dynamics)s,
                %(open_to_cart_current)s, %(open_to_cart_dynamics)s,
                %(orders_current)s, %(orders_dynamics)s,
                %(cart_to_order_current)s, %(cart_to_order_dynamics)s,
                %(visibility_current)s, %(visibility_dynamics)s,
                %(currency)s, %(api_response)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (request_key, nm_id) DO UPDATE SET
                name = EXCLUDED.name,
                vendor_code = EXCLUDED.vendor_code,
                subject_name = EXCLUDED.subject_name,
                brand_name = EXCLUDED.brand_name,
                main_photo = EXCLUDED.main_photo,
                is_advertised = EXCLUDED.is_advertised,
                is_substituted_sku = EXCLUDED.is_substituted_sku,
                is_card_rated = EXCLUDED.is_card_rated,
                rating = EXCLUDED.rating,
                feedback_rating = EXCLUDED.feedback_rating,
                min_price = EXCLUDED.min_price,
                max_price = EXCLUDED.max_price,
                avg_position_current = EXCLUDED.avg_position_current,
                avg_position_dynamics = EXCLUDED.avg_position_dynamics,
                open_card_current = EXCLUDED.open_card_current,
                open_card_dynamics = EXCLUDED.open_card_dynamics,
                add_to_cart_current = EXCLUDED.add_to_cart_current,
                add_to_cart_dynamics = EXCLUDED.add_to_cart_dynamics,
                open_to_cart_current = EXCLUDED.open_to_cart_current,
                open_to_cart_dynamics = EXCLUDED.open_to_cart_dynamics,
                orders_current = EXCLUDED.orders_current,
                orders_dynamics = EXCLUDED.orders_dynamics,
                cart_to_order_current = EXCLUDED.cart_to_order_current,
                cart_to_order_dynamics = EXCLUDED.cart_to_order_dynamics,
                visibility_current = EXCLUDED.visibility_current,
                visibility_dynamics = EXCLUDED.visibility_dynamics,
                currency = EXCLUDED.currency,
                api_response = EXCLUDED.api_response,
                last_synced_at = CURRENT_TIMESTAMP
        """
        prepared = []
        for row in rows:
            item = dict(row)
            item["api_response"] = _to_json(item.get("api_response"))
            prepared.append(item)
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def upsert_search_texts(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_search_query_texts (
                request_key, snapshot_hour, current_period_start, current_period_end,
                past_period_start, past_period_end, batch_index, top_order_by,
                nm_id, text, subject_name, brand_name, vendor_code, product_name,
                is_card_rated, rating, feedback_rating, min_price, max_price,
                frequency_current, frequency_dynamics, week_frequency,
                median_position_current, median_position_dynamics,
                avg_position_current, avg_position_dynamics,
                open_card_current, open_card_dynamics, open_card_percentile,
                add_to_cart_current, add_to_cart_dynamics, add_to_cart_percentile,
                open_to_cart_current, open_to_cart_dynamics, open_to_cart_percentile,
                orders_current, orders_dynamics, orders_percentile,
                cart_to_order_current, cart_to_order_dynamics, cart_to_order_percentile,
                visibility_current, visibility_dynamics,
                currency, api_response, last_synced_at
            ) VALUES (
                %(request_key)s, %(snapshot_hour)s, %(current_period_start)s, %(current_period_end)s,
                %(past_period_start)s, %(past_period_end)s, %(batch_index)s, %(top_order_by)s,
                %(nm_id)s, %(text)s, %(subject_name)s, %(brand_name)s, %(vendor_code)s, %(product_name)s,
                %(is_card_rated)s, %(rating)s, %(feedback_rating)s, %(min_price)s, %(max_price)s,
                %(frequency_current)s, %(frequency_dynamics)s, %(week_frequency)s,
                %(median_position_current)s, %(median_position_dynamics)s,
                %(avg_position_current)s, %(avg_position_dynamics)s,
                %(open_card_current)s, %(open_card_dynamics)s, %(open_card_percentile)s,
                %(add_to_cart_current)s, %(add_to_cart_dynamics)s, %(add_to_cart_percentile)s,
                %(open_to_cart_current)s, %(open_to_cart_dynamics)s, %(open_to_cart_percentile)s,
                %(orders_current)s, %(orders_dynamics)s, %(orders_percentile)s,
                %(cart_to_order_current)s, %(cart_to_order_dynamics)s, %(cart_to_order_percentile)s,
                %(visibility_current)s, %(visibility_dynamics)s,
                %(currency)s, %(api_response)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (
                snapshot_hour, current_period_start, current_period_end, nm_id, text, top_order_by
            ) DO UPDATE SET
                request_key = EXCLUDED.request_key,
                subject_name = EXCLUDED.subject_name,
                brand_name = EXCLUDED.brand_name,
                vendor_code = EXCLUDED.vendor_code,
                product_name = EXCLUDED.product_name,
                is_card_rated = EXCLUDED.is_card_rated,
                rating = EXCLUDED.rating,
                feedback_rating = EXCLUDED.feedback_rating,
                min_price = EXCLUDED.min_price,
                max_price = EXCLUDED.max_price,
                frequency_current = EXCLUDED.frequency_current,
                frequency_dynamics = EXCLUDED.frequency_dynamics,
                week_frequency = EXCLUDED.week_frequency,
                median_position_current = EXCLUDED.median_position_current,
                median_position_dynamics = EXCLUDED.median_position_dynamics,
                avg_position_current = EXCLUDED.avg_position_current,
                avg_position_dynamics = EXCLUDED.avg_position_dynamics,
                open_card_current = EXCLUDED.open_card_current,
                open_card_dynamics = EXCLUDED.open_card_dynamics,
                open_card_percentile = EXCLUDED.open_card_percentile,
                add_to_cart_current = EXCLUDED.add_to_cart_current,
                add_to_cart_dynamics = EXCLUDED.add_to_cart_dynamics,
                add_to_cart_percentile = EXCLUDED.add_to_cart_percentile,
                open_to_cart_current = EXCLUDED.open_to_cart_current,
                open_to_cart_dynamics = EXCLUDED.open_to_cart_dynamics,
                open_to_cart_percentile = EXCLUDED.open_to_cart_percentile,
                orders_current = EXCLUDED.orders_current,
                orders_dynamics = EXCLUDED.orders_dynamics,
                orders_percentile = EXCLUDED.orders_percentile,
                cart_to_order_current = EXCLUDED.cart_to_order_current,
                cart_to_order_dynamics = EXCLUDED.cart_to_order_dynamics,
                cart_to_order_percentile = EXCLUDED.cart_to_order_percentile,
                visibility_current = EXCLUDED.visibility_current,
                visibility_dynamics = EXCLUDED.visibility_dynamics,
                currency = EXCLUDED.currency,
                api_response = EXCLUDED.api_response,
                last_synced_at = CURRENT_TIMESTAMP
        """
        prepared = []
        for row in rows:
            item = dict(row)
            item["api_response"] = _to_json(item.get("api_response"))
            prepared.append(item)
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def upsert_orders_totals(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_search_query_orders_total_daily (
                snapshot_hour, current_period_start, current_period_end,
                nm_id, dt, avg_position, orders_count, api_response, last_synced_at
            ) VALUES (
                %(snapshot_hour)s, %(current_period_start)s, %(current_period_end)s,
                %(nm_id)s, %(dt)s, %(avg_position)s, %(orders_count)s, %(api_response)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (snapshot_hour, current_period_start, current_period_end, nm_id, dt) DO UPDATE SET
                avg_position = EXCLUDED.avg_position,
                orders_count = EXCLUDED.orders_count,
                api_response = EXCLUDED.api_response,
                last_synced_at = CURRENT_TIMESTAMP
        """
        prepared = []
        for row in rows:
            item = dict(row)
            item["api_response"] = _to_json(item.get("api_response"))
            prepared.append(item)
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def upsert_orders_text_daily(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_search_query_orders_text_daily (
                request_key, snapshot_hour, current_period_start, current_period_end,
                nm_id, text, frequency, dt, avg_position, orders_count,
                api_response, last_synced_at
            ) VALUES (
                %(request_key)s, %(snapshot_hour)s, %(current_period_start)s, %(current_period_end)s,
                %(nm_id)s, %(text)s, %(frequency)s, %(dt)s, %(avg_position)s, %(orders_count)s,
                %(api_response)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (snapshot_hour, current_period_start, current_period_end, nm_id, text, dt) DO UPDATE SET
                request_key = EXCLUDED.request_key,
                frequency = EXCLUDED.frequency,
                avg_position = EXCLUDED.avg_position,
                orders_count = EXCLUDED.orders_count,
                api_response = EXCLUDED.api_response,
                last_synced_at = CURRENT_TIMESTAMP
        """
        prepared = []
        for row in rows:
            item = dict(row)
            item["api_response"] = _to_json(item.get("api_response"))
            prepared.append(item)
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def get_report_subject_ids(
        self,
        *,
        snapshot_hour,
        current_period_start,
        current_period_end,
    ) -> list[int]:
        execute_sql(self.cursor, 
            """
            SELECT DISTINCT subject_id
            FROM reports.wb_search_query_report_groups
            WHERE snapshot_hour = %s
              AND current_period_start = %s
              AND current_period_end = %s
              AND subject_id IS NOT NULL
            ORDER BY subject_id
            """,
            (snapshot_hour, current_period_start, current_period_end),
        )
        return [int(row[0]) for row in self.cursor.fetchall()]

    def get_search_texts_for_orders(
        self,
        *,
        snapshot_hour,
        current_period_start,
        current_period_end,
    ) -> dict[int, list[str]]:
        execute_sql(self.cursor, 
            """
            SELECT nm_id, text
            FROM reports.wb_search_query_texts
            WHERE snapshot_hour = %s
              AND current_period_start = %s
              AND current_period_end = %s
              AND nm_id IS NOT NULL
              AND text IS NOT NULL
            GROUP BY nm_id, text
            ORDER BY nm_id, text
            """,
            (snapshot_hour, current_period_start, current_period_end),
        )
        result: dict[int, list[str]] = {}
        for nm_id, text in self.cursor.fetchall():
            result.setdefault(int(nm_id), []).append(str(text))
        return result

    def get_search_text_nm_ids_for_top_order_by(
        self,
        *,
        snapshot_hour,
        current_period_start,
        current_period_end,
        top_order_by_values: Iterable[str],
    ) -> set[int]:
        values = list(top_order_by_values)
        if not values:
            return set()
        execute_sql(self.cursor,
            """
            WITH requested AS (
                SELECT
                    (jsonb_array_elements_text(request_payload->'nmIds'))::BIGINT AS nm_id,
                    top_order_by
                FROM reports.wb_search_query_api_requests
                WHERE snapshot_hour = %s
                  AND current_period_start = %s
                  AND current_period_end = %s
                  AND method_name = 'search_texts'
                  AND top_order_by = ANY(%s)
                  AND request_payload ? 'nmIds'
                  AND jsonb_typeof(request_payload->'nmIds') = 'array'
            )
            SELECT nm_id
            FROM requested
            GROUP BY nm_id
            HAVING COUNT(DISTINCT top_order_by) = %s
            ORDER BY nm_id
            """,
            (snapshot_hour, current_period_start, current_period_end, values, len(values)),
        )
        return {int(row[0]) for row in self.cursor.fetchall()}

    def get_search_text_nm_ids_with_rows_for_top_order_by(
        self,
        *,
        snapshot_hour,
        current_period_start,
        current_period_end,
        top_order_by_values: Iterable[str],
    ) -> set[int]:
        values = list(top_order_by_values)
        if not values:
            return set()
        execute_sql(self.cursor,
            """
            SELECT nm_id
            FROM reports.wb_search_query_texts
            WHERE snapshot_hour = %s
              AND current_period_start = %s
              AND current_period_end = %s
              AND top_order_by = ANY(%s)
              AND nm_id IS NOT NULL
            GROUP BY nm_id
            HAVING COUNT(DISTINCT top_order_by) = %s
            ORDER BY nm_id
            """,
            (snapshot_hour, current_period_start, current_period_end, values, len(values)),
        )
        return {int(row[0]) for row in self.cursor.fetchall()}

    def get_completed_order_texts(
        self,
        *,
        snapshot_hour,
        current_period_start,
        current_period_end,
    ) -> dict[int, set[str]]:
        execute_sql(self.cursor,
            """
            WITH requested AS (
                SELECT
                    nm_id,
                    jsonb_array_elements_text(request_payload->'searchTexts') AS text
                FROM reports.wb_search_query_api_requests
                WHERE snapshot_hour = %s
                  AND current_period_start = %s
                  AND current_period_end = %s
                  AND method_name = 'orders'
                  AND nm_id IS NOT NULL
                  AND request_payload ? 'searchTexts'
                  AND jsonb_typeof(request_payload->'searchTexts') = 'array'
            ),
            materialized AS (
                SELECT nm_id, text
                FROM reports.wb_search_query_orders_text_daily
                WHERE snapshot_hour = %s
                  AND current_period_start = %s
                  AND current_period_end = %s
                  AND nm_id IS NOT NULL
                  AND text IS NOT NULL
                GROUP BY nm_id, text
            )
            SELECT nm_id, text FROM requested
            UNION
            SELECT nm_id, text FROM materialized
            ORDER BY nm_id, text
            """,
            (
                snapshot_hour,
                current_period_start,
                current_period_end,
                snapshot_hour,
                current_period_start,
                current_period_end,
            ),
        )
        result: dict[int, set[str]] = {}
        for nm_id, text in self.cursor.fetchall():
            result.setdefault(int(nm_id), set()).add(str(text))
        return result

    def get_snapshot_counts(self, *, snapshot_hour) -> dict[str, int]:
        tables = {
            "api_requests": "reports.wb_search_query_api_requests",
            "report_overview": "reports.wb_search_query_report_overview",
            "report_groups": "reports.wb_search_query_report_groups",
            "groups": "reports.wb_search_query_groups",
            "details": "reports.wb_search_query_details",
            "search_texts": "reports.wb_search_query_texts",
            "orders_total_daily": "reports.wb_search_query_orders_total_daily",
            "orders_text_daily": "reports.wb_search_query_orders_text_daily",
        }
        counts: dict[str, int] = {}
        for key, table_name in tables.items():
            execute_sql(self.cursor, 
                f"SELECT COUNT(*) FROM {table_name} WHERE snapshot_hour = %s",
                (snapshot_hour,),
            )
            counts[key] = int(self.cursor.fetchone()[0])
        return counts
