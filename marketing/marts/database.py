"""Материализованные витрины маркетинга для forecast-сценариев."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from wb_schemas import execute_ddl_bundle, execute_sql

from .config import Config

logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
MART_NAMES = (
    "marketing.mart_marketing_query_daily",
    "marketing.mart_marketing_campaign_daily",
    "marketing.mart_marketing_query_bands",
    "marketing.mart_marketing_forecast_ready",
)


def resolve_snapshot_hour(snapshot_hour: datetime | None) -> datetime:
    if snapshot_hour is None:
        snapshot_hour = datetime.now(MOSCOW_TZ)
    elif snapshot_hour.tzinfo is None:
        snapshot_hour = snapshot_hour.replace(tzinfo=MOSCOW_TZ)
    return snapshot_hour.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


class MarketingMartsDatabase:
    def __init__(self) -> None:
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        self.conn = psycopg2.connect(Config.get_db_connection_string())
        self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        self.cursor = self.conn.cursor()
        logger.info("Подключение к PostgreSQL установлено (marketing marts)")

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к БД закрыто (marketing marts)")

    def _existing_marts(self) -> dict[str, bool]:
        states: dict[str, bool] = {}
        for mart_name in MART_NAMES:
            execute_sql(self.cursor, "SELECT to_regclass(%s)::text", (mart_name,))
            states[mart_name] = bool(self.cursor.fetchone()[0])
        return states

    def create_tables(self, *, rebuild: bool = False) -> dict[str, bool]:
        states = self._existing_marts()
        existing = [name for name, exists in states.items() if exists]

        if rebuild:
            execute_ddl_bundle(self.cursor, "schema_wb_marketing_marts.sql")
            logger.info("DDL bundle schema_wb_marketing_marts.sql выполнен в режиме rebuild")
            return self._existing_marts()

        if len(existing) == len(MART_NAMES):
            logger.info("Marketing marts already exist; bootstrap DDL skipped")
            return states

        if not existing:
            execute_ddl_bundle(self.cursor, "schema_wb_marketing_marts.sql")
            logger.info("DDL bundle schema_wb_marketing_marts.sql выполнен для bootstrap")
            return self._existing_marts()

        missing = [name for name, exists in states.items() if not exists]
        raise RuntimeError(
            "Marketing marts are in a partial state. "
            f"Existing={existing}; missing={missing}. "
            "Use explicit rebuild mode instead of scheduled refresh."
        )

    def _resolve_effective_snapshot_date(self, snapshot_date: date) -> date:
        execute_sql(
            self.cursor,
            """
            SELECT COALESCE(
                (
                    SELECT MAX(snapshot_date)
                    FROM marketing.wb_marketing_campaigns
                    WHERE snapshot_date <= %s
                ),
                (
                    SELECT MAX(snapshot_date)
                    FROM marketing.wb_marketing_campaign_nms
                    WHERE snapshot_date <= %s
                ),
                (
                    SELECT MAX(stat_date)
                    FROM marketing.wb_marketing_normquery_stats_daily
                    WHERE stat_date <= %s
                ),
                %s
            )
            """,
            (snapshot_date, snapshot_date, snapshot_date, snapshot_date),
        )
        resolved = self.cursor.fetchone()[0]
        return resolved or snapshot_date

    def refresh_marts(self, snapshot_hour: datetime | None = None, *, rebuild: bool = False) -> dict[str, object]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        snapshot_date = snapshot_hour.date()
        states = self.create_tables(rebuild=rebuild)
        refreshed: list[str] = []
        for mart_name in MART_NAMES:
            if not states.get(mart_name):
                raise RuntimeError(f"Marketing mart {mart_name} is missing after bootstrap/rebuild")
            execute_sql(self.cursor, f"REFRESH MATERIALIZED VIEW {mart_name}")
            refreshed.append(mart_name)
            logger.info("Refresh materialized view: %s", mart_name)
        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_date.isoformat(),
            "refreshed_marts": refreshed,
            "rebuild": rebuild,
        }

    def _raw_summary(self, snapshot_date: date) -> dict[str, dict[str, object]]:
        raw_queries = {
            "campaigns": (
                "SELECT COUNT(*), COALESCE(MAX(snapshot_hour)::text, ''), "
                "COUNT(*) FILTER (WHERE COALESCE(NULLIF(LOWER(payment_type), ''), '') = '') "
                "FROM marketing.wb_marketing_campaigns WHERE snapshot_date = %s",
                (snapshot_date,),
            ),
            "campaign_nms": (
                "SELECT COUNT(*), COALESCE(MAX(snapshot_hour)::text, ''), 0 "
                "FROM marketing.wb_marketing_campaign_nms WHERE snapshot_date = %s",
                (snapshot_date,),
            ),
            "normquery_stats_daily": (
                "SELECT COUNT(*), COALESCE(MAX(stat_date)::text, ''), "
                "COALESCE(SUM(COALESCE(views, 0) + COALESCE(clicks, 0) + COALESCE(orders, 0)), 0) "
                "FROM marketing.wb_marketing_normquery_stats_daily "
                "WHERE stat_date BETWEEN %s - INTERVAL '6 day' AND %s",
                (snapshot_date, snapshot_date),
            ),
            "campaign_stats_daily": (
                "SELECT COUNT(*), COALESCE(MAX(stat_date)::text, ''), "
                "COALESCE(SUM(COALESCE(views, 0) + COALESCE(clicks, 0) + COALESCE(orders, 0)), 0) "
                "FROM marketing.wb_marketing_campaign_stats_daily "
                "WHERE stat_date BETWEEN %s - INTERVAL '6 day' AND %s",
                (snapshot_date, snapshot_date),
            ),
            "normquery_bids": (
                "SELECT COUNT(*), COALESCE(MAX(snapshot_hour)::text, ''), 0 "
                "FROM marketing.wb_marketing_normquery_bids WHERE snapshot_date = %s",
                (snapshot_date,),
            ),
            "normquery_clusters": (
                "SELECT COUNT(*), COALESCE(MAX(snapshot_hour)::text, ''), 0 "
                "FROM marketing.wb_marketing_normquery_clusters WHERE snapshot_date = %s",
                (snapshot_date,),
            ),
        }
        summary: dict[str, dict[str, object]] = {}
        for key, (sql, params) in raw_queries.items():
            execute_sql(self.cursor, sql, params)
            count, max_marker, metric_total = self.cursor.fetchone()
            summary[key] = {
                "count": int(count or 0),
                "max_marker": max_marker or None,
                "metric_total": float(metric_total or 0),
            }
        return summary

    def _mart_summary(self, snapshot_date: date) -> dict[str, dict[str, object]]:
        mart_queries = {
            "mart_marketing_query_daily": (
                "SELECT to_regclass('marketing.mart_marketing_query_daily')::text, "
                "COUNT(*) FILTER (WHERE stat_date BETWEEN %s - INTERVAL '6 day' AND %s), "
                "COALESCE(MAX(stat_date)::text, ''), "
                "COUNT(*) FILTER (WHERE COALESCE(payment_type, 'unknown') = 'unknown') "
                "FROM marketing.mart_marketing_query_daily",
                (snapshot_date, snapshot_date),
            ),
            "mart_marketing_campaign_daily": (
                "SELECT to_regclass('marketing.mart_marketing_campaign_daily')::text, "
                "COUNT(*) FILTER (WHERE stat_date BETWEEN %s - INTERVAL '6 day' AND %s), "
                "COALESCE(MAX(stat_date)::text, ''), "
                "COUNT(*) FILTER (WHERE COALESCE(payment_type, 'unknown') = 'unknown') "
                "FROM marketing.mart_marketing_campaign_daily",
                (snapshot_date, snapshot_date),
            ),
            "mart_marketing_query_bands": (
                "SELECT to_regclass('marketing.mart_marketing_query_bands')::text, "
                "COUNT(*) FILTER (WHERE snapshot_date = %s), "
                "COALESCE(MAX(snapshot_date)::text, ''), "
                "COUNT(*) FILTER (WHERE COALESCE(payment_type, 'unknown') = 'unknown') "
                "FROM marketing.mart_marketing_query_bands",
                (snapshot_date,),
            ),
            "mart_marketing_forecast_ready": (
                "SELECT to_regclass('marketing.mart_marketing_forecast_ready')::text, "
                "COUNT(*) FILTER (WHERE snapshot_date = %s), "
                "COALESCE(MAX(snapshot_date)::text, ''), "
                "COUNT(*) FILTER (WHERE COALESCE(payment_type, 'unknown') = 'unknown') "
                "FROM marketing.mart_marketing_forecast_ready",
                (snapshot_date,),
            ),
        }
        summary: dict[str, dict[str, object]] = {}
        for key, (sql, params) in mart_queries.items():
            execute_sql(self.cursor, sql, params)
            relation_name, count, max_marker, unknown_payment_type = self.cursor.fetchone()
            summary[key] = {
                "exists": bool(relation_name),
                "count": int(count or 0),
                "max_marker": max_marker or None,
                "unknown_payment_type": int(unknown_payment_type or 0),
            }
        return summary

    def debug_marts(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        requested_snapshot_date = snapshot_hour.date()
        effective_snapshot_date = self._resolve_effective_snapshot_date(requested_snapshot_date)
        raw = self._raw_summary(effective_snapshot_date)
        marts = self._mart_summary(effective_snapshot_date)
        issues: list[dict[str, str]] = []

        for mart_name, info in marts.items():
            if not info["exists"]:
                issues.append(
                    {
                        "scope": mart_name,
                        "status": "refresh_failed",
                        "message": "materialized view отсутствует",
                        "recommended_action": "проверить DDL bundle и выполнение refresh",
                    }
                )
            elif info["count"] == 0:
                issues.append(
                    {
                        "scope": mart_name,
                        "status": "refresh_failed",
                        "message": "витрина создана, но не содержит строк на текущий snapshot",
                        "recommended_action": "проверить refresh и upstream raw layer",
                    }
                )
            if info["unknown_payment_type"] > 0:
                issues.append(
                    {
                        "scope": mart_name,
                        "status": "payment_type_unresolved",
                        "message": "есть строки с unresolved payment_type",
                        "recommended_action": "проверить campaign payment_type и rules инференса",
                    }
                )

        if raw["campaigns"]["count"] == 0 or raw["campaign_nms"]["count"] == 0:
            issues.append(
                {
                    "scope": "raw_layer",
                    "status": "raw_missing",
                    "message": "нет campaigns или campaign_nms за snapshot_date",
                    "recommended_action": "переисполнить fetch_campaigns",
                }
            )
        if raw["normquery_stats_daily"]["count"] == 0:
            issues.append(
                {
                    "scope": "raw_layer",
                    "status": "raw_missing",
                    "message": "нет normquery_stats_daily за 7-дневное окно",
                    "recommended_action": "переисполнить fetch_normquery_stats",
                }
            )
        if raw["campaign_stats_daily"]["count"] == 0:
            issues.append(
                {
                    "scope": "raw_layer",
                    "status": "raw_missing",
                    "message": "нет campaign_stats_daily за 7-дневное окно",
                    "recommended_action": "переисполнить fetch_marketing_stats с fullstats",
                }
            )
        if (
            raw["normquery_stats_daily"]["count"] > 0
            and raw["normquery_stats_daily"]["metric_total"] == 0
            and raw["campaign_stats_daily"]["count"] > 0
            and raw["campaign_stats_daily"]["metric_total"] == 0
        ):
            issues.append(
                {
                    "scope": "raw_layer",
                    "status": "all_zero_metrics",
                    "message": "raw статистика есть, но метрики all-zero",
                    "recommended_action": "проверить, что WB API не вернул пустые stats",
                }
            )

        if (
            raw["campaigns"]["count"] > 0
            and raw["normquery_stats_daily"]["count"] > 0
            and marts["mart_marketing_query_daily"]["count"] == 0
        ):
            issues.append(
                {
                    "scope": "mart_marketing_query_daily",
                    "status": "join_breakage",
                    "message": "raw есть, но query mart пустой; вероятен сломанный join advert_id/nm_id/norm_query",
                    "recommended_action": "проверить join на advert_id/nm_id и latest snapshot logic",
                }
            )

        if (
            raw["campaigns"]["max_marker"]
            and raw["campaigns"]["max_marker"][:10] != effective_snapshot_date.isoformat()
        ) or (
            raw["campaign_nms"]["max_marker"]
            and raw["campaign_nms"]["max_marker"][:10] != effective_snapshot_date.isoformat()
        ):
            issues.append(
                {
                    "scope": "raw_layer",
                    "status": "snapshot_mismatch",
                    "message": "latest raw snapshot не совпадает с target snapshot_date",
                    "recommended_action": "проверить snapshot_hour contract и latest-hour joins",
                }
            )

        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": requested_snapshot_date.isoformat(),
            "effective_snapshot_date": effective_snapshot_date.isoformat(),
            "raw": raw,
            "marts": marts,
            "issues": issues,
        }

    def validate_marts(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        summary = self.debug_marts(snapshot_hour)
        mart_failures = [
            issue
            for issue in summary["issues"]
            if issue["status"] in {"refresh_failed", "raw_missing", "join_breakage", "snapshot_mismatch", "all_zero_metrics"}
        ]
        summary["status"] = "ok" if not mart_failures else "error"
        if mart_failures:
            logger.error("Marketing marts validation failed: %s", json.dumps(summary, ensure_ascii=False))
            raise ValueError(json.dumps(summary, ensure_ascii=False))
        logger.info("Marketing marts validation passed: %s", json.dumps(summary, ensure_ascii=False))
        return summary
