"""Configuration for 1pager ML forecasting."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

for env_file in (PROJECT_ROOT / ".env", PROJECT_ROOT / "API WB" / ".env"):
    if env_file.exists():
        load_dotenv(env_file)
        break


def _parse_db_from_url(url: Optional[str]) -> dict[str, object]:
    if not url:
        return {}
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return {
            "host": parsed.hostname,
            "port": parsed.port,
            "dbname": (parsed.path or "").lstrip("/"),
            "user": parsed.username,
            "password": parsed.password,
        }
    except Exception:
        return {}


class Config:
    DB_URL: Optional[str] = os.getenv("DATABASE_URL") or os.getenv("PG_DSN")
    _db_from_url = _parse_db_from_url(DB_URL)
    DB_HOST: Optional[str] = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or _db_from_url.get("host")
    DB_PORT: int = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or _db_from_url.get("port") or "5432")
    DB_NAME: Optional[str] = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB") or _db_from_url.get("dbname")
    DB_USER: Optional[str] = os.getenv("DB_USER") or os.getenv("POSTGRES_USER") or _db_from_url.get("user")
    DB_PASSWORD: Optional[str] = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or _db_from_url.get("password")

    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL: Optional[str] = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")

    TRAIN_VIEW: str = "analytics_ai.v_1pager_ml_train"
    SERVING_VIEW: str = "reports.v_1pager_ml"
    FORECAST_TABLE: str = "analytics_ai.wb_ml_forecast_daily"
    EXPLANATION_TABLE: str = "analytics_ai.wb_ml_forecast_explanations"
    FORECAST_VIEW: str = "reports.v_1pager_ml_forecast"

    BUYOUTS_TARGET: str = "target_buyouts_next_7d"
    ORDERS_TARGET: str = "target_orders_next_7d"
    TARGET_COLUMNS: tuple[str, ...] = (
        "target_orders_next_1d",
        "target_buyouts_next_1d",
        "target_orders_next_7d",
        "target_buyouts_next_7d",
        "target_orders_next_14d",
        "target_buyouts_next_14d",
        "target_orders_next_21d",
        "target_buyouts_next_21d",
        "target_orders_next_31d",
        "target_buyouts_next_31d",
    )
    NON_FEATURE_COLUMNS: tuple[str, ...] = (
        # Metadata rating has no verified historical observation time/lineage.
        # Keep it out even when the sales-only feature fallback is used.
        "product_rating",
        "feedback_rating",
        "report_date",
        "id",
        "sku",
        "last_supply_date",
        "target_ready_7d_flag",
        "target_ready_14d_flag",
        "target_ready_21d_flag",
        "target_ready_31d_flag",
        *TARGET_COLUMNS,
    )
    SALES_FEATURE_COLUMNS: tuple[str, ...] = (
        "buyouts_1d",
        "buyouts_7d",
        "buyouts_28d_avg_per_day",
        "sales_lag_1w",
        "sales_lag_2w",
        "sales_lag_4w",
        "sales_rolling_4w_avg",
        "sales_rolling_4w_std",
    )

    ENSEMBLE_SEEDS: tuple[int, ...] = (13, 29, 43, 71, 101)
    TREND_RELATIVE_THRESHOLD: float = float(os.getenv("WB_1PAGER_ML_TREND_RELATIVE_THRESHOLD", "0.15"))
    FORMULA_TREND_RELATIVE_THRESHOLD: float = float(os.getenv("WB_1PAGER_ML_FORMULA_TREND_RELATIVE_THRESHOLD", "0.20"))
    ZERO_BASELINE_GROWTH_THRESHOLD: float = float(os.getenv("WB_1PAGER_ML_ZERO_BASELINE_GROWTH_THRESHOLD", "1.0"))
    USE_LOG1P_TARGET: bool = os.getenv("WB_1PAGER_ML_USE_LOG1P_TARGET", "1") != "0"
    SALES_FORECAST_CAP_MULTIPLIER: float = float(os.getenv("WB_1PAGER_ML_SALES_FORECAST_CAP_MULTIPLIER", "1.35"))
    FORMULA_V2_LOW_MULTIPLIER: float = float(os.getenv("WB_1PAGER_ML_FORMULA_V2_LOW_MULTIPLIER", "0.70"))
    FORMULA_V2_HIGH_MULTIPLIER: float = float(os.getenv("WB_1PAGER_ML_FORMULA_V2_HIGH_MULTIPLIER", "1.10"))
    CONFIDENCE_HIGH_THRESHOLD: float = float(os.getenv("WB_1PAGER_ML_CONFIDENCE_HIGH_THRESHOLD", "0.75"))
    CONFIDENCE_MEDIUM_THRESHOLD: float = float(os.getenv("WB_1PAGER_ML_CONFIDENCE_MEDIUM_THRESHOLD", "0.50"))
    HOLDOUT_DAYS: int = int(os.getenv("WB_1PAGER_ML_HOLDOUT_DAYS", "14"))
    MODEL_VERSION_PREFIX: str = os.getenv("WB_1PAGER_ML_MODEL_VERSION_PREFIX", "1pager_ml_7d")

    EXPLAIN_MODEL: str = os.getenv("WB_1PAGER_ML_EXPLAIN_MODEL", "gpt-4o-mini")
    EXPLAIN_TIMEOUT_SEC: float = float(os.getenv("WB_1PAGER_ML_EXPLAIN_TIMEOUT_SEC", "60"))
    EXPLAIN_MAX_TOKENS: int = int(os.getenv("WB_1PAGER_ML_EXPLAIN_MAX_TOKENS", "300"))
    EXPLAIN_PROMPT_VERSION: str = os.getenv("WB_1PAGER_ML_EXPLAIN_PROMPT_VERSION", "v1")

    EXPLAIN_FIELDS: tuple[str, ...] = (
        "sku",
        "qty_on_stock",
        "days_of_stock",
        "pending_supply_qty",
        "price_before_discount",
        "price_after_discount",
        "discount_pct",
        "spp_pct",
        "price_change_pct",
        "net_profit_per_unit",
        "orders_1d",
        "buyouts_1d",
        "buyouts_7d",
        "buyouts_28d_avg_per_day",
        "sales_lag_1w",
        "sales_lag_2w",
        "sales_lag_4w",
        "sales_rolling_4w_avg",
        "sales_rolling_4w_std",
        "open_count",
        "open_to_cart_pct",
        "cart_to_order_pct",
        "open_count_lag_1w",
        "open_count_rolling_7d",
        "in_promo_flag",
        "days_to_next_promo",
        "return_rate_30d",
        "has_active_campaign_flag",
        "adv_spend_day",
        "adv_orders_day",
        "adv_cpo",
        "adv_roas",
        "marketing_views_day",
        "marketing_clicks_day",
        "marketing_orders_day",
        "marketing_spend_day",
        "marketing_ctr_day",
        "marketing_cpc_day",
        "marketing_cr_day",
        "marketing_views_7d",
        "marketing_clicks_7d",
        "marketing_orders_7d",
        "marketing_spend_7d",
    )

    RUNTIME_ROOT: Path = Path(os.getenv("WB_RUNTIME_ROOT") or (PROJECT_ROOT / "runtime" / "local-ml"))
    ARTIFACT_DIR: Path = RUNTIME_ROOT / "artifacts"
    MODEL_META_PATH: Path = ARTIFACT_DIR / "model_meta.json"
    BUYOUTS_MODEL_PATH: Path = ARTIFACT_DIR / "buyouts_7d_model.pkl"
    ORDERS_MODEL_PATH: Path = ARTIFACT_DIR / "orders_7d_model.pkl"
    PROMPT_PATH: Path = BASE_DIR / "prompts" / "explain_forecast.txt"
    JSON_OUTPUT_DIR: Path = Path(os.getenv("WB_RUNTIME_JSON_OUTPUT_DIR") or (RUNTIME_ROOT / "json_data"))

    @classmethod
    def ensure_runtime_dirs(cls) -> None:
        cls.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        cls.JSON_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def validate_db(cls) -> None:
        missing = []
        if not cls.DB_HOST:
            missing.append("DB_HOST")
        if not cls.DB_NAME:
            missing.append("DB_NAME")
        if not cls.DB_USER:
            missing.append("DB_USER")
        if missing:
            raise ValueError(f"Missing DB configuration: {', '.join(missing)}")

    @classmethod
    def validate_openai(cls) -> None:
        if not cls.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for ML explanations")

    @classmethod
    def get_db_connection_string(cls) -> str:
        parts = [
            f"host={cls.DB_HOST}",
            f"port={cls.DB_PORT}",
            f"dbname={cls.DB_NAME}",
            f"user={cls.DB_USER}",
        ]
        if cls.DB_PASSWORD:
            parts.append(f"password={cls.DB_PASSWORD}")
        return " ".join(parts)

    @classmethod
    def dump_runtime_state(cls) -> str:
        payload = {
            "runtime_root": str(cls.RUNTIME_ROOT),
            "artifact_dir": str(cls.ARTIFACT_DIR),
            "buyouts_model_path": str(cls.BUYOUTS_MODEL_PATH),
            "orders_model_path": str(cls.ORDERS_MODEL_PATH),
            "model_meta_path": str(cls.MODEL_META_PATH),
        }
        return json.dumps(payload, ensure_ascii=False)
