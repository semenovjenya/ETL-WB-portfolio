"""Parse prices from WB product URLs using WB public card detail endpoint."""
import json
import logging
import os
import re
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import requests

from config import Config
from database import WBSkuAIAnalysisDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

NM_ID_RE = re.compile(r"/catalog/(\d+)/detail\.aspx")


def _money_from_u(value: Any) -> Optional[float]:
    if value is None:
        return None
    amount = (Decimal(str(value)) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(amount)


class WBLinkPriceParser:
    """Updates latest SKU snapshot with prices fetched from WB product URLs."""

    def __init__(self) -> None:
        Config.validate()
        self.db = WBSkuAIAnalysisDatabase()
        self.session = requests.Session()
        self._last_request_ts: Optional[float] = None
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        }

    def _wait(self) -> None:
        if self._last_request_ts is None:
            return
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < Config.REQUEST_INTERVAL_WB_LINKS:
            time.sleep(Config.REQUEST_INTERVAL_WB_LINKS - elapsed)

    def _request_batch(self, nm_ids: List[int]) -> Dict[str, Any]:
        params = {
            "appType": 1,
            "curr": "rub",
            "dest": -1257786,
            "spp": 0,
            "nm": ";".join(str(nm_id) for nm_id in nm_ids),
        }
        for attempt in range(Config.RETRY_COUNT):
            self._wait()
            try:
                response = self.session.get(
                    Config.WB_LINK_CARD_DETAIL_URL,
                    params=params,
                    headers=self._headers(),
                    timeout=60,
                )
                self._last_request_ts = time.monotonic()
                if response.status_code == 429:
                    wait = max(Config.RETRY_DELAY_429, (attempt + 1) * Config.RETRY_DELAY * 2)
                    logger.warning("429 при чтении цен WB links, ожидание %s сек", wait)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "Ошибка запроса цен WB links, попытка %s/%s: %s",
                    attempt + 1,
                    Config.RETRY_COUNT,
                    exc,
                )
                if attempt == Config.RETRY_COUNT - 1:
                    raise
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        raise RuntimeError("Не удалось получить цены по WB links")

    @staticmethod
    def _chunked(values: List[int], size: int) -> Iterable[List[int]]:
        for index in range(0, len(values), size):
            yield values[index : index + size]

    @staticmethod
    def extract_nm_id(product_url: Optional[str]) -> Optional[int]:
        if not product_url:
            return None
        path = urlparse(product_url).path
        match = NM_ID_RE.search(path)
        if not match:
            return None
        return int(match.group(1))

    @staticmethod
    def _match_size(product: Dict[str, Any], tech_size: Optional[str]) -> Dict[str, Any]:
        sizes = product.get("sizes") or []
        if not sizes:
            return {}
        if tech_size is not None:
            tech_size_str = str(tech_size).strip()
            for size in sizes:
                candidates = [str(size.get("origName") or "").strip(), str(size.get("name") or "").strip()]
                if tech_size_str in candidates:
                    return size
        return sizes[0]

    @staticmethod
    def _build_row(snapshot_date, nm_id: int, barcode: str, size: Dict[str, Any], product: Dict[str, Any]) -> Dict[str, Any]:
        price = size.get("price") or {}
        regular_price = _money_from_u(price.get("basic"))
        promo_price = _money_from_u(price.get("product"))
        is_promo = bool(product.get("promotions")) or (
            regular_price is not None and promo_price is not None and promo_price < regular_price
        )
        discount_percent = None
        if regular_price and promo_price is not None and regular_price > 0:
            discount_percent = float(
                ((Decimal(str(regular_price)) - Decimal(str(promo_price))) / Decimal(str(regular_price)) * Decimal("100"))
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
        return {
            "snapshot_date": snapshot_date,
            "nm_id": nm_id,
            "barcode": barcode,
            "wb_link_price_regular": regular_price,
            "wb_link_price_promo": promo_price,
            "wb_link_discount_percent": discount_percent,
            "wb_link_is_promo": is_promo,
            "wb_link_panel_promo_id": product.get("panelPromoId"),
            "wb_link_promotions_json": product.get("promotions") or [],
            "wb_link_sale_conditions": size.get("saleConditions"),
            "wb_link_price_payload_json": {
                "source": "https://card.wb.ru/cards/v4/detail",
                "product": {
                    "id": product.get("id"),
                    "panelPromoId": product.get("panelPromoId"),
                    "promotions": product.get("promotions"),
                },
                "size": size,
            },
        }

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        except Exception:
            return None

    @classmethod
    def _build_fallback_row(cls, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        regular_price = cls._number(row.get("price"))
        promo_price = cls._number(
            row.get("club_discounted_price")
            if row.get("club_discounted_price") is not None
            else row.get("discounted_price")
        )
        if promo_price is None:
            promo_price = cls._number(row.get("discounted_price"))
        if promo_price is None:
            promo_price = regular_price
        if regular_price is None:
            regular_price = promo_price
        if regular_price is None or promo_price is None:
            return None

        discount_percent = None
        if regular_price > 0:
            discount_percent = float(
                ((Decimal(str(regular_price)) - Decimal(str(promo_price))) / Decimal(str(regular_price)) * Decimal("100"))
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
        elif row.get("discount") is not None:
            discount_percent = cls._number(row.get("discount"))

        return {
            "snapshot_date": row["snapshot_date"],
            "nm_id": int(row["nm_id"]),
            "barcode": row["barcode"],
            "wb_link_price_regular": regular_price,
            "wb_link_price_promo": promo_price,
            "wb_link_discount_percent": discount_percent,
            "wb_link_is_promo": bool(discount_percent and discount_percent > 0),
            "wb_link_panel_promo_id": None,
            "wb_link_promotions_json": [],
            "wb_link_sale_conditions": None,
            "wb_link_price_payload_json": {
                "source": "discounts-prices-api fallback",
                "reason": "card.wb.ru detail endpoint unavailable",
                "price": cls._number(row.get("price")),
                "discounted_price": cls._number(row.get("discounted_price")),
                "club_discounted_price": cls._number(row.get("club_discounted_price")),
                "discount": cls._number(row.get("discount")),
                "club_discount": cls._number(row.get("club_discount")),
                "price_json": row.get("price_json"),
            },
        }

    def _build_fallback_rows(self, source_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = []
        for row in source_rows:
            fallback_row = self._build_fallback_row(row)
            if fallback_row:
                rows.append(fallback_row)
        return rows

    def save_to_json(self, rows: List[Dict[str, Any]]) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(Config.JSON_OUTPUT_DIR, f"wb_link_prices_{ts}.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "generated_at": datetime.now().isoformat(),
                    "total_items": len(rows),
                    "data": rows,
                },
                file,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        logger.info("Сохранён JSON цен по WB ссылкам: %s", path)
        return path

    def run(self) -> Dict[str, Any]:
        self.db.connect()
        try:
            self.db.create_tables()
            source_rows = self.db.get_latest_snapshot_rows()
            nm_ids = sorted({self.extract_nm_id(row.get("product_url")) for row in source_rows if self.extract_nm_id(row.get("product_url"))})
            if not nm_ids:
                logger.info("Нет product_url для парсинга цен")
                return {"rows": 0, "json_path": None}

            product_lookup: Dict[int, Dict[str, Any]] = {}
            for batch in self._chunked(nm_ids, Config.WB_LINK_BATCH_SIZE):
                try:
                    data = self._request_batch(batch)
                except requests.exceptions.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response is not None else None
                    if status_code == 403:
                        logger.warning(
                            "WB card detail endpoint вернул 403; используем fallback из seller prices API"
                        )
                        fallback_rows = self._build_fallback_rows(source_rows)
                        json_path = self.save_to_json(fallback_rows)
                        updated_rows = self.db.update_link_prices(fallback_rows)
                        return {
                            "rows": updated_rows,
                            "json_path": json_path,
                            "source": "discounts-prices-api fallback",
                        }
                    raise
                for product in data.get("products") or []:
                    product_id = product.get("id")
                    if product_id is not None:
                        product_lookup[int(product_id)] = product

            result_rows: List[Dict[str, Any]] = []
            for row in source_rows:
                nm_id = self.extract_nm_id(row.get("product_url"))
                if nm_id is None:
                    continue
                product = product_lookup.get(nm_id)
                if not product:
                    continue
                size = self._match_size(product, row.get("tech_size"))
                if not size:
                    continue
                result_rows.append(
                    self._build_row(
                        row["snapshot_date"],
                        nm_id,
                        row["barcode"],
                        size,
                        product,
                    )
                )
            if len(result_rows) < len(source_rows):
                existing_keys = {
                    (item["snapshot_date"], int(item["nm_id"]), item["barcode"])
                    for item in result_rows
                }
                fallback_rows = [
                    item
                    for item in self._build_fallback_rows(source_rows)
                    if (item["snapshot_date"], int(item["nm_id"]), item["barcode"]) not in existing_keys
                ]
                if fallback_rows:
                    logger.info("Добавляем fallback-цены для строк без ответа card detail: %s", len(fallback_rows))
                    result_rows.extend(fallback_rows)

            json_path = self.save_to_json(result_rows)
            updated_rows = self.db.update_link_prices(result_rows)
            return {"rows": updated_rows, "json_path": json_path}
        finally:
            self.db.close()


def run_parser() -> Dict[str, Any]:
    parser = WBLinkPriceParser()
    return parser.run()


def main() -> None:
    result = run_parser()
    logger.info("Парсер цен по WB ссылкам завершён: %s", result)


if __name__ == "__main__":
    main()
