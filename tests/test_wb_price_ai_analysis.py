import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "wb_price_ai_analysis"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

sys.modules.pop("database", None)
sys.modules.pop("config", None)

from competitor_pipeline import (  # noqa: E402
    apply_hard_filter,
    build_competitor_features,
    build_source_features,
    compatible_dimensions,
    normalize_relevance_payload,
    normalize_vision_payload,
    parse_vision_response_text,
    vision_grade_priority,
)
from apply_hard_filters_per_sku import build_filtered_rows  # noqa: E402
from fetch_raw_competitors_per_sku import is_supported_runtime, run_one as run_raw_one  # noqa: E402
from finalize_price_ai_row import (  # noqa: E402
    build_analysis_status,
    calculate_discount_percent,
    summarize_competitors,
    summarize_strict_competitors,
)
from grade_visual_match_per_sku import run_one as run_vision_one  # noqa: E402
from generate_seo_keywords import validate_keywords  # noqa: E402
from prepare_active_skus import collapse_source_rows  # noqa: E402
import database as analysis_database  # noqa: E402

if str(MODULE_DIR) in sys.path:
    sys.path.remove(str(MODULE_DIR))


class WBPriceAIAnalysisHelpersTest(unittest.TestCase):
    def test_schema_bootstrap_uses_and_releases_advisory_lock(self) -> None:
        events = []

        class Cursor:
            def execute(self, sql, params=None):
                events.append((sql, params))

        db = analysis_database.WBPriceAIAnalysisDatabase()
        db.cursor = Cursor()

        with patch.object(
            analysis_database,
            "execute_ddl_bundle",
            side_effect=lambda cursor, name: events.append(("ddl", name)),
        ):
            db.create_tables()

        self.assertIn("pg_advisory_lock", events[0][0])
        self.assertEqual(events[1], ("ddl", "schema_wb_price_ai_analysis.sql"))
        self.assertIn("pg_advisory_unlock", events[2][0])

    def test_schema_bootstrap_releases_advisory_lock_after_ddl_error(self) -> None:
        statements = []

        class Cursor:
            def execute(self, sql, params=None):
                statements.append(sql)

        db = analysis_database.WBPriceAIAnalysisDatabase()
        db.cursor = Cursor()

        with patch.object(
            analysis_database,
            "execute_ddl_bundle",
            side_effect=RuntimeError("ddl failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "ddl failed"):
                db.create_tables()

        self.assertIn("pg_advisory_lock", statements[0])
        self.assertIn("pg_advisory_unlock", statements[-1])

    def test_collapse_source_rows_aggregates_variants_and_filters_missing_wb_link_price(self) -> None:
        rows = [
            {
                "snapshot_date": date(2026, 3, 10),
                "nm_id": 1,
                "barcode": "111",
                "vendor_code": "sku-1",
                "supplier_article": "sku-1",
                "brand": "Brand",
                "subject_name": "Кровати",
                "title": "Кровать 90х200",
                "description": "Описание",
                "product_url": "https://www.wildberries.ru/catalog/1/detail.aspx",
                "main_photo_url": "https://img/1.webp",
                "characteristics_json": [{"name": "Цвет", "value": ["белый"]}],
                "tags_json": [{"name": "кровать"}],
                "sizes_json": [{"skus": ["111"]}],
                "warehouse_names": ["Коледино"],
                "warehouse_count": 1,
                "total_quantity": 2,
                "total_quantity_full": 2,
                "wb_link_price_regular": 10000,
                "wb_link_price_promo": 8000,
            },
            {
                "snapshot_date": date(2026, 3, 10),
                "nm_id": 1,
                "barcode": "222",
                "vendor_code": "sku-1",
                "supplier_article": "sku-1",
                "brand": "Brand",
                "subject_name": "Кровати",
                "title": "Кровать 90х200",
                "description": "Описание",
                "product_url": "https://www.wildberries.ru/catalog/1/detail.aspx",
                "main_photo_url": "https://img/1.webp",
                "characteristics_json": [{"name": "Цвет", "value": ["белый"]}],
                "tags_json": [{"name": "кровать"}],
                "sizes_json": [{"skus": ["222"]}],
                "warehouse_names": ["Электросталь"],
                "warehouse_count": 1,
                "total_quantity": 3,
                "total_quantity_full": 3,
                "wb_link_price_regular": 10000,
                "wb_link_price_promo": 8000,
            },
            {
                "snapshot_date": date(2026, 3, 10),
                "nm_id": 2,
                "barcode": "333",
                "vendor_code": "sku-2",
                "supplier_article": "sku-2",
                "brand": "Brand",
                "subject_name": "Кровати",
                "title": "Кровать 80х200",
                "description": "Описание",
                "product_url": "https://www.wildberries.ru/catalog/2/detail.aspx",
                "main_photo_url": "https://img/2.webp",
                "characteristics_json": [],
                "tags_json": [],
                "sizes_json": [],
                "warehouse_names": ["Коледино"],
                "warehouse_count": 1,
                "total_quantity": 1,
                "total_quantity_full": 1,
                "wb_link_price_regular": None,
                "wb_link_price_promo": None,
            },
        ]
        payloads = collapse_source_rows(rows, run_date=date(2026, 3, 10))
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["source_nm_id"], 1)
        self.assertEqual(payloads[0]["source_barcodes_json"], ["111", "222"])
        self.assertEqual(payloads[0]["source_total_quantity"], 5)
        self.assertEqual(sorted(payloads[0]["source_warehouse_names_json"]), ["Коледино", "Электросталь"])

    def test_validate_keywords_enforces_five_clean_keywords(self) -> None:
        payload = {
            "source_vendor_code": "ABC-123",
            "source_supplier_article": "ABC-123",
        }
        valid = validate_keywords(
            [
                "кровать деревянная",
                "Кровать деревянная",
                "ABC-123",
                "односпальная кровать 90х200",
                "кровать белая деревянная",
                "мебель",
                "ортопедическая кровать из сосны",
                "кровать для дачи",
            ],
            payload,
        )
        self.assertEqual(
            valid,
            [
                "кровать деревянная",
                "односпальная кровать 90х200",
                "кровать белая деревянная",
                "ортопедическая кровать из сосны",
                "кровать для дачи",
            ],
        )

    def test_summarize_competitors_prefers_llm_accepted_rows(self) -> None:
        rows = [
            {
                "competitor_nm_id": 10,
                "keyword": "кровать",
                "keyword_order": 2,
                "catalog_position_absolute": 4,
                "competitor_title": "A",
                "competitor_product_url": "u1",
                "competitor_price_promo": 9000.0,
                "competitor_price_regular": 12000.0,
                "competitor_rating": 4.8,
                "competitor_feedbacks": 10,
                "price_delta_percent": -10.0,
                "passed_hard_filters": True,
                "llm_status": "failed",
            },
            {
                "competitor_nm_id": 20,
                "keyword": "кровать",
                "keyword_order": 1,
                "catalog_position_absolute": 1,
                "competitor_title": "B",
                "competitor_product_url": "u2",
                "competitor_price_promo": 11000.0,
                "competitor_price_regular": 13000.0,
                "competitor_rating": 4.9,
                "competitor_feedbacks": 100,
                "price_delta_percent": 10.0,
                "passed_hard_filters": True,
                "llm_status": "success",
                "relevance_score": 0.91,
                "relevance_verdict": True,
                "vision_status": "success",
                "vision_grade": "close_analog",
            },
        ]
        summary = summarize_competitors(rows, source_price_promo=10000.0, limit=20, threshold=0.75)
        self.assertEqual(summary["competitor_count"], 1)
        self.assertEqual(summary["competitor_pricier_count"], 1)
        self.assertEqual(summary["best_competitor_position"], 1)
        self.assertEqual(summary["competitor_price_avg"], 11000.0)
        self.assertEqual(summary["llm_kept_count"], 1)
        self.assertEqual(summary["vision_close_count"], 1)

    def test_calculate_discount_percent(self) -> None:
        self.assertEqual(calculate_discount_percent(10000.0, 8000.0), 20.0)
        self.assertIsNone(calculate_discount_percent(None, 8000.0))

    def test_build_analysis_status(self) -> None:
        self.assertEqual(build_analysis_status("success", "success"), "success")
        self.assertEqual(build_analysis_status("failed", "success"), "partial")

    def test_runtime_preflight_helper(self) -> None:
        self.assertIsInstance(is_supported_runtime(), bool)

    def test_raw_stage_skips_when_seo_failed(self) -> None:
        result = run_raw_one(
            {
                "run_date": "2026-03-16",
                "source_nm_id": 123,
                "seo_status": "failed",
            }
        )
        self.assertEqual(result["raw_status"], "skipped_missing_keywords")

    def test_raw_stage_returns_controlled_failure_when_host_runner_disabled_in_docker(self) -> None:
        payload = {
            "run_date": "2026-03-16",
            "source_nm_id": 123,
            "seo_status": "success",
            "keywords_json": ["тестовый запрос", "ещё запрос"],
        }
        with patch("fetch_raw_competitors_per_sku.is_supported_runtime", return_value=False), patch(
            "fetch_raw_competitors_per_sku.Config.WB_PRICE_AI_HOST_RUNNER_ENABLED",
            False,
        ):
            result = run_raw_one(payload)
        self.assertEqual(result["raw_status"], "failed")
        self.assertIn("Host runner disabled", result["raw_error"])

    def test_build_source_features_extracts_bed_size(self) -> None:
        features = build_source_features(
            {
                "source_title": "Кровать односпальная 60х200 см из массива сосны",
                "source_description": "Белая кровать для дачи",
                "source_subject_name": "Кровати",
                "source_characteristics_json": [{"name": "Цвет", "value": ["белый"]}],
                "source_sizes_json": [],
                "source_tags_json": [],
            }
        )
        self.assertEqual(features["source_bed_type"], "single")
        self.assertEqual(features["source_sleep_size_json"], [60, 200])

    def test_build_competitor_features_extracts_gamepad_platform(self) -> None:
        features = build_competitor_features(
            {
                "competitor_title": "Беспроводной геймпад для PS4/ПК/телефона с Bluetooth",
                "competitor_subject_name": "Геймпады",
                "competitor_colors_json": [],
                "detail_payload_json": {},
            }
        )
        self.assertIn("ps4", features["competitor_platform"])
        self.assertIn("pc", features["competitor_platform"])
        self.assertEqual(features["competitor_connection_type"], "wireless")

    def test_compatible_dimensions(self) -> None:
        self.assertTrue(compatible_dimensions([60, 200], [60, 200], tolerance=0.05))
        self.assertFalse(compatible_dimensions([60, 200], [90, 200], tolerance=0.05))
        self.assertIsNone(compatible_dimensions(None, [90, 200], tolerance=0.05))

    def test_apply_hard_filter_rejects_bed_size_mismatch(self) -> None:
        raw_row = {"within_price_segment": True}
        features = {
            "source_subject_norm": "beds",
            "competitor_subject_norm": "beds",
            "source_bed_type": "single",
            "competitor_bed_type": "single",
            "source_sleep_size_json": [60, 200],
            "competitor_sleep_size_json": [90, 200],
        }
        decision = apply_hard_filter(raw_row, features)
        self.assertFalse(decision["passed_hard_filters"])
        self.assertEqual(decision["hard_filter_reason"], "sleep_size_mismatch")

    def test_apply_hard_filter_rejects_tie_subtype_mismatch(self) -> None:
        raw_row = {"within_price_segment": True}
        features = {
            "source_subject_norm": "cable_ties",
            "competitor_subject_norm": "cable_ties",
            "source_subtype": "velcro",
            "competitor_subtype": "plastic",
        }
        decision = apply_hard_filter(raw_row, features)
        self.assertFalse(decision["passed_hard_filters"])
        self.assertEqual(decision["hard_filter_reason"], "subtype_mismatch")

    def test_apply_hard_filter_keeps_unknown_attributes(self) -> None:
        raw_row = {"within_price_segment": True}
        features = {
            "source_subject_norm": "gamepads",
            "competitor_subject_norm": "gamepads",
            "source_platform": [],
            "competitor_platform": [],
            "source_connection_type": None,
            "competitor_connection_type": None,
        }
        decision = apply_hard_filter(raw_row, features)
        self.assertTrue(decision["passed_hard_filters"])

    def test_build_filtered_rows_marks_price_peer_without_using_price_as_validity(self) -> None:
        payload = {
            "run_date": "2026-03-16",
            "source_nm_id": 100,
            "source_price_promo": 1000.0,
        }
        raw_rows = [
            {
                "keyword": "сыворотка",
                "keyword_order": 1,
                "catalog_position_absolute": 2,
                "competitor_nm_id": 200,
                "competitor_price_promo": 950.0,
                "competitor_rating": 4.8,
                "competitor_feedbacks": 25,
                "price_delta_percent": -5.0,
                "within_price_segment": True,
                "source_price_segment_max": 1350.0,
            },
        ]
        feature_rows = [
            {
                "keyword": "сыворотка",
                "competitor_nm_id": 200,
                "source_subject_norm": "patches",
                "competitor_subject_norm": "patches",
            },
        ]
        rows, summary = build_filtered_rows(payload=payload, raw_rows=raw_rows, feature_rows=feature_rows)
        self.assertEqual(summary["selected_mode"], "structural_market")
        self.assertEqual(summary["hard_filter_pass_count"], 1)
        self.assertEqual(rows[0]["filter_mode"], "price_peer")
        self.assertEqual(rows[0]["hard_filter_reason"], "accepted_price_peer")
        self.assertTrue(rows[0]["passed_hard_filters"])
        self.assertTrue(rows[0]["effective_price_match"])

    def test_build_filtered_rows_keeps_structural_competitor_outside_price_band(self) -> None:
        payload = {
            "run_date": "2026-03-16",
            "source_nm_id": 100,
            "source_price_promo": 3000.0,
        }
        raw_rows = [
            {
                "keyword": "сыворотка",
                "keyword_order": 1,
                "catalog_position_absolute": 1,
                "competitor_nm_id": 201,
                "competitor_price_promo": 2900.0,
                "price_delta_percent": -3.33,
                "within_price_segment": True,
            },
            {
                "keyword": "сыворотка",
                "keyword_order": 1,
                "catalog_position_absolute": 2,
                "competitor_nm_id": 202,
                "competitor_price_promo": 600.0,
                "price_delta_percent": -80.0,
                "within_price_segment": False,
            },
        ]
        feature_rows = [
            {"keyword": "сыворотка", "competitor_nm_id": 201, "source_subject_norm": "serums", "competitor_subject_norm": "serums"},
            {"keyword": "сыворотка", "competitor_nm_id": 202, "source_subject_norm": "serums", "competitor_subject_norm": "serums"},
        ]

        rows, summary = build_filtered_rows(payload=payload, raw_rows=raw_rows, feature_rows=feature_rows)

        self.assertEqual(summary["hard_filter_pass_count"], 2)
        self.assertTrue(all(row["passed_hard_filters"] for row in rows))
        self.assertEqual([row["filter_mode"] for row in rows], ["price_peer", "market_competitor"])

    def test_build_filtered_rows_uses_expanded_mode_for_outlier_source(self) -> None:
        payload = {
            "run_date": "2026-03-16",
            "source_nm_id": 101,
            "source_price_promo": 4000.0,
        }
        raw_rows = [
            {
                "keyword": "патчи",
                "keyword_order": 1,
                "catalog_position_absolute": 1,
                "competitor_nm_id": 201,
                "competitor_price_promo": 800.0,
                "competitor_rating": 4.9,
                "competitor_feedbacks": 120,
                "price_delta_percent": -80.0,
                "within_price_segment": False,
                "source_price_segment_max": 5400.0,
            },
            {
                "keyword": "патчи",
                "keyword_order": 1,
                "catalog_position_absolute": 2,
                "competitor_nm_id": 202,
                "competitor_price_promo": 900.0,
                "competitor_rating": 4.7,
                "competitor_feedbacks": 80,
                "price_delta_percent": -77.5,
                "within_price_segment": False,
                "source_price_segment_max": 5400.0,
            },
            {
                "keyword": "патчи",
                "keyword_order": 1,
                "catalog_position_absolute": 3,
                "competitor_nm_id": 203,
                "competitor_price_promo": 1000.0,
                "competitor_rating": 4.6,
                "competitor_feedbacks": 60,
                "price_delta_percent": -75.0,
                "within_price_segment": False,
                "source_price_segment_max": 5400.0,
            },
        ]
        feature_rows = [
            {"keyword": "патчи", "competitor_nm_id": 201, "source_subject_norm": "patches", "competitor_subject_norm": "patches"},
            {"keyword": "патчи", "competitor_nm_id": 202, "source_subject_norm": "patches", "competitor_subject_norm": "patches"},
            {"keyword": "патчи", "competitor_nm_id": 203, "source_subject_norm": "patches", "competitor_subject_norm": "patches"},
        ]
        rows, summary = build_filtered_rows(payload=payload, raw_rows=raw_rows, feature_rows=feature_rows)
        passed = [row for row in rows if row["passed_hard_filters"]]
        self.assertEqual(summary["selected_mode"], "structural_market")
        self.assertTrue(summary["is_price_outlier"])
        self.assertEqual(len(passed), 3)
        self.assertTrue(all(row["filter_mode"] == "market_competitor" for row in passed))
        self.assertTrue(all(row["hard_filter_reason"] == "accepted_market_competitor" for row in passed))

    def test_build_filtered_rows_uses_market_fallback_when_strict_pool_is_empty(self) -> None:
        payload = {
            "run_date": "2026-03-16",
            "source_nm_id": 102,
            "source_price_promo": 1100.0,
        }
        raw_rows = [
            {
                "keyword": "тоник",
                "keyword_order": 1,
                "catalog_position_absolute": 1,
                "competitor_nm_id": 301,
                "competitor_price_promo": 600.0,
                "competitor_rating": 4.7,
                "competitor_feedbacks": 90,
                "price_delta_percent": -45.45,
                "within_price_segment": False,
                "source_price_segment_max": 1485.0,
            },
            {
                "keyword": "тоник",
                "keyword_order": 1,
                "catalog_position_absolute": 2,
                "competitor_nm_id": 302,
                "competitor_price_promo": 650.0,
                "competitor_rating": 4.8,
                "competitor_feedbacks": 100,
                "price_delta_percent": -40.91,
                "within_price_segment": False,
                "source_price_segment_max": 1485.0,
            },
            {
                "keyword": "тоник",
                "keyword_order": 1,
                "catalog_position_absolute": 3,
                "competitor_nm_id": 303,
                "competitor_price_promo": 700.0,
                "competitor_rating": 4.6,
                "competitor_feedbacks": 70,
                "price_delta_percent": -36.36,
                "within_price_segment": False,
                "source_price_segment_max": 1485.0,
            },
        ]
        feature_rows = [
            {"keyword": "тоник", "competitor_nm_id": 301, "source_subject_norm": "toners", "competitor_subject_norm": "toners"},
            {"keyword": "тоник", "competitor_nm_id": 302, "source_subject_norm": "toners", "competitor_subject_norm": "toners"},
            {"keyword": "тоник", "competitor_nm_id": 303, "source_subject_norm": "toners", "competitor_subject_norm": "toners"},
        ]
        rows, summary = build_filtered_rows(payload=payload, raw_rows=raw_rows, feature_rows=feature_rows)
        passed = [row for row in rows if row["passed_hard_filters"]]
        self.assertEqual(summary["selected_mode"], "structural_market")
        self.assertFalse(summary["is_price_outlier"])
        self.assertEqual(len(passed), 3)
        self.assertTrue(all(row["filter_mode"] == "market_competitor" for row in passed))

    def test_build_filtered_rows_preserves_structural_guards_in_fallback(self) -> None:
        payload = {
            "run_date": "2026-03-16",
            "source_nm_id": 103,
            "source_price_promo": 1100.0,
        }
        raw_rows = [
            {
                "keyword": "кровать",
                "keyword_order": 1,
                "catalog_position_absolute": 1,
                "competitor_nm_id": 401,
                "competitor_price_promo": 600.0,
                "competitor_rating": 4.9,
                "competitor_feedbacks": 10,
                "price_delta_percent": -45.0,
                "within_price_segment": False,
                "source_price_segment_max": 1485.0,
            },
        ]
        feature_rows = [
            {
                "keyword": "кровать",
                "competitor_nm_id": 401,
                "source_subject_norm": "beds",
                "competitor_subject_norm": "beds",
                "source_bed_type": "single",
                "competitor_bed_type": "single",
                "source_sleep_size_json": [60, 200],
                "competitor_sleep_size_json": [90, 200],
            },
        ]
        rows, summary = build_filtered_rows(payload=payload, raw_rows=raw_rows, feature_rows=feature_rows)
        self.assertEqual(summary["selected_mode"], "rejected")
        self.assertEqual(summary["hard_filter_pass_count"], 0)
        self.assertFalse(rows[0]["passed_hard_filters"])
        self.assertEqual(rows[0]["hard_filter_reason"], "sleep_size_mismatch")

    def test_normalize_relevance_payload(self) -> None:
        payload = normalize_relevance_payload(
            {
                "relevance_score": 0.82,
                "relevance_verdict": True,
                "relevance_reason": "Похоже на тот же товарный тип",
                "matched_attributes_json": {"same_type": True},
            }
        )
        self.assertEqual(payload["relevance_score"], 0.82)
        self.assertTrue(payload["relevance_verdict"])

    def test_normalize_vision_payload(self) -> None:
        payload = normalize_vision_payload(
            {
                "vision_score": 0.88,
                "vision_grade": "absolute_analog",
                "vision_reason": "Очень похожий форм-фактор",
                "visual_signals_json": {"same_form_factor": True},
            }
        )
        self.assertEqual(payload["vision_score"], 0.88)
        self.assertEqual(payload["vision_grade"], "absolute_analog")

    def test_parse_vision_response_text_rejects_unknown_grade(self) -> None:
        payload = parse_vision_response_text(
            '{"vision_score": 0.2, "vision_grade": "wrong", "vision_reason": "x", "visual_signals_json": {}}'
        )
        self.assertIsNone(payload)

    def test_vision_grade_priority(self) -> None:
        self.assertLess(vision_grade_priority("absolute_analog"), vision_grade_priority("close_analog"))
        self.assertLess(vision_grade_priority("close_analog"), vision_grade_priority("not_analog"))

    def test_summarize_competitors_prioritizes_better_vision_grade(self) -> None:
        rows = [
            {
                "competitor_nm_id": 10,
                "keyword": "мини принтер",
                "keyword_order": 1,
                "catalog_position_absolute": 5,
                "competitor_title": "A",
                "competitor_product_url": "u1",
                "competitor_price_promo": 5000.0,
                "competitor_price_regular": 6000.0,
                "competitor_rating": 4.9,
                "competitor_feedbacks": 100,
                "price_delta_percent": 1.0,
                "within_price_segment": False,
                "passed_hard_filters": True,
                "filter_mode": "market_competitor",
                "market_price_median": 5000.0,
                "hard_filter_flags_json": {"structural_compatible": True, "market_price_min": 4800.0, "market_price_p25": 4900.0, "market_price_p75": 5100.0, "market_price_max": 5200.0},
                "llm_status": "success",
                "relevance_score": 0.91,
                "relevance_verdict": True,
                "vision_status": "success",
                "vision_grade": "close_analog",
            },
            {
                "competitor_nm_id": 20,
                "keyword": "мини принтер",
                "keyword_order": 1,
                "catalog_position_absolute": 5,
                "competitor_title": "B",
                "competitor_product_url": "u2",
                "competitor_price_promo": 5000.0,
                "competitor_price_regular": 6000.0,
                "competitor_rating": 4.9,
                "competitor_feedbacks": 100,
                "price_delta_percent": 1.0,
                "within_price_segment": False,
                "passed_hard_filters": True,
                "filter_mode": "market_competitor",
                "market_price_median": 5000.0,
                "hard_filter_flags_json": {"structural_compatible": True, "market_price_min": 4800.0, "market_price_p25": 4900.0, "market_price_p75": 5100.0, "market_price_max": 5200.0},
                "llm_status": "success",
                "relevance_score": 0.91,
                "relevance_verdict": True,
                "vision_status": "success",
                "vision_grade": "absolute_analog",
            },
        ]
        summary = summarize_competitors(rows, source_price_promo=5100.0, limit=1, threshold=0.75)
        self.assertEqual(summary["competitors_json"][0]["competitor_nm_id"], 20)
        self.assertEqual(summary["vision_absolute_count"], 1)
        self.assertEqual(summary["competitor_selection_mode"], "structural_market")
        self.assertFalse(summary["used_market_fallback"])
        self.assertEqual(summary["market_price_median"], 5000.0)

    def test_summarize_strict_competitors_matches_selected_strict_path(self) -> None:
        rows = [
            {
                "competitor_nm_id": 10,
                "keyword": "патчи",
                "keyword_order": 1,
                "catalog_position_absolute": 5,
                "competitor_title": "A",
                "competitor_product_url": "u1",
                "competitor_price_promo": 950.0,
                "competitor_price_regular": 1000.0,
                "competitor_rating": 4.9,
                "competitor_feedbacks": 100,
                "price_delta_percent": -5.0,
                "within_price_segment": True,
                "passed_hard_filters": True,
                "filter_mode": "strict",
                "market_price_median": 940.0,
                "hard_filter_flags_json": {
                    "structural_compatible": True,
                    "within_price_segment": True,
                    "market_price_min": 900.0,
                    "market_price_p25": 920.0,
                    "market_price_p75": 980.0,
                    "market_price_max": 1000.0,
                },
                "llm_status": "success",
                "relevance_score": 0.91,
                "relevance_verdict": True,
                "vision_status": "success",
                "vision_grade": "close_analog",
            },
        ]
        summary = summarize_competitors(rows, source_price_promo=1000.0, limit=20, threshold=0.75)
        strict_summary = summarize_strict_competitors(rows, source_price_promo=1000.0, limit=20, threshold=0.75)
        self.assertEqual(summary["competitor_count"], 1)
        self.assertEqual(strict_summary["strict_competitor_count"], 1)
        self.assertEqual(summary["competitor_price_median"], strict_summary["strict_competitor_price_median"])

    def test_summarize_strict_competitors_is_empty_for_outlier_only_rows(self) -> None:
        rows = [
            {
                "competitor_nm_id": 20,
                "keyword": "патчи",
                "keyword_order": 1,
                "catalog_position_absolute": 3,
                "competitor_title": "B",
                "competitor_product_url": "u2",
                "competitor_price_promo": 450.0,
                "competitor_price_regular": 1000.0,
                "competitor_rating": 4.8,
                "competitor_feedbacks": 90,
                "price_delta_percent": -79.0,
                "within_price_segment": False,
                "passed_hard_filters": True,
                "filter_mode": "expanded_outlier",
                "market_price_median": 385.0,
                "hard_filter_flags_json": {
                    "structural_compatible": True,
                    "within_price_segment": False,
                    "market_price_min": 122.0,
                    "market_price_p25": 214.0,
                    "market_price_p75": 477.0,
                    "market_price_max": 1112.0,
                },
                "llm_status": "success",
                "relevance_score": 0.81,
                "relevance_verdict": True,
                "vision_status": None,
                "vision_grade": None,
            },
        ]
        summary = summarize_competitors(rows, source_price_promo=2158.0, limit=20, threshold=0.75)
        strict_summary = summarize_strict_competitors(rows, source_price_promo=2158.0, limit=20, threshold=0.75)
        self.assertEqual(summary["competitor_selection_mode"], "structural_market")
        self.assertEqual(summary["competitor_count"], 1)
        self.assertEqual(strict_summary["strict_competitor_count"], 0)
        self.assertIsNone(strict_summary["strict_competitor_price_median"])

    def test_summarize_strict_competitors_uses_hard_filter_fallback(self) -> None:
        rows = [
            {
                "competitor_nm_id": 30,
                "keyword": "патчи",
                "keyword_order": 1,
                "catalog_position_absolute": 7,
                "competitor_title": "C",
                "competitor_product_url": "u3",
                "competitor_price_promo": 980.0,
                "competitor_price_regular": 1200.0,
                "competitor_rating": 4.7,
                "competitor_feedbacks": 80,
                "price_delta_percent": -2.0,
                "within_price_segment": True,
                "passed_hard_filters": False,
                "filter_mode": "rejected",
                "market_price_median": 970.0,
                "hard_filter_flags_json": {
                    "structural_compatible": True,
                    "within_price_segment": True,
                },
                "llm_status": "failed",
                "relevance_score": None,
                "relevance_verdict": None,
                "vision_status": None,
                "vision_grade": None,
            },
        ]
        strict_summary = summarize_strict_competitors(rows, source_price_promo=1000.0, limit=20, threshold=0.75)
        self.assertEqual(strict_summary["strict_competitor_count"], 1)
        self.assertTrue(strict_summary["strict_used_llm_fallback"])

    def test_vision_stage_skips_when_filter_failed(self) -> None:
        result = run_vision_one(
            {
                "run_date": "2026-03-16",
                "source_nm_id": 123,
                "filter_status": "failed",
            }
        )
        self.assertEqual(result["vision_status"], "skipped_missing_filter")


if __name__ == "__main__":
    unittest.main()
