from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "wb_price_ai_analysis"
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

sys.modules.pop("database", None)
sys.modules.pop("config", None)

from serp_snapshot import (  # noqa: E402
    _compatibility_rows,
    _downstream_payload,
    _source_site_price_context,
    choose_queries,
    deterministic_batch_id,
    deterministic_run_id,
    is_own_brand_query,
    is_query_relevant,
    local_seo_fallback,
    normalize_query,
    select_queries_per_sku,
)

sys.modules.pop("database", None)
sys.modules.pop("config", None)
if str(MODULE_DIR) in sys.path:
    sys.path.remove(str(MODULE_DIR))


def test_query_selection_prioritizes_orders_then_frequency_and_fills_with_seo() -> None:
    selected = choose_queries(
        [
            {"query": "Сыворотка для лица", "orders_7d": 4, "frequency": 100},
            {"query": "Крем для лица", "orders_7d": 0, "frequency": 500},
        ],
        ["сыворотка для лица", "косметика для лица", "уход за кожей"],
        limit=4,
    )

    assert [row["query_source"] for row in selected] == ["orders", "frequency", "seo", "seo"]
    assert [row["query_rank"] for row in selected] == [1, 2, 3, 4]
    assert selected[2]["query_normalized"] == "косметика для лица"


def test_query_selection_marks_pure_seo_as_stale_fallback() -> None:
    selected = choose_queries([], ["Патчи для глаз", "патчи  для глаз"], limit=5)
    assert len(selected) == 1
    assert selected[0]["query_source"] == "seo_fallback_stale"


def test_deterministic_ids_are_stable_and_query_specific() -> None:
    batch_a = deterministic_batch_id("tenant-a", "2026-07-20T10:30:00+03:00")
    batch_b = deterministic_batch_id("tenant-a", "2026-07-20T10:30:00+03:00")
    assert batch_a == batch_b
    assert deterministic_run_id(batch_a, 1, "патчи") == deterministic_run_id(batch_a, 1, "патчи")
    assert deterministic_run_id(batch_a, 1, "патчи") != deterministic_run_id(batch_a, 1, "сыворотка")


def test_normalize_query_collapses_case_and_spaces() -> None:
    assert normalize_query("  Патчи   Для Глаз ") == "патчи для глаз"


def test_local_seo_fallback_uses_title_subject_and_brand() -> None:
    assert local_seo_fallback(
        {
            "source_title": "Крем для лица",
            "source_subject_name": "Кремы",
            "source_brand": "LIFECODE",
        }
    ) == ["Крем для лица", "Кремы"]


def test_query_selection_excludes_own_brand_from_real_and_seo_queries() -> None:
    selected = choose_queries(
        [
            {"query": "lifecode", "orders_7d": 5, "frequency": 200},
            {"query": "LIFECODE сыворотка для лица", "orders_7d": 2, "frequency": 100},
            {"query": "лайфкод сыворотка", "orders_7d": 1, "frequency": 90},
            {"query": "70194686", "orders_7d": 1, "frequency": 85},
            {"query": "сыворотка с гиалуроновой кислотой", "orders_7d": 1, "frequency": 80},
        ],
        ["крем LIFECODE", "антивозрастная сыворотка", "сыворотка для лица"],
        limit=2,
        excluded_brands=["LIFECODE", "лайфкод"],
        excluded_queries=[70194686],
    )

    assert [row["query"] for row in selected] == [
        "сыворотка с гиалуроновой кислотой",
        "антивозрастная сыворотка",
    ]
    assert is_own_brand_query("крем lifecode для лица", ["LIFECODE"])
    assert not is_own_brand_query("крем для лица", ["LIFECODE"])


def test_query_relevance_rejects_unrelated_report_noise() -> None:
    reference = ["Сыворотка для лица биоактивная лифтинг-эффект", "Сыворотки"]
    assert is_query_relevant("сыворотка с гиалуроновой кислотой", reference)
    assert is_query_relevant("лифтинг сыворотка", reference)
    assert not is_query_relevant("пилинг с салициловой кислотой для лица", reference)
    assert not is_query_relevant("holton", reference)


def test_select_queries_reuses_frozen_set_without_generating(monkeypatch) -> None:
    frozen_specs = [
        {
            "query": "сыворотка с гиалуроновой кислотой",
            "query_normalized": "сыворотка с гиалуроновой кислотой",
            "query_source": "frequency",
            "query_orders_7d": 0.0,
            "query_frequency": 74.0,
            "query_rank": 1,
        }
    ]

    class FakeDatabase:
        def connect(self) -> None:
            pass

        def close(self) -> None:
            pass

        def get_serp_query_set(self, source_nm_id: int):
            assert source_nm_id == 70194686
            return {
                "query_specs": frozen_specs,
                "created_at": "2026-07-20T13:15:47+00:00",
                "frozen_from_batch_id": "ab698a40-8c7f-5755-ab3d-09f8e69c94cb",
            }

        def get_recent_real_queries(self, source_nm_id: int, max_age_days: int):
            raise AssertionError("daily query selection must not run for a frozen SKU")

    monkeypatch.setitem(
        select_queries_per_sku.__globals__,
        "WBPriceAIAnalysisDatabase",
        FakeDatabase,
    )
    selected = select_queries_per_sku({"source_nm_id": 70194686})

    assert selected["query_specs"] == frozen_specs
    assert selected["query_set_mode"] == "frozen"
    assert selected["query_count"] == 1


def test_compatibility_projection_keeps_only_cards_above_organic_source() -> None:
    payload = {
        "observed_at": "2026-07-22T10:30:00+03:00",
        "source_nm_id": 70194686,
        "source_price_promo": None,
        "source_barcodes_json": [],
        "source_subject_name": "Сыворотки",
    }
    spec = {"query": "сыворотка с мочевиной", "query_rank": 1}
    items = [
        {"is_source": False, "result_nm_id": 10, "position_absolute": 1, "position_on_page": 1, "catalog_page": 1, "placement_type": "organic", "price_effective": 500.0, "price_regular": 700.0},
        {"is_source": True, "result_nm_id": 70194686, "position_absolute": 2, "position_on_page": 2, "catalog_page": 1, "placement_type": "organic", "price_effective": 3000.0, "price_regular": 3500.0},
        {"is_source": False, "result_nm_id": 20, "position_absolute": 3, "position_on_page": 3, "catalog_page": 1, "placement_type": "organic", "price_effective": 600.0, "price_regular": 800.0},
    ]

    rows = _compatibility_rows(payload, spec, items)

    assert [row["competitor_nm_id"] for row in rows] == [10]
    assert rows[0]["source_price_promo"] == 3000.0
    assert rows[0]["within_price_segment"] is False


def test_compatibility_projection_prefers_public_serp_source_price() -> None:
    rows = _compatibility_rows(
        {
            "observed_at": "2026-07-22T10:30:00+03:00",
            "source_nm_id": 1,
            "source_price_promo": 5739.20,
            "source_price_regular": 8440.0,
            "source_barcodes_json": [],
        },
        {"query": "сыворотка", "query_rank": 1},
        [
            {
                "is_source": False,
                "result_nm_id": 2,
                "position_absolute": 1,
                "position_on_page": 1,
                "catalog_page": 1,
                "placement_type": "organic",
                "price_effective": 2920.0,
            },
            {
                "is_source": True,
                "result_nm_id": 1,
                "position_absolute": 2,
                "position_on_page": 2,
                "catalog_page": 1,
                "placement_type": "organic",
                "price_effective": 3380.0,
                "price_regular": 8440.0,
            },
        ],
    )

    assert rows[0]["source_price_promo"] == 3380.0
    assert rows[0]["price_delta_percent"] == -13.61
    assert rows[0]["within_price_segment"] is True


def test_compatibility_projection_is_empty_when_source_not_found() -> None:
    rows = _compatibility_rows(
        {"observed_at": "2026-07-22T10:30:00+03:00", "source_nm_id": 1, "source_price_promo": 1000},
        {"query": "крем", "query_rank": 1},
        [{"is_source": False, "result_nm_id": 2, "position_absolute": 1, "placement_type": "organic"}],
    )
    assert rows == []


def test_downstream_payload_preserves_source_and_marks_raw_success() -> None:
    result = _downstream_payload(
        {
            "source_nm_id": 1,
            "source_price_promo": 1000.0,
            "query_specs": [{"query": "крем для лица"}],
        },
        {"status": "completed", "compatibility_rows_written": 12},
    )
    assert result["source_price_promo"] == 1000.0
    assert result["keywords_json"] == ["крем для лица"]
    assert result["raw_status"] == "success"
    assert result["raw_rows_written"] == 12


def test_downstream_payload_keeps_report_price_and_separates_public_price() -> None:
    result = _downstream_payload(
        {
            "source_nm_id": 1,
            "source_price_promo": 5739.20,
            "source_price_site_display": 3449.0,
            "source_price_site_wallet": 3380.0,
            "source_platform_discount_percent": 39.9045,
            "source_wallet_discount_percent": 2.0006,
            "source_report_to_site_discount_percent": 41.1068,
            "query_specs": [{"query": "крем для лица"}],
        },
        {
            "status": "completed",
            "compatibility_rows_written": 1,
            "source_price_promo": 3380.0,
            "source_price_site_wallet": 3380.0,
            "source_platform_discount_percent": None,
            "source_report_to_site_discount_percent": None,
        },
    )

    assert result["source_price_promo"] == 5739.20
    assert result["source_price_site_display"] == 3449.0
    assert result["source_price_site_wallet"] == 3380.0
    assert result["source_platform_discount_percent"] == 39.9045
    assert result["source_wallet_discount_percent"] == 2.0006
    assert result["source_report_to_site_discount_percent"] == 41.1068


def test_source_site_price_context_separates_platform_and_wallet_discounts() -> None:
    context = _source_site_price_context(
        5739.20,
        [3449.0, 3449.0],
        [3380.0, 3380.0],
        [3380.0, 3380.0],
    )

    assert context["source_price_site_display"] == 3449.0
    assert context["source_price_site_wallet"] == 3380.0
    assert context["source_platform_discount_percent"] == 39.9045
    assert context["source_wallet_discount_percent"] == 2.0006
    assert context["source_report_to_site_discount_percent"] == 41.1068
