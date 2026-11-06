"""Модуль для работы с PostgreSQL для тарифов WB (common-api wb-tariffs)."""
import json
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


class TariffsDatabase:
    """Класс для работы с БД тарифов WB."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (тарифы)")
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
            execute_ddl_bundle(self.cursor, "schema_wb_tariffs.sql")
            logger.info("Таблицы тарифов созданы или уже существуют")
        except FileNotFoundError:
            logger.warning(
                "Файл schema_wb_tariffs.sql не найден, создание таблиц пропущено"
            )
        except psycopg2.Error as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise

    def upsert_commission(self, report: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime) -> int:
        """Вставка/обновление комиссии на дату среза."""
        if not report:
            return 0
        query = """
            INSERT INTO reports.wb_tariffs_commission (snapshot_date, report_json, last_synced_at)
            VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_date) DO UPDATE SET
                report_json = EXCLUDED.report_json,
                last_synced_at = CURRENT_TIMESTAMP
        """
        execute_sql(self.cursor, query, (snapshot_date, json.dumps(report)))
        logger.info(f"Комиссия записана за {snapshot_date}")
        return 1

    def upsert_box(self, response_data: Dict[str, Any], snapshot_date: date, snapshot_hour: datetime) -> int:
        """Вставка/обновление тарифов box на дату среза."""
        query = """
            INSERT INTO reports.wb_tariffs_box (snapshot_date, response_json, last_synced_at)
            VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_date) DO UPDATE SET
                response_json = EXCLUDED.response_json,
                last_synced_at = CURRENT_TIMESTAMP
        """
        execute_sql(self.cursor, query, (snapshot_date, json.dumps(response_data)))
        logger.info(f"tariffs box записаны за {snapshot_date}")
        return 1

    def upsert_pallet(self, response_data: Dict[str, Any], snapshot_date: date, snapshot_hour: datetime) -> int:
        """Вставка/обновление тарифов pallet на дату среза."""
        query = """
            INSERT INTO reports.wb_tariffs_pallet (snapshot_date, response_json, last_synced_at)
            VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_date) DO UPDATE SET
                response_json = EXCLUDED.response_json,
                last_synced_at = CURRENT_TIMESTAMP
        """
        execute_sql(self.cursor, query, (snapshot_date, json.dumps(response_data)))
        logger.info(f"tariffs pallet записаны за {snapshot_date}")
        return 1

    def upsert_return(self, response_data: Dict[str, Any], snapshot_date: date, snapshot_hour: datetime) -> int:
        """Вставка/обновление тарифов return на дату среза."""
        query = """
            INSERT INTO reports.wb_tariffs_return (snapshot_date, response_json, last_synced_at)
            VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_date) DO UPDATE SET
                response_json = EXCLUDED.response_json,
                last_synced_at = CURRENT_TIMESTAMP
        """
        execute_sql(self.cursor, query, (snapshot_date, json.dumps(response_data)))
        logger.info(f"tariffs return записаны за {snapshot_date}")
        return 1

    def upsert_acceptance(self, data: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime) -> int:
        """Вставка/обновление коэффициентов приёмки на дату среза."""
        if not data:
            return 0
        query = """
            INSERT INTO reports.wb_tariffs_acceptance (snapshot_date, data_json, last_synced_at)
            VALUES (%s, %s::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_date) DO UPDATE SET
                data_json = EXCLUDED.data_json,
                last_synced_at = CURRENT_TIMESTAMP
        """
        execute_sql(self.cursor, query, (snapshot_date, json.dumps(data)))
        logger.info(f"Коэффициенты приёмки записаны за {snapshot_date}")
        return 1
