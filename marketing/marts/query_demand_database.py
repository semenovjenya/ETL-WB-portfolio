"""Материализованные витрины спроса и ad-share для query-level forecast."""
from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from wb_schemas import execute_ddl_bundle, execute_sql

from .config import Config

logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
QUERY_DEMAND_MART_NAMES = (
    "marketing.mart_marketing_query_demand_daily",
    "marketing.mart_marketing_query_share_daily",
    "marketing.mart_marketing_query_forecast_ready",
    "marketing.mart_marketing_campaign_demand_forecast",
)


def resolve_snapshot_hour(snapshot_hour: datetime | None) -> datetime:
    if snapshot_hour is None:
        snapshot_hour = datetime.now(MOSCOW_TZ)
    elif snapshot_hour.tzinfo is None:
        snapshot_hour = snapshot_hour.replace(tzinfo=MOSCOW_TZ)
    return snapshot_hour.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


class QueryDemandMartsDatabase:
    def __init__(self) -> None:
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        self.conn = psycopg2.connect(Config.get_db_connection_string())
        self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        self.cursor = self.conn.cursor()
        logger.info("Подключение к PostgreSQL установлено (query demand marts)")

    def close(self) -> None:
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к БД закрыто (query demand marts)")

    def create_tables(self) -> None:
        execute_ddl_bundle(self.cursor, "schema_wb_marketing_demand_forecast.sql")
        logger.info("DDL bundle schema_wb_marketing_demand_forecast.sql выполнен")

    def _resolve_effective_snapshot_date(self, snapshot_date: date) -> date:
        execute_sql(
            self.cursor,
            """
            WITH markers AS (
                SELECT LEAST(
                    COALESCE((SELECT MAX(current_period_end) FROM marketing.wb_search_query_texts WHERE current_period_end <= %s), %s),
                    COALESCE((SELECT MAX(current_period_end) FROM marketing.wb_search_query_orders_text_daily WHERE current_period_end <= %s), %s),
                    COALESCE((SELECT MAX(stat_date) FROM marketing.mart_marketing_query_daily WHERE stat_date <= %s), %s)
                ) AS effective_snapshot_date
            )
            SELECT effective_snapshot_date
            FROM markers
            """,
            (snapshot_date, snapshot_date, snapshot_date, snapshot_date, snapshot_date, snapshot_date),
        )
        resolved = self.cursor.fetchone()[0]
        return resolved or snapshot_date

    def refresh_marts(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        snapshot_date = snapshot_hour.date()
        refreshed: list[str] = []
        for mart_name in QUERY_DEMAND_MART_NAMES:
            execute_sql(self.cursor, f"REFRESH MATERIALIZED VIEW {mart_name}")
            refreshed.append(mart_name)
            logger.info("Refresh materialized view: %s", mart_name)
        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": snapshot_date.isoformat(),
            "refreshed_marts": refreshed,
        }

    def _raw_summary(self, snapshot_date: date) -> dict[str, dict[str, object]]:
        raw_queries = {
            "search_query_texts": (
                "SELECT COUNT(*), COALESCE(MAX(current_period_end)::text, ''), "
                "COALESCE(SUM(COALESCE(frequency_current, 0)), 0) "
                "FROM marketing.wb_search_query_texts WHERE current_period_end = %s",
                (snapshot_date,),
            ),
            "search_query_orders_text_daily": (
                "SELECT COUNT(*), COALESCE(MAX(current_period_end)::text, ''), "
                "COALESCE(SUM(COALESCE(frequency, 0) + COALESCE(orders_count, 0)), 0) "
                "FROM marketing.wb_search_query_orders_text_daily WHERE current_period_end = %s",
                (snapshot_date,),
            ),
            "marketing_query_daily": (
                "SELECT COUNT(*), COALESCE(MAX(stat_date)::text, ''), "
                "COALESCE(SUM(COALESCE(views, 0) + COALESCE(clicks, 0) + COALESCE(orders, 0)), 0) "
                "FROM marketing.mart_marketing_query_daily "
                "WHERE stat_date BETWEEN %s - INTERVAL '6 day' AND %s",
                (snapshot_date, snapshot_date),
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
            "mart_marketing_query_demand_daily": (
                "SELECT to_regclass('marketing.mart_marketing_query_demand_daily')::text, "
                "COUNT(*) FILTER (WHERE snapshot_date = %s), "
                "COALESCE(MAX(snapshot_date)::text, ''), "
                "COUNT(*) FILTER (WHERE COALESCE(frequency, 0) <= 0) "
                "FROM marketing.mart_marketing_query_demand_daily",
                (snapshot_date,),
            ),
            "mart_marketing_query_share_daily": (
                "SELECT to_regclass('marketing.mart_marketing_query_share_daily')::text, "
                "COUNT(*) FILTER (WHERE snapshot_date = %s), "
                "COALESCE(MAX(snapshot_date)::text, ''), "
                "COUNT(*) FILTER (WHERE share_resolution_status = 'demand_unresolved') "
                "FROM marketing.mart_marketing_query_share_daily",
                (snapshot_date,),
            ),
            "mart_marketing_query_forecast_ready": (
                "SELECT to_regclass('marketing.mart_marketing_query_forecast_ready')::text, "
                "COUNT(*) FILTER (WHERE snapshot_date = %s), "
                "COALESCE(MAX(snapshot_date)::text, ''), "
                "COUNT(*) FILTER (WHERE COALESCE(confidence, '') = '') "
                "FROM marketing.mart_marketing_query_forecast_ready",
                (snapshot_date,),
            ),
            "mart_marketing_campaign_demand_forecast": (
                "SELECT to_regclass('marketing.mart_marketing_campaign_demand_forecast')::text, "
                "COUNT(*) FILTER (WHERE snapshot_date = %s), "
                "COALESCE(MAX(snapshot_date)::text, ''), "
                "COUNT(*) FILTER (WHERE COALESCE(decision_hint, '') = '') "
                "FROM marketing.mart_marketing_campaign_demand_forecast",
                (snapshot_date,),
            ),
        }
        summary: dict[str, dict[str, object]] = {}
        for key, (sql, params) in mart_queries.items():
            execute_sql(self.cursor, sql, params)
            relation_name, count, max_marker, issue_count = self.cursor.fetchone()
            summary[key] = {
                "exists": bool(relation_name),
                "count": int(count or 0),
                "max_marker": max_marker or None,
                "issue_count": int(issue_count or 0),
            }
        execute_sql(
            self.cursor,
            """
            SELECT
                COUNT(*) FILTER (WHERE share_resolution_status = 'resolved'),
                COUNT(*) FILTER (WHERE share_resolution_status = 'demand_unresolved'),
                COUNT(*) FILTER (WHERE share_resolution_status = 'frequency_zero_or_null'),
                COUNT(*) FILTER (WHERE share_resolution_status = 'resolved' AND COALESCE(ad_view_share, 0) > 5)
            FROM marketing.mart_marketing_query_share_daily
            WHERE snapshot_date = %s
            """,
            (snapshot_date,),
        )
        resolved_count, unresolved_count, zero_frequency_count, unreasonable_share_count = self.cursor.fetchone()
        summary["resolution_breakdown"] = {
            "resolved": int(resolved_count or 0),
            "unresolved": int(unresolved_count or 0),
            "frequency_zero_or_null": int(zero_frequency_count or 0),
            "unreasonable_share_count": int(unreasonable_share_count or 0),
        }
        return summary

    def _top_unresolved_queries(self, snapshot_date: date) -> list[dict[str, object]]:
        execute_sql(
            self.cursor,
            """
            SELECT norm_query, advert_id, nm_id, ad_views
            FROM marketing.mart_marketing_query_share_daily
            WHERE snapshot_date = %s
              AND share_resolution_status = 'demand_unresolved'
            ORDER BY ad_views DESC, norm_query
            LIMIT 10
            """,
            (snapshot_date,),
        )
        return [
            {
                "norm_query": row[0],
                "advert_id": int(row[1]),
                "nm_id": int(row[2]),
                "ad_views": float(row[3] or 0),
            }
            for row in self.cursor.fetchall()
        ]

    def debug_marts(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        requested_snapshot_date = snapshot_hour.date()
        effective_snapshot_date = self._resolve_effective_snapshot_date(requested_snapshot_date)
        raw = self._raw_summary(effective_snapshot_date)
        marts = self._mart_summary(effective_snapshot_date)
        issues: list[dict[str, str]] = []

        for mart_name, info in marts.items():
            if mart_name == "resolution_breakdown":
                continue
            if not info["exists"]:
                issues.append(
                    {
                        "scope": mart_name,
                        "status": "refresh_failed",
                        "message": "materialized view отсутствует",
                        "recommended_action": "проверить DDL bundle и refresh",
                    }
                )
            elif info["count"] == 0:
                issues.append(
                    {
                        "scope": mart_name,
                        "status": "refresh_failed",
                        "message": "витрина создана, но не содержит строк на effective snapshot",
                        "recommended_action": "проверить refresh и upstream raw layer",
                    }
                )

        if raw["search_query_texts"]["count"] == 0 or raw["search_query_orders_text_daily"]["count"] == 0:
            issues.append(
                {
                    "scope": "search_report",
                    "status": "search_report_missing",
                    "message": "нет search-report данных по effective snapshot",
                    "recommended_action": "переисполнить fetch_search_texts и fetch_orders",
                }
            )

        if raw["marketing_query_daily"]["count"] == 0:
            issues.append(
                {
                    "scope": "marketing",
                    "status": "marketing_query_stats_missing",
                    "message": "нет marketing.mart_marketing_query_daily за 7-дневное окно",
                    "recommended_action": "переисполнить fetch_marketing_normquery_stats и refresh_marketing_marts",
                }
            )

        if (
            raw["search_query_texts"]["count"] > 0
            and raw["marketing_query_daily"]["count"] > 0
            and marts["mart_marketing_query_share_daily"]["count"] == 0
        ):
            issues.append(
                {
                    "scope": "mart_marketing_query_share_daily",
                    "status": "join_breakage",
                    "message": "источники есть, но share mart пустой; вероятен сломанный join nm_id + normalized text",
                    "recommended_action": "проверить normalize_query_text и join rule",
                }
            )

        if (
            marts["resolution_breakdown"]["unresolved"] > 0
            and marts["resolution_breakdown"]["resolved"] == 0
        ):
            issues.append(
                {
                    "scope": "mart_marketing_query_share_daily",
                    "status": "join_unresolved",
                    "message": "есть только unresolved query matches",
                    "recommended_action": "проверить exact normalized join и top unresolved queries",
                }
            )

        if marts["resolution_breakdown"]["frequency_zero_or_null"] > 0:
            issues.append(
                {
                    "scope": "mart_marketing_query_share_daily",
                    "status": "frequency_zero_or_null",
                    "message": "часть resolve-строк не имеет frequency > 0",
                    "recommended_action": "проверить frequency_source и search-report completeness",
                }
            )

        if marts["resolution_breakdown"]["unreasonable_share_count"] > 0:
            issues.append(
                {
                    "scope": "mart_marketing_query_share_daily",
                    "status": "all_forecasts_zero",
                    "message": "часть resolved query имеет слишком высокую ad_view_share",
                    "recommended_action": "проверить интерпретацию frequency как proxy общего спроса и caps в forecast",
                }
            )

        execute_sql(
            self.cursor,
            """
            SELECT COUNT(*)
            FROM marketing.mart_marketing_query_forecast_ready
            WHERE snapshot_date = %s
              AND COALESCE(extra_views_10pct, 0) = 0
              AND COALESCE(extra_orders_10pct, 0) = 0
              AND COALESCE(extra_spend_10pct, 0) = 0
            """,
            (effective_snapshot_date,),
        )
        all_zero_rows = int(self.cursor.fetchone()[0] or 0)
        if marts["mart_marketing_query_forecast_ready"]["count"] > 0 and all_zero_rows == marts["mart_marketing_query_forecast_ready"]["count"]:
            issues.append(
                {
                    "scope": "mart_marketing_query_forecast_ready",
                    "status": "all_forecasts_zero",
                    "message": "все query forecasts нулевые",
                    "recommended_action": "проверить share caps, marginal coefficients и data sparsity",
                }
            )

        if (
            raw["search_query_texts"]["max_marker"] and raw["search_query_texts"]["max_marker"][:10] != effective_snapshot_date.isoformat()
        ) or (
            raw["marketing_query_daily"]["max_marker"] and raw["marketing_query_daily"]["max_marker"][:10] != effective_snapshot_date.isoformat()
        ):
            issues.append(
                {
                    "scope": "raw_layer",
                    "status": "snapshot_mismatch",
                    "message": "latest common snapshot отличается от requested snapshot",
                    "recommended_action": "использовать latest common effective snapshot",
                }
            )

        return {
            "snapshot_hour": snapshot_hour.isoformat(),
            "snapshot_date": requested_snapshot_date.isoformat(),
            "effective_snapshot_date": effective_snapshot_date.isoformat(),
            "raw": raw,
            "marts": marts,
            "issues": issues,
            "top_unresolved_queries": self._top_unresolved_queries(effective_snapshot_date),
        }

    def validate_marts(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        summary = self.debug_marts(snapshot_hour)
        mart_failures = [
            issue
            for issue in summary["issues"]
            if issue["status"] in {
                "search_report_missing",
                "marketing_query_stats_missing",
                "join_breakage",
                "refresh_failed",
                "snapshot_mismatch",
            }
        ]
        summary["status"] = "ok" if not mart_failures else "error"
        return summary
