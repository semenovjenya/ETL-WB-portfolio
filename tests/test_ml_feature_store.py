import pandas as pd

from ML.feature_store import feature_columns_from_frame


def test_feature_columns_from_frame_prefers_sales_only_columns():
    frame = pd.DataFrame(
        [
            {
                "report_date": "2026-03-26",
                "id": 1,
                "sku": "46225",
                "buyouts_1d": 1,
                "buyouts_7d": 7,
                "buyouts_28d_avg_per_day": 1.0,
                "sales_lag_1w": 3,
                "sales_lag_2w": 12,
                "sales_lag_4w": 17,
                "sales_rolling_4w_avg": 1.1786,
                "sales_rolling_4w_std": 1.467,
                "open_count": 50,
                "target_buyouts_next_7d": 10,
            }
        ]
    )

    assert feature_columns_from_frame(frame) == [
        "buyouts_1d",
        "buyouts_7d",
        "buyouts_28d_avg_per_day",
        "sales_lag_1w",
        "sales_lag_2w",
        "sales_lag_4w",
        "sales_rolling_4w_avg",
        "sales_rolling_4w_std",
    ]


def test_unverified_historical_ratings_never_enter_feature_fallback():
    frame = pd.DataFrame([{"report_date": "2026-09-01", "product_rating": None,
                           "feedback_rating": 4.8, "open_count": 50}])
    assert feature_columns_from_frame(frame) == ["open_count"]
