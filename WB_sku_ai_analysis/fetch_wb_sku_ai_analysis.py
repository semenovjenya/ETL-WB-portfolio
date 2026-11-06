"""Fetch a rich WB SKU snapshot for all SKUs currently in stock."""
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from config import Config
from database import WBSkuAIAnalysisDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


_NUMBER_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


class WBSkuAIAnalysisFetcher:
    """Builds a wide snapshot for all in-stock SKUs."""

    def __init__(self) -> None:
        Config.validate()
        self.db = WBSkuAIAnalysisDatabase()
        self.session = requests.Session()
        self._last_request_ts: Dict[str, float] = {}
        self._basket_host_cache: Dict[int, int] = {}
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": (Config.WB_API_TOKEN or "").strip(),
            "Content-Type": "application/json",
        }

    def _wait_rate_limit(self, key: str, interval: float) -> None:
        last_ts = self._last_request_ts.get(key)
        if last_ts is None:
            return
        elapsed = time.monotonic() - last_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def _request(
        self,
        method: str,
        url: str,
        key: str,
        interval: float,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        retry_count: Optional[int] = None,
    ) -> Any:
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        for attempt in range(retry_count):
            self._wait_rate_limit(key, interval)
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=self._get_headers(),
                    params=params,
                    json=json_body,
                    timeout=180,
                )
                self._last_request_ts[key] = time.monotonic()
                if response.status_code == 429:
                    wait = max(Config.RETRY_DELAY_429, (attempt + 1) * Config.RETRY_DELAY * 2)
                    logger.warning("429 для %s, ожидание %s сек", url, wait)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "Ошибка запроса %s %s, попытка %s/%s: %s",
                    method,
                    url,
                    attempt + 1,
                    retry_count,
                    exc,
                )
                if attempt == retry_count - 1:
                    raise
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        raise RuntimeError(f"Не удалось получить ответ от {url}")

    @staticmethod
    def _strip(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        clean = text.split(".")[0]
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(clean, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _first_non_empty(*values: Any) -> Any:
        for value in values:
            if value not in (None, "", [], {}, ()):
                return value
        return None

    @staticmethod
    def _chunked(values: List[int], size: int) -> Iterable[List[int]]:
        for index in range(0, len(values), size):
            yield values[index : index + size]

    @staticmethod
    def _parse_numeric(value: Any) -> Optional[float]:
        if value in (None, "", False):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_option_numeric(value: Any) -> Optional[float]:
        if value in (None, "", False):
            return None
        match = _NUMBER_RE.search(str(value).replace(",", "."))
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _option_name_matches(name: Any, *patterns: str) -> bool:
        text = str(name or "").strip().lower()
        if not text:
            return False
        return any(pattern in text for pattern in patterns)

    def fetch_stocks_snapshot(self) -> List[Dict[str, Any]]:
        logger.info("Начало полной выгрузки supplier/stocks для wb_sku_ai_analysis")
        rows: List[Dict[str, Any]] = []
        page = 0
        date_from = Config.STOCKS_DATE_FROM_DEFAULT

        while True:
            page += 1
            data = self._request(
                "GET",
                Config.STOCKS_URL,
                "stocks",
                Config.REQUEST_INTERVAL_STOCKS,
                params={"dateFrom": date_from},
            )
            if not isinstance(data, list):
                logger.warning("Ожидался список supplier/stocks, получено: %s", type(data))
                break
            if not data:
                break
            rows.extend(data)
            logger.info("supplier/stocks: страница %s, строк %s", page, len(data))
            last_change = self._strip(data[-1].get("lastChangeDate") or data[-1].get("last_change_date"))
            if not last_change or len(data) < 60000:
                break
            date_from = last_change

        logger.info("supplier/stocks: всего строк %s", len(rows))
        return rows

    def aggregate_stocks(self, rows: List[Dict[str, Any]], snapshot_date: date) -> List[Dict[str, Any]]:
        grouped: Dict[Tuple[int, str], Dict[str, Any]] = {}
        for row in rows:
            nm_id = row.get("nmId") or row.get("nm_id")
            barcode = self._strip(row.get("barcode"))
            if nm_id is None or not barcode:
                continue
            key = (int(nm_id), barcode)
            item = grouped.setdefault(
                key,
                {
                    "snapshot_date": snapshot_date,
                    "nm_id": int(nm_id),
                    "barcode": barcode,
                    "supplier_article": self._strip(row.get("supplierArticle") or row.get("supplier_article")),
                    "brand": self._strip(row.get("brand")),
                    "subject_name": self._strip(row.get("subject") or row.get("category")),
                    "tech_size": self._strip(row.get("techSize") or row.get("tech_size")),
                    "last_change_date": None,
                    "total_quantity": 0,
                    "total_in_way_to_client": 0,
                    "total_in_way_from_client": 0,
                    "total_quantity_full": 0,
                    "warehouse_names": [],
                    "warehouses_json": [],
                },
            )
            warehouse_name = self._strip(row.get("warehouseName") or row.get("warehouse_name"))
            if warehouse_name and warehouse_name not in item["warehouse_names"]:
                item["warehouse_names"].append(warehouse_name)
            item["warehouses_json"].append(row)
            item["total_quantity"] += int(row.get("quantity") or 0)
            item["total_in_way_to_client"] += int(row.get("inWayToClient") or row.get("in_way_to_client") or 0)
            item["total_in_way_from_client"] += int(row.get("inWayFromClient") or row.get("in_way_from_client") or 0)
            item["total_quantity_full"] += int(row.get("quantityFull") or row.get("quantity_full") or 0)
            item["supplier_article"] = self._first_non_empty(
                item.get("supplier_article"),
                self._strip(row.get("supplierArticle") or row.get("supplier_article")),
            )
            item["brand"] = self._first_non_empty(item.get("brand"), self._strip(row.get("brand")))
            item["subject_name"] = self._first_non_empty(
                item.get("subject_name"),
                self._strip(row.get("subject")),
                self._strip(row.get("category")),
            )
            item["tech_size"] = self._first_non_empty(
                item.get("tech_size"),
                self._strip(row.get("techSize") or row.get("tech_size")),
            )
            last_change = self._parse_datetime(row.get("lastChangeDate") or row.get("last_change_date"))
            if last_change and (item["last_change_date"] is None or last_change > item["last_change_date"]):
                item["last_change_date"] = last_change

        items = []
        for item in grouped.values():
            if max(item["total_quantity"], item["total_quantity_full"]) <= 0:
                continue
            item["warehouse_count"] = len(item["warehouse_names"])
            items.append(item)
        logger.info("SKU в положительном остатке: %s", len(items))
        return items

    def _fetch_cards_page(
        self,
        *,
        cursor: Optional[Dict[str, Any]] = None,
        text_search: Optional[str] = None,
    ) -> Dict[str, Any]:
        filter_body: Dict[str, Any] = {"withPhoto": -1}
        if text_search:
            filter_body["textSearch"] = text_search

        cursor_body: Dict[str, Any] = {"limit": Config.CARDS_PAGE_LIMIT}
        if cursor:
            updated_at = self._strip(cursor.get("updatedAt"))
            nm_id = cursor.get("nmID") or cursor.get("nmId")
            if updated_at:
                cursor_body["updatedAt"] = updated_at
            if nm_id is not None:
                cursor_body["nmID"] = nm_id

        body = {
            "settings": {
                "sort": {"ascending": False},
                "filter": filter_body,
                "cursor": cursor_body,
            }
        }
        data = self._request(
            "POST",
            Config.CARDS_URL,
            "cards",
            Config.REQUEST_INTERVAL_CONTENT,
            json_body=body,
        )
        return data if isinstance(data, dict) else {}

    def _fetch_cards_by_text_search(self, query: str) -> List[Dict[str, Any]]:
        data = self._fetch_cards_page(text_search=query)
        cards = data.get("cards") or []
        if not isinstance(cards, list):
            return []
        return cards

    def _fetch_trash_cards_page(
        self,
        *,
        cursor: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cursor_body: Dict[str, Any] = {"limit": Config.CARDS_PAGE_LIMIT}
        if cursor:
            trashed_at = self._strip(cursor.get("trashedAt"))
            nm_id = cursor.get("nmID") or cursor.get("nmId")
            if trashed_at:
                cursor_body["trashedAt"] = trashed_at
            if nm_id is not None:
                cursor_body["nmID"] = nm_id

        body = {
            "settings": {
                "cursor": cursor_body,
            }
        }
        data = self._request(
            "POST",
            "https://content-api.wildberries.ru/content/v2/get/cards/trash",
            "cards_trash",
            Config.REQUEST_INTERVAL_CONTENT,
            json_body=body,
        )
        return data if isinstance(data, dict) else {}

    def _request_public_card_json(self, nm_id: int, basket_host_id: int) -> Optional[Dict[str, Any]]:
        vol = nm_id // 100000
        part = nm_id // 1000
        url = (
            f"https://basket-{basket_host_id:02d}.wbbasket.ru/"
            f"vol{vol}/part{part}/{nm_id}/info/ru/card.json"
        )
        response = self.session.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"},
            timeout=20,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None

    def _fetch_public_card_by_nm_id(self, nm_id: int) -> Optional[Dict[str, Any]]:
        volume_bucket = nm_id // 100000
        preferred_hosts: List[int] = []
        cached_host = self._basket_host_cache.get(volume_bucket)
        if cached_host is not None:
            preferred_hosts.append(cached_host)
        preferred_hosts.extend(host_id for host_id in range(1, 31) if host_id != cached_host)

        for host_id in preferred_hosts:
            self._wait_rate_limit("public_card", Config.REQUEST_INTERVAL_WB_LINKS)
            try:
                data = self._request_public_card_json(nm_id, host_id)
                self._last_request_ts["public_card"] = time.monotonic()
            except requests.exceptions.RequestException:
                self._last_request_ts["public_card"] = time.monotonic()
                continue
            if data is None:
                continue
            self._basket_host_cache[volume_bucket] = host_id
            return data
        return None

    def _extract_public_card_options(self, public_card: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        options: List[Dict[str, Any]] = []
        if not public_card:
            return options
        raw_options = public_card.get("options") or []
        if isinstance(raw_options, list):
            options.extend([item for item in raw_options if isinstance(item, dict)])
        for group in public_card.get("grouped_options") or []:
            if not isinstance(group, dict):
                continue
            group_options = group.get("options") or []
            if isinstance(group_options, list):
                options.extend([item for item in group_options if isinstance(item, dict)])
        return options

    def _extract_public_card_dimensions(self, public_card: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        options = self._extract_public_card_options(public_card)
        dims: Dict[str, Any] = {}

        for option in options:
            name = option.get("name")
            raw_value = option.get("value")
            numeric_value = self._parse_option_numeric(raw_value)
            if numeric_value is None:
                continue

            if self._option_name_matches(name, "длина упаковки", "длина товара"):
                dims["length"] = numeric_value
            elif self._option_name_matches(name, "ширина упаковки", "ширина товара"):
                dims["width"] = numeric_value
            elif self._option_name_matches(name, "высота упаковки", "высота товара"):
                dims["height"] = numeric_value
            elif self._option_name_matches(name, "вес товара с упаковкой", "вес с упаковкой"):
                dims["weightBrutto"] = numeric_value / 1000.0

        return dims

    def _build_public_card_fallback(self, public_card: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not public_card:
            return {}
        dimensions = self._extract_public_card_dimensions(public_card)
        return {
            "nmID": public_card.get("nm_id"),
            "imtID": public_card.get("imt_id"),
            "vendorCode": public_card.get("vendor_code"),
            "subjectName": public_card.get("subj_name"),
            "title": public_card.get("imt_name"),
            "description": public_card.get("description"),
            "sizes": [
                {
                    "chrtID": chrt_id,
                    "techSize": (public_card.get("data") or {}).get("tech_size"),
                }
                for chrt_id in ((public_card.get("data") or {}).get("chrt_ids") or [])
            ],
            "characteristics": self._extract_public_card_options(public_card),
            "dimensions": dimensions or None,
            "_source": "wbbasket_card_json",
            "_public_card_json": public_card,
        }

    def _fetch_public_card_lookup(self, nm_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        result: Dict[int, Dict[str, Any]] = {}
        for nm_id in nm_ids:
            public_card = self._fetch_public_card_by_nm_id(nm_id)
            if not public_card:
                continue
            result[nm_id] = self._build_public_card_fallback(public_card)
        logger.info("public card fallback: найдено %s карточек по nm_id", len(result))
        return result

    def fetch_warehouse_measurements_lookup(
        self,
        nm_ids: List[int],
        snapshot_date: date,
    ) -> Dict[int, Dict[str, Any]]:
        if not nm_ids:
            return {}

        logger.info("Начало выгрузки warehouse-measurements по %s nm_id", len(nm_ids))
        result: Dict[int, Dict[str, Any]] = {}
        limit = 1000
        offset = 0
        date_from = (snapshot_date - timedelta(days=730)).isoformat() + "T00:00:00Z"
        date_to = snapshot_date.isoformat() + "T23:59:59Z"
        url = "https://seller-analytics-api.wildberries.ru/api/analytics/v1/warehouse-measurements"

        while True:
            data = self._request(
                "GET",
                url,
                "warehouse_measurements",
                Config.REQUEST_INTERVAL_ANALYTICS,
                params={
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "limit": limit,
                    "offset": offset,
                },
            )
            reports = (data.get("data") or {}).get("reports") or []
            if not isinstance(reports, list) or not reports:
                break

            for item in reports:
                nm_id = item.get("nmId") or item.get("nmID")
                if nm_id is None:
                    continue
                nm_id = int(nm_id)
                if nm_id not in nm_ids:
                    continue
                current = result.get(nm_id)
                measured_at = self._parse_datetime(
                    item.get("warehouseMeasureDate")
                    or item.get("dt")
                    or item.get("date")
                )
                current_measured_at = self._parse_datetime(
                    (current or {}).get("warehouseMeasureDate")
                    or (current or {}).get("dt")
                    or (current or {}).get("date")
                )
                if current is None or (
                    measured_at is not None and (current_measured_at is None or measured_at > current_measured_at)
                ):
                    result[nm_id] = item

            if len(reports) < limit:
                break
            offset += len(reports)

        logger.info("warehouse-measurements: найдено %s измерений по nm_id", len(result))
        return result

    def _fetch_cards_lookup_by_nm_ids(self, nm_ids: set[int]) -> Dict[int, Dict[str, Any]]:
        cards_by_nm_id: Dict[int, Dict[str, Any]] = {}
        cursor: Optional[Dict[str, Any]] = None
        seen_cursors: set[Tuple[Optional[str], Optional[int]]] = set()
        page = 0

        while len(cards_by_nm_id) < len(nm_ids):
            page += 1
            data = self._fetch_cards_page(cursor=cursor)
            cards = data.get("cards") or []
            if not isinstance(cards, list) or not cards:
                break

            matched_this_page = 0
            for card in cards:
                card_nm_id = card.get("nmID") or card.get("nmId")
                if card_nm_id is None:
                    continue
                card_nm_id = int(card_nm_id)
                if card_nm_id in nm_ids and card_nm_id not in cards_by_nm_id:
                    cards_by_nm_id[card_nm_id] = card
                    matched_this_page += 1

            logger.info(
                "content cards by nm_id: страница %s, карточек %s, найдено target nm_id %s/%s",
                page,
                len(cards),
                len(cards_by_nm_id),
                len(nm_ids),
            )

            next_cursor = data.get("cursor") or {}
            next_key = (
                self._strip(next_cursor.get("updatedAt")),
                next_cursor.get("nmID") or next_cursor.get("nmId"),
            )
            if (
                len(cards) < Config.CARDS_PAGE_LIMIT
                or not next_key[0]
                or next_key in seen_cursors
            ):
                break
            seen_cursors.add(next_key)
            cursor = {
                "updatedAt": next_key[0],
                "nmID": next_key[1],
            }

        return cards_by_nm_id

    def _fetch_trash_cards_lookup_by_nm_ids(self, nm_ids: set[int]) -> Dict[int, Dict[str, Any]]:
        cards_by_nm_id: Dict[int, Dict[str, Any]] = {}
        cursor: Optional[Dict[str, Any]] = None
        seen_cursors: set[Tuple[Optional[str], Optional[int]]] = set()
        page = 0

        while len(cards_by_nm_id) < len(nm_ids):
            page += 1
            data = self._fetch_trash_cards_page(cursor=cursor)
            cards = data.get("cards") or []
            if not isinstance(cards, list) or not cards:
                break

            for card in cards:
                card_nm_id = card.get("nmID") or card.get("nmId")
                if card_nm_id is None:
                    continue
                card_nm_id = int(card_nm_id)
                if card_nm_id in nm_ids and card_nm_id not in cards_by_nm_id:
                    cards_by_nm_id[card_nm_id] = card

            logger.info(
                "content trash cards by nm_id: страница %s, карточек %s, найдено target nm_id %s/%s",
                page,
                len(cards),
                len(cards_by_nm_id),
                len(nm_ids),
            )

            next_cursor = data.get("cursor") or {}
            next_key = (
                self._strip(next_cursor.get("trashedAt")),
                next_cursor.get("nmID") or next_cursor.get("nmId"),
            )
            if (
                len(cards) < Config.CARDS_PAGE_LIMIT
                or not next_key[0]
                or next_key in seen_cursors
            ):
                break
            seen_cursors.add(next_key)
            cursor = {
                "trashedAt": next_key[0],
                "nmID": next_key[1],
            }

        return cards_by_nm_id

    def fetch_cards_lookup(self, aggregated_stocks: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        logger.info("Начало поиска карточек через content/v2/get/cards/list")
        target_nm_ids = {int(stock["nm_id"]) for stock in aggregated_stocks}
        cards = self._fetch_cards_lookup_by_nm_ids(target_nm_ids)
        missing_nm_ids = {nm_id for nm_id in target_nm_ids if nm_id not in cards}
        trash_cards = self._fetch_trash_cards_lookup_by_nm_ids(missing_nm_ids)
        cards.update(trash_cards)
        query_cache: Dict[str, List[Dict[str, Any]]] = {}
        found_pairs: set[Tuple[int, str]] = set()
        matched_by_query_type: Dict[str, int] = {
            "nm_id": 0,
            "trash_nm_id": 0,
            "nm_id_search": 0,
            "barcode": 0,
            "supplier_article": 0,
        }

        for stock in aggregated_stocks:
            nm_id = stock["nm_id"]
            barcode = stock["barcode"]
            supplier_article = self._strip(stock.get("supplier_article"))
            if nm_id in trash_cards:
                found_pairs.add((nm_id, barcode))
                matched_by_query_type["trash_nm_id"] += 1
                continue
            if nm_id in cards:
                found_pairs.add((nm_id, barcode))
                matched_by_query_type["nm_id"] += 1
                continue

            search_queries = [
                ("nm_id_search", str(nm_id)),
                ("barcode", barcode),
                ("supplier_article", supplier_article),
            ]

            for query_type, raw_query in search_queries:
                query = self._strip(raw_query)
                if not query:
                    continue
                if query not in query_cache:
                    query_cache[query] = self._fetch_cards_by_text_search(query)
                for card in query_cache[query]:
                    card_nm_id = card.get("nmID") or card.get("nmId")
                    if card_nm_id is None:
                        continue
                    cards[int(card_nm_id)] = card
                    if int(card_nm_id) == nm_id:
                        if (nm_id, barcode) not in found_pairs:
                            matched_by_query_type[query_type] += 1
                        found_pairs.add((nm_id, barcode))
                if (nm_id, barcode) in found_pairs:
                    break

        logger.info(
            (
                "content cards: найдено карточек %s для %s SKU в остатке "
                "(nm_id=%s, trash_nm_id=%s, nm_id_search=%s, barcode=%s, supplier_article=%s)"
            ),
            len(cards),
            len(found_pairs),
            matched_by_query_type["nm_id"],
            matched_by_query_type["trash_nm_id"],
            matched_by_query_type["nm_id_search"],
            matched_by_query_type["barcode"],
            matched_by_query_type["supplier_article"],
        )
        return cards

    def fetch_prices_lookup(self) -> Dict[int, Dict[str, Any]]:
        logger.info("Начало полной выгрузки list/goods/filter")
        prices: Dict[int, Dict[str, Any]] = {}
        offset = 0
        page = 0
        while True:
            page += 1
            data = self._request(
                "GET",
                Config.PRICES_URL,
                "prices",
                Config.REQUEST_INTERVAL_CONTENT,
                params={"limit": Config.PRICES_PAGE_LIMIT, "offset": offset},
            )
            items = (data.get("data") or {}).get("listGoods") or []
            if not isinstance(items, list) or not items:
                break
            for item in items:
                nm_id = item.get("nmID") or item.get("nmId")
                if nm_id is not None:
                    prices[int(nm_id)] = item
            logger.info("prices: страница %s, товаров %s", page, len(items))
            offset += len(items)
            if len(items) < Config.PRICES_PAGE_LIMIT:
                break
        logger.info("prices: всего товаров %s", len(prices))
        return prices

    def fetch_funnel_lookup(self, nm_ids: List[int], snapshot_date: date) -> Dict[int, Dict[str, Any]]:
        if not nm_ids:
            return {}
        logger.info("Начало выгрузки sales-funnel/products по %s nm_id", len(nm_ids))
        result: Dict[int, Dict[str, Any]] = {}
        selected_end = snapshot_date - timedelta(days=1)
        selected_start = selected_end - timedelta(days=Config.ANALYTICS_PERIOD_DAYS - 1)
        past_end = selected_start - timedelta(days=1)
        past_start = past_end - timedelta(days=Config.ANALYTICS_PERIOD_DAYS - 1)

        for batch_index, batch in enumerate(self._chunked(nm_ids, Config.ANALYTICS_BATCH_LIMIT), start=1):
            body = {
                "selectedPeriod": {"start": selected_start.isoformat(), "end": selected_end.isoformat()},
                "pastPeriod": {"start": past_start.isoformat(), "end": past_end.isoformat()},
                "nmIds": batch,
                "skipDeletedNm": False,
                "limit": len(batch),
                "offset": 0,
            }
            data = self._request(
                "POST",
                Config.FUNNEL_URL,
                "funnel",
                Config.REQUEST_INTERVAL_ANALYTICS,
                json_body=body,
            )
            products = (data.get("data") or {}).get("products") or []
            logger.info("sales funnel: батч %s, товаров %s", batch_index, len(products))
            for item in products:
                product = item.get("product") or {}
                nm_id = product.get("nmId") or product.get("nmID")
                if nm_id is not None:
                    result[int(nm_id)] = item
        return result

    def fetch_stocks_report_lookup(self, nm_ids: List[int], snapshot_date: date) -> Dict[int, Dict[str, Any]]:
        if not nm_ids:
            return {}
        logger.info("Начало выгрузки stocks-report/products/products по %s nm_id", len(nm_ids))
        result: Dict[int, Dict[str, Any]] = {}
        for batch_index, batch in enumerate(self._chunked(nm_ids, Config.ANALYTICS_BATCH_LIMIT), start=1):
            body = {
                "nmIDs": batch,
                "currentPeriod": {"start": snapshot_date.isoformat(), "end": snapshot_date.isoformat()},
                "stockType": "",
                "skipDeletedNm": False,
                "orderBy": {"field": "stockCount", "mode": "desc"},
                "availabilityFilters": ["deficient", "actual", "balanced"],
                "limit": len(batch),
                "offset": 0,
            }
            data = self._request(
                "POST",
                Config.STOCKS_REPORT_PRODUCTS_URL,
                "stocks_report",
                Config.REQUEST_INTERVAL_ANALYTICS,
                json_body=body,
            )
            items = (data.get("data") or {}).get("items") or []
            logger.info("stocks report: батч %s, товаров %s", batch_index, len(items))
            for item in items:
                nm_id = item.get("nmID") or item.get("nmId")
                if nm_id is not None:
                    result[int(nm_id)] = item
        return result

    def _extract_card_match(self, card: Optional[Dict[str, Any]], barcode: str) -> Dict[str, Any]:
        if not card:
            return {}
        matched: Dict[str, Any] = {}
        for size in card.get("sizes") or []:
            skus = [self._strip(sku) for sku in size.get("skus") or []]
            if barcode in skus:
                matched = size
                break
        return matched

    def _extract_photo_urls(self, card: Optional[Dict[str, Any]], stocks_report_item: Optional[Dict[str, Any]]) -> List[str]:
        urls: List[str] = []
        for photo in (card or {}).get("photos") or []:
            if not isinstance(photo, dict):
                continue
            for key in ("big", "c516x688", "c246x328", "square", "tm"):
                value = self._strip(photo.get(key))
                if value and value not in urls:
                    urls.append(value)
        for media in ((card or {}).get("_public_card_json") or {}).get("media") or []:
            if not isinstance(media, dict):
                continue
            value = self._strip(media.get("big") or media.get("c516x688") or media.get("square") or media.get("url"))
            if value and value not in urls:
                urls.append(value)
        main_photo = self._strip((stocks_report_item or {}).get("mainPhoto"))
        if main_photo and main_photo not in urls:
            urls.insert(0, main_photo)
        return urls

    def _extract_measurement_dimensions(self, measurement: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not measurement:
            return {}
        return {
            "width": self._parse_numeric(measurement.get("width")),
            "height": self._parse_numeric(measurement.get("height")),
            "length": self._parse_numeric(measurement.get("length")),
            "weightBrutto": self._parse_numeric(
                self._first_non_empty(
                    measurement.get("weightBrutto"),
                    measurement.get("weight"),
                    measurement.get("volumeSup"),
                )
            ),
        }

    @staticmethod
    def _product_url(nm_id: int) -> str:
        return f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"

    def build_rows(
        self,
        aggregated_stocks: List[Dict[str, Any]],
        cards_lookup: Dict[int, Dict[str, Any]],
        prices_lookup: Dict[int, Dict[str, Any]],
        funnel_lookup: Dict[int, Dict[str, Any]],
        stocks_report_lookup: Dict[int, Dict[str, Any]],
        warehouse_measurements_lookup: Dict[int, Dict[str, Any]],
        public_card_lookup: Dict[int, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for stock in aggregated_stocks:
            nm_id = stock["nm_id"]
            barcode = stock["barcode"]
            card = cards_lookup.get(nm_id) or public_card_lookup.get(nm_id)
            price = prices_lookup.get(nm_id)
            funnel = funnel_lookup.get(nm_id)
            stocks_report_item = stocks_report_lookup.get(nm_id)
            measurement = warehouse_measurements_lookup.get(nm_id)
            matched_size = self._extract_card_match(card, barcode)
            funnel_product = (funnel or {}).get("product") or {}
            selected_stat = ((funnel or {}).get("statistic") or {}).get("selected") or {}
            stocks_report_metrics = (stocks_report_item or {}).get("metrics") or {}
            current_price = stocks_report_metrics.get("currentPrice") or {}
            photo_urls = self._extract_photo_urls(card, stocks_report_item)
            main_photo = self._first_non_empty(
                photo_urls[0] if photo_urls else None,
                self._strip((stocks_report_item or {}).get("mainPhoto")),
            )
            dimensions = (
                (card or {}).get("dimensions")
                or self._extract_measurement_dimensions(measurement)
                or {}
            )

            row = {
                "snapshot_date": stock["snapshot_date"],
                "nm_id": nm_id,
                "barcode": barcode,
                "imt_id": self._first_non_empty((card or {}).get("imtID"), (card or {}).get("imtId")),
                "chrt_id": self._first_non_empty(matched_size.get("chrtID"), matched_size.get("chrtId")),
                "tech_size": self._first_non_empty(stock.get("tech_size"), matched_size.get("techSize"), matched_size.get("techSizeName")),
                "vendor_code": self._first_non_empty(
                    (card or {}).get("vendorCode"),
                    (price or {}).get("vendorCode"),
                    funnel_product.get("vendorCode"),
                ),
                "supplier_article": stock.get("supplier_article"),
                "brand": self._first_non_empty(
                    stock.get("brand"),
                    (card or {}).get("brand"),
                    funnel_product.get("brandName"),
                    (stocks_report_item or {}).get("brandName"),
                ),
                "subject_name": self._first_non_empty(
                    stock.get("subject_name"),
                    (card or {}).get("subjectName"),
                    funnel_product.get("subjectName"),
                    (stocks_report_item or {}).get("subjectName"),
                ),
                "title": self._first_non_empty(
                    (card or {}).get("title"),
                    funnel_product.get("title"),
                    (stocks_report_item or {}).get("name"),
                ),
                "description": (card or {}).get("description"),
                "need_kiz": (card or {}).get("needKiz"),
                "last_change_date": stock.get("last_change_date"),
                "total_quantity": stock.get("total_quantity", 0),
                "total_in_way_to_client": stock.get("total_in_way_to_client", 0),
                "total_in_way_from_client": stock.get("total_in_way_from_client", 0),
                "total_quantity_full": stock.get("total_quantity_full", 0),
                "warehouse_count": stock.get("warehouse_count", 0),
                "warehouse_names": stock.get("warehouse_names"),
                "warehouses_json": stock.get("warehouses_json"),
                "product_url": self._product_url(nm_id),
                "main_photo_url": main_photo,
                "photo_urls": photo_urls,
                "video_url": self._strip((card or {}).get("video")),
                "length_cm": self._parse_numeric(dimensions.get("length")),
                "width_cm": self._parse_numeric(dimensions.get("width")),
                "height_cm": self._parse_numeric(dimensions.get("height")),
                "weight_brutto_kg": self._parse_numeric(
                    self._first_non_empty(
                        dimensions.get("weightBrutto"),
                        dimensions.get("weight"),
                    )
                ),
                "dimensions_json": dimensions or None,
                "characteristics_json": (card or {}).get("characteristics"),
                "sizes_json": (card or {}).get("sizes"),
                "tags_json": self._first_non_empty((card or {}).get("tags"), funnel_product.get("tags")),
                "price": self._first_non_empty(
                    (price or {}).get("price"),
                    ((price or {}).get("sizes") or [{}])[0].get("price") if (price or {}).get("sizes") else None,
                ),
                "discounted_price": self._first_non_empty(
                    (price or {}).get("discountedPrice"),
                    ((price or {}).get("sizes") or [{}])[0].get("discountedPrice") if (price or {}).get("sizes") else None,
                ),
                "club_discounted_price": self._first_non_empty(
                    (price or {}).get("clubDiscountedPrice"),
                    ((price or {}).get("sizes") or [{}])[0].get("clubDiscountedPrice") if (price or {}).get("sizes") else None,
                ),
                "discount": (price or {}).get("discount"),
                "club_discount": (price or {}).get("clubDiscount"),
                "currency_code": self._first_non_empty((price or {}).get("currencyIsoCode4217"), (funnel or {}).get("currency")),
                "price_sizes_json": (price or {}).get("sizes"),
                "analytics_main_photo_url": self._strip((stocks_report_item or {}).get("mainPhoto")),
                "analytics_availability": stocks_report_metrics.get("availability"),
                "analytics_stock_count": stocks_report_metrics.get("stockCount"),
                "analytics_stock_sum": stocks_report_metrics.get("stockSum"),
                "analytics_current_price_min": current_price.get("minPrice"),
                "analytics_current_price_max": current_price.get("maxPrice"),
                "analytics_orders_count": self._first_non_empty(stocks_report_metrics.get("ordersCount"), selected_stat.get("orderCount")),
                "analytics_orders_sum": self._first_non_empty(stocks_report_metrics.get("ordersSum"), selected_stat.get("orderSum")),
                "analytics_buyout_count": self._first_non_empty(stocks_report_metrics.get("buyoutCount"), selected_stat.get("buyoutCount")),
                "analytics_buyout_sum": self._first_non_empty(stocks_report_metrics.get("buyoutSum"), selected_stat.get("buyoutSum")),
                "analytics_buyout_percent": self._first_non_empty(stocks_report_metrics.get("buyoutPercent"), (selected_stat.get("conversions") or {}).get("buyoutPercent")),
                "analytics_open_count": selected_stat.get("openCount"),
                "analytics_cart_count": selected_stat.get("cartCount"),
                "analytics_add_to_wishlist": selected_stat.get("addToWishlist"),
                "analytics_avg_price": self._first_non_empty(stocks_report_metrics.get("avgPrice"), selected_stat.get("avgPrice")),
                "analytics_avg_orders_per_day": self._first_non_empty(stocks_report_metrics.get("avgOrders"), selected_stat.get("avgOrdersCountPerDay")),
                "analytics_to_client_count": self._first_non_empty(stocks_report_metrics.get("toClientCount"), stock.get("total_in_way_to_client")),
                "analytics_from_client_count": self._first_non_empty(stocks_report_metrics.get("fromClientCount"), stock.get("total_in_way_from_client")),
                "analytics_sale_rate_days": (stocks_report_metrics.get("saleRate") or {}).get("days"),
                "analytics_sale_rate_hours": (stocks_report_metrics.get("saleRate") or {}).get("hours"),
                "product_rating": self._first_non_empty(funnel_product.get("productRating"), (card or {}).get("rating")),
                "feedback_rating": funnel_product.get("feedbackRating"),
                "card_json": card,
                "price_json": price,
                "funnel_json": funnel,
                "stocks_report_json": stocks_report_item,
            }
            rows.append(row)
        return rows

    def save_to_json(self, rows: List[Dict[str, Any]], snapshot_date: date) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"wb_sku_ai_analysis_{snapshot_date.isoformat()}_{ts}.json",
        )
        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "snapshot_date": snapshot_date.isoformat(),
                    "total_items": len(rows),
                    "generated_at": datetime.now().isoformat(),
                    "data": rows,
                },
                file,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        logger.info("Сохранён JSON результат: %s", path)
        return path

    def _safe_fetch(self, label: str, fetch_callable, *args):
        try:
            return fetch_callable(*args)
        except Exception as exc:
            logger.warning("%s недоступен, продолжаю с частичными данными: %s", label, exc)
            return {}

    def run(self) -> Dict[str, Any]:
        snapshot_date = date.today()
        self.db.connect()
        try:
            self.db.create_tables()
            raw_stocks = self.fetch_stocks_snapshot()
            aggregated_stocks = self.aggregate_stocks(raw_stocks, snapshot_date)
            nm_ids = sorted({item["nm_id"] for item in aggregated_stocks})

            cards_lookup = self._safe_fetch("content cards", self.fetch_cards_lookup, aggregated_stocks)
            prices_lookup = self._safe_fetch("prices", self.fetch_prices_lookup)
            funnel_lookup = self._safe_fetch("sales funnel", self.fetch_funnel_lookup, nm_ids, snapshot_date)
            stocks_report_lookup = self._safe_fetch(
                "stocks report products",
                self.fetch_stocks_report_lookup,
                nm_ids,
                snapshot_date,
            )
            missing_card_nm_ids = sorted(
                nm_id for nm_id in nm_ids if nm_id not in (cards_lookup if isinstance(cards_lookup, dict) else {})
            )
            warehouse_measurements_lookup = self._safe_fetch(
                "warehouse measurements",
                self.fetch_warehouse_measurements_lookup,
                missing_card_nm_ids,
                snapshot_date,
            )
            public_card_lookup = self._safe_fetch(
                "public card lookup",
                self._fetch_public_card_lookup,
                missing_card_nm_ids,
            )

            rows = self.build_rows(
                aggregated_stocks,
                cards_lookup if isinstance(cards_lookup, dict) else {},
                prices_lookup if isinstance(prices_lookup, dict) else {},
                funnel_lookup if isinstance(funnel_lookup, dict) else {},
                stocks_report_lookup if isinstance(stocks_report_lookup, dict) else {},
                warehouse_measurements_lookup if isinstance(warehouse_measurements_lookup, dict) else {},
                public_card_lookup if isinstance(public_card_lookup, dict) else {},
            )
            json_path = self.save_to_json(rows, snapshot_date)
            written_rows = self.db.upsert_rows(rows)
            calc_sync = None
            if written_rows > 0:
                calc_sync = self.db.sync_profit_calculator_from_sku_snapshot()
            return {
                "snapshot_date": snapshot_date.isoformat(),
                "rows": written_rows,
                "json_path": json_path,
                "profit_calculator_sync": calc_sync,
            }
        finally:
            self.db.close()


def run_fetcher() -> Dict[str, Any]:
    fetcher = WBSkuAIAnalysisFetcher()
    return fetcher.run()


def main() -> None:
    result = run_fetcher()
    logger.info("wb_sku_ai_analysis завершён: %s", result)


if __name__ == "__main__":
    main()
