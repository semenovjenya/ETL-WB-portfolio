"""Модуль для работы с PostgreSQL для маркетинговых кампаний WB (Продвижение)."""
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


class MarketingDatabase:
    """Класс для работы с БД маркетинговых кампаний WB."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def connect(self) -> None:
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Подключение к PostgreSQL установлено (маркетинг)")
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
        for name in ("schema_wb_marketing_campaigns", "schema_wb_marketing_analytics"):
            try:
                execute_ddl_bundle(self.cursor, f"{name}.sql")
                logger.info(f"Таблицы {name} созданы или уже существуют")
            except FileNotFoundError:
                logger.warning(f"Файл {name}.sql не найден, пропуск")
            except psycopg2.Error as e:
                logger.error(f"Ошибка при создании таблиц {name}: {e}")
                raise

    @staticmethod
    def _get_any(item: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in item:
                return item[k]
        return default

    def _get_nested(self, item: Dict[str, Any], *paths: str, default: Any = None) -> Any:
        """Получить значение по пути вида 'settings.name'."""
        for path in paths:
            obj = item
            for key in path.split("."):
                if isinstance(obj, dict) and key in obj:
                    obj = obj[key]
                else:
                    obj = default
                    break
            if obj is not default:
                return obj
        return default

    def parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        s = str(value).strip().replace("Z", "")
        if "." in s:
            s = s.split(".")[0]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        logger.warning(f"Не удалось распарсить дату: {value}")
        return None

    def normalize_row_promotion(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Нормализация строки из GET /api/advert/v2/adverts (рекламные кампании поиска)."""
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        timestamps = get_("timestamps") or {}
        settings = get_("settings") or {}
        external_id = get_("id", "advertId", default=0)
        if not external_id:
            return {}
        created = self.parse_datetime(timestamps.get("created"))
        updated = self.parse_datetime(timestamps.get("updated"))
        started = self.parse_datetime(timestamps.get("started"))
        deleted = self.parse_datetime(timestamps.get("deleted"))
        # Для хранения в settings_json исключаем дублирующие поля
        settings_json = None
        if item:
            raw = dict(item)
            raw.pop("nm_settings", None)
            try:
                settings_json = json.dumps(raw, ensure_ascii=False) if raw else None
            except (TypeError, ValueError):
                settings_json = None
        return {
            "campaign_type": "promotion",
            "external_id": external_id,
            "name": settings.get("name") or get_("name"),
            "status": get_("status"),
            "type": get_("type"),
            "payment_type": settings.get("payment_type"),
            "brand": get_("brand"),
            "created_at": created,
            "updated_at": updated,
            "started_at": started,
            "deleted_at": deleted,
            "change_time": None,
            "end_time": None,
            "settings_json": settings_json,
        }

    def normalize_row_media(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Нормализация строки из GET /adv/v1/adverts (медиакампании)."""
        get_ = lambda *keys, default=None: self._get_any(item, *keys, default=default)
        external_id = get_("advertId", "id", default=0)
        if not external_id:
            return {}
        create_time = self.parse_datetime(get_("createTime", "create_time"))
        end_time = self.parse_datetime(get_("endTime", "end_time"))
        return {
            "campaign_type": "media",
            "external_id": external_id,
            "name": get_("name"),
            "status": get_("status"),
            "type": get_("type"),
            "payment_type": None,
            "brand": get_("brand"),
            "created_at": create_time,
            "updated_at": None,
            "started_at": None,
            "deleted_at": None,
            "change_time": None,
            "end_time": end_time,
            "settings_json": None,
        }

    def upsert_campaigns(
        self,
        rows: List[Dict[str, Any]],
        snapshot_date: date,
        snapshot_hour: datetime,
        campaign_type: str,
    ) -> int:
        """Вставка/обновление кампаний на дату среза."""
        if not rows:
            return 0
        valid = [
            r
            for r in rows
            if r.get("external_id") is not None and r.get("campaign_type") == campaign_type
        ]
        for r in valid:
            r["snapshot_date"] = snapshot_date
            r["snapshot_hour"] = snapshot_hour

        query = """
            INSERT INTO reports.wb_marketing_campaigns (
                snapshot_date, snapshot_hour, campaign_type, external_id, name, status, type,
                payment_type, brand, created_at, updated_at, started_at, deleted_at,
                change_time, end_time, settings_json, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(snapshot_hour)s, %(campaign_type)s, %(external_id)s, %(name)s, %(status)s, %(type)s,
                %(payment_type)s, %(brand)s, %(created_at)s, %(updated_at)s, %(started_at)s, %(deleted_at)s,
                %(change_time)s, %(end_time)s, %(settings_json)s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (snapshot_hour, campaign_type, external_id) DO UPDATE SET
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                type = EXCLUDED.type,
                payment_type = EXCLUDED.payment_type,
                brand = EXCLUDED.brand,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at,
                started_at = EXCLUDED.started_at,
                deleted_at = EXCLUDED.deleted_at,
                change_time = EXCLUDED.change_time,
                end_time = EXCLUDED.end_time,
                settings_json = EXCLUDED.settings_json,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, valid)
            logger.info(
                f"В БД записано/обновлено кампаний ({campaign_type}) за срез {snapshot_date}: {len(valid)}"
            )
            return len(valid)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке кампаний: {e}")
            raise

    def get_campaign_nm_pairs(self, snapshot_date: Optional[date] = None) -> List[tuple]:
        """Список пар (advert_id, nm_id) из wb_marketing_campaign_nms. Если snapshot_date не передан — берётся последняя дата."""
        try:
            if snapshot_date is None:
                execute_sql(self.cursor, 
                    "SELECT MAX(snapshot_date) FROM reports.wb_marketing_campaign_nms"
                )
                row = self.cursor.fetchone()
                if not row or not row[0]:
                    return []
                snapshot_date = row[0]
            execute_sql(self.cursor, 
                """
                SELECT DISTINCT advert_id, nm_id
                FROM reports.wb_marketing_campaign_nms
                WHERE snapshot_date = %s
                  AND snapshot_hour = (
                      SELECT MAX(snapshot_hour)
                      FROM reports.wb_marketing_campaign_nms
                      WHERE snapshot_date = %s
                  )
                ORDER BY advert_id, nm_id
                """,
                (snapshot_date, snapshot_date),
            )
            return [(r[0], r[1]) for r in self.cursor.fetchall()]
        except psycopg2.Error as e:
            logger.error(f"Ошибка при чтении campaign_nm pairs: {e}")
            return []

    def get_campaign_ids(
        self,
        *,
        snapshot_date: Optional[date] = None,
        campaign_type: str = "promotion",
    ) -> List[int]:
        """Список campaign ids из последнего snapshot campaigns."""
        try:
            if snapshot_date is None:
                execute_sql(
                    self.cursor,
                    """
                    SELECT MAX(snapshot_date)
                    FROM reports.wb_marketing_campaigns
                    WHERE campaign_type = %s
                    """,
                    (campaign_type,),
                )
                row = self.cursor.fetchone()
                if not row or not row[0]:
                    return []
                snapshot_date = row[0]
            execute_sql(
                self.cursor,
                """
                SELECT DISTINCT external_id
                FROM reports.wb_marketing_campaigns
                WHERE snapshot_date = %s
                  AND campaign_type = %s
                  AND snapshot_hour = (
                      SELECT MAX(snapshot_hour)
                      FROM reports.wb_marketing_campaigns
                      WHERE snapshot_date = %s
                        AND campaign_type = %s
                  )
                ORDER BY external_id
                """,
                (snapshot_date, campaign_type, snapshot_date, campaign_type),
            )
            return [int(row[0]) for row in self.cursor.fetchall()]
        except psycopg2.Error as e:
            logger.error(f"Ошибка при чтении campaign ids: {e}")
            return []

    def get_campaign_ids_for_period(
        self,
        *,
        period_from: date,
        period_to: date,
        campaign_type: str = "promotion",
    ) -> List[int]:
        """All locally known campaigns that can affect a fullstats period."""

        try:
            execute_sql(
                self.cursor,
                """
                SELECT DISTINCT advert_id
                FROM (
                    SELECT external_id AS advert_id
                    FROM reports.wb_marketing_campaigns
                    WHERE campaign_type = %s
                      AND snapshot_date BETWEEN %s AND %s
                    UNION
                    SELECT advert_id
                    FROM reports.wb_marketing_campaign_stats_daily
                    WHERE stat_date BETWEEN %s AND %s
                    UNION
                    SELECT advert_id
                    FROM reports.wb_marketing_campaign_stats_daily_nms
                    WHERE stat_date BETWEEN %s AND %s
                ) known_campaigns
                WHERE advert_id IS NOT NULL
                ORDER BY advert_id
                """,
                (
                    campaign_type,
                    period_from,
                    period_to,
                    period_from,
                    period_to,
                    period_from,
                    period_to,
                ),
            )
            return [int(row[0]) for row in self.cursor.fetchall()]
        except psycopg2.Error as e:
            logger.error(f"Ошибка при чтении campaign ids за период: {e}")
            raise

    def upsert_normquery_clusters(
        self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime
    ) -> int:
        """Вставка кластеров (active/excluded)."""
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_marketing_normquery_clusters (
                snapshot_date, snapshot_hour, advert_id, nm_id, is_active, norm_query, last_synced_at
            ) VALUES (%(snapshot_date)s, %(snapshot_hour)s, %(advert_id)s, %(nm_id)s, %(is_active)s, %(norm_query)s, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_hour, advert_id, nm_id, is_active, norm_query) DO UPDATE SET last_synced_at = CURRENT_TIMESTAMP
        """
        for r in rows:
            r["snapshot_date"] = snapshot_date
            r["snapshot_hour"] = snapshot_hour
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано кластеров за {snapshot_date}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке кластеров: {e}")
            raise

    def upsert_normquery_bids(
        self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime
    ) -> int:
        """Вставка ставок по кластерам."""
        if not rows:
            return 0
        for r in rows:
            r["snapshot_date"] = snapshot_date
            r["snapshot_hour"] = snapshot_hour
        query = """
            INSERT INTO reports.wb_marketing_normquery_bids (
                snapshot_date, snapshot_hour, advert_id, nm_id, norm_query, bid, last_synced_at
            ) VALUES (%(snapshot_date)s, %(snapshot_hour)s, %(advert_id)s, %(nm_id)s, %(norm_query)s, %(bid)s, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_hour, advert_id, nm_id, norm_query) DO UPDATE SET bid = EXCLUDED.bid, last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано ставок за {snapshot_date}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке ставок: {e}")
            raise

    def upsert_normquery_minus(
        self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime
    ) -> int:
        """Вставка минус-фраз."""
        if not rows:
            return 0
        for r in rows:
            r["snapshot_date"] = snapshot_date
            r["snapshot_hour"] = snapshot_hour
        query = """
            INSERT INTO reports.wb_marketing_normquery_minus (
                snapshot_date, snapshot_hour, advert_id, nm_id, norm_query, last_synced_at
            ) VALUES (%(snapshot_date)s, %(snapshot_hour)s, %(advert_id)s, %(nm_id)s, %(norm_query)s, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_hour, advert_id, nm_id, norm_query) DO UPDATE SET last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано минус-фраз за {snapshot_date}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке минус-фраз: {e}")
            raise

    def upsert_normquery_stats(
        self, rows: List[Dict[str, Any]], period_from: date, period_to: date
    ) -> int:
        """Вставка статистики по кластерам за период (v0)."""
        if not rows:
            return 0
        for r in rows:
            r["period_from"] = period_from
            r["period_to"] = period_to
        query = """
            INSERT INTO reports.wb_marketing_normquery_stats (
                period_from, period_to, advert_id, nm_id, norm_query,
                views, clicks, ctr, cpc, cpm, orders, atbs, avg_pos, last_synced_at
            ) VALUES (
                %(period_from)s, %(period_to)s, %(advert_id)s, %(nm_id)s, %(norm_query)s,
                %(views)s, %(clicks)s, %(ctr)s, %(cpc)s, %(cpm)s, %(orders)s, %(atbs)s, %(avg_pos)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (period_from, period_to, advert_id, nm_id, norm_query) DO UPDATE SET
                views = EXCLUDED.views, clicks = EXCLUDED.clicks, ctr = EXCLUDED.ctr,
                cpc = EXCLUDED.cpc, cpm = EXCLUDED.cpm, orders = EXCLUDED.orders,
                atbs = EXCLUDED.atbs, avg_pos = EXCLUDED.avg_pos, last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано normquery_stats за {period_from}–{period_to}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке normquery_stats: {e}")
            raise

    def upsert_normquery_stats_daily(
        self, rows: List[Dict[str, Any]]
    ) -> int:
        """Вставка статистики по кластерам по дням (v1)."""
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_marketing_normquery_stats_daily (
                stat_date, advert_id, nm_id, norm_query, views, clicks, ctr, cpc, cpm,
                orders, shks, atbs, avg_pos, spend, last_synced_at
            ) VALUES (
                %(stat_date)s, %(advert_id)s, %(nm_id)s, %(norm_query)s, %(views)s, %(clicks)s, %(ctr)s, %(cpc)s, %(cpm)s,
                %(orders)s, %(shks)s, %(atbs)s, %(avg_pos)s, %(spend)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (stat_date, advert_id, nm_id, norm_query) DO UPDATE SET
                views = EXCLUDED.views, clicks = EXCLUDED.clicks, ctr = EXCLUDED.ctr, cpc = EXCLUDED.cpc, cpm = EXCLUDED.cpm,
                orders = EXCLUDED.orders, shks = EXCLUDED.shks, atbs = EXCLUDED.atbs, avg_pos = EXCLUDED.avg_pos,
                spend = EXCLUDED.spend, last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано normquery_stats_daily: {len(rows)} строк")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке normquery_stats_daily: {e}")
            raise

    def upsert_upd(
        self, rows: List[Dict[str, Any]], period_from: date, period_to: date
    ) -> int:
        """Вставка фактических затрат (upd)."""
        if not rows:
            return 0
        execute_sql(
            self.cursor,
            """
            DELETE FROM reports.wb_marketing_upd
            WHERE period_from = %s
              AND period_to = %s
            """,
            (period_from, period_to),
        )
        for r in rows:
            r["period_from"] = period_from
            r["period_to"] = period_to
        query = """
            INSERT INTO reports.wb_marketing_upd (
                period_from, period_to, advert_id, camp_name, upd_sum, upd_time, advert_type, payment_type, advert_status, last_synced_at
            ) VALUES (
                %(period_from)s, %(period_to)s, %(advert_id)s, %(camp_name)s, %(upd_sum)s, %(upd_time)s,
                %(advert_type)s, %(payment_type)s, %(advert_status)s, CURRENT_TIMESTAMP
            )
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано upd за {period_from}–{period_to}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке upd: {e}")
            raise

    def upsert_payments(
        self, rows: List[Dict[str, Any]], period_from: date, period_to: date
    ) -> int:
        """Вставка истории пополнений marketing кабинета."""
        if not rows:
            return 0
        execute_sql(
            self.cursor,
            """
            DELETE FROM reports.wb_marketing_payments
            WHERE period_from = %s
              AND period_to = %s
            """,
            (period_from, period_to),
        )
        for r in rows:
            r["period_from"] = period_from
            r["period_to"] = period_to
        query = """
            INSERT INTO reports.wb_marketing_payments (
                period_from, period_to, upd_num, advert_id, camp_name, upd_sum, upd_time,
                advert_type, payment_type, advert_status, last_synced_at
            ) VALUES (
                %(period_from)s, %(period_to)s, %(upd_num)s, %(advert_id)s, %(camp_name)s, %(upd_sum)s, %(upd_time)s,
                %(advert_type)s, %(payment_type)s, %(advert_status)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (period_from, period_to, upd_num) DO UPDATE SET
                advert_id = EXCLUDED.advert_id,
                camp_name = EXCLUDED.camp_name,
                upd_sum = EXCLUDED.upd_sum,
                upd_time = EXCLUDED.upd_time,
                advert_type = EXCLUDED.advert_type,
                payment_type = EXCLUDED.payment_type,
                advert_status = EXCLUDED.advert_status,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано payments за {period_from}–{period_to}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке payments: {e}")
            raise

    def upsert_balance(self, balance: float, net: float, bonus: float, snapshot_date: date, snapshot_hour: datetime) -> None:
        """Вставка/обновление баланса на дату."""
        query = """
            INSERT INTO reports.wb_marketing_balance (snapshot_date, snapshot_hour, balance, net, bonus, last_synced_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_hour) DO UPDATE SET
                balance = EXCLUDED.balance,
                net = EXCLUDED.net,
                bonus = EXCLUDED.bonus,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            execute_sql(self.cursor, query, (snapshot_date, snapshot_hour, balance, net, bonus))
            logger.info(f"Баланс за {snapshot_hour.isoformat()} обновлён")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при сохранении баланса: {e}")
            raise

    def upsert_budget(
        self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime
    ) -> int:
        """Вставка бюджетов кампаний."""
        if not rows:
            return 0
        for r in rows:
            r["snapshot_date"] = snapshot_date
            r["snapshot_hour"] = snapshot_hour
        query = """
            INSERT INTO reports.wb_marketing_budget (snapshot_date, snapshot_hour, advert_id, cash, netting, total, last_synced_at)
            VALUES (%(snapshot_date)s, %(snapshot_hour)s, %(advert_id)s, %(cash)s, %(netting)s, %(total)s, CURRENT_TIMESTAMP)
            ON CONFLICT (snapshot_hour, advert_id) DO UPDATE SET
                cash = EXCLUDED.cash,
                netting = EXCLUDED.netting,
                total = EXCLUDED.total,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано бюджетов за {snapshot_date}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке бюджетов: {e}")
            raise

    def upsert_campaign_stats_daily(
        self, rows: List[Dict[str, Any]]
    ) -> int:
        """Вставка дневной статистики по кампаниям (из fullstats)."""
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_marketing_campaign_stats_daily (
                stat_date, advert_id, views, clicks, ctr, cpc, orders, shks,
                sum_spend, sum_price, atbs, canceled, cr, last_synced_at
            ) VALUES (
                %(stat_date)s, %(advert_id)s, %(views)s, %(clicks)s, %(ctr)s,
                %(cpc)s, %(orders)s, %(shks)s, %(sum_spend)s, %(sum_price)s,
                %(atbs)s, %(canceled)s, %(cr)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (stat_date, advert_id) DO UPDATE SET
                views = EXCLUDED.views, clicks = EXCLUDED.clicks, ctr = EXCLUDED.ctr, cpc = EXCLUDED.cpc,
                orders = EXCLUDED.orders, shks = EXCLUDED.shks,
                sum_spend = EXCLUDED.sum_spend, sum_price = EXCLUDED.sum_price,
                atbs = EXCLUDED.atbs, canceled = EXCLUDED.canceled, cr = EXCLUDED.cr, last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано campaign_stats_daily: {len(rows)} строк")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке campaign_stats_daily: {e}")
            raise

    def upsert_campaign_nms(
        self, rows: List[Dict[str, Any]], snapshot_date: date, snapshot_hour: datetime
    ) -> int:
        """Вставка детализации кампаний по номенклатуре (nm_id / SKU)."""
        if not rows:
            return 0
        for r in rows:
            r["snapshot_date"] = snapshot_date
            r["snapshot_hour"] = snapshot_hour
        query = """
            INSERT INTO reports.wb_marketing_campaign_nms (
                snapshot_date, snapshot_hour, advert_id, nm_id, subject_id, subject_name,
                bid_search_kopecks, bid_recommendations_kopecks, last_synced_at
            ) VALUES (
                %(snapshot_date)s, %(snapshot_hour)s, %(advert_id)s, %(nm_id)s, %(subject_id)s, %(subject_name)s,
                %(bid_search_kopecks)s, %(bid_recommendations_kopecks)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (snapshot_hour, advert_id, nm_id) DO UPDATE SET
                subject_id = EXCLUDED.subject_id,
                subject_name = EXCLUDED.subject_name,
                bid_search_kopecks = EXCLUDED.bid_search_kopecks,
                bid_recommendations_kopecks = EXCLUDED.bid_recommendations_kopecks,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано кампания–номенклатура (SKU) за {snapshot_date}: {len(rows)}")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке campaign_nms: {e}")
            raise

    def upsert_campaign_stats_daily_nms(
        self, rows: List[Dict[str, Any]]
    ) -> int:
        """Вставка дневной статистики по кампаниям с детализацией по nm_id (SKU)."""
        if not rows:
            return 0
        query = """
            INSERT INTO reports.wb_marketing_campaign_stats_daily_nms (
                stat_date, advert_id, nm_id, nm_name, views, clicks, ctr, cpc,
                orders, shks, sum_spend, sum_price, atbs, canceled, cr,
                last_synced_at
            ) VALUES (
                %(stat_date)s, %(advert_id)s, %(nm_id)s, %(nm_name)s, %(views)s, %(clicks)s, %(ctr)s, %(cpc)s,
                %(orders)s, %(shks)s, %(sum_spend)s, %(sum_price)s, %(atbs)s,
                %(canceled)s, %(cr)s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (stat_date, advert_id, nm_id) DO UPDATE SET
                nm_name = EXCLUDED.nm_name,
                views = EXCLUDED.views, clicks = EXCLUDED.clicks, ctr = EXCLUDED.ctr, cpc = EXCLUDED.cpc,
                orders = EXCLUDED.orders, shks = EXCLUDED.shks,
                sum_spend = EXCLUDED.sum_spend, sum_price = EXCLUDED.sum_price,
                atbs = EXCLUDED.atbs, canceled = EXCLUDED.canceled, cr = EXCLUDED.cr,
                last_synced_at = CURRENT_TIMESTAMP
        """
        try:
            executemany_sql(self.cursor, query, rows)
            logger.info(f"Записано campaign_stats_daily_nms (по SKU): {len(rows)} строк")
            return len(rows)
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке campaign_stats_daily_nms: {e}")
            raise

    def mark_campaign_stats_daily_watermarks(
        self,
        *,
        period_from: date,
        period_to: date,
        source_run_id: str,
    ) -> int:
        """Mark fullstats days complete only after every campaign batch succeeded."""

        query = """
            INSERT INTO reports.wb_marketing_campaign_stats_daily_watermarks (
                stat_date,
                campaign_stats_complete,
                campaign_sku_stats_complete,
                source_run_id,
                source_completed_at,
                last_synced_at
            )
            SELECT
                day::date,
                TRUE,
                TRUE,
                %s,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM generate_series(%s::date, %s::date, interval '1 day') AS day
            ON CONFLICT (stat_date) DO UPDATE SET
                campaign_stats_complete = EXCLUDED.campaign_stats_complete,
                campaign_sku_stats_complete = EXCLUDED.campaign_sku_stats_complete,
                source_run_id = EXCLUDED.source_run_id,
                source_completed_at = EXCLUDED.source_completed_at,
                last_synced_at = CURRENT_TIMESTAMP
        """
        execute_sql(
            self.cursor,
            query,
            (source_run_id, period_from, period_to),
        )
        return max(0, (period_to - period_from).days + 1)

    def get_snapshot_counts(self, *, snapshot_hour: datetime) -> Dict[str, int]:
        snapshot_date = snapshot_hour.date()
        from datetime import timedelta
        window_start = snapshot_date - timedelta(days=31)
        counts: Dict[str, int] = {}
        exact_tables = {
            "campaigns": "reports.wb_marketing_campaigns",
            "campaign_nms": "reports.wb_marketing_campaign_nms",
            "normquery_clusters": "reports.wb_marketing_normquery_clusters",
            "normquery_bids": "reports.wb_marketing_normquery_bids",
            "normquery_minus": "reports.wb_marketing_normquery_minus",
            "balance": "reports.wb_marketing_balance",
            "budget": "reports.wb_marketing_budget",
        }
        for key, table_name in exact_tables.items():
            execute_sql(
                self.cursor,
                f"SELECT COUNT(*) FROM {table_name} WHERE snapshot_hour = %s",
                (snapshot_hour,),
            )
            counts[key] = int(self.cursor.fetchone()[0])

        period_tables = {
            "upd": ("reports.wb_marketing_upd", "period_to"),
            "payments": ("reports.wb_marketing_payments", "period_to"),
            "normquery_stats": ("reports.wb_marketing_normquery_stats", "period_to"),
        }
        for key, (table_name, date_column) in period_tables.items():
            execute_sql(
                self.cursor,
                f"SELECT COUNT(*) FROM {table_name} WHERE {date_column} = %s",
                (snapshot_date,),
            )
            counts[key] = int(self.cursor.fetchone()[0])

        daily_tables = {
            "normquery_stats_daily": "reports.wb_marketing_normquery_stats_daily",
            "campaign_stats_daily": "reports.wb_marketing_campaign_stats_daily",
            "campaign_stats_daily_nms": "reports.wb_marketing_campaign_stats_daily_nms",
        }
        for key, table_name in daily_tables.items():
            execute_sql(
                self.cursor,
                f"SELECT COUNT(*) FROM {table_name} WHERE stat_date BETWEEN %s AND %s",
                (window_start, snapshot_date),
            )
            counts[key] = int(self.cursor.fetchone()[0])

        return counts
