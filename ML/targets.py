"""Target interpretation helpers for 1pager ML forecasts."""
from __future__ import annotations

from statistics import median
from typing import Sequence

import numpy as np

try:
    from config import Config
except ImportError:  # pragma: no cover
    from .config import Config


def compute_delta_pct(predicted_value: float, baseline_value: float) -> float | None:
    if baseline_value == 0:
        return None
    return round((predicted_value - baseline_value) / baseline_value * 100.0, 4)


def compute_sales_baseline_7d(
    sales_lag_1w: float,
    sales_lag_2w: float,
    sales_lag_4w: float,
    sales_rolling_4w_avg: float,
) -> float:
    candidates = [
        float(sales_lag_1w or 0.0),
        float(sales_lag_2w or 0.0),
        float(sales_lag_4w or 0.0),
        float(sales_rolling_4w_avg or 0.0) * 7.0,
    ]
    positive_candidates = [value for value in candidates if value > 0]
    baseline = median(positive_candidates) if positive_candidates else 0.0
    return round(float(baseline), 4)


def compute_sales_forecast_cap_7d(
    sales_lag_1w: float,
    sales_lag_2w: float,
    sales_lag_4w: float,
    sales_rolling_4w_avg: float,
    *,
    multiplier: float | None = None,
) -> float:
    multiplier = multiplier if multiplier is not None else Config.SALES_FORECAST_CAP_MULTIPLIER
    candidates = [
        float(sales_lag_1w or 0.0),
        float(sales_lag_2w or 0.0),
        float(sales_lag_4w or 0.0),
        float(sales_rolling_4w_avg or 0.0) * 7.0,
    ]
    positive_candidates = [value for value in candidates if value > 0]
    if not positive_candidates:
        return round(float(Config.ZERO_BASELINE_GROWTH_THRESHOLD), 4)
    return round(float(max(positive_candidates) * multiplier), 4)


def apply_sales_forecast_cap(predicted_value: float, forecast_cap_7d: float) -> float:
    if forecast_cap_7d <= 0:
        return round(max(0.0, predicted_value), 4)
    return round(min(max(0.0, predicted_value), forecast_cap_7d), 4)


def compute_formula_forecast_7d(
    sales_lag_1w: float,
    sales_lag_2w: float,
    sales_lag_4w: float,
    sales_rolling_4w_avg: float,
) -> float:
    baseline = compute_sales_baseline_7d(
        sales_lag_1w,
        sales_lag_2w,
        sales_lag_4w,
        sales_rolling_4w_avg,
    )
    if baseline <= 0:
        return 0.0
    forecast_raw = 0.60 * baseline + 0.40 * float(sales_lag_1w or 0.0)
    positive_candidates = [
        value
        for value in (
            float(sales_lag_1w or 0.0),
            float(sales_lag_2w or 0.0),
            float(sales_lag_4w or 0.0),
            float(sales_rolling_4w_avg or 0.0) * 7.0,
        )
        if value > 0
    ]
    forecast_high = max(positive_candidates) * 1.15 if positive_candidates else 0.0
    forecast_low = min(positive_candidates) * 0.85 if positive_candidates else 0.0
    if forecast_high <= 0:
        return 0.0
    if forecast_low > forecast_high:
        forecast_low = forecast_high
    return round(float(min(max(forecast_raw, forecast_low), forecast_high)), 4)


def build_formula_reason_bundle(
    sales_lag_1w: float,
    sales_lag_2w: float,
    sales_lag_4w: float,
    sales_rolling_4w_avg: float,
    sales_rolling_4w_std: float,
    forecast_7d: float,
    baseline_7d: float,
) -> tuple[str, str, str]:
    trend_label = compute_trend_label(
        forecast_7d,
        baseline_7d,
        relative_threshold=Config.FORMULA_TREND_RELATIVE_THRESHOLD,
    )
    if baseline_7d <= 0:
        summary = "История продаж почти нулевая, поэтому формульный прогноз остается низким."
    elif trend_label == "growth":
        summary = "Формульный sales-trend указывает на рост относительно исторической базы."
    elif trend_label == "decline":
        summary = "Формульный sales-trend указывает на снижение относительно исторической базы."
    else:
        summary = "Формульный sales-trend близок к исторической базе без сильного сдвига."

    if baseline_7d <= 0:
        reason_1 = "В исторических weekly sales почти нет устойчивой базы."
    else:
        recent_ratio = float(sales_lag_1w or 0.0) / baseline_7d
        if recent_ratio >= 1.2:
            reason_1 = "Последняя неделя продаж выше исторической базы."
        elif recent_ratio <= 0.8:
            reason_1 = "Последняя неделя продаж ниже исторической базы."
        else:
            reason_1 = "Последняя неделя продаж близка к исторической базе."

    sales_lag_2w = float(sales_lag_2w or 0.0)
    sales_lag_1w = float(sales_lag_1w or 0.0)
    if sales_lag_2w > 0 and sales_lag_1w >= sales_lag_2w * 1.15:
        reason_2 = "Есть ускорение относительно периода двухнедельной давности."
    elif sales_lag_2w > 0 and sales_lag_1w <= sales_lag_2w * 0.85:
        reason_2 = "Есть замедление относительно периода двухнедельной давности."
    else:
        if float(sales_rolling_4w_avg or 0.0) > 0 and float(sales_rolling_4w_std or 0.0) >= float(sales_rolling_4w_avg or 0.0) * 0.75:
            reason_2 = "sales волатильны, поэтому прогноз удержан консервативно."
        else:
            reason_2 = "История продаж достаточно стабильна без резких скачков."

    return summary, reason_1, reason_2


def compute_formula_v2_forecast_7d(
    sales_lag_1w: float,
    sales_lag_2w: float,
    sales_lag_4w: float,
    sales_rolling_4w_avg: float,
) -> float:
    baseline = compute_sales_baseline_7d(
        sales_lag_1w,
        sales_lag_2w,
        sales_lag_4w,
        sales_rolling_4w_avg,
    )
    if baseline <= 0:
        return 0.0
    forecast_raw = (
        0.70 * baseline
        + 0.20 * float(sales_lag_1w or 0.0)
        + 0.10 * float(sales_lag_2w or 0.0)
    )
    forecast_low = baseline * Config.FORMULA_V2_LOW_MULTIPLIER
    forecast_high = baseline * Config.FORMULA_V2_HIGH_MULTIPLIER
    if forecast_low > forecast_high:
        forecast_low = forecast_high
    return round(float(min(max(forecast_raw, forecast_low), forecast_high)), 4)


def build_formula_v2_reason_bundle(
    sales_lag_1w: float,
    sales_lag_2w: float,
    sales_lag_4w: float,
    sales_rolling_4w_avg: float,
    forecast_7d: float,
    baseline_7d: float,
) -> tuple[str, str, str]:
    trend_label = compute_trend_label(
        forecast_7d,
        baseline_7d,
        relative_threshold=Config.FORMULA_TREND_RELATIVE_THRESHOLD,
    )
    if baseline_7d <= 0:
        summary = "Консервативная V2-формула удерживает прогноз низким из-за почти пустой истории продаж."
    elif trend_label == "growth":
        summary = "Консервативная V2-формула допускает умеренный рост относительно исторической базы."
    elif trend_label == "decline":
        summary = "Консервативная V2-формула указывает на снижение относительно исторической базы."
    else:
        summary = "Консервативная V2-формула оставляет продажи около исторической базы."

    sales_lag_1w = float(sales_lag_1w or 0.0)
    sales_lag_2w = float(sales_lag_2w or 0.0)
    sales_lag_4w = float(sales_lag_4w or 0.0)
    if baseline_7d <= 0:
        reason_1 = "Исторической sales-базы почти нет, поэтому рост не разгоняется."
    elif sales_lag_1w <= baseline_7d * 0.85:
        reason_1 = "Последняя неделя продаж заметно слабее исторической базы."
    elif sales_lag_1w >= baseline_7d * 1.15:
        reason_1 = "Последняя неделя продаж выше исторической базы."
    else:
        reason_1 = "Последняя неделя продаж близка к исторической базе."

    if sales_lag_2w > 0 and sales_lag_1w <= sales_lag_2w * 0.85:
        reason_2 = "V2 учитывает замедление относительно двухнедельного окна."
    elif sales_lag_2w > 0 and sales_lag_1w >= sales_lag_2w * 1.15:
        reason_2 = "V2 учитывает ускорение относительно двухнедельного окна."
    elif sales_lag_4w > 0 and sales_lag_1w <= sales_lag_4w * 0.85:
        reason_2 = "Последняя неделя также ниже месячного sales-ориентира."
    else:
        reason_2 = "V2 ограничивает прогноз коридором вокруг исторической базы."

    return summary, reason_1, reason_2


def compute_trend_ratio(predicted_buyouts_7d: float, sales_baseline_7d: float) -> float | None:
    if sales_baseline_7d <= 0:
        return None
    return round((predicted_buyouts_7d - sales_baseline_7d) / sales_baseline_7d, 6)


def compute_trend_label(
    predicted_buyouts_7d: float,
    sales_baseline_7d: float,
    *,
    relative_threshold: float | None = None,
) -> str:
    relative_threshold = relative_threshold if relative_threshold is not None else Config.TREND_RELATIVE_THRESHOLD

    if sales_baseline_7d <= 0:
        if predicted_buyouts_7d > Config.ZERO_BASELINE_GROWTH_THRESHOLD:
            return "growth"
        return "flat"

    relative_change = (predicted_buyouts_7d - sales_baseline_7d) / sales_baseline_7d
    if relative_change > relative_threshold:
        return "growth"
    if relative_change < -relative_threshold:
        return "decline"
    return "flat"


def compute_confidence_score(predictions: Sequence[float]) -> float:
    values = np.asarray(list(predictions), dtype=float)
    if values.size == 0:
        return 0.0
    mean_value = float(np.mean(values))
    std_value = float(np.std(values))
    scale = max(abs(mean_value), 1.0)
    dispersion = std_value / scale
    score = 1.0 / (1.0 + dispersion)
    return round(max(0.0, min(1.0, score)), 6)


def compute_confidence_label(confidence_score: float) -> str:
    if confidence_score >= Config.CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    if confidence_score >= Config.CONFIDENCE_MEDIUM_THRESHOLD:
        return "medium"
    return "low"
