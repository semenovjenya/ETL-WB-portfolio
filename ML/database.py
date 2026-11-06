"""Database helpers for 1pager ML forecasting."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

import pandas as pd
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

try:
    from config import Config
except ImportError:  # pragma: no cover
    from .config import Config

from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)


class OnePagerMLDatabase:
    def __init__(self) -> None:
        self.conn: Optional[psycopg2.extensions.connection] = None
        self.cursor: Optional[psycopg2.extensions.cursor] = None

    def connect(self) -> None:
        Config.validate_db()
        self.conn = psycopg2.connect(Config.get_db_connection_string())
        self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        self.cursor = self.conn.cursor()
        logger.info("Connected to PostgreSQL for ML forecasting")

    def close(self) -> None:
        if self.cursor is not None:
            self.cursor.close()
        if self.conn is not None:
            self.conn.close()
        logger.info("Closed PostgreSQL connection for ML forecasting")

    def create_tables(self) -> None:
        assert self.cursor is not None
        execute_ddl_bundle(self.cursor, "schema_wb_ml_forecast.sql")
        execute_ddl_bundle(self.cursor, "1pager_ml_forecast.sql")

    def fetch_dataframe(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> pd.DataFrame:
        assert self.conn is not None
        return pd.read_sql_query(sql, self.conn, params=params)

    def fetch_training_frame(self, target_column: str) -> pd.DataFrame:
        sql = f"""
            SELECT *
            FROM {Config.TRAIN_VIEW}
            WHERE {target_column} IS NOT NULL
              AND report_date <= (
                  SELECT MAX(report_date) - INTERVAL '7 days'
                  FROM {Config.TRAIN_VIEW}
              )
            ORDER BY report_date, id
        """
        return self.fetch_dataframe(sql)

    def get_latest_complete_report_date(self) -> Optional[date]:
        assert self.cursor is not None
        execute_sql(self.cursor, f"SELECT MAX(report_date) FROM {Config.SERVING_VIEW}")
        return self.cursor.fetchone()[0]

    def fetch_scoring_frame(self, report_date: date) -> pd.DataFrame:
        sql = f"""
            SELECT *
            FROM {Config.SERVING_VIEW}
            WHERE report_date = %s
            ORDER BY id
        """
        return self.fetch_dataframe(sql, (report_date,))

    def upsert_forecast_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        assert self.cursor is not None
        query = f"""
            INSERT INTO {Config.FORECAST_TABLE} (
                report_date,
                nm_id,
                sku,
                pred_buyouts_7d,
                pred_orders_7d,
                pred_sales_baseline_7d,
                pred_trend_ratio,
                pred_trend_label,
                pred_delta_pct,
                pred_confidence_score,
                pred_confidence_label,
                sales_formula_v1_forecast_7d,
                sales_formula_v1_baseline_7d,
                sales_formula_v1_trend_ratio,
                sales_formula_v1_trend_label,
                sales_formula_v1_reason_summary,
                sales_formula_v1_reason_1,
                sales_formula_v1_reason_2,
                sales_formula_v2_forecast_7d,
                sales_formula_v2_baseline_7d,
                sales_formula_v2_trend_ratio,
                sales_formula_v2_trend_label,
                sales_formula_v2_reason_summary,
                sales_formula_v2_reason_1,
                sales_formula_v2_reason_2,
                model_version,
                trained_on_max_date,
                created_at,
                updated_at
            ) VALUES (
                %(report_date)s,
                %(nm_id)s,
                %(sku)s,
                %(pred_buyouts_7d)s,
                %(pred_orders_7d)s,
                %(pred_sales_baseline_7d)s,
                %(pred_trend_ratio)s,
                %(pred_trend_label)s,
                %(pred_delta_pct)s,
                %(pred_confidence_score)s,
                %(pred_confidence_label)s,
                %(sales_formula_v1_forecast_7d)s,
                %(sales_formula_v1_baseline_7d)s,
                %(sales_formula_v1_trend_ratio)s,
                %(sales_formula_v1_trend_label)s,
                %(sales_formula_v1_reason_summary)s,
                %(sales_formula_v1_reason_1)s,
                %(sales_formula_v1_reason_2)s,
                %(sales_formula_v2_forecast_7d)s,
                %(sales_formula_v2_baseline_7d)s,
                %(sales_formula_v2_trend_ratio)s,
                %(sales_formula_v2_trend_label)s,
                %(sales_formula_v2_reason_summary)s,
                %(sales_formula_v2_reason_1)s,
                %(sales_formula_v2_reason_2)s,
                %(model_version)s,
                %(trained_on_max_date)s,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (report_date, nm_id, model_version)
            DO UPDATE SET
                sku = EXCLUDED.sku,
                pred_buyouts_7d = EXCLUDED.pred_buyouts_7d,
                pred_orders_7d = EXCLUDED.pred_orders_7d,
                pred_sales_baseline_7d = EXCLUDED.pred_sales_baseline_7d,
                pred_trend_ratio = EXCLUDED.pred_trend_ratio,
                pred_trend_label = EXCLUDED.pred_trend_label,
                pred_delta_pct = EXCLUDED.pred_delta_pct,
                pred_confidence_score = EXCLUDED.pred_confidence_score,
                pred_confidence_label = EXCLUDED.pred_confidence_label,
                sales_formula_v1_forecast_7d = EXCLUDED.sales_formula_v1_forecast_7d,
                sales_formula_v1_baseline_7d = EXCLUDED.sales_formula_v1_baseline_7d,
                sales_formula_v1_trend_ratio = EXCLUDED.sales_formula_v1_trend_ratio,
                sales_formula_v1_trend_label = EXCLUDED.sales_formula_v1_trend_label,
                sales_formula_v1_reason_summary = EXCLUDED.sales_formula_v1_reason_summary,
                sales_formula_v1_reason_1 = EXCLUDED.sales_formula_v1_reason_1,
                sales_formula_v1_reason_2 = EXCLUDED.sales_formula_v1_reason_2,
                sales_formula_v2_forecast_7d = EXCLUDED.sales_formula_v2_forecast_7d,
                sales_formula_v2_baseline_7d = EXCLUDED.sales_formula_v2_baseline_7d,
                sales_formula_v2_trend_ratio = EXCLUDED.sales_formula_v2_trend_ratio,
                sales_formula_v2_trend_label = EXCLUDED.sales_formula_v2_trend_label,
                sales_formula_v2_reason_summary = EXCLUDED.sales_formula_v2_reason_summary,
                sales_formula_v2_reason_1 = EXCLUDED.sales_formula_v2_reason_1,
                sales_formula_v2_reason_2 = EXCLUDED.sales_formula_v2_reason_2,
                trained_on_max_date = EXCLUDED.trained_on_max_date,
                updated_at = CURRENT_TIMESTAMP
        """
        executemany_sql(self.cursor, query, rows)
        return len(rows)

    def upsert_explanation_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        assert self.cursor is not None
        query = f"""
            INSERT INTO {Config.EXPLANATION_TABLE} (
                report_date,
                nm_id,
                sku,
                model_version,
                reason_summary,
                reason_1,
                reason_2,
                reason_3,
                llm_model,
                prompt_version,
                source_features_hash,
                created_at
            ) VALUES (
                %(report_date)s,
                %(nm_id)s,
                %(sku)s,
                %(model_version)s,
                %(reason_summary)s,
                %(reason_1)s,
                %(reason_2)s,
                %(reason_3)s,
                %(llm_model)s,
                %(prompt_version)s,
                %(source_features_hash)s,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (report_date, nm_id, model_version)
            DO UPDATE SET
                sku = EXCLUDED.sku,
                reason_summary = EXCLUDED.reason_summary,
                reason_1 = EXCLUDED.reason_1,
                reason_2 = EXCLUDED.reason_2,
                reason_3 = EXCLUDED.reason_3,
                llm_model = EXCLUDED.llm_model,
                prompt_version = EXCLUDED.prompt_version,
                source_features_hash = EXCLUDED.source_features_hash,
                created_at = CURRENT_TIMESTAMP
        """
        executemany_sql(self.cursor, query, rows)
        return len(rows)

    def get_latest_model_version(self, report_date: date) -> Optional[str]:
        assert self.cursor is not None
        execute_sql(
            self.cursor,
            f"""
            SELECT model_version
            FROM {Config.FORECAST_TABLE}
            WHERE report_date = %s
            ORDER BY updated_at DESC, model_version DESC
            LIMIT 1
            """,
            (report_date,),
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def fetch_explanation_source_rows(self, report_date: date, model_version: str) -> list[dict[str, Any]]:
        sql = f"""
            SELECT
                f.report_date,
                f.nm_id,
                f.sku AS forecast_sku,
                f.pred_buyouts_7d,
                f.pred_orders_7d,
                f.pred_sales_baseline_7d,
                f.pred_trend_ratio,
                f.pred_trend_label,
                f.pred_delta_pct,
                f.pred_confidence_score,
                f.pred_confidence_label,
                f.model_version,
                f.trained_on_max_date,
                row_to_json(s) AS source_payload
            FROM {Config.FORECAST_TABLE} f
            JOIN {Config.SERVING_VIEW} s
              ON s.report_date = f.report_date
             AND s.id = f.nm_id
            WHERE f.report_date = %s
              AND f.model_version = %s
            ORDER BY f.nm_id
        """
        df = self.fetch_dataframe(sql, (report_date, model_version))
        rows: list[dict[str, Any]] = []
        for row in df.to_dict(orient="records"):
            source_payload = row.pop("source_payload", {}) or {}
            if isinstance(source_payload, str):
                try:
                    import json

                    source_payload = json.loads(source_payload)
                except Exception:
                    source_payload = {}
            merged = dict(source_payload)
            merged.update(row)
            rows.append(merged)
        return rows
