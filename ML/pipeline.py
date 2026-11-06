"""Training and inference pipeline for 1pager ML forecasts."""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

try:  # pragma: no cover
    from lightgbm import LGBMRegressor  # type: ignore
except Exception:  # pragma: no cover
    LGBMRegressor = None

try:
    from config import Config
    from database import OnePagerMLDatabase
    from feature_store import feature_columns_from_frame, normalize_feature_frame, split_train_holdout
    from targets import (
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
except ImportError:  # pragma: no cover
    from .config import Config
    from .database import OnePagerMLDatabase
    from .feature_store import feature_columns_from_frame, normalize_feature_frame, split_train_holdout
    from .targets import (
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

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _artifact_path_for_target(target_name: str) -> Path:
    if target_name == Config.BUYOUTS_TARGET:
        return Config.BUYOUTS_MODEL_PATH
    if target_name == Config.ORDERS_TARGET:
        return Config.ORDERS_MODEL_PATH
    raise ValueError(f"Unsupported target: {target_name}")


def _build_regressor(seed: int):
    if LGBMRegressor is not None:
        return LGBMRegressor(
            n_estimators=400,
            learning_rate=0.05,
            max_depth=-1,
            num_leaves=31,
            subsample=0.9,
            colsample_bytree=0.8,
            random_state=seed,
            n_jobs=-1,
        ), "lightgbm"
    return HistGradientBoostingRegressor(
        learning_rate=0.05,
        max_depth=6,
        max_iter=400,
        l2_regularization=0.1,
        random_state=seed,
    ), "hist_gradient_boosting"


def _load_pickle(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return pickle.load(fh)


def _save_pickle(path: Path, payload: dict[str, Any]) -> None:
    with path.open("wb") as fh:
        pickle.dump(payload, fh)


def _read_model_meta() -> dict[str, Any]:
    if not Config.MODEL_META_PATH.exists():
        raise FileNotFoundError(f"Missing model metadata: {Config.MODEL_META_PATH}")
    return json.loads(Config.MODEL_META_PATH.read_text(encoding="utf-8"))


def _write_model_meta(payload: dict[str, Any]) -> dict[str, Any]:
    Config.MODEL_META_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _metrics_payload(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    if y_true.size == 0:
        return {"mae": None, "rmse": None, "row_count": 0}
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 6),
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 6),
        "row_count": int(y_true.size),
    }


def _inverse_target_transform(values: np.ndarray) -> np.ndarray:
    output = np.asarray(values, dtype=float)
    if Config.USE_LOG1P_TARGET:
        output = np.expm1(output)
    return np.maximum(output, 0.0)


def _source_features_hash(row: dict[str, Any]) -> str:
    feature_payload = {field: row.get(field) for field in Config.EXPLAIN_FIELDS}
    encoded = json.dumps(feature_payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def train_target_model(target_name: str) -> dict[str, Any]:
    Config.ensure_runtime_dirs()
    db = OnePagerMLDatabase()
    db.connect()
    try:
        frame = db.fetch_training_frame(target_name)
    finally:
        db.close()

    if frame.empty:
        raise ValueError(f"Training frame is empty for {target_name}")

    feature_columns = feature_columns_from_frame(frame)
    train_df, holdout_df = split_train_holdout(frame)
    if train_df.empty:
        raise ValueError(f"Training split is empty for {target_name}")

    x_train = normalize_feature_frame(train_df, feature_columns)
    y_train_raw = train_df[target_name].astype(float).to_numpy()
    y_train = np.log1p(y_train_raw) if Config.USE_LOG1P_TARGET else y_train_raw
    x_holdout = normalize_feature_frame(holdout_df, feature_columns) if not holdout_df.empty else holdout_df
    y_holdout = holdout_df[target_name].astype(float).to_numpy() if not holdout_df.empty else np.asarray([])

    models = []
    engine_name = None
    holdout_predictions = []
    for seed in Config.ENSEMBLE_SEEDS:
        model, engine_name = _build_regressor(seed)
        model.fit(x_train, y_train)
        models.append(model)
        if not holdout_df.empty:
            holdout_predictions.append(_inverse_target_transform(model.predict(x_holdout)))

    holdout_mean = np.mean(holdout_predictions, axis=0) if holdout_predictions else np.asarray([])
    artifact_payload = {
        "target_name": target_name,
        "feature_columns": feature_columns,
        "engine": engine_name,
        "seeds": list(Config.ENSEMBLE_SEEDS),
        "models": models,
        "target_transform": "log1p" if Config.USE_LOG1P_TARGET else "identity",
        "train_max_date": str(frame["report_date"].max()),
        "trained_at": _iso_now(),
        "metrics": _metrics_payload(y_holdout, holdout_mean),
        "train_row_count": int(len(train_df)),
        "holdout_row_count": int(len(holdout_df)),
    }
    artifact_path = _artifact_path_for_target(target_name)
    _save_pickle(artifact_path, artifact_payload)

    logger.info("Trained %s model: engine=%s rows=%s holdout_rows=%s", target_name, engine_name, len(train_df), len(holdout_df))
    return {
        "target_name": target_name,
        "artifact_path": str(artifact_path),
        "engine": engine_name,
        "metrics": artifact_payload["metrics"],
        "train_row_count": artifact_payload["train_row_count"],
        "holdout_row_count": artifact_payload["holdout_row_count"],
        "train_max_date": artifact_payload["train_max_date"],
        "trained_at": artifact_payload["trained_at"],
    }


def validate_models() -> dict[str, Any]:
    Config.ensure_runtime_dirs()
    artifacts = {}
    for target_name, path in ((Config.BUYOUTS_TARGET, Config.BUYOUTS_MODEL_PATH), (Config.ORDERS_TARGET, Config.ORDERS_MODEL_PATH)):
        if not path.exists():
            raise FileNotFoundError(f"Missing artifact for {target_name}: {path}")
        payload = _load_pickle(path)
        for field in ("target_name", "feature_columns", "models", "metrics", "train_max_date"):
            if field not in payload:
                raise ValueError(f"Artifact {path} is missing field {field}")
        if not payload.get("models"):
            raise ValueError(f"Artifact {path} contains no models")
        artifacts[target_name] = {
            "artifact_path": str(path),
            "engine": payload.get("engine"),
            "metrics": payload.get("metrics"),
            "train_max_date": payload.get("train_max_date"),
        }
    return {"status": "ok", "artifacts": artifacts}


def publish_model_meta() -> dict[str, Any]:
    Config.ensure_runtime_dirs()
    validation = validate_models()
    buyouts_payload = _load_pickle(Config.BUYOUTS_MODEL_PATH)
    orders_payload = _load_pickle(Config.ORDERS_MODEL_PATH)
    train_max_date = min(str(buyouts_payload["train_max_date"]), str(orders_payload["train_max_date"]))
    model_version = f"{Config.MODEL_VERSION_PREFIX}_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
    meta = {
        "model_version": model_version,
        "published_at": _iso_now(),
        "train_max_date": train_max_date,
        "targets": {
            Config.BUYOUTS_TARGET: {
                "target_name": Config.BUYOUTS_TARGET,
                "feature_columns": buyouts_payload["feature_columns"],
                "engine": buyouts_payload["engine"],
                "target_transform": buyouts_payload.get("target_transform", "identity"),
                "metrics": buyouts_payload["metrics"],
                "artifact_path": str(Config.BUYOUTS_MODEL_PATH),
            },
            Config.ORDERS_TARGET: {
                "target_name": Config.ORDERS_TARGET,
                "feature_columns": orders_payload["feature_columns"],
                "engine": orders_payload["engine"],
                "target_transform": orders_payload.get("target_transform", "identity"),
                "metrics": orders_payload["metrics"],
                "artifact_path": str(Config.ORDERS_MODEL_PATH),
            },
        },
    }
    _write_model_meta(meta)
    return {"status": "ok", "validation": validation, "model_meta_path": str(Config.MODEL_META_PATH), "model_version": model_version}


def _require_prediction_artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not Config.BUYOUTS_MODEL_PATH.exists() or not Config.ORDERS_MODEL_PATH.exists():
        raise FileNotFoundError("Model artifacts are missing. Run weekly retrain first.")
    meta = _read_model_meta()
    return meta, _load_pickle(Config.BUYOUTS_MODEL_PATH), _load_pickle(Config.ORDERS_MODEL_PATH)


def run_daily_scoring() -> dict[str, Any]:
    Config.ensure_runtime_dirs()
    model_meta, buyouts_artifact, orders_artifact = _require_prediction_artifacts()

    db = OnePagerMLDatabase()
    db.connect()
    try:
        db.create_tables()
        report_date = db.get_latest_complete_report_date()
        if report_date is None:
            raise ValueError("reports.v_1pager_ml is empty; nothing to score")
        scoring_df = db.fetch_scoring_frame(report_date)
        if scoring_df.empty:
            raise ValueError(f"No scoring rows found for {report_date}")

        buyouts_x = normalize_feature_frame(scoring_df, buyouts_artifact["feature_columns"])
        orders_x = normalize_feature_frame(scoring_df, orders_artifact["feature_columns"])

        buyouts_predictions = np.vstack([
            _inverse_target_transform(model.predict(buyouts_x)) for model in buyouts_artifact["models"]
        ])
        orders_predictions = np.vstack([
            _inverse_target_transform(model.predict(orders_x)) for model in orders_artifact["models"]
        ])

        buyouts_mean = np.mean(buyouts_predictions, axis=0)
        orders_mean = np.mean(orders_predictions, axis=0)
        rows = []
        for index, source_row in scoring_df.reset_index(drop=True).iterrows():
            raw_pred_buyouts = float(buyouts_mean[index])
            raw_pred_orders = float(orders_mean[index])
            sales_baseline_7d = compute_sales_baseline_7d(
                float(source_row.get("sales_lag_1w") or 0.0),
                float(source_row.get("sales_lag_2w") or 0.0),
                float(source_row.get("sales_lag_4w") or 0.0),
                float(source_row.get("sales_rolling_4w_avg") or 0.0),
            )
            forecast_cap_7d = compute_sales_forecast_cap_7d(
                float(source_row.get("sales_lag_1w") or 0.0),
                float(source_row.get("sales_lag_2w") or 0.0),
                float(source_row.get("sales_lag_4w") or 0.0),
                float(source_row.get("sales_rolling_4w_avg") or 0.0),
            )
            pred_buyouts = apply_sales_forecast_cap(raw_pred_buyouts, forecast_cap_7d)
            pred_orders = apply_sales_forecast_cap(raw_pred_orders, forecast_cap_7d)
            trend_ratio = compute_trend_ratio(pred_buyouts, sales_baseline_7d)
            confidence_score = compute_confidence_score(buyouts_predictions[:, index])
            formula_forecast_7d = compute_formula_forecast_7d(
                float(source_row.get("sales_lag_1w") or 0.0),
                float(source_row.get("sales_lag_2w") or 0.0),
                float(source_row.get("sales_lag_4w") or 0.0),
                float(source_row.get("sales_rolling_4w_avg") or 0.0),
            )
            formula_trend_ratio = compute_trend_ratio(formula_forecast_7d, sales_baseline_7d)
            formula_trend_label = compute_trend_label(
                formula_forecast_7d,
                sales_baseline_7d,
                relative_threshold=Config.FORMULA_TREND_RELATIVE_THRESHOLD,
            )
            (
                formula_reason_summary,
                formula_reason_1,
                formula_reason_2,
            ) = build_formula_reason_bundle(
                float(source_row.get("sales_lag_1w") or 0.0),
                float(source_row.get("sales_lag_2w") or 0.0),
                float(source_row.get("sales_lag_4w") or 0.0),
                float(source_row.get("sales_rolling_4w_avg") or 0.0),
                float(source_row.get("sales_rolling_4w_std") or 0.0),
                formula_forecast_7d,
                sales_baseline_7d,
            )
            formula_v2_forecast_7d = compute_formula_v2_forecast_7d(
                float(source_row.get("sales_lag_1w") or 0.0),
                float(source_row.get("sales_lag_2w") or 0.0),
                float(source_row.get("sales_lag_4w") or 0.0),
                float(source_row.get("sales_rolling_4w_avg") or 0.0),
            )
            formula_v2_trend_ratio = compute_trend_ratio(formula_v2_forecast_7d, sales_baseline_7d)
            formula_v2_trend_label = compute_trend_label(
                formula_v2_forecast_7d,
                sales_baseline_7d,
                relative_threshold=Config.FORMULA_TREND_RELATIVE_THRESHOLD,
            )
            (
                formula_v2_reason_summary,
                formula_v2_reason_1,
                formula_v2_reason_2,
            ) = build_formula_v2_reason_bundle(
                float(source_row.get("sales_lag_1w") or 0.0),
                float(source_row.get("sales_lag_2w") or 0.0),
                float(source_row.get("sales_lag_4w") or 0.0),
                float(source_row.get("sales_rolling_4w_avg") or 0.0),
                formula_v2_forecast_7d,
                sales_baseline_7d,
            )
            rows.append(
                {
                    "report_date": report_date,
                    "nm_id": int(source_row["id"]),
                    "sku": source_row.get("sku"),
                    "pred_buyouts_7d": pred_buyouts,
                    "pred_orders_7d": pred_orders,
                    "pred_sales_baseline_7d": sales_baseline_7d,
                    "pred_trend_ratio": trend_ratio,
                    "pred_trend_label": compute_trend_label(pred_buyouts, sales_baseline_7d),
                    "pred_delta_pct": compute_delta_pct(pred_buyouts, sales_baseline_7d),
                    "pred_confidence_score": confidence_score,
                    "pred_confidence_label": compute_confidence_label(confidence_score),
                    "sales_formula_v1_forecast_7d": formula_forecast_7d,
                    "sales_formula_v1_baseline_7d": sales_baseline_7d,
                    "sales_formula_v1_trend_ratio": formula_trend_ratio,
                    "sales_formula_v1_trend_label": formula_trend_label,
                    "sales_formula_v1_reason_summary": formula_reason_summary,
                    "sales_formula_v1_reason_1": formula_reason_1,
                    "sales_formula_v1_reason_2": formula_reason_2,
                    "sales_formula_v2_forecast_7d": formula_v2_forecast_7d,
                    "sales_formula_v2_baseline_7d": sales_baseline_7d,
                    "sales_formula_v2_trend_ratio": formula_v2_trend_ratio,
                    "sales_formula_v2_trend_label": formula_v2_trend_label,
                    "sales_formula_v2_reason_summary": formula_v2_reason_summary,
                    "sales_formula_v2_reason_1": formula_v2_reason_1,
                    "sales_formula_v2_reason_2": formula_v2_reason_2,
                    "model_version": model_meta["model_version"],
                    "trained_on_max_date": model_meta["train_max_date"],
                }
            )

        written = db.upsert_forecast_rows(rows)
        payload = {
            "status": "success",
            "report_date": str(report_date),
            "rows_written": written,
            "model_version": model_meta["model_version"],
            "trained_on_max_date": model_meta["train_max_date"],
        }
        output_path = Config.JSON_OUTPUT_DIR / f"daily_forecast_{report_date}.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload
    finally:
        db.close()


def _build_explanation_payload(row: dict[str, Any]) -> dict[str, Any]:
    source = {field: row.get(field) for field in Config.EXPLAIN_FIELDS}
    return {
        "report_date": str(row["report_date"]),
        "nm_id": int(row["nm_id"]),
        "sku": row.get("sku") or row.get("forecast_sku"),
        "pred_buyouts_7d": row.get("pred_buyouts_7d"),
        "pred_orders_7d": row.get("pred_orders_7d"),
        "pred_sales_baseline_7d": row.get("pred_sales_baseline_7d"),
        "pred_trend_ratio": row.get("pred_trend_ratio"),
        "pred_trend_label": row.get("pred_trend_label"),
        "pred_delta_pct": row.get("pred_delta_pct"),
        "pred_confidence_score": row.get("pred_confidence_score"),
        "pred_confidence_label": row.get("pred_confidence_label"),
        "features": source,
    }


def build_empty_explanation_row(row: dict[str, Any], *, llm_model: str | None = None) -> dict[str, Any]:
    return {
        "report_date": row["report_date"],
        "nm_id": int(row["nm_id"]),
        "sku": row.get("sku") or row.get("forecast_sku"),
        "model_version": row["model_version"],
        "reason_summary": None,
        "reason_1": None,
        "reason_2": None,
        "reason_3": None,
        "llm_model": llm_model,
        "prompt_version": Config.EXPLAIN_PROMPT_VERSION,
        "source_features_hash": _source_features_hash(row),
    }


def run_daily_pipeline() -> dict[str, Any]:
    score_result = run_daily_scoring()
    try:
        try:
            from explain_daily import run as run_daily_explanations
        except ImportError:  # pragma: no cover
            from .explain_daily import run as run_daily_explanations

        explanation_result = run_daily_explanations()
    except Exception as exc:  # pragma: no cover
        logger.warning("ML daily explanation stage failed after scoring: %s", exc)
        explanation_result = {"status": "partial", "error": str(exc)}
    return {
        "score_result": score_result,
        "explanation_result": explanation_result,
    }
