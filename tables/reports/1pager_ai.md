# 1pager AI

View: `reports.v_1pager_ai`

Source: `reports.mart_ai_sales_planning`

Filters:

- excludes the current incomplete `report_date` in Moscow timezone
- only SKUs with `stock_qty > 0`

Added columns beyond the requested list:

- `report_date` to distinguish historical completed daily slices
- `sku` as `vendor_code`
- `product_name` from the latest known funnel title
- `qty_on_stock` as count of units currently on WB stock
- `last_supply_date` to show the latest supply date, with fallback to `report_date - 45 days`

Requested fields mapping:

- `id` -> `nm_id`
- `product_name` -> latest known product title
- `qty_on_stock` -> count of units currently on stock
- `days_on_stock` -> days since `last_supply_date`, fallback to 45 days
- `orders_7d` -> trailing 7-day real orders without cancellations
- `orders_14d` -> trailing 14-day real orders without cancellations
- `orders_21d` -> trailing 21-day real orders without cancellations
- `orders_31d` -> trailing 31-day real orders without cancellations
- `sales_7d` -> trailing 7-day buyouts from the mart
- `sales_31d` -> trailing 31-day buyouts
- `avg_sales_7d` -> `sales_7d / 7`
- `avg_sales_31d` -> `sales_31d / 31`
- `price_before_discount` -> `price_raw`
- `price_after_discount` -> `price_final`
- `discount_pct` -> seller discount percent
- `spp_pct` -> WB SPP percent
- `price_with_spp` -> final price after SPP
- `stock_turnover` -> `stock_turnover_weekly`
- `in_promo` -> `is_promo_period`
- `in_marketing_campaigns` -> `has_active_campaign`
- `supply_qty` -> `pending_supply_qty`
- `open_supply_qty` -> сумма товара в открытых поставках на `report_date`
- `supply_status_ids` -> список `status_id` по открытым поставкам SKU на `report_date`
- `planned_supply_date` -> ближайшая плановая дата поставки по открытым поставкам SKU
- `last_supply_date` -> latest completed supply date, fallback to `report_date - 45 days`
- `price_change_7d_pct` -> change vs `price_final` 7 days ago
- `price_change_31d_pct` -> change vs `price_final` 31 days ago
- `impressions` -> `open_count`
- `cart_conversion_pct` -> `open_to_cart_pct`
- `cart_to_order_conversion_pct` -> `cart_to_order_pct`

## Блок маркетинга (marketing_*)

Источник: `reports.wb_marketing_campaigns`, `wb_marketing_campaign_nms`, `wb_marketing_campaign_stats_daily_nms`.
Джойн: по `snapshot_date = report_date` и `nm_id`. Учитываются только активные (status=9) и недавно остановленные (status=11, последние 30 дней) кампании.

| Колонка | Описание |
|---|---|
| `in_marketing_campaigns` | Есть активная рекламная кампания на дату |
| `marketing_campaign_count` | Количество кампаний |
| `marketing_campaign_names` | Названия кампаний через `\|` |
| `marketing_campaign_types` | Типы кампаний |
| `marketing_bid_search_kopecks` | Ставка поиска, коп. |
| `marketing_bid_recommendations_kopecks` | Ставка рекомендаций, коп. |
| `marketing_views` | Показы рекламы |
| `marketing_clicks` | Клики по рекламе |
| `marketing_orders` | orders с рекламы |
| `marketing_spend` | Расход на рекламу, руб. |
| `marketing_ctr` | CTR, % |
| `marketing_cpc` | CPC, руб. |
| `marketing_cr` | CR клик→заказ, % |

## Блок промо (promo_*)

Источник: `reports.wb_calendar_promotions_details`.
Берётся последний по `snapshot_date` снимок на каждую акцию. Джойн по периоду акции:
`promo_start_date <= report_date <= promo_end_date`.

**Уровень аккаунта** (все активные акции, включая автоакции):

| Колонка | Описание |
|---|---|
| `in_promo` | SKU попадает в период акции (`is_promo_period` из mart) |
| `promo_names` | Названия активных акций через `\|` |
| `promo_types` | Типы акций (`auto`, `regular`) |
| `promo_nearest_end_date` | Дата окончания ближайшей акции |
| `promo_boost_max` | Максимальный буст позиции в поиске среди всех активных акций |

**Уровень SKU** (только regular-акции, для автоакций API не отдаёт nm_id):

| Колонка | Описание |
|---|---|
| `promo_nm_in_action` | SKU сейчас участвует в акции (`in_action = true` в nomenclatures) |
| `promo_gap_min` | Минимальный разрыв: `plan_discount − discount_pct`, % |
| `promo_eligible_names` | Акции, условие которых SKU уже выполняет (`gap ≤ 0`) |

**Как читать `promo_gap_min`:**
- `≤ 0` → скидка достаточна, SKU может участвовать (или уже участвует)
- `> 0` → нужно поднять скидку на `gap`%, чтобы войти в акцию

**Буст** — кратность поднятия позиции в поиске при участии в акции (поле `ranging` в API).
Значение `7` означает позицию в 7 раз выше обычной.

Example:

```sql
SELECT *
FROM reports.v_1pager_ai
ORDER BY report_date DESC, sales_31d DESC, id;
```

```sql
-- SKU, которые уже выполняют условие акции (gap <= 0), но ещё не в ней:
SELECT report_date, id, sku, product_name, discount_pct,
       promo_gap_min, promo_eligible_names, promo_nm_in_action
FROM reports.v_1pager_ai
WHERE promo_gap_min <= 0
  AND promo_nm_in_action = false
ORDER BY promo_gap_min ASC;
```
