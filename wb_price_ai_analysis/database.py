"""Database helpers for wb_price_ai_analysis."""
import json
import logging
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2.extras import Json

from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql

logger = logging.getLogger(__name__)

_SCHEMA_ADVISORY_LOCK = "wb_price_ai_analysis_schema"


class WBPriceAIAnalysisDatabase:
    """PostgreSQL helper for wb_price_ai_analysis."""

    def __init__(self) -> None:
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        self.conn = psycopg2.connect(Config.get_db_connection_string())
        self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        self.cursor = self.conn.cursor()
        logger.info("Подключение к PostgreSQL установлено (wb_price_ai_analysis)")

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к PostgreSQL закрыто (wb_price_ai_analysis)")

    @staticmethod
    def _json(value: Any) -> Any:
        if value is None:
            return None
        return Json(value)

    def create_tables(self) -> None:
        if not self.cursor:
            raise RuntimeError("PostgreSQL connection is not initialized")

        # Several host workers can start at the same time.  PostgreSQL DDL from
        # the shared schema bundle must run one worker at a time, otherwise two
        # CREATE OR REPLACE VIEW statements can deadlock during startup.
        self.cursor.execute(
            "SELECT pg_advisory_lock(hashtext(%s))",
            (_SCHEMA_ADVISORY_LOCK,),
        )
        try:
            execute_ddl_bundle(self.cursor, "schema_wb_price_ai_analysis.sql")
            logger.info("Таблицы wb_price_ai_analysis готовы")
        finally:
            self.cursor.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))",
                (_SCHEMA_ADVISORY_LOCK,),
            )

    @staticmethod
    def _decode_json(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def enqueue_competitor_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = """
            INSERT INTO reports.wb_price_ai_competitor_jobs (
                run_date,
                source_nm_id,
                status,
                payload_json,
                result_json,
                worker_id,
                worker_host,
                worker_pid,
                attempts,
                last_error,
                claimed_at,
                last_heartbeat_at,
                finished_at,
                updated_at
            ) VALUES (
                %(run_date)s,
                %(source_nm_id)s,
                'pending',
                %(payload_json)s,
                NULL,
                NULL,
                NULL,
                NULL,
                0,
                NULL,
                NULL,
                NULL,
                NULL,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (run_date, source_nm_id) DO UPDATE SET
                status = 'pending',
                payload_json = EXCLUDED.payload_json,
                result_json = NULL,
                worker_id = NULL,
                worker_host = NULL,
                worker_pid = NULL,
                attempts = 0,
                last_error = NULL,
                claimed_at = NULL,
                last_heartbeat_at = NULL,
                finished_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            RETURNING
                id,
                run_date,
                source_nm_id,
                status,
                payload_json,
                result_json,
                worker_id,
                worker_host,
                worker_pid,
                attempts,
                last_error,
                claimed_at,
                last_heartbeat_at,
                finished_at,
                created_at,
                updated_at
        """
        params = {
            "run_date": payload["run_date"],
            "source_nm_id": int(payload["source_nm_id"]),
            "payload_json": self._json(payload),
        }
        execute_sql(self.cursor, query, params)
        return self._map_competitor_job_row(self.cursor.fetchone())

    def claim_next_competitor_job(self, worker_id: str, stale_after_seconds: int) -> Optional[Dict[str, Any]]:
        query = """
            WITH candidate AS (
                SELECT id
                FROM reports.wb_price_ai_competitor_jobs
                WHERE status = 'pending'
                   OR (
                        status = 'processing'
                        AND COALESCE(last_heartbeat_at, claimed_at, updated_at) < CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
                   )
                ORDER BY created_at, id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE reports.wb_price_ai_competitor_jobs AS jobs
            SET
                status = 'processing',
                worker_id = %s,
                worker_host = %s,
                worker_pid = %s,
                attempts = jobs.attempts + 1,
                last_error = NULL,
                claimed_at = CURRENT_TIMESTAMP,
                last_heartbeat_at = CURRENT_TIMESTAMP,
                finished_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            FROM candidate
            WHERE jobs.id = candidate.id
            RETURNING
                jobs.id,
                jobs.run_date,
                jobs.source_nm_id,
                jobs.status,
                jobs.payload_json,
                jobs.result_json,
                jobs.worker_id,
                jobs.worker_host,
                jobs.worker_pid,
                jobs.attempts,
                jobs.last_error,
                jobs.claimed_at,
                jobs.last_heartbeat_at,
                jobs.finished_at,
                jobs.created_at,
                jobs.updated_at
        """
        execute_sql(self.cursor, 
            query,
            (stale_after_seconds, worker_id, os.uname().nodename, os.getpid()),
        )
        row = self.cursor.fetchone()
        return self._map_competitor_job_row(row) if row else None

    def touch_competitor_job(self, job_id: int) -> None:
        query = """
            UPDATE reports.wb_price_ai_competitor_jobs
            SET
                last_heartbeat_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """
        execute_sql(self.cursor, query, (job_id,))

    def complete_competitor_job(self, job_id: int, result: Dict[str, Any]) -> None:
        query = """
            UPDATE reports.wb_price_ai_competitor_jobs
            SET
                status = 'completed',
                result_json = %s,
                last_error = NULL,
                last_heartbeat_at = CURRENT_TIMESTAMP,
                finished_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """
        execute_sql(self.cursor, query, (self._json(result), job_id))

    def fail_competitor_job(self, job_id: int, error_text: str, result: Optional[Dict[str, Any]] = None) -> None:
        query = """
            UPDATE reports.wb_price_ai_competitor_jobs
            SET
                status = 'failed',
                result_json = %s,
                last_error = %s,
                last_heartbeat_at = CURRENT_TIMESTAMP,
                finished_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """
        execute_sql(self.cursor, query, (self._json(result), error_text, job_id))

    def get_competitor_job(self, run_date: Any, source_nm_id: int) -> Optional[Dict[str, Any]]:
        query = """
            SELECT
                id,
                run_date,
                source_nm_id,
                status,
                payload_json,
                result_json,
                worker_id,
                worker_host,
                worker_pid,
                attempts,
                last_error,
                claimed_at,
                last_heartbeat_at,
                finished_at,
                created_at,
                updated_at
            FROM reports.wb_price_ai_competitor_jobs
            WHERE run_date = %s
              AND source_nm_id = %s
        """
        execute_sql(self.cursor, query, (run_date, int(source_nm_id)))
        row = self.cursor.fetchone()
        return self._map_competitor_job_row(row) if row else None

    def _map_competitor_job_row(self, row: Any) -> Dict[str, Any]:
        return {
            "id": row[0],
            "run_date": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
            "source_nm_id": int(row[2]),
            "status": row[3],
            "payload_json": self._decode_json(row[4]) or {},
            "result_json": self._decode_json(row[5]),
            "worker_id": row[6],
            "worker_host": row[7],
            "worker_pid": row[8],
            "attempts": int(row[9] or 0),
            "last_error": row[10],
            "claimed_at": row[11].isoformat() if row[11] else None,
            "last_heartbeat_at": row[12].isoformat() if row[12] else None,
            "finished_at": row[13].isoformat() if row[13] else None,
            "created_at": row[14].isoformat() if row[14] else None,
            "updated_at": row[15].isoformat() if row[15] else None,
        }

    def enqueue_serp_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = """
            INSERT INTO analytics_ai.wb_serp_jobs (
                batch_id, batch_key, source_nm_id, status, payload_json
            ) VALUES (
                %(batch_id)s, %(batch_key)s, %(source_nm_id)s, 'pending', %(payload_json)s
            )
            ON CONFLICT (batch_id, source_nm_id) DO UPDATE SET
                status = CASE
                    WHEN analytics_ai.wb_serp_jobs.status = 'completed' THEN 'completed'
                    ELSE 'pending'
                END,
                payload_json = EXCLUDED.payload_json,
                result_json = CASE
                    WHEN analytics_ai.wb_serp_jobs.status = 'completed'
                    THEN analytics_ai.wb_serp_jobs.result_json
                    ELSE NULL
                END,
                worker_id = CASE WHEN analytics_ai.wb_serp_jobs.status = 'completed' THEN analytics_ai.wb_serp_jobs.worker_id ELSE NULL END,
                worker_host = CASE WHEN analytics_ai.wb_serp_jobs.status = 'completed' THEN analytics_ai.wb_serp_jobs.worker_host ELSE NULL END,
                worker_pid = CASE WHEN analytics_ai.wb_serp_jobs.status = 'completed' THEN analytics_ai.wb_serp_jobs.worker_pid ELSE NULL END,
                last_error = CASE WHEN analytics_ai.wb_serp_jobs.status = 'completed' THEN analytics_ai.wb_serp_jobs.last_error ELSE NULL END,
                claimed_at = CASE WHEN analytics_ai.wb_serp_jobs.status = 'completed' THEN analytics_ai.wb_serp_jobs.claimed_at ELSE NULL END,
                last_heartbeat_at = CASE WHEN analytics_ai.wb_serp_jobs.status = 'completed' THEN analytics_ai.wb_serp_jobs.last_heartbeat_at ELSE NULL END,
                finished_at = CASE WHEN analytics_ai.wb_serp_jobs.status = 'completed' THEN analytics_ai.wb_serp_jobs.finished_at ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, batch_id, batch_key, source_nm_id, status, payload_json, result_json,
                      worker_id, worker_host, worker_pid, attempts, last_error, claimed_at,
                      last_heartbeat_at, finished_at, created_at, updated_at
        """
        execute_sql(
            self.cursor,
            query,
            {
                "batch_id": payload["batch_id"],
                "batch_key": payload["batch_key"],
                "source_nm_id": int(payload["source_nm_id"]),
                "payload_json": self._json(payload),
            },
        )
        return self._map_serp_job_row(self.cursor.fetchone())

    def claim_next_serp_job(self, worker_id: str, stale_after_seconds: int) -> Optional[Dict[str, Any]]:
        query = """
            WITH candidate AS (
                SELECT id
                FROM analytics_ai.wb_serp_jobs
                WHERE status = 'pending'
                   OR (
                        status = 'processing'
                        AND COALESCE(last_heartbeat_at, claimed_at, updated_at)
                            < CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
                   )
                ORDER BY created_at, id
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE analytics_ai.wb_serp_jobs AS jobs
            SET status = 'processing', worker_id = %s, worker_host = %s, worker_pid = %s,
                attempts = jobs.attempts + 1, last_error = NULL,
                claimed_at = CURRENT_TIMESTAMP, last_heartbeat_at = CURRENT_TIMESTAMP,
                finished_at = NULL, updated_at = CURRENT_TIMESTAMP
            FROM candidate
            WHERE jobs.id = candidate.id
            RETURNING jobs.id, jobs.batch_id, jobs.batch_key, jobs.source_nm_id, jobs.status,
                      jobs.payload_json, jobs.result_json, jobs.worker_id, jobs.worker_host,
                      jobs.worker_pid, jobs.attempts, jobs.last_error, jobs.claimed_at,
                      jobs.last_heartbeat_at, jobs.finished_at, jobs.created_at, jobs.updated_at
        """
        execute_sql(
            self.cursor,
            query,
            (stale_after_seconds, worker_id, os.uname().nodename, os.getpid()),
        )
        row = self.cursor.fetchone()
        return self._map_serp_job_row(row) if row else None

    def touch_serp_job(self, job_id: int) -> None:
        execute_sql(
            self.cursor,
            """UPDATE analytics_ai.wb_serp_jobs
               SET last_heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (job_id,),
        )

    def complete_serp_job(self, job_id: int, result: Dict[str, Any]) -> None:
        execute_sql(
            self.cursor,
            """UPDATE analytics_ai.wb_serp_jobs
               SET status = 'completed', result_json = %s, last_error = NULL,
                   last_heartbeat_at = CURRENT_TIMESTAMP, finished_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (self._json(result), job_id),
        )

    def fail_serp_job(self, job_id: int, error_text: str, result: Optional[Dict[str, Any]] = None) -> None:
        execute_sql(
            self.cursor,
            """UPDATE analytics_ai.wb_serp_jobs
               SET status = 'failed', result_json = %s, last_error = %s,
                   last_heartbeat_at = CURRENT_TIMESTAMP, finished_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (self._json(result), error_text, job_id),
        )

    def get_serp_job(self, batch_id: Any, source_nm_id: int) -> Optional[Dict[str, Any]]:
        execute_sql(
            self.cursor,
            """SELECT id, batch_id, batch_key, source_nm_id, status, payload_json, result_json,
                      worker_id, worker_host, worker_pid, attempts, last_error, claimed_at,
                      last_heartbeat_at, finished_at, created_at, updated_at
               FROM analytics_ai.wb_serp_jobs
               WHERE batch_id = %s AND source_nm_id = %s""",
            (batch_id, int(source_nm_id)),
        )
        row = self.cursor.fetchone()
        return self._map_serp_job_row(row) if row else None

    def get_completed_serp_jobs(self, batch_id: Any) -> List[Dict[str, Any]]:
        """Return source jobs whose canonical browser snapshot is complete."""
        execute_sql(
            self.cursor,
            """SELECT id, batch_id, batch_key, source_nm_id, status, payload_json, result_json,
                      worker_id, worker_host, worker_pid, attempts, last_error, claimed_at,
                      last_heartbeat_at, finished_at, created_at, updated_at
               FROM analytics_ai.wb_serp_jobs
               WHERE batch_id = %s
                 AND status = 'completed'
               ORDER BY source_nm_id""",
            (batch_id,),
        )
        return [self._map_serp_job_row(row) for row in self.cursor.fetchall()]

    def get_serp_projection_runs(self, batch_id: Any, source_nm_id: int) -> List[Dict[str, Any]]:
        """Load canonical runs/items in the shape used by the legacy projection."""
        execute_sql(
            self.cursor,
            """SELECT
                   runs.run_id,
                   runs.query,
                   runs.query_normalized,
                   runs.query_source,
                   runs.query_rank,
                   runs.query_orders_7d,
                   runs.query_frequency,
                   runs.parser_status,
                   items.result_nm_id,
                   items.is_source,
                   items.catalog_page,
                   items.position_on_page,
                   items.position_absolute,
                   items.position_organic,
                   items.placement_type,
                   items.placement_detection,
                   items.brand,
                   items.subject_name,
                   items.title,
                   items.product_url,
                   items.image_url,
                   items.price_regular,
                   items.price_display,
                   items.price_wallet,
                   items.price_effective,
                   items.price_basis,
                   items.discount_percent,
                   items.promo_label,
                   items.rating,
                   items.feedbacks,
                   items.raw_payload
               FROM analytics_ai.wb_serp_runs AS runs
               LEFT JOIN analytics_ai.wb_serp_items AS items
                 ON items.run_id = runs.run_id
               WHERE runs.batch_id = %s
                 AND runs.source_nm_id = %s
               ORDER BY runs.query_rank, items.position_absolute""",
            (batch_id, int(source_nm_id)),
        )
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in self.cursor.fetchall():
            run_id = str(row[0])
            run = grouped.setdefault(
                run_id,
                {
                    "run_id": run_id,
                    "spec": {
                        "query": row[1],
                        "query_normalized": row[2],
                        "query_source": row[3],
                        "query_rank": int(row[4]),
                        "query_orders_7d": float(row[5] or 0),
                        "query_frequency": float(row[6] or 0),
                    },
                    "parser_status": row[7],
                    "items": [],
                },
            )
            if row[8] is None:
                continue
            run["items"].append(
                {
                    "run_id": run_id,
                    "result_nm_id": int(row[8]),
                    "is_source": bool(row[9]),
                    "catalog_page": int(row[10]),
                    "position_on_page": int(row[11]),
                    "position_absolute": int(row[12]),
                    "position_organic": int(row[13]) if row[13] is not None else None,
                    "placement_type": row[14],
                    "placement_detection": row[15],
                    "brand": row[16],
                    "subject_name": row[17],
                    "title": row[18],
                    "product_url": row[19],
                    "image_url": row[20],
                    "price_regular": float(row[21]) if row[21] is not None else None,
                    "price_display": float(row[22]) if row[22] is not None else None,
                    "price_wallet": float(row[23]) if row[23] is not None else None,
                    "price_effective": float(row[24]) if row[24] is not None else None,
                    "price_basis": row[25],
                    "discount_percent": float(row[26]) if row[26] is not None else None,
                    "promo_label": row[27],
                    "rating": float(row[28]) if row[28] is not None else None,
                    "feedbacks": int(row[29] or 0),
                    "raw_payload": self._decode_json(row[30]) or {},
                }
            )
        return list(grouped.values())

    def _map_serp_job_row(self, row: Any) -> Dict[str, Any]:
        return {
            "id": int(row[0]),
            "batch_id": str(row[1]),
            "batch_key": row[2],
            "source_nm_id": int(row[3]),
            "status": row[4],
            "payload_json": self._decode_json(row[5]) or {},
            "result_json": self._decode_json(row[6]),
            "worker_id": row[7],
            "worker_host": row[8],
            "worker_pid": row[9],
            "attempts": int(row[10] or 0),
            "last_error": row[11],
            "claimed_at": row[12].isoformat() if row[12] else None,
            "last_heartbeat_at": row[13].isoformat() if row[13] else None,
            "finished_at": row[14].isoformat() if row[14] else None,
            "created_at": row[15].isoformat() if row[15] else None,
            "updated_at": row[16].isoformat() if row[16] else None,
        }

    def touch_serp_worker(self, worker_id: str, *, status: str = "running") -> None:
        execute_sql(
            self.cursor,
            """INSERT INTO analytics_ai.wb_serp_worker_heartbeats (
                   worker_id, worker_host, worker_pid, status,
                   started_at, last_heartbeat_at, updated_at
               ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
               ON CONFLICT (worker_id) DO UPDATE SET
                   worker_host = EXCLUDED.worker_host,
                   worker_pid = EXCLUDED.worker_pid,
                   status = EXCLUDED.status,
                   last_heartbeat_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP""",
            (worker_id, os.uname().nodename, os.getpid(), status),
        )

    def get_recent_real_queries(self, source_nm_id: int, max_age_days: int) -> List[Dict[str, Any]]:
        query = """
            WITH latest AS (
                SELECT MAX(snapshot_hour) AS snapshot_hour
                FROM marketing.wb_search_query_texts
                WHERE nm_id = %s
            ),
            orders AS (
                SELECT LOWER(REGEXP_REPLACE(TRIM(text), '\\s+', ' ', 'g')) AS query_normalized,
                       MAX(text) AS query,
                       SUM(COALESCE(orders_count, 0)) AS orders_7d,
                       MAX(COALESCE(frequency, 0)) AS frequency
                FROM marketing.wb_search_query_orders_text_daily rows
                JOIN latest ON latest.snapshot_hour = rows.snapshot_hour
                WHERE rows.nm_id = %s
                GROUP BY LOWER(REGEXP_REPLACE(TRIM(text), '\\s+', ' ', 'g'))
            ),
            frequencies AS (
                SELECT LOWER(REGEXP_REPLACE(TRIM(text), '\\s+', ' ', 'g')) AS query_normalized,
                       MAX(text) AS query,
                       MAX(COALESCE(frequency_current, week_frequency, 0)) AS frequency
                FROM marketing.wb_search_query_texts rows
                JOIN latest ON latest.snapshot_hour = rows.snapshot_hour
                WHERE rows.nm_id = %s
                GROUP BY LOWER(REGEXP_REPLACE(TRIM(text), '\\s+', ' ', 'g'))
            )
            SELECT COALESCE(orders.query, frequencies.query) AS query,
                   COALESCE(orders.query_normalized, frequencies.query_normalized) AS query_normalized,
                   COALESCE(orders.orders_7d, 0) AS orders_7d,
                   GREATEST(COALESCE(orders.frequency, 0), COALESCE(frequencies.frequency, 0)) AS frequency,
                   latest.snapshot_hour
            FROM latest
            JOIN frequencies ON TRUE
            FULL JOIN orders ON orders.query_normalized = frequencies.query_normalized
            WHERE latest.snapshot_hour >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
            ORDER BY (COALESCE(orders.orders_7d, 0) > 0) DESC,
                     COALESCE(orders.orders_7d, 0) DESC,
                     GREATEST(COALESCE(orders.frequency, 0), COALESCE(frequencies.frequency, 0)) DESC,
                     COALESCE(orders.query_normalized, frequencies.query_normalized)
        """
        execute_sql(
            self.cursor,
            query,
            (int(source_nm_id), int(source_nm_id), int(source_nm_id), int(max_age_days)),
        )
        return [
            {
                "query": row[0],
                "query_normalized": row[1],
                "orders_7d": float(row[2] or 0),
                "frequency": float(row[3] or 0),
                "snapshot_hour": row[4].isoformat() if row[4] else None,
            }
            for row in self.cursor.fetchall()
            if row[0]
        ]

    def upsert_serp_run(self, run: Dict[str, Any]) -> None:
        query = """
            INSERT INTO analytics_ai.wb_serp_runs (
                run_id, batch_id, batch_key, observed_at, source_snapshot_date, source_nm_id,
                source_title, source_price_regular, source_price_display,
                query, query_normalized, query_source, query_rank, query_orders_7d, query_frequency,
                region_dest, currency, locale, device, browser_profile, requested_max_positions,
                pages_scanned, max_position_scanned, organic_positions_scanned,
                source_found_any, source_found_organic, source_found_sponsored,
                source_position_absolute, source_position_organic, source_position_organic_absolute,
                source_position_sponsored, complete_until_source, hit_position_limit,
                result_count, sponsored_count, organic_count, unknown_placement_count,
                parser_status, parser_error, completed_at
            ) VALUES (
                %(run_id)s, %(batch_id)s, %(batch_key)s, %(observed_at)s, %(source_snapshot_date)s,
                %(source_nm_id)s, %(source_title)s, %(source_price_regular)s, %(source_price_display)s,
                %(query)s, %(query_normalized)s, %(query_source)s, %(query_rank)s,
                %(query_orders_7d)s, %(query_frequency)s, %(region_dest)s, %(currency)s,
                %(locale)s, %(device)s, %(browser_profile)s, %(requested_max_positions)s,
                %(pages_scanned)s, %(max_position_scanned)s, %(organic_positions_scanned)s,
                %(source_found_any)s, %(source_found_organic)s, %(source_found_sponsored)s,
                %(source_position_absolute)s, %(source_position_organic)s,
                %(source_position_organic_absolute)s, %(source_position_sponsored)s,
                %(complete_until_source)s, %(hit_position_limit)s, %(result_count)s,
                %(sponsored_count)s, %(organic_count)s, %(unknown_placement_count)s,
                %(parser_status)s, %(parser_error)s, %(completed_at)s
            )
            ON CONFLICT (run_id) DO UPDATE SET
                pages_scanned = EXCLUDED.pages_scanned,
                max_position_scanned = EXCLUDED.max_position_scanned,
                organic_positions_scanned = EXCLUDED.organic_positions_scanned,
                source_found_any = EXCLUDED.source_found_any,
                source_found_organic = EXCLUDED.source_found_organic,
                source_found_sponsored = EXCLUDED.source_found_sponsored,
                source_position_absolute = EXCLUDED.source_position_absolute,
                source_position_organic = EXCLUDED.source_position_organic,
                source_position_organic_absolute = EXCLUDED.source_position_organic_absolute,
                source_position_sponsored = EXCLUDED.source_position_sponsored,
                complete_until_source = EXCLUDED.complete_until_source,
                hit_position_limit = EXCLUDED.hit_position_limit,
                result_count = EXCLUDED.result_count,
                sponsored_count = EXCLUDED.sponsored_count,
                organic_count = EXCLUDED.organic_count,
                unknown_placement_count = EXCLUDED.unknown_placement_count,
                parser_status = EXCLUDED.parser_status,
                parser_error = EXCLUDED.parser_error,
                completed_at = EXCLUDED.completed_at
        """
        execute_sql(self.cursor, query, run)

    def replace_serp_items(self, run_id: Any, items: List[Dict[str, Any]]) -> int:
        execute_sql(self.cursor, "DELETE FROM analytics_ai.wb_serp_items WHERE run_id = %s", (run_id,))
        if not items:
            return 0
        prepared = []
        for row in items:
            item = dict(row)
            item["raw_payload"] = self._json(item.get("raw_payload") or {})
            prepared.append(item)
        query = """
            INSERT INTO analytics_ai.wb_serp_items (
                run_id, result_nm_id, is_source, catalog_page, position_on_page,
                position_absolute, position_organic, placement_type, placement_detection,
                brand, subject_name, title, product_url, image_url,
                price_regular, price_display, price_wallet, price_effective, price_basis,
                discount_percent, promo_label, rating, feedbacks, raw_payload
            ) VALUES (
                %(run_id)s, %(result_nm_id)s, %(is_source)s, %(catalog_page)s,
                %(position_on_page)s, %(position_absolute)s, %(position_organic)s,
                %(placement_type)s, %(placement_detection)s, %(brand)s, %(subject_name)s,
                %(title)s, %(product_url)s, %(image_url)s, %(price_regular)s,
                %(price_display)s, %(price_wallet)s, %(price_effective)s, %(price_basis)s,
                %(discount_percent)s, %(promo_label)s, %(rating)s, %(feedbacks)s, %(raw_payload)s
            )
            ON CONFLICT (run_id, position_absolute) DO UPDATE SET
                result_nm_id = EXCLUDED.result_nm_id,
                is_source = EXCLUDED.is_source,
                position_organic = EXCLUDED.position_organic,
                placement_type = EXCLUDED.placement_type,
                placement_detection = EXCLUDED.placement_detection,
                price_regular = EXCLUDED.price_regular,
                price_display = EXCLUDED.price_display,
                price_wallet = EXCLUDED.price_wallet,
                price_effective = EXCLUDED.price_effective,
                price_basis = EXCLUDED.price_basis,
                discount_percent = EXCLUDED.discount_percent,
                promo_label = EXCLUDED.promo_label,
                rating = EXCLUDED.rating,
                feedbacks = EXCLUDED.feedbacks,
                raw_payload = EXCLUDED.raw_payload
        """
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def get_serp_batch_summary(self, batch_id: Any) -> Dict[str, Any]:
        execute_sql(
            self.cursor,
            """WITH planned AS (
                   SELECT COALESCE(SUM(JSONB_ARRAY_LENGTH(payload_json -> 'query_specs')), 0) AS planned_runs
                   FROM analytics_ai.wb_serp_jobs
                   WHERE batch_id = %s
               )
               SELECT
                   MAX(planned.planned_runs) AS planned_runs,
                   COUNT(*) FILTER (WHERE parser_status IN ('success', 'source_not_found')) AS completed_runs,
                   COUNT(*) FILTER (WHERE parser_status = 'success') AS source_found_runs,
                   COUNT(*) FILTER (WHERE parser_status = 'source_not_found') AS source_not_found_runs,
                   COUNT(*) FILTER (WHERE parser_status = 'partial') AS partial_runs,
                   COUNT(*) FILTER (WHERE parser_status = 'failed') AS failed_runs,
                   COALESCE(SUM(result_count), 0) AS result_count,
                   COALESCE(SUM(unknown_placement_count), 0) AS unknown_placement_count
               FROM analytics_ai.wb_serp_runs
               CROSS JOIN planned
               WHERE batch_id = %s""",
            (batch_id, batch_id),
        )
        row = self.cursor.fetchone()
        planned = int(row[0] or 0)
        completed = int(row[1] or 0)
        return {
            "batch_id": str(batch_id),
            "planned_runs": planned,
            "completed_runs": completed,
            "completion_ratio": completed / planned if planned else 0.0,
            "source_found_runs": int(row[2] or 0),
            "source_not_found_runs": int(row[3] or 0),
            "partial_runs": int(row[4] or 0),
            "failed_runs": int(row[5] or 0),
            "result_count": int(row[6] or 0),
            "unknown_placement_count": int(row[7] or 0),
        }

    def get_serp_query_set(self, source_nm_id: int) -> Optional[Dict[str, Any]]:
        execute_sql(
            self.cursor,
            """SELECT source_nm_id, query_specs_json, query_count,
                      frozen_from_batch_id, frozen_from_observed_at,
                      created_reason, created_at, updated_at
               FROM analytics_ai.wb_serp_query_sets
               WHERE source_nm_id = %s""",
            (int(source_nm_id),),
        )
        row = self.cursor.fetchone()
        if not row:
            return None
        return {
            "source_nm_id": int(row[0]),
            "query_specs": self._decode_json(row[1]) or [],
            "query_count": int(row[2] or 0),
            "frozen_from_batch_id": str(row[3]) if row[3] else None,
            "frozen_from_observed_at": row[4].isoformat() if row[4] else None,
            "created_reason": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
            "updated_at": row[7].isoformat() if row[7] else None,
        }

    def create_serp_query_set(
        self,
        source_nm_id: int,
        query_specs: List[Dict[str, Any]],
        *,
        frozen_from_batch_id: Any = None,
        frozen_from_observed_at: Any = None,
        created_reason: str = "initial_selection",
    ) -> Dict[str, Any]:
        """Create a stable query set once; never replace an existing set."""
        execute_sql(
            self.cursor,
            """INSERT INTO analytics_ai.wb_serp_query_sets (
                   source_nm_id, query_specs_json, query_count,
                   frozen_from_batch_id, frozen_from_observed_at, created_reason
               ) VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (source_nm_id) DO NOTHING""",
            (
                int(source_nm_id),
                self._json(query_specs),
                len(query_specs),
                frozen_from_batch_id,
                frozen_from_observed_at,
                created_reason,
            ),
        )
        stored = self.get_serp_query_set(int(source_nm_id))
        if not stored:
            raise RuntimeError(f"Failed to freeze SERP query set for nm_id={source_nm_id}")
        return stored

    def get_latest_successful_seo_keywords(self, source_nm_id: int) -> List[str]:
        execute_sql(
            self.cursor,
            """SELECT keywords_json
               FROM analytics_ai.wb_price_ai_seo_keywords
               WHERE source_nm_id = %s
                 AND seo_status = 'success'
                 AND keyword_count > 0
               ORDER BY run_date DESC, created_at DESC
               LIMIT 1""",
            (int(source_nm_id),),
        )
        row = self.cursor.fetchone()
        return list(self._decode_json(row[0]) or []) if row else []

    def get_latest_source_rows(self) -> List[Dict[str, Any]]:
        query = """
            SELECT
                source.snapshot_date,
                source.nm_id,
                source.barcode,
                source.vendor_code,
                source.supplier_article,
                source.brand,
                source.subject_name,
                source.title,
                source.description,
                source.product_url,
                source.main_photo_url,
                source.characteristics_json,
                source.tags_json,
                source.sizes_json,
                source.warehouse_names,
                source.warehouse_count,
                source.total_quantity,
                source.total_quantity_full,
                COALESCE(prices.price, source.wb_link_price_regular),
                COALESCE(prices.club_discounted_price, prices.discounted_price, source.wb_link_price_promo)
            FROM reports.wb_sku_ai_analysis AS source
            LEFT JOIN LATERAL (
                SELECT price, discounted_price, club_discounted_price
                FROM pricing.wb_supplier_prices AS price_rows
                WHERE price_rows.nm_id = source.nm_id
                ORDER BY price_rows.snapshot_date DESC, price_rows.last_synced_at DESC
                LIMIT 1
            ) AS prices ON TRUE
            WHERE source.snapshot_date = (
                SELECT MAX(snapshot_date) FROM reports.wb_sku_ai_analysis
            )
            ORDER BY source.nm_id, source.barcode
        """
        execute_sql(self.cursor, query)
        rows = self.cursor.fetchall()
        return [
            {
                "snapshot_date": row[0],
                "nm_id": row[1],
                "barcode": row[2],
                "vendor_code": row[3],
                "supplier_article": row[4],
                "brand": row[5],
                "subject_name": row[6],
                "title": row[7],
                "description": row[8],
                "product_url": row[9],
                "main_photo_url": row[10],
                "characteristics_json": row[11],
                "tags_json": row[12],
                "sizes_json": row[13],
                "warehouse_names": row[14] or [],
                "warehouse_count": row[15] or 0,
                "total_quantity": row[16] or 0,
                "total_quantity_full": row[17] or 0,
                "wb_link_price_regular": row[18],
                "wb_link_price_promo": row[19],
            }
            for row in rows
        ]

    def get_latest_active_nm_ids(self) -> List[int]:
        query = """
            SELECT DISTINCT nm_id
            FROM reports.wb_sku_ai_analysis
            WHERE snapshot_date = (
                SELECT MAX(snapshot_date) FROM reports.wb_sku_ai_analysis
            )
              AND GREATEST(COALESCE(total_quantity, 0), COALESCE(total_quantity_full, 0)) > 0
            ORDER BY nm_id
        """
        execute_sql(self.cursor, query)
        return [int(row[0]) for row in self.cursor.fetchall()]

    def upsert_seo_row(self, row: Dict[str, Any]) -> int:
        item = dict(row)
        item["keywords_json"] = self._json(item.get("keywords_json") or [])
        item["raw_response_json"] = self._json(item.get("raw_response_json"))
        query = """
            INSERT INTO reports.wb_price_ai_seo_keywords (
                run_date,
                source_snapshot_date,
                source_nm_id,
                source_title,
                source_subject_name,
                source_brand,
                keywords_json,
                keyword_count,
                seo_model,
                seo_prompt_version,
                seo_status,
                seo_error,
                raw_response_json
            ) VALUES (
                %(run_date)s,
                %(source_snapshot_date)s,
                %(source_nm_id)s,
                %(source_title)s,
                %(source_subject_name)s,
                %(source_brand)s,
                %(keywords_json)s,
                %(keyword_count)s,
                %(seo_model)s,
                %(seo_prompt_version)s,
                %(seo_status)s,
                %(seo_error)s,
                %(raw_response_json)s
            )
            ON CONFLICT (run_date, source_nm_id) DO UPDATE SET
                source_snapshot_date = EXCLUDED.source_snapshot_date,
                source_title = EXCLUDED.source_title,
                source_subject_name = EXCLUDED.source_subject_name,
                source_brand = EXCLUDED.source_brand,
                keywords_json = EXCLUDED.keywords_json,
                keyword_count = EXCLUDED.keyword_count,
                seo_model = EXCLUDED.seo_model,
                seo_prompt_version = EXCLUDED.seo_prompt_version,
                seo_status = EXCLUDED.seo_status,
                seo_error = EXCLUDED.seo_error,
                raw_response_json = EXCLUDED.raw_response_json,
                created_at = CURRENT_TIMESTAMP
        """
        execute_sql(self.cursor, query, item)
        return 1

    def upsert_raw_competitor_rows(self, rows: List[Dict[str, Any]]) -> int:
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
            INSERT INTO reports.wb_price_ai_competitors_raw (
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
                parser_error,
                competitor_status,
                competitor_error,
                task_attempt
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
                %(parser_error)s,
                %(competitor_status)s,
                %(competitor_error)s,
                %(task_attempt)s
            )
            ON CONFLICT (run_date, source_nm_id, keyword, competitor_nm_id) DO UPDATE SET
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
                parser_error = EXCLUDED.parser_error,
                competitor_status = EXCLUDED.competitor_status,
                competitor_error = EXCLUDED.competitor_error,
                task_attempt = EXCLUDED.task_attempt,
                created_at = CURRENT_TIMESTAMP
        """
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def delete_raw_competitors(self, run_date: Any, source_nm_id: int) -> None:
        execute_sql(self.cursor, 
            "DELETE FROM reports.wb_price_ai_competitors_raw WHERE run_date = %s AND source_nm_id = %s",
            (run_date, int(source_nm_id)),
        )

    def get_raw_competitors(self, run_date: date, source_nm_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT
                keyword,
                keyword_order,
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
                price_delta_abs,
                price_delta_percent,
                same_color,
                competitor_status,
                competitor_error
            FROM reports.wb_price_ai_competitors_raw
            WHERE run_date = %s
              AND source_nm_id = %s
            ORDER BY keyword_order, catalog_position_absolute NULLS LAST, competitor_nm_id
        """
        execute_sql(self.cursor, query, (run_date, source_nm_id))
        rows = self.cursor.fetchall()
        return [
            {
                "keyword": row[0],
                "keyword_order": row[1],
                "catalog_position_absolute": row[2],
                "competitor_nm_id": row[3],
                "competitor_brand": row[4],
                "competitor_supplier_name": row[5],
                "competitor_supplier_id": row[6],
                "competitor_subject_name": row[7],
                "competitor_title": row[8],
                "competitor_description_short": row[9],
                "competitor_colors_json": row[10] or [],
                "competitor_main_photo_url": row[11],
                "competitor_product_url": row[12],
                "competitor_price_regular": float(row[13]) if row[13] is not None else None,
                "competitor_price_promo": float(row[14]) if row[14] is not None else None,
                "competitor_discount_percent": float(row[15]) if row[15] is not None else None,
                "competitor_rating": float(row[16]) if row[16] is not None else None,
                "competitor_feedbacks": row[17] or 0,
                "price_delta_abs": float(row[18]) if row[18] is not None else None,
                "price_delta_percent": float(row[19]) if row[19] is not None else None,
                "same_color": row[20],
                "competitor_status": row[21],
                "competitor_error": row[22],
            }
            for row in rows
        ]

    def get_raw_competitors_full(self, run_date: date, source_nm_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT
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
                price_delta_abs,
                price_delta_percent,
                within_price_segment,
                same_subject,
                same_color,
                search_payload_json,
                detail_payload_json,
                parser_status,
                parser_error,
                competitor_status,
                competitor_error
            FROM reports.wb_price_ai_competitors_raw
            WHERE run_date = %s
              AND source_nm_id = %s
            ORDER BY keyword_order, catalog_position_absolute NULLS LAST, competitor_nm_id
        """
        execute_sql(self.cursor, query, (run_date, source_nm_id))
        rows = self.cursor.fetchall()
        return [
            {
                "run_date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "source_snapshot_date": row[1].isoformat() if hasattr(row[1], "isoformat") else (str(row[1]) if row[1] else None),
                "source_nm_id": int(row[2]),
                "source_barcode": row[3],
                "source_brand": row[4],
                "source_subject_name": row[5],
                "source_title": row[6],
                "source_product_url": row[7],
                "source_price_regular": float(row[8]) if row[8] is not None else None,
                "source_price_promo": float(row[9]) if row[9] is not None else None,
                "source_price_segment_min": float(row[10]) if row[10] is not None else None,
                "source_price_segment_max": float(row[11]) if row[11] is not None else None,
                "source_colors_json": self._decode_json(row[12]) or [],
                "keyword": row[13],
                "keyword_order": row[14],
                "catalog_page": row[15],
                "catalog_position_on_page": row[16],
                "catalog_position_absolute": row[17],
                "competitor_nm_id": int(row[18]),
                "competitor_brand": row[19],
                "competitor_supplier_name": row[20],
                "competitor_supplier_id": row[21],
                "competitor_subject_name": row[22],
                "competitor_title": row[23],
                "competitor_description_short": row[24],
                "competitor_colors_json": self._decode_json(row[25]) or [],
                "competitor_main_photo_url": row[26],
                "competitor_product_url": row[27],
                "competitor_price_regular": float(row[28]) if row[28] is not None else None,
                "competitor_price_promo": float(row[29]) if row[29] is not None else None,
                "competitor_discount_percent": float(row[30]) if row[30] is not None else None,
                "competitor_rating": float(row[31]) if row[31] is not None else None,
                "competitor_feedbacks": row[32] or 0,
                "price_delta_abs": float(row[33]) if row[33] is not None else None,
                "price_delta_percent": float(row[34]) if row[34] is not None else None,
                "within_price_segment": bool(row[35]),
                "same_subject": bool(row[36]),
                "same_color": row[37],
                "search_payload_json": self._decode_json(row[38]) or {},
                "detail_payload_json": self._decode_json(row[39]) or {},
                "parser_status": row[40],
                "parser_error": row[41],
                "competitor_status": row[42],
                "competitor_error": row[43],
            }
            for row in rows
        ]

    def upsert_feature_rows(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        prepared: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in (
                "source_dimensions_json",
                "source_platform",
                "source_sleep_size_json",
                "competitor_dimensions_json",
                "competitor_platform",
                "competitor_sleep_size_json",
            ):
                item[key] = self._json(item.get(key))
            prepared.append(item)
        query = """
            INSERT INTO reports.wb_price_ai_competitor_features (
                run_date,
                source_nm_id,
                keyword,
                competitor_nm_id,
                source_subject_norm,
                source_subtype,
                source_dimensions_json,
                source_material,
                source_shape,
                source_platform,
                source_connection_type,
                source_bed_type,
                source_sleep_size_json,
                source_color_family,
                competitor_subject_norm,
                competitor_subtype,
                competitor_dimensions_json,
                competitor_material,
                competitor_shape,
                competitor_platform,
                competitor_connection_type,
                competitor_bed_type,
                competitor_sleep_size_json,
                competitor_color_family,
                normalization_status,
                normalization_error,
                normalization_version
            ) VALUES (
                %(run_date)s,
                %(source_nm_id)s,
                %(keyword)s,
                %(competitor_nm_id)s,
                %(source_subject_norm)s,
                %(source_subtype)s,
                %(source_dimensions_json)s,
                %(source_material)s,
                %(source_shape)s,
                %(source_platform)s,
                %(source_connection_type)s,
                %(source_bed_type)s,
                %(source_sleep_size_json)s,
                %(source_color_family)s,
                %(competitor_subject_norm)s,
                %(competitor_subtype)s,
                %(competitor_dimensions_json)s,
                %(competitor_material)s,
                %(competitor_shape)s,
                %(competitor_platform)s,
                %(competitor_connection_type)s,
                %(competitor_bed_type)s,
                %(competitor_sleep_size_json)s,
                %(competitor_color_family)s,
                %(normalization_status)s,
                %(normalization_error)s,
                %(normalization_version)s
            )
            ON CONFLICT (run_date, source_nm_id, keyword, competitor_nm_id) DO UPDATE SET
                source_subject_norm = EXCLUDED.source_subject_norm,
                source_subtype = EXCLUDED.source_subtype,
                source_dimensions_json = EXCLUDED.source_dimensions_json,
                source_material = EXCLUDED.source_material,
                source_shape = EXCLUDED.source_shape,
                source_platform = EXCLUDED.source_platform,
                source_connection_type = EXCLUDED.source_connection_type,
                source_bed_type = EXCLUDED.source_bed_type,
                source_sleep_size_json = EXCLUDED.source_sleep_size_json,
                source_color_family = EXCLUDED.source_color_family,
                competitor_subject_norm = EXCLUDED.competitor_subject_norm,
                competitor_subtype = EXCLUDED.competitor_subtype,
                competitor_dimensions_json = EXCLUDED.competitor_dimensions_json,
                competitor_material = EXCLUDED.competitor_material,
                competitor_shape = EXCLUDED.competitor_shape,
                competitor_platform = EXCLUDED.competitor_platform,
                competitor_connection_type = EXCLUDED.competitor_connection_type,
                competitor_bed_type = EXCLUDED.competitor_bed_type,
                competitor_sleep_size_json = EXCLUDED.competitor_sleep_size_json,
                competitor_color_family = EXCLUDED.competitor_color_family,
                normalization_status = EXCLUDED.normalization_status,
                normalization_error = EXCLUDED.normalization_error,
                normalization_version = EXCLUDED.normalization_version,
                created_at = CURRENT_TIMESTAMP
        """
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def delete_feature_rows(self, run_date: Any, source_nm_id: int) -> None:
        execute_sql(self.cursor, 
            "DELETE FROM reports.wb_price_ai_competitor_features WHERE run_date = %s AND source_nm_id = %s",
            (run_date, int(source_nm_id)),
        )

    def upsert_filtered_rows(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        prepared: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["hard_filter_flags_json"] = self._json(item.get("hard_filter_flags_json") or {})
            prepared.append(item)
        query = """
            INSERT INTO reports.wb_price_ai_competitors_filtered (
                run_date,
                source_nm_id,
                keyword,
                competitor_nm_id,
                passed_hard_filters,
                hard_filter_reason,
                hard_filter_flags_json,
                filter_profile,
                filter_version,
                is_llm_candidate,
                filter_mode,
                effective_price_match,
                is_price_outlier,
                market_price_median,
                source_to_market_price_ratio,
                filter_status,
                filter_error
            ) VALUES (
                %(run_date)s,
                %(source_nm_id)s,
                %(keyword)s,
                %(competitor_nm_id)s,
                %(passed_hard_filters)s,
                %(hard_filter_reason)s,
                %(hard_filter_flags_json)s,
                %(filter_profile)s,
                %(filter_version)s,
                %(is_llm_candidate)s,
                %(filter_mode)s,
                %(effective_price_match)s,
                %(is_price_outlier)s,
                %(market_price_median)s,
                %(source_to_market_price_ratio)s,
                %(filter_status)s,
                %(filter_error)s
            )
            ON CONFLICT (run_date, source_nm_id, keyword, competitor_nm_id) DO UPDATE SET
                passed_hard_filters = EXCLUDED.passed_hard_filters,
                hard_filter_reason = EXCLUDED.hard_filter_reason,
                hard_filter_flags_json = EXCLUDED.hard_filter_flags_json,
                filter_profile = EXCLUDED.filter_profile,
                filter_version = EXCLUDED.filter_version,
                is_llm_candidate = EXCLUDED.is_llm_candidate,
                filter_mode = EXCLUDED.filter_mode,
                effective_price_match = EXCLUDED.effective_price_match,
                is_price_outlier = EXCLUDED.is_price_outlier,
                market_price_median = EXCLUDED.market_price_median,
                source_to_market_price_ratio = EXCLUDED.source_to_market_price_ratio,
                filter_status = EXCLUDED.filter_status,
                filter_error = EXCLUDED.filter_error,
                created_at = CURRENT_TIMESTAMP
        """
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def delete_filtered_rows(self, run_date: Any, source_nm_id: int) -> None:
        execute_sql(self.cursor, 
            "DELETE FROM reports.wb_price_ai_competitors_filtered WHERE run_date = %s AND source_nm_id = %s",
            (run_date, int(source_nm_id)),
        )

    def upsert_relevance_rows(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        prepared: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["matched_attributes_json"] = self._json(item.get("matched_attributes_json") or {})
            item["raw_response_json"] = self._json(item.get("raw_response_json"))
            prepared.append(item)
        query = """
            INSERT INTO reports.wb_price_ai_competitor_relevance (
                run_date,
                source_nm_id,
                keyword,
                competitor_nm_id,
                relevance_score,
                relevance_verdict,
                relevance_reason,
                matched_attributes_json,
                llm_model,
                llm_prompt_version,
                llm_status,
                llm_error,
                raw_response_json
            ) VALUES (
                %(run_date)s,
                %(source_nm_id)s,
                %(keyword)s,
                %(competitor_nm_id)s,
                %(relevance_score)s,
                %(relevance_verdict)s,
                %(relevance_reason)s,
                %(matched_attributes_json)s,
                %(llm_model)s,
                %(llm_prompt_version)s,
                %(llm_status)s,
                %(llm_error)s,
                %(raw_response_json)s
            )
            ON CONFLICT (run_date, source_nm_id, keyword, competitor_nm_id) DO UPDATE SET
                relevance_score = EXCLUDED.relevance_score,
                relevance_verdict = EXCLUDED.relevance_verdict,
                relevance_reason = EXCLUDED.relevance_reason,
                matched_attributes_json = EXCLUDED.matched_attributes_json,
                llm_model = EXCLUDED.llm_model,
                llm_prompt_version = EXCLUDED.llm_prompt_version,
                llm_status = EXCLUDED.llm_status,
                llm_error = EXCLUDED.llm_error,
                raw_response_json = EXCLUDED.raw_response_json,
                created_at = CURRENT_TIMESTAMP
        """
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def delete_relevance_rows(self, run_date: Any, source_nm_id: int) -> None:
        execute_sql(self.cursor, 
            "DELETE FROM reports.wb_price_ai_competitor_relevance WHERE run_date = %s AND source_nm_id = %s",
            (run_date, int(source_nm_id)),
        )

    def upsert_vision_rows(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        prepared: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["visual_signals_json"] = self._json(item.get("visual_signals_json") or {})
            item["raw_response_json"] = self._json(item.get("raw_response_json"))
            prepared.append(item)
        query = """
            INSERT INTO reports.wb_price_ai_competitor_vision (
                run_date,
                source_nm_id,
                keyword,
                competitor_nm_id,
                vision_score,
                vision_grade,
                vision_reason,
                visual_signals_json,
                vision_model,
                vision_prompt_version,
                vision_status,
                vision_error,
                raw_response_json
            ) VALUES (
                %(run_date)s,
                %(source_nm_id)s,
                %(keyword)s,
                %(competitor_nm_id)s,
                %(vision_score)s,
                %(vision_grade)s,
                %(vision_reason)s,
                %(visual_signals_json)s,
                %(vision_model)s,
                %(vision_prompt_version)s,
                %(vision_status)s,
                %(vision_error)s,
                %(raw_response_json)s
            )
            ON CONFLICT (run_date, source_nm_id, keyword, competitor_nm_id) DO UPDATE SET
                vision_score = EXCLUDED.vision_score,
                vision_grade = EXCLUDED.vision_grade,
                vision_reason = EXCLUDED.vision_reason,
                visual_signals_json = EXCLUDED.visual_signals_json,
                vision_model = EXCLUDED.vision_model,
                vision_prompt_version = EXCLUDED.vision_prompt_version,
                vision_status = EXCLUDED.vision_status,
                vision_error = EXCLUDED.vision_error,
                raw_response_json = EXCLUDED.raw_response_json,
                created_at = CURRENT_TIMESTAMP
        """
        executemany_sql(self.cursor, query, prepared)
        return len(prepared)

    def delete_vision_rows(self, run_date: Any, source_nm_id: int) -> None:
        execute_sql(self.cursor, 
            "DELETE FROM reports.wb_price_ai_competitor_vision WHERE run_date = %s AND source_nm_id = %s",
            (run_date, int(source_nm_id)),
        )

    def get_vision_rows_for_source(self, run_date: date, source_nm_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT
                run_date,
                source_nm_id,
                keyword,
                competitor_nm_id,
                vision_score,
                vision_grade,
                vision_reason,
                visual_signals_json,
                vision_model,
                vision_prompt_version,
                vision_status,
                vision_error,
                raw_response_json
            FROM reports.wb_price_ai_competitor_vision
            WHERE run_date = %s
              AND source_nm_id = %s
        """
        execute_sql(self.cursor, query, (run_date, int(source_nm_id)))
        rows = self.cursor.fetchall()
        return [
            {
                "run_date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "source_nm_id": int(row[1]),
                "keyword": row[2],
                "competitor_nm_id": int(row[3]),
                "vision_score": float(row[4]) if row[4] is not None else None,
                "vision_grade": row[5],
                "vision_reason": row[6],
                "visual_signals_json": self._decode_json(row[7]) or {},
                "vision_model": row[8],
                "vision_prompt_version": row[9],
                "vision_status": row[10],
                "vision_error": row[11],
                "raw_response_json": self._decode_json(row[12]),
            }
            for row in rows
        ]

    def get_features_for_source(self, run_date: date, source_nm_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT
                run_date,
                source_nm_id,
                keyword,
                competitor_nm_id,
                source_subject_norm,
                source_subtype,
                source_dimensions_json,
                source_material,
                source_shape,
                source_platform,
                source_connection_type,
                source_bed_type,
                source_sleep_size_json,
                source_color_family,
                competitor_subject_norm,
                competitor_subtype,
                competitor_dimensions_json,
                competitor_material,
                competitor_shape,
                competitor_platform,
                competitor_connection_type,
                competitor_bed_type,
                competitor_sleep_size_json,
                competitor_color_family,
                normalization_status,
                normalization_error,
                normalization_version
            FROM reports.wb_price_ai_competitor_features
            WHERE run_date = %s
              AND source_nm_id = %s
        """
        execute_sql(self.cursor, query, (run_date, source_nm_id))
        rows = self.cursor.fetchall()
        return [
            {
                "run_date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "source_nm_id": int(row[1]),
                "keyword": row[2],
                "competitor_nm_id": int(row[3]),
                "source_subject_norm": row[4],
                "source_subtype": row[5],
                "source_dimensions_json": self._decode_json(row[6]),
                "source_material": row[7],
                "source_shape": row[8],
                "source_platform": self._decode_json(row[9]) or [],
                "source_connection_type": row[10],
                "source_bed_type": row[11],
                "source_sleep_size_json": self._decode_json(row[12]),
                "source_color_family": row[13],
                "competitor_subject_norm": row[14],
                "competitor_subtype": row[15],
                "competitor_dimensions_json": self._decode_json(row[16]),
                "competitor_material": row[17],
                "competitor_shape": row[18],
                "competitor_platform": self._decode_json(row[19]) or [],
                "competitor_connection_type": row[20],
                "competitor_bed_type": row[21],
                "competitor_sleep_size_json": self._decode_json(row[22]),
                "competitor_color_family": row[23],
                "normalization_status": row[24],
                "normalization_error": row[25],
                "normalization_version": row[26],
            }
            for row in rows
        ]

    def get_filtered_candidates_for_llm(self, run_date: date, source_nm_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT
                raw.keyword,
                raw.keyword_order,
                raw.catalog_position_absolute,
                raw.competitor_nm_id,
                raw.competitor_title,
                raw.competitor_subject_name,
                raw.competitor_price_promo,
                raw.competitor_price_regular,
                raw.competitor_rating,
                raw.competitor_feedbacks,
                raw.price_delta_percent,
                raw.source_title,
                raw.source_subject_name,
                raw.source_price_promo,
                features.source_subject_norm,
                features.source_subtype,
                features.source_dimensions_json,
                features.source_material,
                features.source_shape,
                features.source_platform,
                features.source_connection_type,
                features.source_bed_type,
                features.source_sleep_size_json,
                features.source_color_family,
                features.competitor_subject_norm,
                features.competitor_subtype,
                features.competitor_dimensions_json,
                features.competitor_material,
                features.competitor_shape,
                features.competitor_platform,
                features.competitor_connection_type,
                features.competitor_bed_type,
                features.competitor_sleep_size_json,
                features.competitor_color_family,
                filtered.passed_hard_filters,
                filtered.hard_filter_reason,
                filtered.hard_filter_flags_json,
                filtered.filter_profile,
                filtered.is_llm_candidate
            FROM reports.wb_price_ai_competitors_raw AS raw
            JOIN reports.wb_price_ai_competitor_features AS features
              ON features.run_date = raw.run_date
             AND features.source_nm_id = raw.source_nm_id
             AND features.keyword = raw.keyword
             AND features.competitor_nm_id = raw.competitor_nm_id
            JOIN reports.wb_price_ai_competitors_filtered AS filtered
              ON filtered.run_date = raw.run_date
             AND filtered.source_nm_id = raw.source_nm_id
             AND filtered.keyword = raw.keyword
             AND filtered.competitor_nm_id = raw.competitor_nm_id
            WHERE raw.run_date = %s
              AND raw.source_nm_id = %s
              AND filtered.is_llm_candidate = TRUE
            ORDER BY raw.keyword_order, raw.catalog_position_absolute NULLS LAST, raw.competitor_nm_id
        """
        execute_sql(self.cursor, query, (run_date, source_nm_id))
        rows = self.cursor.fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "keyword": row[0],
                    "keyword_order": row[1],
                    "catalog_position_absolute": row[2],
                    "competitor_nm_id": int(row[3]),
                    "competitor_title": row[4],
                    "competitor_subject_name": row[5],
                    "competitor_price_promo": float(row[6]) if row[6] is not None else None,
                    "competitor_price_regular": float(row[7]) if row[7] is not None else None,
                    "competitor_rating": float(row[8]) if row[8] is not None else None,
                    "competitor_feedbacks": row[9] or 0,
                    "price_delta_percent": float(row[10]) if row[10] is not None else None,
                    "source_title": row[11],
                    "source_subject_name": row[12],
                    "source_price_promo": float(row[13]) if row[13] is not None else None,
                    "source_subject_norm": row[14],
                    "source_subtype": row[15],
                    "source_dimensions_json": self._decode_json(row[16]),
                    "source_material": row[17],
                    "source_shape": row[18],
                    "source_platform": self._decode_json(row[19]) or [],
                    "source_connection_type": row[20],
                    "source_bed_type": row[21],
                    "source_sleep_size_json": self._decode_json(row[22]),
                    "source_color_family": row[23],
                    "competitor_subject_norm": row[24],
                    "competitor_subtype": row[25],
                    "competitor_dimensions_json": self._decode_json(row[26]),
                    "competitor_material": row[27],
                    "competitor_shape": row[28],
                    "competitor_platform": self._decode_json(row[29]) or [],
                    "competitor_connection_type": row[30],
                    "competitor_bed_type": row[31],
                    "competitor_sleep_size_json": self._decode_json(row[32]),
                    "competitor_color_family": row[33],
                    "passed_hard_filters": bool(row[34]),
                    "hard_filter_reason": row[35],
                    "hard_filter_flags_json": self._decode_json(row[36]) or {},
                    "filter_profile": row[37],
                    "is_llm_candidate": bool(row[38]),
                }
            )
        return result

    def get_final_candidates(self, run_date: date, source_nm_id: int) -> List[Dict[str, Any]]:
        query = """
            SELECT
                raw.keyword,
                raw.keyword_order,
                raw.catalog_position_absolute,
                raw.catalog_page,
                raw.catalog_position_on_page,
                raw.competitor_nm_id,
                raw.competitor_brand,
                raw.competitor_supplier_name,
                raw.competitor_supplier_id,
                raw.competitor_subject_name,
                raw.competitor_title,
                raw.competitor_description_short,
                raw.competitor_main_photo_url,
                raw.competitor_product_url,
                raw.competitor_price_regular,
                raw.competitor_price_promo,
                raw.competitor_discount_percent,
                raw.competitor_rating,
                raw.competitor_feedbacks,
                raw.price_delta_abs,
                raw.price_delta_percent,
                raw.source_price_promo,
                raw.source_price_regular,
                raw.source_price_segment_min,
                raw.source_price_segment_max,
                raw.within_price_segment,
                filtered.passed_hard_filters,
                filtered.hard_filter_reason,
                filtered.hard_filter_flags_json,
                filtered.filter_profile,
                filtered.filter_mode,
                filtered.effective_price_match,
                filtered.is_price_outlier,
                filtered.market_price_median,
                filtered.source_to_market_price_ratio,
                relevance.relevance_score,
                relevance.relevance_verdict,
                relevance.relevance_reason,
                relevance.matched_attributes_json,
                relevance.llm_model,
                relevance.llm_prompt_version,
                relevance.llm_status,
                relevance.llm_error,
                vision.vision_score,
                vision.vision_grade,
                vision.vision_reason,
                vision.visual_signals_json,
                vision.vision_model,
                vision.vision_prompt_version,
                vision.vision_status,
                vision.vision_error,
                features.source_subject_norm,
                features.source_subtype,
                features.source_dimensions_json,
                features.source_material,
                features.source_shape,
                features.source_platform,
                features.source_connection_type,
                features.source_bed_type,
                features.source_sleep_size_json,
                features.source_color_family,
                features.competitor_subject_norm,
                features.competitor_subtype,
                features.competitor_dimensions_json,
                features.competitor_material,
                features.competitor_shape,
                features.competitor_platform,
                features.competitor_connection_type,
                features.competitor_bed_type,
                features.competitor_sleep_size_json,
                features.competitor_color_family
            FROM reports.wb_price_ai_competitors_raw AS raw
            JOIN reports.wb_price_ai_competitor_features AS features
              ON features.run_date = raw.run_date
             AND features.source_nm_id = raw.source_nm_id
             AND features.keyword = raw.keyword
             AND features.competitor_nm_id = raw.competitor_nm_id
            JOIN reports.wb_price_ai_competitors_filtered AS filtered
              ON filtered.run_date = raw.run_date
             AND filtered.source_nm_id = raw.source_nm_id
             AND filtered.keyword = raw.keyword
             AND filtered.competitor_nm_id = raw.competitor_nm_id
            LEFT JOIN reports.wb_price_ai_competitor_relevance AS relevance
              ON relevance.run_date = raw.run_date
             AND relevance.source_nm_id = raw.source_nm_id
             AND relevance.keyword = raw.keyword
             AND relevance.competitor_nm_id = raw.competitor_nm_id
            LEFT JOIN reports.wb_price_ai_competitor_vision AS vision
              ON vision.run_date = raw.run_date
             AND vision.source_nm_id = raw.source_nm_id
             AND vision.keyword = raw.keyword
             AND vision.competitor_nm_id = raw.competitor_nm_id
            WHERE raw.run_date = %s
              AND raw.source_nm_id = %s
            ORDER BY raw.keyword_order, raw.catalog_position_absolute NULLS LAST, raw.competitor_nm_id
        """
        execute_sql(self.cursor, query, (run_date, source_nm_id))
        rows = self.cursor.fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "keyword": row[0],
                    "keyword_order": row[1],
                    "catalog_position_absolute": row[2],
                    "catalog_page": row[3],
                    "catalog_position_on_page": row[4],
                    "competitor_nm_id": int(row[5]),
                    "competitor_brand": row[6],
                    "competitor_supplier_name": row[7],
                    "competitor_supplier_id": row[8],
                    "competitor_subject_name": row[9],
                    "competitor_title": row[10],
                    "competitor_description_short": row[11],
                    "competitor_main_photo_url": row[12],
                    "competitor_product_url": row[13],
                    "competitor_price_regular": float(row[14]) if row[14] is not None else None,
                    "competitor_price_promo": float(row[15]) if row[15] is not None else None,
                    "competitor_discount_percent": float(row[16]) if row[16] is not None else None,
                    "competitor_rating": float(row[17]) if row[17] is not None else None,
                    "competitor_feedbacks": row[18] or 0,
                    "price_delta_abs": float(row[19]) if row[19] is not None else None,
                    "price_delta_percent": float(row[20]) if row[20] is not None else None,
                    "source_price_promo": float(row[21]) if row[21] is not None else None,
                    "source_price_regular": float(row[22]) if row[22] is not None else None,
                    "source_price_segment_min": float(row[23]) if row[23] is not None else None,
                    "source_price_segment_max": float(row[24]) if row[24] is not None else None,
                    "within_price_segment": bool(row[25]),
                    "passed_hard_filters": bool(row[26]),
                    "hard_filter_reason": row[27],
                    "hard_filter_flags_json": self._decode_json(row[28]) or {},
                    "filter_profile": row[29],
                    "filter_mode": row[30],
                    "effective_price_match": bool(row[31]),
                    "is_price_outlier": bool(row[32]),
                    "market_price_median": float(row[33]) if row[33] is not None else None,
                    "source_to_market_price_ratio": float(row[34]) if row[34] is not None else None,
                    "relevance_score": float(row[35]) if row[35] is not None else None,
                    "relevance_verdict": row[36],
                    "relevance_reason": row[37],
                    "matched_attributes_json": self._decode_json(row[38]) or {},
                    "llm_model": row[39],
                    "llm_prompt_version": row[40],
                    "llm_status": row[41],
                    "llm_error": row[42],
                    "vision_score": float(row[43]) if row[43] is not None else None,
                    "vision_grade": row[44],
                    "vision_reason": row[45],
                    "visual_signals_json": self._decode_json(row[46]) or {},
                    "vision_model": row[47],
                    "vision_prompt_version": row[48],
                    "vision_status": row[49],
                    "vision_error": row[50],
                    "source_subject_norm": row[51],
                    "source_subtype": row[52],
                    "source_dimensions_json": self._decode_json(row[53]),
                    "source_material": row[54],
                    "source_shape": row[55],
                    "source_platform": self._decode_json(row[56]) or [],
                    "source_connection_type": row[57],
                    "source_bed_type": row[58],
                    "source_sleep_size_json": self._decode_json(row[59]),
                    "source_color_family": row[60],
                    "competitor_subject_norm": row[61],
                    "competitor_subtype": row[62],
                    "competitor_dimensions_json": self._decode_json(row[63]),
                    "competitor_material": row[64],
                    "competitor_shape": row[65],
                    "competitor_platform": self._decode_json(row[66]) or [],
                    "competitor_connection_type": row[67],
                    "competitor_bed_type": row[68],
                    "competitor_sleep_size_json": self._decode_json(row[69]),
                    "competitor_color_family": row[70],
                }
            )
        return result

    def upsert_analysis_row(self, row: Dict[str, Any]) -> int:
        item = dict(row)
        for key in (
            "source_price_site_display",
            "source_price_site_wallet",
            "source_price_site_effective",
            "source_platform_discount_percent",
            "source_wallet_discount_percent",
            "source_report_to_site_discount_percent",
        ):
            item.setdefault(key, None)
        for key in ("source_barcodes_json", "source_warehouse_names_json", "seo_keywords_json", "competitors_json"):
            item[key] = self._json(item.get(key) or [])
        query = """
            INSERT INTO reports.wb_price_ai_analysis (
                run_date,
                source_snapshot_date,
                source_nm_id,
                source_vendor_code,
                source_supplier_article,
                source_brand,
                source_subject_name,
                source_title,
                source_description,
                source_product_url,
                source_main_photo_url,
                source_barcodes_json,
                variant_count,
                source_total_quantity,
                source_total_quantity_full,
                source_warehouse_names_json,
                source_warehouse_count,
                source_price_regular,
                source_price_promo,
                source_price_site_display,
                source_price_site_wallet,
                source_price_site_effective,
                source_platform_discount_percent,
                source_wallet_discount_percent,
                source_report_to_site_discount_percent,
                source_discount_percent,
                seo_keywords_json,
                seo_keyword_count,
                seo_model,
                seo_status,
                seo_error,
                competitor_status,
                competitor_error,
                competitor_count,
                competitor_cheaper_count,
                competitor_pricier_count,
                competitor_price_min,
                competitor_price_max,
                competitor_price_avg,
                competitor_price_median,
                strict_competitor_count,
                strict_competitor_cheaper_count,
                strict_competitor_pricier_count,
                strict_competitor_price_min,
                strict_competitor_price_max,
                strict_competitor_price_avg,
                strict_competitor_price_median,
                best_competitor_position,
                hard_filter_pass_count,
                llm_checked_count,
                llm_kept_count,
                relevance_avg_score,
                relevance_threshold,
                vision_checked_count,
                vision_absolute_count,
                vision_close_count,
                vision_similar_count,
                vision_not_analog_count,
                vision_avg_score,
                vision_prompt_version,
                pipeline_version,
                competitor_selection_mode,
                used_outlier_expanded_segment,
                used_market_fallback,
                is_price_outlier,
                market_candidate_count,
                market_price_min,
                market_price_p25,
                market_price_median,
                market_price_p75,
                market_price_max,
                source_to_market_price_ratio,
                competitors_json,
                analysis_status
            ) VALUES (
                %(run_date)s,
                %(source_snapshot_date)s,
                %(source_nm_id)s,
                %(source_vendor_code)s,
                %(source_supplier_article)s,
                %(source_brand)s,
                %(source_subject_name)s,
                %(source_title)s,
                %(source_description)s,
                %(source_product_url)s,
                %(source_main_photo_url)s,
                %(source_barcodes_json)s,
                %(variant_count)s,
                %(source_total_quantity)s,
                %(source_total_quantity_full)s,
                %(source_warehouse_names_json)s,
                %(source_warehouse_count)s,
                %(source_price_regular)s,
                %(source_price_promo)s,
                %(source_price_site_display)s,
                %(source_price_site_wallet)s,
                %(source_price_site_effective)s,
                %(source_platform_discount_percent)s,
                %(source_wallet_discount_percent)s,
                %(source_report_to_site_discount_percent)s,
                %(source_discount_percent)s,
                %(seo_keywords_json)s,
                %(seo_keyword_count)s,
                %(seo_model)s,
                %(seo_status)s,
                %(seo_error)s,
                %(competitor_status)s,
                %(competitor_error)s,
                %(competitor_count)s,
                %(competitor_cheaper_count)s,
                %(competitor_pricier_count)s,
                %(competitor_price_min)s,
                %(competitor_price_max)s,
                %(competitor_price_avg)s,
                %(competitor_price_median)s,
                %(strict_competitor_count)s,
                %(strict_competitor_cheaper_count)s,
                %(strict_competitor_pricier_count)s,
                %(strict_competitor_price_min)s,
                %(strict_competitor_price_max)s,
                %(strict_competitor_price_avg)s,
                %(strict_competitor_price_median)s,
                %(best_competitor_position)s,
                %(hard_filter_pass_count)s,
                %(llm_checked_count)s,
                %(llm_kept_count)s,
                %(relevance_avg_score)s,
                %(relevance_threshold)s,
                %(vision_checked_count)s,
                %(vision_absolute_count)s,
                %(vision_close_count)s,
                %(vision_similar_count)s,
                %(vision_not_analog_count)s,
                %(vision_avg_score)s,
                %(vision_prompt_version)s,
                %(pipeline_version)s,
                %(competitor_selection_mode)s,
                %(used_outlier_expanded_segment)s,
                %(used_market_fallback)s,
                %(is_price_outlier)s,
                %(market_candidate_count)s,
                %(market_price_min)s,
                %(market_price_p25)s,
                %(market_price_median)s,
                %(market_price_p75)s,
                %(market_price_max)s,
                %(source_to_market_price_ratio)s,
                %(competitors_json)s,
                %(analysis_status)s
            )
            ON CONFLICT (run_date, source_nm_id) DO UPDATE SET
                source_snapshot_date = EXCLUDED.source_snapshot_date,
                source_vendor_code = EXCLUDED.source_vendor_code,
                source_supplier_article = EXCLUDED.source_supplier_article,
                source_brand = EXCLUDED.source_brand,
                source_subject_name = EXCLUDED.source_subject_name,
                source_title = EXCLUDED.source_title,
                source_description = EXCLUDED.source_description,
                source_product_url = EXCLUDED.source_product_url,
                source_main_photo_url = EXCLUDED.source_main_photo_url,
                source_barcodes_json = EXCLUDED.source_barcodes_json,
                variant_count = EXCLUDED.variant_count,
                source_total_quantity = EXCLUDED.source_total_quantity,
                source_total_quantity_full = EXCLUDED.source_total_quantity_full,
                source_warehouse_names_json = EXCLUDED.source_warehouse_names_json,
                source_warehouse_count = EXCLUDED.source_warehouse_count,
                source_price_regular = EXCLUDED.source_price_regular,
                source_price_promo = EXCLUDED.source_price_promo,
                source_price_site_display = EXCLUDED.source_price_site_display,
                source_price_site_wallet = EXCLUDED.source_price_site_wallet,
                source_price_site_effective = EXCLUDED.source_price_site_effective,
                source_platform_discount_percent = EXCLUDED.source_platform_discount_percent,
                source_wallet_discount_percent = EXCLUDED.source_wallet_discount_percent,
                source_report_to_site_discount_percent = EXCLUDED.source_report_to_site_discount_percent,
                source_discount_percent = EXCLUDED.source_discount_percent,
                seo_keywords_json = EXCLUDED.seo_keywords_json,
                seo_keyword_count = EXCLUDED.seo_keyword_count,
                seo_model = EXCLUDED.seo_model,
                seo_status = EXCLUDED.seo_status,
                seo_error = EXCLUDED.seo_error,
                competitor_status = EXCLUDED.competitor_status,
                competitor_error = EXCLUDED.competitor_error,
                competitor_count = EXCLUDED.competitor_count,
                competitor_cheaper_count = EXCLUDED.competitor_cheaper_count,
                competitor_pricier_count = EXCLUDED.competitor_pricier_count,
                competitor_price_min = EXCLUDED.competitor_price_min,
                competitor_price_max = EXCLUDED.competitor_price_max,
                competitor_price_avg = EXCLUDED.competitor_price_avg,
                competitor_price_median = EXCLUDED.competitor_price_median,
                strict_competitor_count = EXCLUDED.strict_competitor_count,
                strict_competitor_cheaper_count = EXCLUDED.strict_competitor_cheaper_count,
                strict_competitor_pricier_count = EXCLUDED.strict_competitor_pricier_count,
                strict_competitor_price_min = EXCLUDED.strict_competitor_price_min,
                strict_competitor_price_max = EXCLUDED.strict_competitor_price_max,
                strict_competitor_price_avg = EXCLUDED.strict_competitor_price_avg,
                strict_competitor_price_median = EXCLUDED.strict_competitor_price_median,
                best_competitor_position = EXCLUDED.best_competitor_position,
                hard_filter_pass_count = EXCLUDED.hard_filter_pass_count,
                llm_checked_count = EXCLUDED.llm_checked_count,
                llm_kept_count = EXCLUDED.llm_kept_count,
                relevance_avg_score = EXCLUDED.relevance_avg_score,
                relevance_threshold = EXCLUDED.relevance_threshold,
                vision_checked_count = EXCLUDED.vision_checked_count,
                vision_absolute_count = EXCLUDED.vision_absolute_count,
                vision_close_count = EXCLUDED.vision_close_count,
                vision_similar_count = EXCLUDED.vision_similar_count,
                vision_not_analog_count = EXCLUDED.vision_not_analog_count,
                vision_avg_score = EXCLUDED.vision_avg_score,
                vision_prompt_version = EXCLUDED.vision_prompt_version,
                pipeline_version = EXCLUDED.pipeline_version,
                competitor_selection_mode = EXCLUDED.competitor_selection_mode,
                used_outlier_expanded_segment = EXCLUDED.used_outlier_expanded_segment,
                used_market_fallback = EXCLUDED.used_market_fallback,
                is_price_outlier = EXCLUDED.is_price_outlier,
                market_candidate_count = EXCLUDED.market_candidate_count,
                market_price_min = EXCLUDED.market_price_min,
                market_price_p25 = EXCLUDED.market_price_p25,
                market_price_median = EXCLUDED.market_price_median,
                market_price_p75 = EXCLUDED.market_price_p75,
                market_price_max = EXCLUDED.market_price_max,
                source_to_market_price_ratio = EXCLUDED.source_to_market_price_ratio,
                competitors_json = EXCLUDED.competitors_json,
                analysis_status = EXCLUDED.analysis_status,
                last_synced_at = CURRENT_TIMESTAMP
        """
        execute_sql(self.cursor, query, item)
        return 1

    def get_run_analysis_rows(self, run_date: date) -> List[Dict[str, Any]]:
        query = """
            SELECT
                run_date,
                source_nm_id,
                source_title,
                source_price_promo,
                seo_status,
                competitor_status,
                competitor_count,
                analysis_status
            FROM reports.wb_price_ai_analysis
            WHERE run_date = %s
            ORDER BY source_nm_id
        """
        execute_sql(self.cursor, query, (run_date,))
        rows = self.cursor.fetchall()
        return [
            {
                "run_date": row[0].isoformat() if isinstance(row[0], date) else str(row[0]),
                "source_nm_id": row[1],
                "source_title": row[2],
                "source_price_promo": float(row[3]) if row[3] is not None else None,
                "seo_status": row[4],
                "competitor_status": row[5],
                "competitor_count": row[6],
                "analysis_status": row[7],
            }
            for row in rows
        ]

    def get_run_summary(self, run_date: date) -> Dict[str, Any]:
        query = """
            SELECT
                COUNT(*) AS sku_total,
                COUNT(*) FILTER (WHERE seo_status = 'success') AS seo_success_count,
                COUNT(*) FILTER (WHERE competitor_status = 'success') AS competitor_success_count,
                COALESCE(SUM(competitor_count), 0) AS competitors_total
            FROM reports.wb_price_ai_analysis
            WHERE run_date = %s
        """
        execute_sql(self.cursor, query, (run_date,))
        row = self.cursor.fetchone()
        return {
            "run_date": run_date.isoformat(),
            "sku_total": int(row[0] or 0),
            "seo_success_count": int(row[1] or 0),
            "competitor_success_count": int(row[2] or 0),
            "competitors_total": int(row[3] or 0),
        }


def dump_json(path: str, payload: Dict[str, Any]) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, default=str)
    return path
