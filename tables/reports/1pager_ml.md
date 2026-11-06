# 1pager ML

View: `reports.v_1pager_ml`

Purpose:

- feature table for ML training / validation
- live ML feature table for the latest 3 export dates
- compact numeric / flag-oriented feature set

Source:

- `reports.mart_ai_sales_planning`
- `reports.wb_marketing_campaign_stats_daily_nms` for current-day marketing views/clicks/orders/spend

Design:

- one row per `nm_id` per `report_date`
- keeps only the latest 3 `report_date` values
- feature columns are mostly numeric or binary flags
- target columns are forward-looking labels for horizons `1 / 7 / 14 / 21 / 31` days

Important:

- target columns may be `NULL` near the last dates, because future actuals do not exist yet
- this is expected and correct for ML training
- `target_ready_*_flag` helps filter rows with complete labels

Main feature groups:

- stock / supply
- prices and unit economics
- sales history and lags
- traffic / conversion
- promo / seasonality
- returns
- marketing daily metrics and rolling windows

Targets:

- `target_orders_next_1d`
- `target_buyouts_next_1d`
- `target_orders_next_7d`
- `target_buyouts_next_7d`
- `target_orders_next_14d`
- `target_buyouts_next_14d`
- `target_orders_next_21d`
- `target_buyouts_next_21d`
- `target_orders_next_31d`
- `target_buyouts_next_31d`

Example:

```sql
SELECT *
FROM reports.v_1pager_ml
ORDER BY report_date DESC, id
LIMIT 100;
```
