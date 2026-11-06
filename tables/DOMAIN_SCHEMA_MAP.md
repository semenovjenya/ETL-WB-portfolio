# Domain Schema Map

Каноническая схема объектов больше не `reports.*`.

## Prefix Map

| Старый префикс | Новая схема |
| --- | --- |
| `reports.wb_supplier_stocks*`, `reports.v_wb_supplier_stocks*`, `reports.wb_supplies*`, `reports.v_wb_supplies*` | `supply` |
| `reports.wb_supplier_sales*`, `reports.v_wb_supplier_sales*`, `reports.wb_supplier_orders*`, `reports.v_wb_supplier_orders*`, `reports.wb_sales_funnel*` | `sales` |
| `reports.wb_supplier_prices*`, `reports.v_wb_supplier_prices*`, `reports.wb_tariffs*`, `reports.v_wb_tariffs*`, `reports.parse_wb_numeric` | `pricing` |
| `reports.wb_marketing*`, `reports.v_wb_marketing*`, `reports.wb_calendar_promotions*`, `reports.v_wb_calendar_promotions*`, `reports.wb_search_query*` | `marketing` |
| `reports.wb_report_detail*`, `reports.wb_product_cost*`, `reports.wb_profit_calculator*`, `reports.v_wb_profit_calculator_results_source`, `reports.refresh_wb_profit_calculator_results`, `reports.sync_wb_profit_calculator_scenarios_from_stocks`, `reports.sync_wb_profit_calculator_scenarios_from_sku_ai_analysis`, `reports.seed_wb_profit_calculator_scenarios`, `reports.set_wb_profit_calc_updated_at` | `finance` |
| `reports.wb_stocks_sales*`, `reports.v_stocks_sales*`, `reports.mart_ai_sales_planning`, `reports.v_1pager*`, `reports.wb_1pager_ai_hourly*`, `reports.wb_unit_economics`, `reports.v_wb_unit_economics`, `reports.wb_sku_*`, `reports.v_wb_sku_competitors_export`, `reports.wb_price_ai*`, `reports.v_wb_price_ai_analysis_latest`, `reports.v_report_*` | `analytics_ai` |

## Compatibility Layer

- `reports` остаётся read-only compatibility namespace.
- Для объектов, вынесенных в канонические схемы, в `tables/compat_reports/*.sql` создаются views с прежними именами `reports.*`.
- Writers и DAG-задачи должны обращаться к каноническим схемам напрямую или через SQL rewrite из [`wb_schemas.py`](.).

## DDL Layout

- `tables/supply`
- `tables/sales`
- `tables/pricing`
- `tables/marketing`
- `tables/finance`
- `tables/analytics_ai`
- `tables/compat_reports`
