# ML

ML-layer for `1pager_ml`.

What it does:
- trains two 7-day models on `analytics_ai.v_1pager_ml_train`
- scores the latest complete date from `reports.v_1pager_ml`
- writes forecasts to `analytics_ai.wb_ml_forecast_daily`
- writes LLM explanations to `analytics_ai.wb_ml_forecast_explanations`
- exposes joined consumer view `reports.v_1pager_ml_forecast`

Runtime artifacts are stored under `runtime/<tenant>/ML/`.

Main entrypoints:
- `train_buyouts_7d.run`
- `train_orders_7d.run`
- `pipeline.validate_models`
- `pipeline.publish_model_meta`
- `predict_daily.run`
- `explain_daily.run`
