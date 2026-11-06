"""Feature loading and matrix preparation for 1pager ML."""
from __future__ import annotations

from typing import Iterable

import pandas as pd

try:
    from config import Config
except ImportError:  # pragma: no cover
    from .config import Config


def feature_columns_from_frame(df: pd.DataFrame) -> list[str]:
    configured = [column for column in Config.SALES_FEATURE_COLUMNS if column in df.columns]
    if configured:
        return configured
    excluded = set(Config.NON_FEATURE_COLUMNS)
    return [column for column in df.columns if column not in excluded]


def normalize_feature_frame(df: pd.DataFrame, feature_columns: Iterable[str]) -> pd.DataFrame:
    feature_columns = list(feature_columns)
    normalized = df.copy()
    for column in feature_columns:
        if column not in normalized.columns:
            normalized[column] = 0
    normalized = normalized[feature_columns]
    normalized = normalized.apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return normalized


def split_train_holdout(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df.copy(), df.copy()
    unique_dates = sorted(df["report_date"].dropna().unique())
    if len(unique_dates) < 2:
        return df.copy(), df.iloc[0:0].copy()

    holdout_dates_count = min(Config.HOLDOUT_DAYS, max(1, len(unique_dates) // 5))
    holdout_dates = set(unique_dates[-holdout_dates_count:])
    holdout_df = df[df["report_date"].isin(holdout_dates)].copy()
    train_df = df[~df["report_date"].isin(holdout_dates)].copy()
    if train_df.empty:
        train_df = df.iloc[:-1].copy()
        holdout_df = df.iloc[-1:].copy()
    return train_df, holdout_df
