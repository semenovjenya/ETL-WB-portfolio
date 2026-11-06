"""Database access for WB SKU AI analysis."""
import logging
import os
from typing import Any, Dict, List

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import Json

from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


class WBSkuAIAnalysisDatabase:
    """PostgreSQL helper for reports.wb_sku_ai_analysis."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (wb_sku_ai_analysis)")
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
            execute_ddl_bundle(self.cursor, "schema_wb_sku_ai_analysis.sql")
            logger.info("Таблица wb_sku_ai_analysis создана или уже существует")
        except FileNotFoundError:
            logger.warning("Файл schema_wb_sku_ai_analysis.sql не найден")
        except psycopg2.Error as exc:
            logger.error("Ошибка при создании таблицы: %s", exc)
            raise

    def create_competitor_tables(self) -> None:
        try:
            execute_ddl_bundle(self.cursor, "schema_wb_sku_competitors.sql")
            logger.info("Таблица wb_sku_competitors создана или уже существует")
        except FileNotFoundError:
            logger.warning("Файл schema_wb_sku_competitors.sql не найден")
        except psycopg2.Error as exc:
            logger.error("Ошибка при создании таблицы wb_sku_competitors: %s", exc)
            raise

    def sync_profit_calculator_from_sku_snapshot(self) -> Dict[str, int]:
        execute_sql(self.cursor, "SELECT reports.sync_wb_profit_calculator_scenarios_from_sku_ai_analysis()")
        synced_rows = int(self.cursor.fetchone()[0] or 0)

        execute_sql(self.cursor, "SELECT reports.refresh_wb_profit_calculator_results()")
        refreshed_rows = int(self.cursor.fetchone()[0] or 0)

        logger.info(
            "Калькулятор синхронизирован из wb_sku_ai_analysis: changed_scenarios=%s, refreshed_results=%s",
            synced_rows,
            refreshed_rows,
        )
        return {
            "changed_scenarios": synced_rows,
            "refreshed_results": refreshed_rows,
        }

    @staticmethod
    def _json(value: Any) -> Any:
        if value is None:
            return None
        return Json(value)

    def upsert_rows(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0

        prepared: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in (
                "warehouse_names",
                "warehouses_json",
                "photo_urls",
                "dimensions_json",
                "characteristics_json",
                "sizes_json",
                "tags_json",
                "price_sizes_json",
                "card_json",
                "price_json",
                "funnel_json",
                "stocks_report_json",
            ):
                item[key] = self._json(item.get(key))
            prepared.append(item)

        query = """
            INSERT INTO reports.wb_sku_ai_analysis (
                snapshot_date,
                nm_id,
                barcode,
                imt_id,
                chrt_id,
                tech_size,
                vendor_code,
                supplier_article,
                brand,
                subject_name,
                title,
                description,
                need_kiz,
                last_change_date,
                total_quantity,
                total_in_way_to_client,
                total_in_way_from_client,
                total_quantity_full,
                warehouse_count,
                warehouse_names,
                warehouses_json,
                product_url,
                main_photo_url,
                photo_urls,
                video_url,
                length_cm,
                width_cm,
                height_cm,
                weight_brutto_kg,
                dimensions_json,
                characteristics_json,
                sizes_json,
                tags_json,
                price,
                discounted_price,
                club_discounted_price,
                discount,
                club_discount,
                currency_code,
                price_sizes_json,
                analytics_main_photo_url,
                analytics_availability,
                analytics_stock_count,
                analytics_stock_sum,
                analytics_current_price_min,
                analytics_current_price_max,
                analytics_orders_count,
                analytics_orders_sum,
                analytics_buyout_count,
                analytics_buyout_sum,
                analytics_buyout_percent,
                analytics_open_count,
                analytics_cart_count,
                analytics_add_to_wishlist,
                analytics_avg_price,
                analytics_avg_orders_per_day,
                analytics_to_client_count,
                analytics_from_client_count,
                analytics_sale_rate_days,
                analytics_sale_rate_hours,
                product_rating,
                feedback_rating,
                card_json,
                price_json,
                funnel_json,
                stocks_report_json,
                last_synced_at
            ) VALUES (
                %(snapshot_date)s,
                %(nm_id)s,
                %(barcode)s,
                %(imt_id)s,
                %(chrt_id)s,
                %(tech_size)s,
                %(vendor_code)s,
                %(supplier_article)s,
                %(brand)s,
                %(subject_name)s,
                %(title)s,
                %(description)s,
                %(need_kiz)s,
                %(last_change_date)s,
                %(total_quantity)s,
                %(total_in_way_to_client)s,
                %(total_in_way_from_client)s,
                %(total_quantity_full)s,
                %(warehouse_count)s,
                %(warehouse_names)s,
                %(warehouses_json)s,
                %(product_url)s,
                %(main_photo_url)s,
                %(photo_urls)s,
                %(video_url)s,
                %(length_cm)s,
                %(width_cm)s,
                %(height_cm)s,
                %(weight_brutto_kg)s,
                %(dimensions_json)s,
                %(characteristics_json)s,
                %(sizes_json)s,
                %(tags_json)s,
                %(price)s,
                %(discounted_price)s,
                %(club_discounted_price)s,
                %(discount)s,
                %(club_discount)s,
                %(currency_code)s,
                %(price_sizes_json)s,
                %(analytics_main_photo_url)s,
                %(analytics_availability)s,
                %(analytics_stock_count)s,
                %(analytics_stock_sum)s,
                %(analytics_current_price_min)s,
                %(analytics_current_price_max)s,
                %(analytics_orders_count)s,
                %(analytics_orders_sum)s,
                %(analytics_buyout_count)s,
                %(analytics_buyout_sum)s,
                %(analytics_buyout_percent)s,
                %(analytics_open_count)s,
                %(analytics_cart_count)s,
                %(analytics_add_to_wishlist)s,
                %(analytics_avg_price)s,
                %(analytics_avg_orders_per_day)s,
                %(analytics_to_client_count)s,
                %(analytics_from_client_count)s,
                %(analytics_sale_rate_days)s,
                %(analytics_sale_rate_hours)s,
                %(product_rating)s,
                %(feedback_rating)s,
                %(card_json)s,
                %(price_json)s,
                %(funnel_json)s,
                %(stocks_report_json)s,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (snapshot_date, nm_id, barcode) DO UPDATE SET
                imt_id = EXCLUDED.imt_id,
                chrt_id = EXCLUDED.chrt_id,
                tech_size = EXCLUDED.tech_size,
                vendor_code = EXCLUDED.vendor_code,
                supplier_article = EXCLUDED.supplier_article,
                brand = EXCLUDED.brand,
                subject_name = EXCLUDED.subject_name,
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                need_kiz = EXCLUDED.need_kiz,
                last_change_date = EXCLUDED.last_change_date,
                total_quantity = EXCLUDED.total_quantity,
                total_in_way_to_client = EXCLUDED.total_in_way_to_client,
                total_in_way_from_client = EXCLUDED.total_in_way_from_client,
                total_quantity_full = EXCLUDED.total_quantity_full,
                warehouse_count = EXCLUDED.warehouse_count,
                warehouse_names = EXCLUDED.warehouse_names,
                warehouses_json = EXCLUDED.warehouses_json,
                product_url = EXCLUDED.product_url,
                main_photo_url = EXCLUDED.main_photo_url,
                photo_urls = EXCLUDED.photo_urls,
                video_url = EXCLUDED.video_url,
                length_cm = EXCLUDED.length_cm,
                width_cm = EXCLUDED.width_cm,
                height_cm = EXCLUDED.height_cm,
                weight_brutto_kg = EXCLUDED.weight_brutto_kg,
                dimensions_json = EXCLUDED.dimensions_json,
                characteristics_json = EXCLUDED.characteristics_json,
                sizes_json = EXCLUDED.sizes_json,
                tags_json = EXCLUDED.tags_json,
                price = EXCLUDED.price,
                discounted_price = EXCLUDED.discounted_price,
                club_discounted_price = EXCLUDED.club_discounted_price,
                discount = EXCLUDED.discount,
                club_discount = EXCLUDED.club_discount,
                currency_code = EXCLUDED.currency_code,
                price_sizes_json = EXCLUDED.price_sizes_json,
                analytics_main_photo_url = EXCLUDED.analytics_main_photo_url,
                analytics_availability = EXCLUDED.analytics_availability,
                analytics_stock_count = EXCLUDED.analytics_stock_count,
                analytics_stock_sum = EXCLUDED.analytics_stock_sum,
                analytics_current_price_min = EXCLUDED.analytics_current_price_min,
                analytics_current_price_max = EXCLUDED.analytics_current_price_max,
                analytics_orders_count = EXCLUDED.analytics_orders_count,
                analytics_orders_sum = EXCLUDED.analytics_orders_sum,
                analytics_buyout_count = EXCLUDED.analytics_buyout_count,
                analytics_buyout_sum = EXCLUDED.analytics_buyout_sum,
                analytics_buyout_percent = EXCLUDED.analytics_buyout_percent,
                analytics_open_count = EXCLUDED.analytics_open_count,
                analytics_cart_count = EXCLUDED.analytics_cart_count,
                analytics_add_to_wishlist = EXCLUDED.analytics_add_to_wishlist,
                analytics_avg_price = EXCLUDED.analytics_avg_price,
                analytics_avg_orders_per_day = EXCLUDED.analytics_avg_orders_per_day,
                analytics_to_client_count = EXCLUDED.analytics_to_client_count,
                analytics_from_client_count = EXCLUDED.analytics_from_client_count,
                analytics_sale_rate_days = EXCLUDED.analytics_sale_rate_days,
                analytics_sale_rate_hours = EXCLUDED.analytics_sale_rate_hours,
                product_rating = EXCLUDED.product_rating,
                feedback_rating = EXCLUDED.feedback_rating,
                card_json = EXCLUDED.card_json,
                price_json = EXCLUDED.price_json,
                funnel_json = EXCLUDED.funnel_json,
                stocks_report_json = EXCLUDED.stocks_report_json,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, prepared)
            logger.info("В БД записано/обновлено строк wb_sku_ai_analysis: %s", len(prepared))
            return len(prepared)
        except psycopg2.Error as exc:
            logger.error("Ошибка при вставке wb_sku_ai_analysis: %s", exc)
            raise

    def get_latest_snapshot_rows(self) -> List[Dict[str, Any]]:
        query = """
            SELECT
                snapshot_date,
                nm_id,
                barcode,
                tech_size,
                product_url,
                price,
                discounted_price,
                club_discounted_price,
                discount,
                club_discount,
                price_json
            FROM reports.wb_sku_ai_analysis
            WHERE snapshot_date = (
                SELECT MAX(snapshot_date) FROM reports.wb_sku_ai_analysis
            )
            ORDER BY nm_id, barcode
        """
        execute_sql(self.cursor, query)
        rows = self.cursor.fetchall()
        return [
            {
                "snapshot_date": row[0],
                "nm_id": row[1],
                "barcode": row[2],
                "tech_size": row[3],
                "product_url": row[4],
                "price": row[5],
                "discounted_price": row[6],
                "club_discounted_price": row[7],
                "discount": row[8],
                "club_discount": row[9],
                "price_json": row[10],
            }
            for row in rows
        ]

    def get_latest_source_skus(self) -> List[Dict[str, Any]]:
        query = """
            SELECT
                snapshot_date,
                nm_id,
                barcode,
                brand,
                subject_name,
                title,
                description,
                product_url,
                main_photo_url,
                price,
                discounted_price,
                club_discounted_price,
                wb_link_price_regular,
                wb_link_price_promo,
                characteristics_json,
                card_json
            FROM reports.wb_sku_ai_analysis
            WHERE snapshot_date = (
                SELECT MAX(snapshot_date) FROM reports.wb_sku_ai_analysis
            )
            ORDER BY nm_id, barcode
        """
        execute_sql(self.cursor, query)
        rows = self.cursor.fetchall()
        return [
            {
                "snapshot_date": row[0],
                "nm_id": row[1],
                "barcode": row[2],
                "brand": row[3],
                "subject_name": row[4],
                "title": row[5],
                "description": row[6],
                "product_url": row[7],
                "main_photo_url": row[8],
                "price": row[9],
                "discounted_price": row[10],
                "club_discounted_price": row[11],
                "wb_link_price_regular": row[12],
                "wb_link_price_promo": row[13],
                "characteristics_json": row[14],
                "card_json": row[15],
            }
            for row in rows
        ]

    def update_link_prices(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        prepared: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("wb_link_promotions_json", "wb_link_price_payload_json"):
                item[key] = self._json(item.get(key))
            prepared.append(item)

        query = """
            UPDATE reports.wb_sku_ai_analysis
            SET
                wb_link_price_regular = %(wb_link_price_regular)s,
                wb_link_price_promo = %(wb_link_price_promo)s,
                wb_link_discount_percent = %(wb_link_discount_percent)s,
                wb_link_is_promo = %(wb_link_is_promo)s,
                wb_link_panel_promo_id = %(wb_link_panel_promo_id)s,
                wb_link_promotions_json = %(wb_link_promotions_json)s,
                wb_link_sale_conditions = %(wb_link_sale_conditions)s,
                wb_link_price_payload_json = %(wb_link_price_payload_json)s,
                wb_link_price_checked_at = CURRENT_TIMESTAMP
            WHERE snapshot_date = %(snapshot_date)s
              AND nm_id = %(nm_id)s
              AND barcode = %(barcode)s
        """
        executemany_sql(self.cursor, query, prepared)
        logger.info("Обновлено строк цен по WB-ссылкам: %s", len(prepared))
        return len(prepared)

    def upsert_competitor_rows(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0

        prepared: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in (
                "source_colors_json",
                "competitor_colors_json",
                "search_payload_json",
                "detail_payload_json",
                "photo_ai_raw_json",
            ):
                item[key] = self._json(item.get(key))
            prepared.append(item)

        query = """
            INSERT INTO reports.wb_sku_competitors (
                run_date,
                source_snapshot_date,
                source_nm_id,
                source_barcode,
                source_brand,
                source_subject_name,
                source_title,
                source_product_url,
                source_price_regular,
                source_price_promo,
                source_price_segment_min,
                source_price_segment_max,
                source_colors_json,
                keyword,
                keyword_order,
                catalog_page,
                catalog_position_on_page,
                catalog_position_absolute,
                competitor_nm_id,
                competitor_brand,
                competitor_supplier_name,
                competitor_supplier_id,
                competitor_subject_name,
                competitor_title,
                competitor_description_short,
                competitor_colors_json,
                competitor_main_photo_url,
                competitor_product_url,
                competitor_price_regular,
                competitor_price_promo,
                competitor_discount_percent,
                competitor_rating,
                competitor_feedbacks,
                photo_ai_is_competitor,
                photo_ai_confidence,
                photo_ai_reason,
                photo_ai_model,
                photo_ai_raw_json,
                price_delta_abs,
                price_delta_percent,
                within_price_segment,
                same_subject,
                same_color,
                search_payload_json,
                detail_payload_json,
                parser_status,
                parser_error
            ) VALUES (
                %(run_date)s,
                %(source_snapshot_date)s,
                %(source_nm_id)s,
                %(source_barcode)s,
                %(source_brand)s,
                %(source_subject_name)s,
                %(source_title)s,
                %(source_product_url)s,
                %(source_price_regular)s,
                %(source_price_promo)s,
                %(source_price_segment_min)s,
                %(source_price_segment_max)s,
                %(source_colors_json)s,
                %(keyword)s,
                %(keyword_order)s,
                %(catalog_page)s,
                %(catalog_position_on_page)s,
                %(catalog_position_absolute)s,
                %(competitor_nm_id)s,
                %(competitor_brand)s,
                %(competitor_supplier_name)s,
                %(competitor_supplier_id)s,
                %(competitor_subject_name)s,
                %(competitor_title)s,
                %(competitor_description_short)s,
                %(competitor_colors_json)s,
                %(competitor_main_photo_url)s,
                %(competitor_product_url)s,
                %(competitor_price_regular)s,
                %(competitor_price_promo)s,
                %(competitor_discount_percent)s,
                %(competitor_rating)s,
                %(competitor_feedbacks)s,
                %(photo_ai_is_competitor)s,
                %(photo_ai_confidence)s,
                %(photo_ai_reason)s,
                %(photo_ai_model)s,
                %(photo_ai_raw_json)s,
                %(price_delta_abs)s,
                %(price_delta_percent)s,
                %(within_price_segment)s,
                %(same_subject)s,
                %(same_color)s,
                %(search_payload_json)s,
                %(detail_payload_json)s,
                %(parser_status)s,
                %(parser_error)s
            )
            ON CONFLICT (run_date, source_nm_id, keyword, competitor_nm_id) DO UPDATE SET
                searched_at = CURRENT_TIMESTAMP,
                source_snapshot_date = EXCLUDED.source_snapshot_date,
                source_barcode = EXCLUDED.source_barcode,
                source_brand = EXCLUDED.source_brand,
                source_subject_name = EXCLUDED.source_subject_name,
                source_title = EXCLUDED.source_title,
                source_product_url = EXCLUDED.source_product_url,
                source_price_regular = EXCLUDED.source_price_regular,
                source_price_promo = EXCLUDED.source_price_promo,
                source_price_segment_min = EXCLUDED.source_price_segment_min,
                source_price_segment_max = EXCLUDED.source_price_segment_max,
                source_colors_json = EXCLUDED.source_colors_json,
                keyword_order = EXCLUDED.keyword_order,
                catalog_page = EXCLUDED.catalog_page,
                catalog_position_on_page = EXCLUDED.catalog_position_on_page,
                catalog_position_absolute = EXCLUDED.catalog_position_absolute,
                competitor_brand = EXCLUDED.competitor_brand,
                competitor_supplier_name = EXCLUDED.competitor_supplier_name,
                competitor_supplier_id = EXCLUDED.competitor_supplier_id,
                competitor_subject_name = EXCLUDED.competitor_subject_name,
                competitor_title = EXCLUDED.competitor_title,
                competitor_description_short = EXCLUDED.competitor_description_short,
                competitor_colors_json = EXCLUDED.competitor_colors_json,
                competitor_main_photo_url = EXCLUDED.competitor_main_photo_url,
                competitor_product_url = EXCLUDED.competitor_product_url,
                competitor_price_regular = EXCLUDED.competitor_price_regular,
                competitor_price_promo = EXCLUDED.competitor_price_promo,
                competitor_discount_percent = EXCLUDED.competitor_discount_percent,
                competitor_rating = EXCLUDED.competitor_rating,
                competitor_feedbacks = EXCLUDED.competitor_feedbacks,
                photo_ai_is_competitor = EXCLUDED.photo_ai_is_competitor,
                photo_ai_confidence = EXCLUDED.photo_ai_confidence,
                photo_ai_reason = EXCLUDED.photo_ai_reason,
                photo_ai_model = EXCLUDED.photo_ai_model,
                photo_ai_raw_json = EXCLUDED.photo_ai_raw_json,
                price_delta_abs = EXCLUDED.price_delta_abs,
                price_delta_percent = EXCLUDED.price_delta_percent,
                within_price_segment = EXCLUDED.within_price_segment,
                same_subject = EXCLUDED.same_subject,
                same_color = EXCLUDED.same_color,
                search_payload_json = EXCLUDED.search_payload_json,
                detail_payload_json = EXCLUDED.detail_payload_json,
                parser_status = EXCLUDED.parser_status,
                parser_error = EXCLUDED.parser_error
        """
        executemany_sql(self.cursor, query, prepared)
        logger.info("В БД записано/обновлено строк wb_sku_competitors: %s", len(prepared))
        return len(prepared)
