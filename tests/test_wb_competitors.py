import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "WB_sku_ai_analysis"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from fetch_wb_competitors import (  # noqa: E402
    WBCompetitorFetcher,
    build_catalog_url_from_metadata,
    build_short_description,
    calculate_price_window,
    detect_product_placement,
    extract_json_object_from_text,
    extract_bed_type,
    extract_products_from_payload,
    merge_products_with_dom_details,
    normalize_photo_ai_payload,
    normalize_keywords,
    normalize_image_url,
    pick_source_prices,
    select_top_competitor_ids,
)


class WBCompetitorsHelpersTest(unittest.TestCase):
    def test_pick_source_prices_prefers_wb_link_fields(self) -> None:
        regular, promo = pick_source_prices(
            {
                "price": "2500",
                "discounted_price": "2200",
                "club_discounted_price": "2100",
                "wb_link_price_regular": "2600",
                "wb_link_price_promo": "2050",
            }
        )
        self.assertEqual(regular, Decimal("2600.00"))
        self.assertEqual(promo, Decimal("2050.00"))

    def test_normalize_keywords_deduplicates_and_strips(self) -> None:
        self.assertEqual(
            normalize_keywords([" кровать ", "КРОВАТЬ", "", "матрас"]),
            ["кровать", "матрас"],
        )

    def test_calculate_price_window(self) -> None:
        lower, upper = calculate_price_window(Decimal("1000.00"), 15)
        self.assertEqual(lower, Decimal("850.00"))
        self.assertEqual(upper, Decimal("1150.00"))

    def test_build_short_description(self) -> None:
        self.assertEqual(
            build_short_description("Кровать", "Solarius", "Кровати"),
            "Кровать Бренд: Solarius. Категория: Кровати.",
        )

    def test_extract_bed_type(self) -> None:
        self.assertEqual(extract_bed_type("Кровать односпальная ортопедическая"), "single")
        self.assertEqual(extract_bed_type("Кровать двуспальная массив сосны"), "double")
        self.assertEqual(extract_bed_type("Кровать полуторная сосновая"), "semi-double")
        self.assertIsNone(extract_bed_type("Кровать сосновая ортопедическая"))

    def test_extract_products_from_payload(self) -> None:
        payload = {"data": {"products": [{"id": 1}, {"id": 2}]}}
        self.assertEqual(extract_products_from_payload(payload), [{"id": 1}, {"id": 2}])

    def test_build_catalog_url_from_metadata(self) -> None:
        url = build_catalog_url_from_metadata({"shardKey": "presets/bucket_10269", "query": "preset=10105860"}, 3)
        self.assertIn("catalog/presets/bucket_10269/catalog", url)
        self.assertIn("preset=10105860", url)
        self.assertIn("page=3", url)

    def test_normalize_image_url(self) -> None:
        self.assertEqual(normalize_image_url("//basket-12.wbbasket.ru/test.webp"), "https://basket-12.wbbasket.ru/test.webp")
        self.assertEqual(normalize_image_url("https://basket-12.wbbasket.ru/test.webp"), "https://basket-12.wbbasket.ru/test.webp")
        self.assertIsNone(normalize_image_url(""))

    def test_merge_products_with_dom_details_adds_image(self) -> None:
        merged = merge_products_with_dom_details(
            [{"id": 123, "name": "Товар", "rating": None}],
            [{"id": 123, "imageUrl": "//basket-12.wbbasket.ru/test.webp", "rating": 4.8, "feedbacks": 12}],
        )
        self.assertEqual(merged[0]["imageUrl"], "//basket-12.wbbasket.ru/test.webp")
        self.assertEqual(merged[0]["rating"], 4.8)
        self.assertEqual(merged[0]["feedbacks"], 12)

    def test_merge_products_with_dom_details_keeps_display_and_wallet_separate(self) -> None:
        merged = merge_products_with_dom_details(
            [{"id": 70194686, "salePriceU": 338000}],
            [{"id": 70194686, "displayPriceU": 344900, "walletPriceU": 338000}],
        )
        self.assertEqual(merged[0]["displayPriceU"], 344900)
        self.assertEqual(merged[0]["walletPriceU"], 338000)

    def test_extract_json_object_from_text(self) -> None:
        text = '```json\n{"is_visual_competitor": true, "confidence": 0.91, "reason": "Похожа"}\n```'
        self.assertEqual(
            extract_json_object_from_text(text),
            {"is_visual_competitor": True, "confidence": 0.91, "reason": "Похожа"},
        )

    def test_normalize_photo_ai_payload(self) -> None:
        normalized = normalize_photo_ai_payload(
            {"is_visual_competitor": "true", "confidence": "1.2", "reason": "Совпадает", "model": "gpt-4o-mini"}
        )
        self.assertEqual(normalized["photo_ai_is_competitor"], True)
        self.assertEqual(normalized["photo_ai_confidence"], 1.0)
        self.assertEqual(normalized["photo_ai_reason"], "Совпадает")
        self.assertEqual(normalized["photo_ai_model"], "gpt-4o-mini")

    def test_select_top_competitor_ids(self) -> None:
        rows = [
            {
                "competitor_nm_id": 1,
                "keyword_order": 2,
                "catalog_position_absolute": 20,
                "price_delta_percent": 5.0,
                "competitor_rating": 4.9,
                "competitor_feedbacks": 100,
            },
            {
                "competitor_nm_id": 2,
                "keyword_order": 1,
                "catalog_position_absolute": 30,
                "price_delta_percent": 4.0,
                "competitor_rating": 4.0,
                "competitor_feedbacks": 50,
            },
            {
                "competitor_nm_id": 3,
                "keyword_order": 1,
                "catalog_position_absolute": 10,
                "price_delta_percent": 8.0,
                "competitor_rating": 4.8,
                "competitor_feedbacks": 10,
            },
        ]
        self.assertEqual(select_top_competitor_ids(rows, 2), {2, 3})


class WBCompetitorsSearchTest(unittest.TestCase):
    def test_source_detail_page_prices_are_kept_separate(self) -> None:
        class Page:
            def goto(self, *args, **kwargs):
                return None

            def evaluate(self, script):
                return {
                    "regularPriceU": 844000,
                    "displayPriceU": 344900,
                    "walletPriceU": 338000,
                    "evidence": {"display": {"selector": "priceBlockFinalPrice"}},
                }

        fetcher = WBCompetitorFetcher(limit_per_sku=10, page_limit=1, dry_run=True, photo_ai_filter_enabled=False)
        fetcher._browser_page = Page()
        fetcher._browser_warmed_up = True
        fetcher._wait_for_search_page_ready = lambda page: None  # type: ignore[assignment]

        prices = fetcher._fetch_source_detail_page_prices(70194686)

        self.assertEqual(prices["regular"], Decimal("8440.00"))
        self.assertEqual(prices["display"], Decimal("3449.00"))
        self.assertEqual(prices["wallet"], Decimal("3380.00"))
        self.assertEqual(prices["evidence"]["display"]["selector"], "priceBlockFinalPrice")

    def test_search_keyword_tracks_catalog_positions_and_best_page_hit(self) -> None:
        fetcher = WBCompetitorFetcher(limit_per_sku=20, page_limit=2, dry_run=True, photo_ai_filter_enabled=False)
        fetcher._browser_page = object()
        fetcher._warmup_browser = lambda: None  # type: ignore[assignment]
        fetcher._open_search_page = lambda page, keyword, page_number: None  # type: ignore[assignment]

        def fake_collect(page, page_number):
            if page_number == 1:
                return [
                    {"id": 10, "brand": "A", "subjectName": "Кровати", "name": "Товар 10", "priceU": 200000, "salePriceU": 150000, "rating": 4.5, "feedbacks": 7},
                    {"id": 20, "brand": "B", "subjectName": "Кровати", "name": "Товар 20", "priceU": 210000, "salePriceU": 160000, "rating": 4.7, "feedbacks": 8},
                ]
            return [
                {"id": 20, "brand": "B", "subjectName": "Кровати", "name": "Товар 20", "priceU": 210000, "salePriceU": 160000, "rating": 4.7, "feedbacks": 8},
                {"id": 30, "brand": "C", "subjectName": "Кровати", "name": "Товар 30", "priceU": 220000, "salePriceU": 170000, "rating": 4.8, "feedbacks": 9},
            ]

        fetcher._collect_products_from_browser = fake_collect  # type: ignore[assignment]
        hits = fetcher._search_keyword("кровать")
        by_nm_id = {item["competitor_nm_id"]: item for item in hits}

        self.assertEqual(by_nm_id[10]["catalog_page"], 1)
        self.assertEqual(by_nm_id[10]["catalog_position_on_page"], 1)
        self.assertEqual(by_nm_id[10]["catalog_position_absolute"], 1)
        self.assertEqual(by_nm_id[20]["catalog_page"], 1)
        self.assertEqual(by_nm_id[20]["catalog_position_absolute"], 2)
        self.assertEqual(by_nm_id[30]["catalog_page"], 2)
        self.assertEqual(by_nm_id[30]["catalog_position_absolute"], 4)

    def test_search_keyword_stops_before_source_nm_id(self) -> None:
        fetcher = WBCompetitorFetcher(limit_per_sku=20, page_limit=2, dry_run=True, photo_ai_filter_enabled=False)
        fetcher._browser_page = object()
        fetcher._warmup_browser = lambda: None  # type: ignore[assignment]
        opened_pages = []

        def fake_open(page, keyword, page_number):
            opened_pages.append(page_number)

        def fake_collect(page, page_number):
            if page_number != 1:
                self.fail("Search should stop after finding the source SKU on the first page")
            return [
                {"id": 10, "brand": "A", "subjectName": "Кровати", "name": "Товар 10", "priceU": 200000, "salePriceU": 150000, "rating": 4.5, "feedbacks": 7},
                {"id": 20, "brand": "Our", "subjectName": "Кровати", "name": "Наш товар", "priceU": 210000, "salePriceU": 160000, "rating": 4.7, "feedbacks": 8, "isSponsored": False},
                {"id": 30, "brand": "C", "subjectName": "Кровати", "name": "Товар 30", "priceU": 220000, "salePriceU": 170000, "rating": 4.8, "feedbacks": 9},
            ]

        fetcher._open_search_page = fake_open  # type: ignore[assignment]
        fetcher._collect_products_from_browser = fake_collect  # type: ignore[assignment]

        hits = fetcher._search_keyword("кровать", stop_nm_id=20)

        self.assertEqual([item["competitor_nm_id"] for item in hits], [10])
        self.assertEqual(opened_pages, [1])
        self.assertEqual(
            fetcher._last_search_stop_metadata,
            {
                "keyword": "кровать",
                "stop_nm_id": 20,
                "found": True,
                "catalog_page": 1,
                "catalog_position_on_page": 2,
                "catalog_position_absolute": 2,
            },
        )

    def test_scan_keeps_sponsored_and_organic_occurrences_and_stops_on_organic_source(self) -> None:
        fetcher = WBCompetitorFetcher(limit_per_sku=20, page_limit=2, dry_run=True, photo_ai_filter_enabled=False)
        fetcher._browser_page = object()
        fetcher._warmup_browser = lambda: None  # type: ignore[assignment]
        opened_pages = []
        fetcher._open_search_page = lambda page, keyword, page_number: opened_pages.append(page_number)  # type: ignore[assignment]

        def fake_collect(page, page_number):
            if page_number == 1:
                return [
                    {"id": 20, "name": "Наш товар реклама", "salePriceU": 100000, "isSponsored": True},
                    {"id": 10, "name": "Конкурент", "salePriceU": 90000, "isSponsored": False},
                ]
            return [
                {"id": 30, "name": "Конкурент 2", "salePriceU": 95000, "isSponsored": False},
                {"id": 20, "name": "Наш товар органика", "salePriceU": 100000, "isSponsored": False},
                {"id": 40, "name": "После нас", "salePriceU": 80000, "isSponsored": False},
            ]

        fetcher._collect_products_from_browser = fake_collect  # type: ignore[assignment]
        rows = fetcher._scan_keyword("товар", source_nm_id=20, max_positions=200)

        self.assertEqual([row["competitor_nm_id"] for row in rows], [20, 10, 30, 20])
        self.assertEqual([row["catalog_position_absolute"] for row in rows], [1, 2, 3, 4])
        self.assertEqual(rows[0]["placement_type"], "sponsored")
        self.assertEqual(rows[3]["catalog_position_organic"], 3)
        self.assertEqual(opened_pages, [1, 2])
        self.assertTrue(fetcher._last_serp_scan_metadata["source_found_sponsored"])
        self.assertTrue(fetcher._last_serp_scan_metadata["source_found_organic"])
        self.assertEqual(fetcher._last_serp_scan_metadata["source_position_sponsored"], 1)
        self.assertEqual(fetcher._last_serp_scan_metadata["source_position_organic_absolute"], 4)

    def test_scan_uses_cumulative_absolute_position_for_variable_page_sizes(self) -> None:
        fetcher = WBCompetitorFetcher(limit_per_sku=20, page_limit=2, dry_run=True, photo_ai_filter_enabled=False)
        fetcher._browser_page = object()
        fetcher._warmup_browser = lambda: None  # type: ignore[assignment]
        fetcher._open_search_page = lambda page, keyword, page_number: None  # type: ignore[assignment]
        fetcher._collect_products_from_browser = lambda page, page_number: (  # type: ignore[assignment]
            [{"id": 1, "isSponsored": False}, {"id": 2, "isSponsored": False}, {"id": 3, "isSponsored": False}]
            if page_number == 1
            else [{"id": 4, "isSponsored": False}]
        )

        rows = fetcher._scan_keyword("товар", max_positions=200)
        self.assertEqual([row["catalog_position_absolute"] for row in rows], [1, 2, 3, 4])

    def test_unknown_placement_is_not_organic(self) -> None:
        self.assertEqual(detect_product_placement({}), ("unknown", "unclassified"))
        self.assertEqual(detect_product_placement({"isSponsored": True}), ("sponsored", "isSponsored"))
        self.assertEqual(detect_product_placement({"isSponsored": False}), ("organic", "isSponsored"))

    def test_search_price_units_are_converted_from_kopecks(self) -> None:
        fetcher = WBCompetitorFetcher(limit_per_sku=10, page_limit=1, dry_run=True, photo_ai_filter_enabled=False)
        row = fetcher._normalize_browser_product(
            {
                "id": 70194686,
                "priceU": 844000,
                "salePriceU": 329500,
                "walletPriceU": 299900,
                "isSponsored": False,
            },
            page_number=1,
            index=1,
            absolute_position=1,
            organic_position=1,
        )

        self.assertEqual(row["competitor_price_regular_search"], Decimal("8440.00"))
        self.assertEqual(row["competitor_price_promo_search"], Decimal("3295.00"))
        self.assertEqual(row["competitor_price_wallet_search"], Decimal("2999.00"))
        self.assertEqual(row["competitor_price_effective_search"], Decimal("2999.00"))
        self.assertEqual(row["competitor_price_basis_search"], "wallet")

    def test_display_price_is_distinct_from_wallet_price(self) -> None:
        fetcher = WBCompetitorFetcher(limit_per_sku=10, page_limit=1, dry_run=True, photo_ai_filter_enabled=False)
        row = fetcher._normalize_browser_product(
            {
                "id": 70194686,
                "priceU": 844000,
                "salePriceU": 338000,
                "displayPriceU": 344900,
                "walletPriceU": 338000,
                "isSponsored": False,
            },
            page_number=1,
            index=1,
            absolute_position=1,
            organic_position=1,
        )

        self.assertEqual(row["competitor_price_promo_search"], Decimal("3449.00"))
        self.assertEqual(row["competitor_price_wallet_search"], Decimal("3380.00"))
        self.assertEqual(row["competitor_price_effective_search"], Decimal("3380.00"))


if __name__ == "__main__":
    unittest.main()
