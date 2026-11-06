from ML.targets import (
    apply_sales_forecast_cap,
    build_formula_reason_bundle,
    build_formula_v2_reason_bundle,
    compute_confidence_label,
    compute_confidence_score,
    compute_delta_pct,
    compute_formula_forecast_7d,
    compute_formula_v2_forecast_7d,
    compute_sales_baseline_7d,
    compute_sales_forecast_cap_7d,
    compute_trend_label,
    compute_trend_ratio,
)


def test_compute_delta_pct_handles_zero_baseline():
    assert compute_delta_pct(5.0, 0.0) is None
    assert compute_delta_pct(12.0, 10.0) == 20.0


def test_compute_trend_label_for_growth_decline_and_flat():
    assert compute_trend_label(14.0, 10.0, relative_threshold=0.15) == "growth"
    assert compute_trend_label(8.0, 10.0, relative_threshold=0.15) == "decline"
    assert compute_trend_label(10.5, 10.0, relative_threshold=0.15) == "flat"
    assert compute_trend_label(2.0, 0.0) == "growth"
    assert compute_trend_label(0.0, 0.0) == "flat"


def test_compute_sales_baseline_and_trend_ratio():
    baseline = compute_sales_baseline_7d(3.0, 12.0, 17.0, 1.1786)
    assert baseline == 10.1251
    assert compute_trend_ratio(19.5483, baseline) == 0.930677


def test_compute_sales_forecast_cap_and_apply_cap():
    cap = compute_sales_forecast_cap_7d(3.0, 12.0, 17.0, 1.1786, multiplier=1.35)
    assert cap == 22.95
    assert apply_sales_forecast_cap(30.0, cap) == 22.95
    assert apply_sales_forecast_cap(19.0, cap) == 19.0


def test_compute_formula_forecast_and_reason_bundle():
    forecast = compute_formula_forecast_7d(3.0, 12.0, 17.0, 1.1786)
    assert forecast == 7.2751
    summary, reason_1, reason_2 = build_formula_reason_bundle(
        3.0,
        12.0,
        17.0,
        1.1786,
        1.467,
        forecast,
        compute_sales_baseline_7d(3.0, 12.0, 17.0, 1.1786),
    )
    assert "снижение" in summary.lower()
    assert "ниже исторической базы" in reason_1.lower()
    assert reason_2


def test_compute_formula_v2_forecast_and_reason_bundle():
    baseline = compute_sales_baseline_7d(3.0, 12.0, 17.0, 1.1786)
    forecast = compute_formula_v2_forecast_7d(3.0, 12.0, 17.0, 1.1786)
    assert forecast == 8.8876
    assert baseline * 0.70 <= forecast <= baseline * 1.10
    summary, reason_1, reason_2 = build_formula_v2_reason_bundle(
        3.0,
        12.0,
        17.0,
        1.1786,
        forecast,
        baseline,
    )
    assert "историчес" in summary.lower()
    assert reason_1
    assert reason_2


def test_compute_confidence_score_and_label():
    stable_score = compute_confidence_score([10.0, 10.0, 10.0, 10.0, 10.0])
    unstable_score = compute_confidence_score([0.0, 5.0, 10.0, 15.0, 20.0])
    assert stable_score > unstable_score
    assert compute_confidence_label(stable_score) == "high"
