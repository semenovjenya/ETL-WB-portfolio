"""Выгрузка воронки продаж по дням за 90 дней: вызов sales-funnel/products по одному дню на каждую дату."""
import json
import logging
import os
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set

import requests

from config import Config
from database import SalesFunnelDatabase
from wb_api_support import (
    TOKEN_MODE_BASE,
    extract_rate_limit_snapshot,
    resolve_wb_token_mode,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DAYS_TO_FETCH = 90
"""Количество дней для выгрузки (последние 90 дней до вчера включительно)."""


def build_missing_report_dates(
    period_start: date,
    period_end: date,
    loaded_dates: Set[date],
) -> List[date]:
    """Построить список отсутствующих report_date внутри рабочего окна."""
    missing_dates: List[date] = []
    current_date = period_start
    while current_date <= period_end:
        if current_date not in loaded_dates:
            missing_dates.append(current_date)
        current_date += timedelta(days=1)
    return missing_dates


class SalesFunnelFetcher:
    """Клиент API sales-funnel/products (лимит 3 запр./мин, интервал 20 сек)."""

    def __init__(self):
        Config.validate()
        self.db = SalesFunnelDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
        self.token_mode = resolve_wb_token_mode(Config.WB_API_TOKEN, Config.WB_API_TOKEN_MODE)
        self._rate_profile = self._build_rate_profile()
        self._last_request_times: List[float] = []

    def _build_rate_profile(self) -> Dict[str, float]:
        if self.token_mode == TOKEN_MODE_BASE:
            return {
                "max_requests": float(Config.BASE_TOKEN_REQUESTS_PER_WINDOW),
                "window_seconds": Config.BASE_TOKEN_REQUEST_WINDOW_SEC,
                "min_interval_seconds": Config.BASE_TOKEN_REQUEST_INTERVAL_SEC,
                "retry_delay_429": float(Config.BASE_TOKEN_RETRY_DELAY_429),
            }
        return {
            "max_requests": float(Config.PERSONAL_SERVICE_REQUESTS_PER_WINDOW),
            "window_seconds": Config.PERSONAL_SERVICE_REQUEST_WINDOW_SEC,
            "min_interval_seconds": Config.PERSONAL_SERVICE_REQUEST_INTERVAL_SEC,
            "retry_delay_429": float(Config.RETRY_DELAY_429),
        }

    def _wait_rate_limit(self) -> None:
        now = time.monotonic()
        interval = self._rate_profile["min_interval_seconds"]
        per_window = max(1, int(self._rate_profile["max_requests"]))
        window_seconds = self._rate_profile["window_seconds"]
        times = self._last_request_times
        if len(times) >= per_window:
            wait_sliding = window_seconds - (now - times[0])
            if wait_sliding > 0:
                time.sleep(wait_sliding)
                now = time.monotonic()
        if times:
            wait_interval = interval - (now - times[-1])
            if wait_interval > 0:
                time.sleep(wait_interval)
                now = time.monotonic()
        self._last_request_times = (times + [now])[-per_window:]

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        headers = {"Authorization": token, "Content-Type": "application/json"}
        client_secret = (Config.WB_API_CLIENT_SECRET or "").strip()
        if client_secret:
            headers["X-Client-Secret"] = client_secret
        return headers

    def _retry_wait_for_429(self, resp: requests.Response, attempt: int) -> float:
        snapshot = extract_rate_limit_snapshot(resp.headers)
        if snapshot.wait_hint is not None:
            return snapshot.wait_hint
        return float(self._rate_profile["retry_delay_429"])

    def fetch_page(
        self,
        period_start: date,
        period_end: date,
        offset: int = 0,
        nm_ids: Optional[Sequence[int]] = None,
        retry_count: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = Config.WB_API_BASE_URL
        headers = self._get_headers()
        body = {
            "selectedPeriod": {"start": period_start.isoformat(), "end": period_end.isoformat()},
            "limit": Config.PAGE_LIMIT,
            "offset": offset,
        }
        if nm_ids is not None:
            body["nmIds"] = list(nm_ids)
        for attempt in range(retry_count):
            try:
                self._wait_rate_limit()
                resp = requests.post(url, headers=headers, json=body, timeout=120)
                if resp.status_code == 429:
                    rate_limit = extract_rate_limit_snapshot(resp.headers)
                    wait = self._retry_wait_for_429(resp, attempt)
                    logger.warning(
                        "429 Too Many Requests, ожидание %.1f сек... "
                        "(mode=%s, retry=%s, reset=%s, remaining=%s, limit=%s, retry_after=%s)",
                        wait,
                        self.token_mode,
                        rate_limit.retry,
                        rate_limit.reset,
                        rate_limit.remaining,
                        rate_limit.limit,
                        rate_limit.retry_after,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                products = (data.get("data") or {}).get("products") or []
                currency = (data.get("data") or {}).get("currency")
                logger.info(
                    f"Получено карточек воронки: {len(products)} (offset={offset}, period {period_start}–{period_end})"
                )
                return {"products": products, "currency": currency}
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{retry_count} не удалась: {e}")
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки исчерпаны: {e}")
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def fetch_all_products_for_day(
        self,
        report_date: date,
    ) -> tuple[List[Dict[str, Any]], Optional[str], int]:
        """
        Забрать все карточки WB sales-funnel за день через offset/limit пагинацию.

        Не опираемся на локальные source-таблицы для отбора nm_id: API должен вернуть
        весь набор товаров, который доступен воронке за эту дату.
        """
        offset = 0
        request_count = 0
        day_products: List[Dict[str, Any]] = []
        currency: Optional[str] = None

        while True:
            result = self.fetch_page(report_date, report_date, offset=offset, nm_ids=None)
            request_count += 1
            if result is None:
                raise RuntimeError(
                    "Не удалось получить полную воронку за "
                    f"{report_date} на offset={offset} после всех ретраев"
                )

            products = result.get("products") or []
            if result.get("currency") is not None:
                currency = result["currency"]

            logger.info(
                "Воронка %s: offset=%s, карточек=%s",
                report_date,
                offset,
                len(products),
            )

            if not products:
                break

            day_products.extend(products)
            if len(products) < Config.PAGE_LIMIT:
                break

            offset += len(products)

        logger.info(
            "Воронка %s: после пагинации собрано карточек=%s, запросов=%s",
            report_date,
            len(day_products),
            request_count,
        )
        return day_products, currency, request_count


def run_90d_daily(
    days: int = DAYS_TO_FETCH,
    save_json: bool = False,
) -> None:
    """
    Поддерживает дозаливку дыр по датам: обрабатывает только отсутствующие report_date
    внутри рабочего окна последних `days` дней до вчера включительно.
    """
    Config.validate()
    fetcher = SalesFunnelFetcher()
    db = fetcher.db

    try:
        db.connect()
        db.ensure_daily_table_only()
    except Exception as e:
        logger.error(f"Подключение к БД: {e}")
        raise

    period_end = date.today() - timedelta(days=1)
    period_start = period_end - timedelta(days=days - 1)
    loaded_dates = db.get_loaded_daily_report_dates(period_start, period_end)
    missing_dates = build_missing_report_dates(period_start, period_end, loaded_dates)

    logger.info(
        "Целевое окно воронки: %s – %s (%s дн.), уже загружено дат: %s, пропущено дат: %s",
        period_start,
        period_end,
        days,
        len(loaded_dates),
        len(missing_dates),
    )
    if missing_dates:
        logger.info(
            "Будут дозагружены даты воронки: %s",
            ", ".join(day.isoformat() for day in missing_dates[:15])
            + (" ..." if len(missing_dates) > 15 else ""),
        )
    else:
        logger.info(
            "Пропущенных дат в рабочем окне нет: повторная загрузка существующих report_date не требуется."
        )
        db.close()
        return

    days_to_process = len(missing_dates)
    logger.info(
        "Воронка по дням: %s – %s (нужно дозагрузить %s дн.). "
        "Режим токена=%s, window=%s сек, max_requests=%s, интервал ≥%s сек.",
        period_start,
        period_end,
        days_to_process,
        fetcher.token_mode,
        fetcher._rate_profile["window_seconds"],
        int(fetcher._rate_profile["max_requests"]),
        fetcher._rate_profile["min_interval_seconds"],
    )

    total_rows = 0
    total_requests = 0
    os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    for day_index, report_date in enumerate(missing_dates):
        day_products, currency, request_count = fetcher.fetch_all_products_for_day(report_date)
        total_requests += request_count

        rows = []
        for item in day_products:
            row = db.normalize_product_to_daily_row(
                item, report_date, currency=currency
            )
            if row is not None:
                rows.append(row)
        if rows:
            db.upsert_funnel_daily(rows)
            total_rows += len(rows)

        if save_json and day_products:
            path = os.path.join(
                Config.JSON_OUTPUT_DIR,
                f"funnel_daily_{report_date.isoformat()}.json",
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "report_date": report_date.isoformat(),
                        "products": day_products,
                        "currency": currency,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info(f"Сохранён JSON: {path} ({len(day_products)} карточек)")

        logger.info(
            f"День {day_index + 1}/{days_to_process} ({report_date}): "
            f"обработано {len(day_products)} карточек, всего строк в БД: {total_rows}"
        )

    logger.info(
        f"Выгрузка воронки по дням завершена. Дозагружено {days_to_process} дн., "
        f"всего API-запросов: {total_requests}, "
        f"всего записей записано/обновлено: {total_rows}"
    )
    db.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="sales_funnel по дням за 90 дней (sales-funnel/products по одному дню)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DAYS_TO_FETCH,
        help=f"Количество дней (по умолчанию {DAYS_TO_FETCH})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Сохранять JSON по каждому дню в json_data",
    )
    args = parser.parse_args()
    run_90d_daily(days=args.days, save_json=args.json)


if __name__ == "__main__":
    main()
