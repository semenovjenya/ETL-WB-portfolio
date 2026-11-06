"""Find WB competitors for source SKUs using browser-first Playwright search."""
import argparse
import json
import logging
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote, urlencode

import requests

from config import Config
from database import WBSkuAIAnalysisDatabase
try:
    from openai import OpenAI
except Exception:  # pragma: no cover - handled at runtime
    OpenAI = None

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - handled at runtime
    PlaywrightError = RuntimeError
    PlaywrightTimeoutError = RuntimeError
    sync_playwright = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SPACE_RE = re.compile(r"\s+")
COLOR_SPLIT_RE = re.compile(r"[/,;|]+")
NM_ID_IN_URL_RE = re.compile(r"/catalog/(\d+)/detail\.aspx")
JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
WB_SEARCH_HOME_URL = "https://www.wildberries.ru/"
WB_SEARCH_HTML_URL = "https://www.wildberries.ru/catalog/0/search.aspx"
SEARCH_INPUT_SELECTORS = [
    "input[name='search']",
    "input[type='search']",
    "input[placeholder*='Поиск']",
    "input[placeholder*='Найти']",
    ".search-catalog__input",
    ".search-block__input",
]
SEARCH_RESULT_CARD_SELECTORS = [
    "[data-card-index]",
    ".product-card",
    ".product-card__wrapper",
    "[class*='product-card']",
]
ANTIBOT_TEXT_MARKERS = (
    "Подозрительная активность",
    "Почти готово",
    "Что-то не так",
)
DOM_PRODUCTS_EXTRACTOR_JS = """
() => {
  const parseMoney = (text) => {
    if (!text) return null;
    const normalized = String(text).replace(/\\s+/g, ' ').replace(/,/g, '.');
    const match = normalized.match(/(\\d[\\d\\s.]*)/);
    if (!match) return null;
    const value = Number(match[1].replace(/\\s+/g, '').replace(/\\.(?=.*\\.)/g, ''));
    if (!Number.isFinite(value) || value <= 0) return null;
    return Math.round(value * 100);
  };
  const firstText = (root, selectors) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      if (node && node.textContent && node.textContent.trim()) {
        return node.textContent.trim();
      }
    }
    return '';
  };
  const parseCount = (text) => {
    if (!text) return 0;
    const match = String(text).replace(/\\s+/g, ' ').match(/(\\d[\\d\\s]*)/);
    if (!match) return 0;
    return Number(match[1].replace(/\\s+/g, '')) || 0;
  };
  const parseFloatValue = (text) => {
    if (!text) return null;
    const match = String(text).replace(/\\s+/g, ' ').replace(',', '.').match(/(\\d+(?:\\.\\d+)?)/);
    if (!match) return null;
    const value = Number(match[1]);
    return Number.isFinite(value) ? value : null;
  };
  const firstImageUrl = (root) => {
    const node = root.querySelector('img');
    if (!node) return '';
    const srcset = node.getAttribute('srcset') || '';
    if (srcset.trim()) {
      const first = srcset.split(',')[0].trim().split(' ')[0];
      if (first) return first;
    }
    return (
      node.currentSrc ||
      node.getAttribute('src') ||
      node.getAttribute('data-src') ||
      node.getAttribute('data-original') ||
      ''
    );
  };
  const cards = Array.from(document.querySelectorAll('article.product-card[data-nm-id]'));
  const results = [];
  for (const card of cards) {
    const id = Number(card.getAttribute('data-nm-id'));
    if (!id) continue;
    const anchor = card.querySelector('a[href*="/catalog/"][href*="/detail.aspx"]');
    const href = (anchor && (anchor.href || anchor.getAttribute('href'))) || '';
    const title = firstText(card, [
      'span.product-card__name',
      '[class*="product-card__name"]',
      '[class*="product-card__title"]',
      '[class*="goods-name"]',
    ]).replace(/^\\//, '').trim();
    const brand = firstText(card, [
      'span.product-card__brand',
      '[class*="product-card__brand"]',
      '[class*="brand-name"]',
      '[class*="brand"]',
    ]);
    let promoPrice = parseMoney(firstText(card, [
      'ins.price__lower-price',
      'ins',
      '[class*="final-price"]',
      '[class*="finalPrice"]',
      '[class*="lower-price"]',
      '[class*="sale-price"]',
      '[class*="price"]',
    ]));
    const regularPrice = parseMoney(firstText(card, [
      'del',
      '[class*="upper-price"]',
      '[class*="old-price"]',
      '[class*="list-price"]',
    ]));
    const rating = parseFloatValue(firstText(card, [
      'span.address-rate-mini',
      '[class*="address-rate-mini"]',
      '[class*="rating"]',
    ]));
    const feedbacks = parseCount(firstText(card, [
      'span.product-card__count',
      '[class*="product-card__count"]',
      '[class*="feedback"]',
    ]));
    const cardText = String(card.textContent || '').toLowerCase();
    const sponsoredNode = card.querySelector(
      '[class*="advert"], [class*="promo"], [data-tag="advertising"], [aria-label*="Реклама"]'
    );
    const isSponsored = Boolean(sponsoredNode) || /(^|\s)реклама(\s|$)/i.test(cardText);
    const walletPrice = parseMoney(firstText(card, [
      '[class*="wallet-price"]',
      '[class*="walletPrice"]',
      '[class*="club-price"]',
    ]));
    // WB can render both the ordinary buyer price and the lower Wallet price
    // inside the same card. If the first generic <ins> is the Wallet price,
    // recover the next distinct price below the crossed-out regular price.
    if (walletPrice && promoPrice === walletPrice) {
      const priceCandidates = Array.from(card.querySelectorAll(
        'ins, [class*="price"], [class*="Price"]'
      ))
        .map((node) => parseMoney(node.textContent || ''))
        .filter((value) => value && value > walletPrice && (!regularPrice || value < regularPrice));
      if (priceCandidates.length) promoPrice = Math.min(...priceCandidates);
    }
    const promoLabel = firstText(card, [
      '[class*="promo"]',
      '[class*="badge"]',
      '[class*="label"]',
    ]);
    const imageUrl = firstImageUrl(card);
    results.push({
      id,
      name: title,
      brand,
      priceU: regularPrice,
      salePriceU: promoPrice || regularPrice,
      displayPriceU: promoPrice || regularPrice,
      url: href,
      imageUrl,
      rating,
      feedbacks,
      isSponsored,
      walletPriceU: walletPrice,
      promoLabel,
    });
  }
  return results;
}
"""

PRODUCT_DETAIL_PRICES_EXTRACTOR_JS = r"""
() => {
  const parseMoney = (text) => {
    if (!text) return null;
    const normalized = String(text).replace(/\s+/g, ' ').replace(/,/g, '.');
    const match = normalized.match(/(\d[\d\s.]*)/);
    if (!match) return null;
    const value = Number(match[1].replace(/\s+/g, '').replace(/\.(?=.*\.)/g, ''));
    if (!Number.isFinite(value) || value <= 0) return null;
    return Math.round(value * 100);
  };
  const read = (selectors) => {
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (node && node.textContent && node.textContent.trim()) {
        return {valueU: parseMoney(node.textContent), text: node.textContent.trim(), selector};
      }
    }
    return {valueU: null, text: null, selector: null};
  };
  const regular = read([
    '[class*="priceBlockOldPrice"]',
    '[class*="oldPrice"]',
    '[class*="old-price"]',
    'del',
  ]);
  const display = read([
    '[class*="priceBlockFinalPrice"]',
    '[class*="finalPrice"]',
    '[class*="final-price"]',
  ]);
  const wallet = read([
    '[class*="priceBlockWalletPrice"]',
    '[class*="walletPrice"]',
    '[class*="wallet-price"]',
    '[class*="clubPrice"]',
  ]);
  return {
    regularPriceU: regular.valueU,
    displayPriceU: display.valueU,
    walletPriceU: wallet.valueU,
    evidence: {regular, display, wallet},
  };
}
"""

COLOR_ALIASES = {
    "white": ("бел", "white", "ivory", "айвори", "слоновая кость"),
    "black": ("черн", "black"),
    "gray": ("сер", "gray", "grey", "графит", "антрацит"),
    "beige": ("беж", "cream", "крем", "молочн"),
    "brown": ("корич", "brown", "шоколад"),
    "pink": ("роз", "pink"),
    "blue": ("син", "голуб", "blue"),
    "green": ("зелен", "green", "олив"),
    "red": ("красн", "red", "бордо"),
    "yellow": ("желт", "yellow", "gold", "золот"),
    "orange": ("оранж", "orange"),
    "purple": ("фиолет", "purple", "сирен", "lilac"),
    "wood_oak": ("дуб", "oak", "сонома"),
    "wood_alder": ("ольха", "alder"),
    "wood_wenge": ("венге", "wenge"),
    "wood_walnut": ("орех", "walnut"),
    "wood_natural": ("натурал", "natural", "сосна"),
    "wood_lacquer": ("лак", "лакирован"),
    "platinum": ("платин", "platinum"),
    "onyx": ("оникс", "onix", "onyx"),
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return SPACE_RE.sub(" ", str(value).strip().lower())


def normalize_display_text(value: Any) -> str:
    if value is None:
        return ""
    return SPACE_RE.sub(" ", str(value).strip())


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def decimal_to_float(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    return float(_quantize(value))


def money_from_u(value: Any) -> Optional[Decimal]:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return None
    return _quantize(decimal_value / Decimal("100"))


def parse_search_money(value: Any) -> Optional[Decimal]:
    """Parse WB fields ending in ``U``; their unit is always one kopeck."""
    return money_from_u(value)


def pick_source_prices(row: Dict[str, Any]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    regular = _to_decimal(row.get("wb_link_price_regular"))
    promo = _to_decimal(row.get("wb_link_price_promo"))
    if regular is not None:
        regular = _quantize(regular)
    if promo is not None:
        promo = _quantize(promo)
    return regular, promo


def build_short_description(title: Optional[str], brand: Optional[str], subject_name: Optional[str]) -> str:
    safe_title = (title or "").strip() or "Товар WB"
    parts = [safe_title.rstrip(".")]
    if brand:
        parts.append(f"Бренд: {str(brand).strip()}.")
    if subject_name:
        parts.append(f"Категория: {str(subject_name).strip()}.")
    return " ".join(parts).strip()


def extract_bed_type(value: Any) -> Optional[str]:
    text = normalize_text(value)
    if not text:
        return None
    if "односпал" in text:
        return "single"
    if "двуспал" in text:
        return "double"
    if "полутор" in text or "полутора" in text:
        return "semi-double"
    return None


def _collect_color_labels(raw_values: Sequence[Any]) -> List[str]:
    seen: Set[str] = set()
    labels: List[str] = []
    for raw_value in raw_values:
        raw_text = normalize_display_text(raw_value)
        if not raw_text:
            continue
        parts = [raw_text]
        parts.extend(part.strip() for part in COLOR_SPLIT_RE.split(raw_text) if part.strip())
        for part in parts:
            dedupe_key = normalize_text(part)
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            labels.append(part)
    return labels


def _extract_color_keys(color_labels: Sequence[str]) -> Set[str]:
    keys: Set[str] = set()
    for label in color_labels:
        normalized = normalize_text(label)
        if not normalized:
            continue
        for color_key, aliases in COLOR_ALIASES.items():
            if any(alias in normalized for alias in aliases):
                keys.add(color_key)
    return keys


def extract_colors_from_characteristics(characteristics: Any) -> List[str]:
    raw_values: List[Any] = []
    if not isinstance(characteristics, list):
        return []
    for item in characteristics:
        if not isinstance(item, dict):
            continue
        name = normalize_text(item.get("name"))
        if "цвет" not in name:
            continue
        value = item.get("value")
        if isinstance(value, list):
            raw_values.extend(value)
        elif value not in (None, ""):
            raw_values.append(value)
    return _collect_color_labels(raw_values)


def extract_source_colors(source_row: Dict[str, Any]) -> List[str]:
    colors = extract_colors_from_characteristics(source_row.get("characteristics_json"))
    if colors:
        return colors
    card = source_row.get("card_json")
    if isinstance(card, dict):
        colors = extract_colors_from_characteristics(card.get("characteristics"))
        if colors:
            return colors
    return []


def extract_detail_colors(product: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(product, dict):
        return []
    raw_values: List[Any] = []
    colors = product.get("colors")
    if isinstance(colors, list):
        for item in colors:
            if isinstance(item, dict):
                raw_values.append(item.get("name"))
            elif item not in (None, ""):
                raw_values.append(item)
    if not raw_values and product.get("characteristics"):
        return extract_colors_from_characteristics(product.get("characteristics"))
    return _collect_color_labels(raw_values)


def match_color_sets(source_colors: Sequence[str], competitor_colors: Sequence[str]) -> Optional[bool]:
    source_keys = _extract_color_keys(source_colors)
    competitor_keys = _extract_color_keys(competitor_colors)
    if not source_keys or not competitor_keys:
        return None
    return bool(source_keys & competitor_keys)


def calculate_discount_percent(regular: Optional[Decimal], promo: Optional[Decimal]) -> Optional[Decimal]:
    if regular is None or promo is None or regular <= 0:
        return None
    return _quantize(((regular - promo) / regular) * Decimal("100"))


def calculate_price_window(source_price_promo: Decimal, segment_percent: float) -> Tuple[Decimal, Decimal]:
    factor = Decimal(str(segment_percent)) / Decimal("100")
    lower = _quantize(source_price_promo * (Decimal("1") - factor))
    upper = _quantize(source_price_promo * (Decimal("1") + factor))
    return lower, upper


def normalize_keywords(keywords: Sequence[Any]) -> List[str]:
    seen: Set[str] = set()
    normalized: List[str] = []
    for keyword in keywords:
        text = SPACE_RE.sub(" ", str(keyword or "").strip())
        if not text:
            continue
        dedupe_key = text.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(text)
    return normalized


def detect_product_placement(product: Dict[str, Any]) -> Tuple[str, str]:
    """Return placement type and the evidence used to classify it."""
    for key in ("isSponsored", "isAdvertised", "isAdvertising", "isAd"):
        if key not in product:
            continue
        value = _to_bool(product.get(key))
        if value is True:
            return "sponsored", key
        if value is False:
            return "organic", key
    placement = str(product.get("placementType") or product.get("placement_type") or "").strip().lower()
    if placement in {"advert", "advertising", "ad", "sponsored", "promo"}:
        return "sponsored", "placement_type"
    if placement in {"organic", "natural"}:
        return "organic", "placement_type"
    return "unknown", "unclassified"


def build_product_url(nm_id: int) -> str:
    return f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"


def normalize_image_url(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if normalized.startswith("//"):
        return f"https:{normalized}"
    return normalized


def _to_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def extract_json_object_from_text(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass
    match = JSON_OBJECT_RE.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def normalize_photo_ai_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not payload:
        return None
    is_competitor = _to_bool(payload.get("is_visual_competitor"))
    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None:
        confidence = max(0.0, min(1.0, confidence))
    return {
        "photo_ai_is_competitor": is_competitor,
        "photo_ai_confidence": confidence,
        "photo_ai_reason": str(payload.get("reason") or "").strip() or None,
        "photo_ai_model": str(payload.get("model") or "").strip() or None,
        "photo_ai_raw_json": payload,
    }


def extract_nm_id_from_url(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = NM_ID_IN_URL_RE.search(value)
    if not match:
        return None
    return int(match.group(1))


def extract_products_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    products = payload.get("products")
    if isinstance(products, list):
        return products
    data = payload.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("products"), list):
        return data["products"]
    return []


def merge_products_with_dom_details(
    products: Sequence[Dict[str, Any]],
    dom_products: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    dom_by_id: Dict[int, Dict[str, Any]] = {}
    for product in dom_products:
        product_id = product.get("id")
        if product_id is None:
            continue
        try:
            dom_by_id[int(product_id)] = product
        except (TypeError, ValueError):
            continue

    merged_products: List[Dict[str, Any]] = []
    for product in products:
        merged = dict(product)
        product_id = product.get("id") or extract_nm_id_from_url(product.get("url"))
        dom_match = None
        if product_id is not None:
            try:
                dom_match = dom_by_id.get(int(product_id))
            except (TypeError, ValueError):
                dom_match = None
        if dom_match:
            if dom_match.get("imageUrl") and not merged.get("imageUrl"):
                merged["imageUrl"] = dom_match.get("imageUrl")
            if dom_match.get("url") and not merged.get("url"):
                merged["url"] = dom_match.get("url")
            if dom_match.get("rating") not in (None, "") and merged.get("rating") in (None, ""):
                merged["rating"] = dom_match.get("rating")
            if dom_match.get("feedbacks") not in (None, "") and merged.get("feedbacks") in (None, ""):
                merged["feedbacks"] = dom_match.get("feedbacks")
            for field in ("isSponsored", "displayPriceU", "walletPriceU", "promoLabel"):
                if field in dom_match:
                    merged[field] = dom_match.get(field)
        merged_products.append(merged)
    return merged_products


def build_catalog_url_from_metadata(metadata: Dict[str, Any], page_number: int) -> Optional[str]:
    shard_key = metadata.get("shardKey")
    query = metadata.get("query")
    if not shard_key or not query:
        return None
    params = {
        "ab_testing": "false",
        "appType": "1",
        "curr": "rub",
        "dest": "-1257786",
        "lang": "ru",
        "page": str(page_number),
        "sort": "popular",
        "spp": "0",
    }
    return f"https://catalog.wb.ru/catalog/{shard_key}/catalog?{query}&{urlencode(params)}"


def select_top_competitor_ids(rows: List[Dict[str, Any]], limit: int) -> Set[int]:
    best_rows: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        competitor_nm_id = int(row["competitor_nm_id"])
        current = best_rows.get(competitor_nm_id)
        if current is None:
            best_rows[competitor_nm_id] = row
            continue
        candidate_key = (
            row["keyword_order"],
            row["catalog_position_absolute"] or 10**9,
            abs(row["price_delta_percent"] or 10**9),
            -(row["competitor_rating"] or 0),
            -(row["competitor_feedbacks"] or 0),
        )
        current_key = (
            current["keyword_order"],
            current["catalog_position_absolute"] or 10**9,
            abs(current["price_delta_percent"] or 10**9),
            -(current["competitor_rating"] or 0),
            -(current["competitor_feedbacks"] or 0),
        )
        if candidate_key < current_key:
            best_rows[competitor_nm_id] = row

    ordered = sorted(
        best_rows.values(),
        key=lambda item: (
            item["keyword_order"],
            item["catalog_position_absolute"] or 10**9,
            abs(item["price_delta_percent"] or 10**9),
            -(item["competitor_rating"] or 0),
            -(item["competitor_feedbacks"] or 0),
            item["competitor_nm_id"],
        ),
    )
    return {int(item["competitor_nm_id"]) for item in ordered[:limit]}


class WBCompetitorFetcher:
    """Searches WB competitors for source SKUs by keyword map."""

    def __init__(
        self,
        *,
        limit_per_sku: int,
        page_limit: int,
        dry_run: bool,
        photo_ai_filter_enabled: bool,
    ) -> None:
        self.limit_per_sku = limit_per_sku
        self.page_limit = page_limit
        self.dry_run = dry_run
        self.photo_ai_filter_enabled = photo_ai_filter_enabled
        self.db: Optional[WBSkuAIAnalysisDatabase] = None
        self.session = requests.Session()
        self._last_request_ts: Dict[str, float] = {}
        self._detail_cache: Dict[int, Optional[Dict[str, Any]]] = {}
        self._photo_ai_cache: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self._openai_client = None
        self._playwright = None
        self._browser_context = None
        self._browser_page = None
        self._browser_warmed_up = False
        self._browser_responses: List[Dict[str, Any]] = []
        self._browser_listener_attached = False
        self._last_search_stop_metadata: Dict[str, Any] = {}
        self._last_serp_scan_metadata: Dict[str, Any] = {}
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": Config.WB_BROWSER_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Origin": "https://www.wildberries.ru",
            "Referer": "https://www.wildberries.ru/",
        }

    def _wait_rate_limit(self, key: str, interval: float) -> None:
        last_ts = self._last_request_ts.get(key)
        if last_ts is None:
            return
        elapsed = time.monotonic() - last_ts
        if elapsed < interval:
            time.sleep(interval - elapsed)

    @staticmethod
    def _chunked(values: List[int], size: int) -> Iterable[List[int]]:
        for index in range(0, len(values), size):
            yield values[index : index + size]

    def _ensure_db(self) -> None:
        if self.db is not None:
            return
        Config.validate_db()
        self.db = WBSkuAIAnalysisDatabase()
        self.db.connect()

    def _ensure_browser(self) -> None:
        if self._browser_page is not None:
            return
        if sync_playwright is None:
            raise RuntimeError("Playwright не установлен. Установите пакет playwright и браузеры.")
        os.makedirs(Config.WB_BROWSER_PROFILE_DIR, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._browser_context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=Config.WB_BROWSER_PROFILE_DIR,
            headless=Config.WB_BROWSER_HEADLESS,
            viewport={
                "width": Config.WB_BROWSER_VIEWPORT_WIDTH,
                "height": Config.WB_BROWSER_VIEWPORT_HEIGHT,
            },
            locale="ru-RU",
            user_agent=Config.WB_BROWSER_USER_AGENT,
            slow_mo=Config.WB_BROWSER_SLOW_MO_MS,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        pages = self._browser_context.pages
        self._browser_page = pages[0] if pages else self._browser_context.new_page()
        if not self._browser_listener_attached:
            self._browser_page.on("response", self._handle_browser_response)
            self._browser_listener_attached = True

    def _ensure_openai_client(self) -> None:
        if self._openai_client is not None:
            return
        if OpenAI is None:
            raise RuntimeError("Пакет openai не установлен")
        if not Config.OPENAI_API_KEY:
            raise RuntimeError("Для AI-фильтра по фото нужен OPENAI_API_KEY")
        kwargs: Dict[str, Any] = {"api_key": Config.OPENAI_API_KEY}
        if Config.OPENAI_BASE_URL:
            kwargs["base_url"] = Config.OPENAI_BASE_URL
        self._openai_client = OpenAI(**kwargs)

    def _handle_browser_response(self, response: Any) -> None:
        url = response.url
        if "search.wb.ru" not in url and "catalog.wb.ru" not in url:
            return
        try:
            text = response.text()
        except Exception:
            return
        self._browser_responses.append(
            {
                "url": url,
                "status": response.status,
                "text": text,
            }
        )

    def _clear_browser_response_buffer(self) -> None:
        self._browser_responses = []

    def _safe_page_title(self, page: Any) -> str:
        try:
            return page.title()
        except PlaywrightError:
            return ""

    def _safe_body_text(self, page: Any) -> str:
        try:
            return page.locator("body").inner_text(timeout=5000)
        except PlaywrightError:
            return ""

    def _is_antibot_page(self, title: str, body_text: str) -> bool:
        haystack = f"{title}\n{body_text}"
        return any(marker in haystack for marker in ANTIBOT_TEXT_MARKERS)

    def _maybe_click(self, page: Any, selectors: Sequence[str]) -> None:
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=2000)
                locator.click(timeout=2000)
                return
            except PlaywrightError:
                continue

    def _warmup_browser(self) -> None:
        self._ensure_browser()
        if self._browser_warmed_up:
            return
        assert self._browser_page is not None
        self._browser_page.goto(WB_SEARCH_HOME_URL, wait_until="domcontentloaded", timeout=Config.WB_BROWSER_TIMEOUT_MS)
        self._browser_page.wait_for_timeout(Config.WB_BROWSER_POST_NAVIGATION_WAIT_MS)
        self._maybe_click(
            self._browser_page,
            [
                "button:has-text('Принять')",
                "button:has-text('Согласен')",
                "button:has-text('Понятно')",
            ],
        )
        self._browser_warmed_up = True

    def _fetch_source_detail_page_prices(self, nm_id: int) -> Dict[str, Any]:
        """Read buyer-facing price layers that WB omits from search cards."""
        try:
            self._warmup_browser()
            assert self._browser_page is not None
            self._browser_page.goto(
                build_product_url(int(nm_id)),
                wait_until="domcontentloaded",
                timeout=Config.WB_BROWSER_TIMEOUT_MS,
            )
            self._wait_for_search_page_ready(self._browser_page)
            extracted = self._browser_page.evaluate(PRODUCT_DETAIL_PRICES_EXTRACTOR_JS)
        except (PlaywrightError, RuntimeError) as exc:
            logger.warning("Не удалось прочитать цены карточки WB nm_id=%s: %s", nm_id, exc)
            return {}
        if not isinstance(extracted, dict):
            return {}
        return {
            "regular": parse_search_money(extracted.get("regularPriceU")),
            "display": parse_search_money(extracted.get("displayPriceU")),
            "wallet": parse_search_money(extracted.get("walletPriceU")),
            "evidence": extracted.get("evidence") if isinstance(extracted.get("evidence"), dict) else {},
        }

    def _find_search_input(self, page: Any) -> Any:
        for selector in SEARCH_INPUT_SELECTORS:
            locator = page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=3000)
                return locator
            except PlaywrightError:
                continue
        raise RuntimeError("Не удалось найти поисковую строку WB на странице")

    def _wait_for_search_page_ready(self, page: Any) -> None:
        page.wait_for_timeout(Config.WB_BROWSER_POST_NAVIGATION_WAIT_MS)
        deadline = time.monotonic() + (Config.WB_BROWSER_CHALLENGE_WAIT_MS / 1000)
        last_body = ""
        while time.monotonic() < deadline:
            title = self._safe_page_title(page)
            body_text = self._safe_body_text(page)
            last_body = body_text[:500]
            if not self._is_antibot_page(title, body_text):
                return
            page.wait_for_timeout(5000)
        raise RuntimeError(f"WB антибот не пропустил browser session: {last_body}")

    def _search_via_ui(self, page: Any, keyword: str) -> None:
        self._clear_browser_response_buffer()
        page.goto(WB_SEARCH_HOME_URL, wait_until="domcontentloaded", timeout=Config.WB_BROWSER_TIMEOUT_MS)
        page.wait_for_timeout(3000)
        try:
            search_input = self._find_search_input(page)
        except RuntimeError:
            page.goto(f"{WB_SEARCH_HTML_URL}?search={quote(keyword)}", wait_until="domcontentloaded", timeout=Config.WB_BROWSER_TIMEOUT_MS)
            self._wait_for_search_page_ready(page)
            return
        try:
            search_input.click(timeout=5000)
            search_input.press("Meta+A")
            search_input.press("Delete")
            search_input.type(keyword, delay=Config.WB_BROWSER_TYPING_DELAY_MS)
            search_input.press("Enter")
        except PlaywrightError:
            logger.warning("UI search input is blocked by overlay, fallback to browser search URL for keyword=%r", keyword)
            page.goto(f"{WB_SEARCH_HTML_URL}?search={quote(keyword)}", wait_until="domcontentloaded", timeout=Config.WB_BROWSER_TIMEOUT_MS)
            self._wait_for_search_page_ready(page)
            return
        try:
            page.wait_for_url("**/search.aspx?**", timeout=max(5000, Config.WB_BROWSER_TIMEOUT_MS // 2))
        except PlaywrightTimeoutError:
            pass
        if "/search.aspx" not in page.url:
            page.goto(f"{WB_SEARCH_HTML_URL}?search={quote(keyword)}", wait_until="domcontentloaded", timeout=Config.WB_BROWSER_TIMEOUT_MS)
        self._wait_for_search_page_ready(page)

    def _open_search_page(self, page: Any, keyword: str, page_number: int) -> None:
        if page_number == 1:
            self._search_via_ui(page, keyword)
            return
        self._clear_browser_response_buffer()
        url = f"{WB_SEARCH_HTML_URL}?search={quote(keyword)}&page={page_number}"
        page.goto(url, wait_until="domcontentloaded", timeout=Config.WB_BROWSER_TIMEOUT_MS)
        self._wait_for_search_page_ready(page)

    def _fetch_catalog_payload_from_metadata(self, page: Any, metadata: Dict[str, Any], page_number: int) -> Optional[Dict[str, Any]]:
        catalog_url = build_catalog_url_from_metadata(metadata, page_number)
        if not catalog_url:
            return None
        try:
            result = page.evaluate(
                """async ({url}) => {
                    const response = await fetch(url, {
                        credentials: 'include',
                        headers: {'Accept': 'application/json, text/plain, */*'}
                    });
                    return {
                        status: response.status,
                        text: await response.text(),
                    };
                }""",
                {"url": catalog_url},
            )
        except PlaywrightError as exc:
            logger.warning("Ошибка browser fetch catalog.wb.ru: %s", exc)
            return None
        if not isinstance(result, dict) or int(result.get("status") or 0) != 200:
            return None
        try:
            payload = json.loads(result.get("text") or "")
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _collect_products_from_browser(self, page: Any, page_number: int) -> List[Dict[str, Any]]:
        dom_products: List[Dict[str, Any]] = []
        if "/search.aspx" in page.url:
            try:
                extracted = page.evaluate(DOM_PRODUCTS_EXTRACTOR_JS)
            except PlaywrightError:
                extracted = []
            if isinstance(extracted, list):
                dom_products = extracted

        metadata_payloads: List[Dict[str, Any]] = []
        for item in self._browser_responses:
            try:
                payload = json.loads(item["text"])
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            products = extract_products_from_payload(payload)
            if products:
                return merge_products_with_dom_details(products, dom_products)
            if payload.get("shardKey") and payload.get("query"):
                metadata_payloads.append(payload)

        for metadata in metadata_payloads:
            payload = self._fetch_catalog_payload_from_metadata(page, metadata, page_number)
            if payload:
                products = extract_products_from_payload(payload)
                if products:
                    return merge_products_with_dom_details(products, dom_products)

        return dom_products

    def _normalize_browser_product(
        self,
        product: Dict[str, Any],
        page_number: int,
        index: int,
        absolute_position: int,
        organic_position: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        competitor_nm_id = product.get("id") or extract_nm_id_from_url(product.get("url"))
        if competitor_nm_id is None:
            return None
        competitor_nm_id = int(competitor_nm_id)
        placement_type, placement_detection = detect_product_placement(product)
        wallet_u = product.get("walletPriceU") or product.get("clubPriceU")
        wallet_price = parse_search_money(wallet_u)
        if wallet_price is None:
            wallet_price = _to_decimal(product.get("walletPrice") or product.get("clubPrice"))
        display_price = parse_search_money(product.get("displayPriceU") or product.get("salePriceU"))
        if display_price is None:
            display_price = _to_decimal(product.get("salePrice"))
        regular_price = parse_search_money(product.get("priceU"))
        if regular_price is None:
            regular_price = _to_decimal(product.get("price"))
        effective_price = wallet_price or display_price or regular_price
        if wallet_price is not None:
            price_basis = "wallet"
        elif display_price is not None:
            price_basis = "display"
        elif regular_price is not None:
            price_basis = "regular"
        else:
            price_basis = None
        return {
            "competitor_nm_id": competitor_nm_id,
            "competitor_brand": product.get("brand"),
            "competitor_subject_name": product.get("subjectName") or product.get("entity"),
            "competitor_title": product.get("name"),
            "competitor_price_regular_search": regular_price,
            "competitor_price_promo_search": display_price,
            "competitor_price_wallet_search": wallet_price,
            "competitor_price_effective_search": effective_price,
            "competitor_price_basis_search": price_basis,
            "competitor_promo_label": str(product.get("promoLabel") or "").strip() or None,
            "competitor_main_photo_url": normalize_image_url(product.get("imageUrl")),
            "competitor_rating": _to_decimal(product.get("rating")),
            "competitor_feedbacks": int(product.get("feedbacks") or 0),
            "catalog_page": page_number,
            "catalog_position_on_page": index,
            "catalog_position_absolute": absolute_position,
            "catalog_position_organic": organic_position,
            "placement_type": placement_type,
            "placement_detection": placement_detection,
            "search_payload_json": product,
        }

    def _scan_keyword(
        self,
        keyword: str,
        source_nm_id: Optional[int] = None,
        max_positions: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        self._warmup_browser()
        assert self._browser_page is not None
        source_id = int(source_nm_id) if source_nm_id is not None else None
        position_limit = max(int(max_positions or 0), 1) if max_positions else None
        metadata: Dict[str, Any] = {
            "keyword": keyword,
            "source_nm_id": source_id,
            "source_found_any": False,
            "source_found_organic": False,
            "source_found_sponsored": False,
            "source_position_absolute": None,
            "source_position_organic": None,
            "source_position_organic_absolute": None,
            "source_position_sponsored": None,
            "pages_scanned": 0,
            "max_position_scanned": 0,
            "organic_positions_scanned": 0,
            "complete_until_source": False,
            "hit_position_limit": False,
        }
        occurrences: List[Dict[str, Any]] = []
        absolute_position = 0
        organic_position = 0
        stop_scan = False
        for page_number in range(1, self.page_limit + 1):
            self._open_search_page(self._browser_page, keyword, page_number)
            products = self._collect_products_from_browser(self._browser_page, page_number)
            if not products:
                break
            metadata["pages_scanned"] = page_number
            for index, product in enumerate(products, start=1):
                if position_limit is not None and absolute_position >= position_limit:
                    metadata["hit_position_limit"] = True
                    stop_scan = True
                    break
                placement_type, _ = detect_product_placement(product)
                absolute_position += 1
                row_organic_position: Optional[int] = None
                if placement_type == "organic":
                    organic_position += 1
                    row_organic_position = organic_position
                occurrence = self._normalize_browser_product(
                    product,
                    page_number,
                    index,
                    absolute_position,
                    row_organic_position,
                )
                if not occurrence:
                    continue
                occurrences.append(occurrence)
                if source_id is not None and occurrence["competitor_nm_id"] == source_id:
                    metadata["source_found_any"] = True
                    if metadata["source_position_absolute"] is None:
                        metadata["source_position_absolute"] = occurrence["catalog_position_absolute"]
                    if occurrence["placement_type"] == "sponsored":
                        metadata["source_found_sponsored"] = True
                        if metadata["source_position_sponsored"] is None:
                            metadata["source_position_sponsored"] = occurrence["catalog_position_absolute"]
                    elif occurrence["placement_type"] == "organic":
                        metadata["source_found_organic"] = True
                        metadata["source_position_organic"] = occurrence["catalog_position_organic"]
                        metadata["source_position_organic_absolute"] = occurrence["catalog_position_absolute"]
                        metadata["complete_until_source"] = True
                        stop_scan = True
                        break
            if stop_scan:
                break
        metadata["max_position_scanned"] = absolute_position
        metadata["organic_positions_scanned"] = organic_position
        if position_limit is not None and absolute_position >= position_limit and not metadata["source_found_organic"]:
            metadata["hit_position_limit"] = True
        self._last_serp_scan_metadata = metadata
        return occurrences

    def _search_keyword(self, keyword: str, stop_nm_id: Optional[int] = None) -> List[Dict[str, Any]]:
        occurrences = self._scan_keyword(keyword, source_nm_id=stop_nm_id)
        stop_id = int(stop_nm_id) if stop_nm_id is not None else None
        best_hits: Dict[int, Dict[str, Any]] = {}
        for occurrence in occurrences:
            competitor_nm_id = int(occurrence["competitor_nm_id"])
            if stop_id is not None and competitor_nm_id == stop_id:
                continue
            current = best_hits.get(competitor_nm_id)
            if current is None or occurrence["catalog_position_absolute"] < current["catalog_position_absolute"]:
                best_hits[competitor_nm_id] = occurrence
        scan = self._last_serp_scan_metadata
        self._last_search_stop_metadata = {
            "keyword": keyword,
            "stop_nm_id": stop_id,
            "found": bool(scan.get("source_found_organic")),
            "catalog_page": next(
                (
                    item.get("catalog_page")
                    for item in occurrences
                    if stop_id is not None
                    and int(item["competitor_nm_id"]) == stop_id
                    and item.get("placement_type") == "organic"
                ),
                None,
            ),
            "catalog_position_on_page": next(
                (
                    item.get("catalog_position_on_page")
                    for item in occurrences
                    if stop_id is not None
                    and int(item["competitor_nm_id"]) == stop_id
                    and item.get("placement_type") == "organic"
                ),
                None,
            ),
            "catalog_position_absolute": next(
                (
                    item.get("catalog_position_absolute")
                    for item in occurrences
                    if stop_id is not None
                    and int(item["competitor_nm_id"]) == stop_id
                    and item.get("placement_type") == "organic"
                ),
                None,
            ),
        }
        return list(best_hits.values())

    def _request_detail_batch(self, nm_ids: List[int]) -> Dict[str, Any]:
        params = {
            "appType": 1,
            "curr": "rub",
            "dest": -1257786,
            "spp": 0,
            "nm": ";".join(str(nm_id) for nm_id in nm_ids),
        }
        for attempt in range(Config.RETRY_COUNT):
            self._wait_rate_limit("detail", Config.REQUEST_INTERVAL_WB_LINKS)
            try:
                response = self.session.get(
                    Config.WB_LINK_CARD_DETAIL_URL,
                    params=params,
                    headers=self._headers(),
                    timeout=60,
                )
                self._last_request_ts["detail"] = time.monotonic()
                if response.status_code == 429:
                    delay = max(Config.RETRY_DELAY_429, (attempt + 1) * Config.RETRY_DELAY * 2)
                    logger.warning("429 при чтении WB detail, ожидание %s сек", delay)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "Ошибка detail batch попытка %s/%s: %s",
                    attempt + 1,
                    Config.RETRY_COUNT,
                    exc,
                )
                if attempt == Config.RETRY_COUNT - 1:
                    raise
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        raise RuntimeError("Не удалось получить WB detail batch")

    def _fetch_detail_lookup(self, nm_ids: List[int]) -> Dict[int, Optional[Dict[str, Any]]]:
        missing = [nm_id for nm_id in nm_ids if nm_id not in self._detail_cache]
        for batch in self._chunked(missing, Config.WB_LINK_BATCH_SIZE):
            try:
                data = self._request_detail_batch(batch)
            except RuntimeError as exc:
                logger.warning("Не удалось получить detail batch %s: %s", batch, exc)
                for nm_id in batch:
                    self._detail_cache[nm_id] = None
                continue
            found_ids: Set[int] = set()
            for product in data.get("products") or []:
                product_id = product.get("id")
                if product_id is None:
                    continue
                found_ids.add(int(product_id))
                self._detail_cache[int(product_id)] = product
            for nm_id in batch:
                if nm_id not in found_ids:
                    self._detail_cache[nm_id] = None
        return {nm_id: self._detail_cache.get(nm_id) for nm_id in nm_ids}

    @staticmethod
    def _extract_detail_prices(product: Optional[Dict[str, Any]]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        if not product:
            return None, None
        regular_prices: List[Decimal] = []
        promo_prices: List[Decimal] = []
        for size in product.get("sizes") or []:
            price = size.get("price") or {}
            regular = money_from_u(price.get("basic"))
            promo = money_from_u(price.get("product"))
            if regular is not None:
                regular_prices.append(regular)
            if promo is not None:
                promo_prices.append(promo)
        return (min(regular_prices) if regular_prices else None, min(promo_prices) if promo_prices else None)

    def _evaluate_photo_competitor_match(
        self,
        *,
        source_nm_id: int,
        competitor_nm_id: int,
        source_title: Optional[str],
        competitor_title: Optional[str],
        source_photo_url: Optional[str],
        competitor_photo_url: Optional[str],
    ) -> Dict[str, Any]:
        cache_key = (source_nm_id, competitor_nm_id)
        cached = self._photo_ai_cache.get(cache_key)
        if cached is not None:
            return cached

        if not source_photo_url or not competitor_photo_url:
            result = {
                "photo_ai_is_competitor": None,
                "photo_ai_confidence": None,
                "photo_ai_reason": "Пропущено: отсутствует фото для сравнения.",
                "photo_ai_model": Config.WB_COMPETITOR_PHOTO_AI_MODEL,
                "photo_ai_raw_json": None,
            }
            self._photo_ai_cache[cache_key] = result
            return result

        self._ensure_openai_client()
        prompt = (
            "Сравни два фото товаров Wildberries. "
            "Нужно определить, можно ли считать второй товар реальным визуальным конкурентом первому. "
            "Смотри только на саму кровать, игнорируй декор, постельное белье, цвет стены и фон. "
            "Верни только JSON без markdown в формате: "
            "{\"is_visual_competitor\": true/false, "
            "\"confidence\": 0.0-1.0, "
            "\"reason\": \"короткая причина на русском\", "
            "\"model\": \"имя модели\"}. "
            "Ставь false, если это визуально другой тип мебели, другая конструкция кровати, "
            "другая вместимость/форм-фактор или явно другой сегмент изделия."
        )
        user_text = (
            f"Товар-источник: {source_title or 'без названия'}.\n"
            f"Кандидат-конкурент: {competitor_title or 'без названия'}.\n"
            "Ответ нужен только в JSON."
        )
        response = self._openai_client.responses.create(
            model=Config.WB_COMPETITOR_PHOTO_AI_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_text", "text": user_text},
                        {"type": "input_image", "image_url": source_photo_url},
                        {"type": "input_image", "image_url": competitor_photo_url},
                    ],
                }
            ],
            max_output_tokens=Config.WB_COMPETITOR_PHOTO_AI_MAX_OUTPUT_TOKENS,
            timeout=Config.WB_COMPETITOR_PHOTO_AI_TIMEOUT_SEC,
        )
        payload = normalize_photo_ai_payload(extract_json_object_from_text(response.output_text))
        if payload is None:
            payload = {
                "photo_ai_is_competitor": None,
                "photo_ai_confidence": None,
                "photo_ai_reason": "OpenAI вернул ответ, который не удалось распарсить как JSON.",
                "photo_ai_model": Config.WB_COMPETITOR_PHOTO_AI_MODEL,
                "photo_ai_raw_json": {"raw_output_text": response.output_text},
            }
        elif not payload.get("photo_ai_model"):
            payload["photo_ai_model"] = Config.WB_COMPETITOR_PHOTO_AI_MODEL
        self._photo_ai_cache[cache_key] = payload
        return payload

    def _apply_photo_ai_filter(
        self,
        *,
        source_row: Dict[str, Any],
        rows: List[Dict[str, Any]],
        stats: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        if not self.photo_ai_filter_enabled or not rows:
            return rows

        source_photo_url = normalize_image_url(source_row.get("main_photo_url") or source_row.get("analytics_main_photo_url"))
        if not source_photo_url:
            stats["photo_ai_skipped_missing_photo"] += len({int(row["competitor_nm_id"]) for row in rows})
            return rows

        kept_rows: List[Dict[str, Any]] = []
        by_competitor: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            by_competitor.setdefault(int(row["competitor_nm_id"]), []).append(row)

        for competitor_nm_id, competitor_rows in by_competitor.items():
            representative = competitor_rows[0]
            competitor_photo_url = normalize_image_url(representative.get("competitor_main_photo_url"))
            if not competitor_photo_url:
                stats["photo_ai_skipped_missing_photo"] += 1
                kept_rows.extend(competitor_rows)
                continue
            try:
                verdict = self._evaluate_photo_competitor_match(
                    source_nm_id=int(source_row["nm_id"]),
                    competitor_nm_id=competitor_nm_id,
                    source_title=source_row.get("title"),
                    competitor_title=representative.get("competitor_title"),
                    source_photo_url=source_photo_url,
                    competitor_photo_url=competitor_photo_url,
                )
                stats["photo_ai_checked_unique"] += 1
            except Exception as exc:
                logger.warning(
                    "Photo AI filter failed: source_nm_id=%s competitor_nm_id=%s error=%s",
                    source_row.get("nm_id"),
                    competitor_nm_id,
                    exc,
                )
                stats["photo_ai_failed_unique"] += 1
                kept_rows.extend(competitor_rows)
                continue

            for row in competitor_rows:
                row.update(verdict)
            if verdict.get("photo_ai_is_competitor") is False:
                stats["filtered_photo_ai_mismatch"] += len(competitor_rows)
                continue
            kept_rows.extend(competitor_rows)
        return kept_rows

    @staticmethod
    def _source_score(row: Dict[str, Any]) -> int:
        score = 0
        if row.get("wb_link_price_promo") not in (None, ""):
            score += 10
        if row.get("wb_link_price_regular") not in (None, ""):
            score += 5
        for key in (
            "title",
            "subject_name",
            "product_url",
            "main_photo_url",
        ):
            if row.get(key) not in (None, ""):
                score += 1
        return score

    def _collapse_source_rows(self, rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        collapsed: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            nm_id = row.get("nm_id")
            if nm_id is None:
                continue
            nm_id = int(nm_id)
            current = collapsed.get(nm_id)
            if current is None or self._source_score(row) > self._source_score(current):
                collapsed[nm_id] = dict(row)
        return collapsed

    def _load_source_rows_from_json(self, path: str) -> List[Dict[str, Any]]:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            rows = payload["data"]
        elif isinstance(payload, list):
            rows = payload
        else:
            raise ValueError("Ожидался JSON c ключом data или список строк")
        if not isinstance(rows, list):
            raise ValueError("Некорректный формат source JSON")
        return [dict(item) for item in rows if isinstance(item, dict)]

    def _load_keywords_map(self, path: str, available_nm_ids: Set[int]) -> Dict[int, List[str]]:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, dict):
            raise ValueError("keywords JSON должен быть объектом вида nm_id -> [keywords]")

        result: Dict[int, List[str]] = {}
        for raw_nm_id, raw_keywords in payload.items():
            try:
                nm_id = int(str(raw_nm_id).strip())
            except ValueError:
                logger.warning("Пропуск некорректного nm_id в keywords JSON: %r", raw_nm_id)
                continue
            if nm_id not in available_nm_ids:
                logger.warning("Пропуск keywords для nm_id=%s: SKU отсутствует в source", nm_id)
                continue
            if not isinstance(raw_keywords, list):
                logger.warning("Пропуск keywords для nm_id=%s: ожидался список", nm_id)
                continue
            keywords = normalize_keywords(raw_keywords)
            if not keywords:
                logger.warning("Пропуск пустого keywords списка для nm_id=%s", nm_id)
                continue
            result[nm_id] = keywords
        return result

    def _load_source_rows(self, source_json: Optional[str], use_db_latest: bool) -> List[Dict[str, Any]]:
        if source_json:
            return self._load_source_rows_from_json(source_json)
        if use_db_latest:
            self._ensure_db()
            assert self.db is not None
            return self.db.get_latest_source_skus()
        raise ValueError("Нужно указать --source-json или --use-db-latest")

    def _build_competitor_rows_for_source(
        self,
        *,
        source_row: Dict[str, Any],
        keywords: List[str],
        own_nm_ids: Set[int],
        run_date: date,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        source_nm_id = int(source_row["nm_id"])
        source_snapshot_date = source_row.get("snapshot_date")
        source_subject_normalized = normalize_text(source_row.get("subject_name"))
        source_bed_type = extract_bed_type(source_row.get("title"))
        source_colors = extract_source_colors(source_row)
        source_price_regular, source_price_promo = pick_source_prices(source_row)
        if source_price_promo is None:
            return [], {"skipped_missing_price": 1}

        lower_bound, upper_bound = calculate_price_window(source_price_promo, Config.WB_COMPETITOR_PRICE_SEGMENT_PCT)
        raw_occurrences: List[Dict[str, Any]] = []
        stats = {
            "keywords_total": len(keywords),
            "keywords_failed_429": 0,
            "keywords_failed_other": 0,
            "search_hits": 0,
            "filtered_out_of_subject": 0,
            "filtered_out_of_bed_type": 0,
            "filtered_out_of_color": 0,
            "filtered_own_sku": 0,
            "filtered_missing_price": 0,
            "filtered_out_of_segment": 0,
            "source_found_keywords": 0,
            "source_not_found_keywords": 0,
            "photo_ai_checked_unique": 0,
            "photo_ai_failed_unique": 0,
            "photo_ai_skipped_missing_photo": 0,
            "filtered_photo_ai_mismatch": 0,
        }

        for keyword_order, keyword in enumerate(keywords, start=1):
            try:
                hits = self._search_keyword(keyword, stop_nm_id=source_nm_id)
            except RuntimeError as exc:
                logger.warning("Keyword пропущен browser-first search: nm_id=%s keyword=%r error=%s", source_nm_id, keyword, exc)
                stats["keywords_failed_other"] += 1
                continue

            stop_metadata = self._last_search_stop_metadata
            if stop_metadata.get("stop_nm_id") == source_nm_id and stop_metadata.get("found"):
                stats["source_found_keywords"] += 1
            else:
                stats["source_not_found_keywords"] += 1

            for hit in hits:
                competitor_nm_id = int(hit["competitor_nm_id"])
                if competitor_nm_id in own_nm_ids:
                    stats["filtered_own_sku"] += 1
                    continue
                if hit.get("competitor_price_promo_search") is None:
                    stats["filtered_missing_price"] += 1
                    continue
                occurrence = dict(hit)
                occurrence.update(
                    {
                        "run_date": run_date,
                        "source_snapshot_date": source_snapshot_date,
                        "source_nm_id": source_nm_id,
                        "source_barcode": source_row.get("barcode"),
                        "source_brand": source_row.get("brand"),
                        "source_subject_name": source_row.get("subject_name"),
                        "source_title": source_row.get("title"),
                        "source_product_url": source_row.get("product_url") or build_product_url(source_nm_id),
                        "source_price_regular": source_price_regular,
                        "source_price_promo": source_price_promo,
                        "source_price_segment_min": lower_bound,
                        "source_price_segment_max": upper_bound,
                        "keyword": keyword,
                        "keyword_order": keyword_order,
                    }
                )
                raw_occurrences.append(occurrence)

        if not raw_occurrences:
            return [], stats

        stats["search_hits"] = len(raw_occurrences)
        detail_lookup = self._fetch_detail_lookup(sorted({int(item["competitor_nm_id"]) for item in raw_occurrences}))
        enriched_rows: List[Dict[str, Any]] = []

        for item in raw_occurrences:
            competitor_nm_id = int(item["competitor_nm_id"])
            detail_product = detail_lookup.get(competitor_nm_id)
            detail_regular, detail_promo = self._extract_detail_prices(detail_product)
            competitor_price_regular = detail_regular or item.get("competitor_price_regular_search")
            competitor_price_promo = detail_promo or item.get("competitor_price_promo_search")
            if competitor_price_promo is None:
                stats["filtered_missing_price"] += 1
                continue

            competitor_subject_name = (
                (detail_product or {}).get("entity")
                or item.get("competitor_subject_name")
            )
            competitor_title = (detail_product or {}).get("name") or item.get("competitor_title")
            competitor_colors = extract_detail_colors(detail_product)
            same_subject = normalize_text(competitor_subject_name) == source_subject_normalized
            if not same_subject:
                stats["filtered_out_of_subject"] += 1
                continue
            competitor_bed_type = extract_bed_type(competitor_title)
            if source_bed_type is not None and competitor_bed_type != source_bed_type:
                stats["filtered_out_of_bed_type"] += 1
                continue
            same_color = match_color_sets(source_colors, competitor_colors)

            within_segment = lower_bound <= competitor_price_promo <= upper_bound
            if not within_segment:
                stats["filtered_out_of_segment"] += 1
                continue

            competitor_brand = (detail_product or {}).get("brand") or item.get("competitor_brand")
            competitor_supplier_name = (detail_product or {}).get("supplier")
            competitor_supplier_id = (detail_product or {}).get("supplierId")
            competitor_rating = (
                _to_decimal((detail_product or {}).get("reviewRating"))
                or _to_decimal((detail_product or {}).get("rating"))
                or item.get("competitor_rating")
            )
            competitor_feedbacks = int((detail_product or {}).get("feedbacks") or item.get("competitor_feedbacks") or 0)
            discount_percent = calculate_discount_percent(competitor_price_regular, competitor_price_promo)
            price_delta_abs = _quantize(competitor_price_promo - source_price_promo)
            price_delta_percent = _quantize((price_delta_abs / source_price_promo) * Decimal("100"))

            enriched_rows.append(
                {
                    "run_date": item["run_date"],
                    "source_snapshot_date": item.get("source_snapshot_date"),
                    "source_nm_id": item["source_nm_id"],
                    "source_barcode": item.get("source_barcode"),
                    "source_brand": item.get("source_brand"),
                    "source_subject_name": item.get("source_subject_name"),
                    "source_title": item.get("source_title"),
                    "source_product_url": item.get("source_product_url"),
                    "source_price_regular": decimal_to_float(item.get("source_price_regular")),
                    "source_price_promo": decimal_to_float(item.get("source_price_promo")),
                    "source_price_segment_min": decimal_to_float(item.get("source_price_segment_min")),
                    "source_price_segment_max": decimal_to_float(item.get("source_price_segment_max")),
                    "source_colors_json": list(source_colors),
                    "keyword": item["keyword"],
                    "keyword_order": item["keyword_order"],
                    "catalog_page": item.get("catalog_page"),
                    "catalog_position_on_page": item.get("catalog_position_on_page"),
                    "catalog_position_absolute": item.get("catalog_position_absolute"),
                    "competitor_nm_id": competitor_nm_id,
                    "competitor_brand": competitor_brand,
                    "competitor_supplier_name": competitor_supplier_name,
                    "competitor_supplier_id": competitor_supplier_id,
                    "competitor_subject_name": competitor_subject_name,
                    "competitor_title": competitor_title,
                    "competitor_description_short": build_short_description(
                        competitor_title,
                        competitor_brand,
                        competitor_subject_name,
                    ),
                    "competitor_colors_json": competitor_colors,
                    "competitor_main_photo_url": item.get("competitor_main_photo_url"),
                    "competitor_product_url": build_product_url(competitor_nm_id),
                    "competitor_price_regular": decimal_to_float(competitor_price_regular),
                    "competitor_price_promo": decimal_to_float(competitor_price_promo),
                    "competitor_discount_percent": decimal_to_float(discount_percent),
                    "competitor_rating": decimal_to_float(competitor_rating),
                    "competitor_feedbacks": competitor_feedbacks,
                    "photo_ai_is_competitor": None,
                    "photo_ai_confidence": None,
                    "photo_ai_reason": None,
                    "photo_ai_model": None,
                    "photo_ai_raw_json": None,
                    "price_delta_abs": decimal_to_float(price_delta_abs),
                    "price_delta_percent": decimal_to_float(price_delta_percent),
                    "within_price_segment": True,
                    "same_subject": True,
                    "same_color": same_color,
                    "search_payload_json": item.get("search_payload_json"),
                    "detail_payload_json": detail_product,
                    "parser_status": "matched",
                    "parser_error": None,
                }
            )

        if not enriched_rows:
            return [], stats

        enriched_rows = self._apply_photo_ai_filter(source_row=source_row, rows=enriched_rows, stats=stats)
        if not enriched_rows:
            return [], stats

        top_competitor_ids = select_top_competitor_ids(enriched_rows, self.limit_per_sku)
        final_rows = [row for row in enriched_rows if int(row["competitor_nm_id"]) in top_competitor_ids]
        final_rows.sort(key=lambda row: (row["keyword_order"], row["catalog_position_absolute"] or 10**9, row["competitor_nm_id"]))
        return final_rows, stats

    def save_to_json(self, rows: List[Dict[str, Any]], stats: Dict[str, Any]) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(Config.JSON_OUTPUT_DIR, f"wb_competitors_{ts}.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "generated_at": datetime.now().isoformat(),
                    "total_items": len(rows),
                    "stats": stats,
                    "data": rows,
                },
                file,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        logger.info("Сохранён JSON конкурентов WB: %s", path)
        return path

    def run(self, *, source_json: Optional[str], use_db_latest: bool, keywords_json: str) -> Dict[str, Any]:
        source_rows = self._load_source_rows(source_json, use_db_latest)
        source_by_nm_id = self._collapse_source_rows(source_rows)
        if not source_by_nm_id:
            raise ValueError("Не найдено исходных SKU для поиска конкурентов")

        keywords_map = self._load_keywords_map(keywords_json, set(source_by_nm_id.keys()))
        if not keywords_map:
            raise ValueError("После валидации не осталось ни одного nm_id с keywords")

        run_date = date.today()
        own_nm_ids = set(source_by_nm_id.keys())
        all_rows: List[Dict[str, Any]] = []
        aggregated_stats: Dict[str, Any] = {
            "source_skus_total": len(source_by_nm_id),
            "source_skus_with_keywords": len(keywords_map),
            "source_skus_processed": 0,
            "source_skus_skipped_missing_price": 0,
            "rows_matched": 0,
            "unique_competitors": 0,
            "keywords_total": 0,
            "keywords_failed_429": 0,
            "keywords_failed_other": 0,
            "search_hits": 0,
            "filtered_out_of_subject": 0,
            "filtered_out_of_bed_type": 0,
            "filtered_out_of_color": 0,
            "filtered_own_sku": 0,
            "filtered_missing_price": 0,
            "filtered_out_of_segment": 0,
            "source_found_keywords": 0,
            "source_not_found_keywords": 0,
            "photo_ai_checked_unique": 0,
            "photo_ai_failed_unique": 0,
            "photo_ai_skipped_missing_photo": 0,
            "filtered_photo_ai_mismatch": 0,
        }

        for source_nm_id in sorted(keywords_map.keys()):
            source_row = source_by_nm_id[source_nm_id]
            rows, stats = self._build_competitor_rows_for_source(
                source_row=source_row,
                keywords=keywords_map[source_nm_id],
                own_nm_ids=own_nm_ids,
                run_date=run_date,
            )
            aggregated_stats["source_skus_processed"] += 1
            for key, value in stats.items():
                if key == "skipped_missing_price":
                    aggregated_stats["source_skus_skipped_missing_price"] += value
                elif key in aggregated_stats:
                    aggregated_stats[key] += value
            all_rows.extend(rows)
            logger.info("Обработан source nm_id=%s: keywords=%s, rows=%s", source_nm_id, len(keywords_map[source_nm_id]), len(rows))

        aggregated_stats["rows_matched"] = len(all_rows)
        aggregated_stats["unique_competitors"] = len({row["competitor_nm_id"] for row in all_rows})
        json_path = self.save_to_json(all_rows, aggregated_stats)

        written_rows = 0
        if not self.dry_run:
            self._ensure_db()
            assert self.db is not None
            self.db.create_competitor_tables()
            written_rows = self.db.upsert_competitor_rows(all_rows)

        return {
            "rows": written_rows if not self.dry_run else len(all_rows),
            "json_path": json_path,
            "stats": aggregated_stats,
            "dry_run": self.dry_run,
        }

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
        if self._browser_context is not None:
            self._browser_context.close()
            self._browser_context = None
            self._browser_page = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find WB competitors for source SKUs")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source-json", help="Path to wb_sku_ai_analysis JSON")
    source_group.add_argument("--use-db-latest", action="store_true", help="Use latest snapshot from reports.wb_sku_ai_analysis")
    parser.add_argument("--keywords-json", required=True, help="Path to JSON nm_id -> [keywords]")
    parser.add_argument("--limit-per-sku", type=int, default=Config.WB_COMPETITORS_PER_SKU, help="Unique competitors to keep per source nm_id")
    parser.add_argument("--page-limit", type=int, default=Config.WB_SEARCH_PAGE_LIMIT, help="How many WB search pages to read per keyword")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing to PostgreSQL")
    parser.add_argument("--browser-profile-dir", default=Config.WB_BROWSER_PROFILE_DIR, help="Persistent Playwright profile directory")
    parser.add_argument("--headless", dest="headless", action="store_true", help="Run Playwright browser headless")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run Playwright browser with visible window")
    parser.add_argument(
        "--enable-photo-ai-filter",
        dest="photo_ai_filter",
        action="store_true",
        help="Enable OpenAI photo-based competitor filter",
    )
    parser.add_argument(
        "--disable-photo-ai-filter",
        dest="photo_ai_filter",
        action="store_false",
        help="Disable OpenAI photo-based competitor filter",
    )
    parser.set_defaults(headless=Config.WB_BROWSER_HEADLESS)
    parser.set_defaults(photo_ai_filter=Config.WB_COMPETITOR_PHOTO_AI_ENABLED)
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    Config.WB_BROWSER_PROFILE_DIR = args.browser_profile_dir
    Config.WB_BROWSER_HEADLESS = args.headless
    Config.WB_COMPETITOR_PHOTO_AI_ENABLED = args.photo_ai_filter
    fetcher = WBCompetitorFetcher(
        limit_per_sku=args.limit_per_sku,
        page_limit=args.page_limit,
        dry_run=args.dry_run,
        photo_ai_filter_enabled=args.photo_ai_filter,
    )
    try:
        result = fetcher.run(source_json=args.source_json, use_db_latest=args.use_db_latest, keywords_json=args.keywords_json)
        logger.info("Парсер конкурентов WB завершён: %s", result)
    finally:
        fetcher.close()


if __name__ == "__main__":
    main()
