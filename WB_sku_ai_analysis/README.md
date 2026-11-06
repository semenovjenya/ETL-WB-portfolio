# WB SKU AI Analysis

Модуль собирает широкий срез по всем SKU, которые сейчас есть в остатке на складах WB.

Источники:
- `GET /api/v1/supplier/stocks` — остатки по складам и баркодам;
- `POST /content/v2/get/cards/list` — карточка товара, фото, видео, размеры, характеристики;
- `GET /api/v2/list/goods/filter` — цены и скидки;
- `POST /api/analytics/v3/sales-funnel/products` — воронка и рейтинги;
- `POST /api/v2/stocks-report/products/products` — аналитика по остаткам, mainPhoto, availability.

Что пишет в БД:
- таблицу `reports.wb_sku_ai_analysis`;
- таблицу `reports.wb_sku_competitors`;
- одну строку на `snapshot_date + nm_id + barcode`;
- ссылки на карточку товара и фото;
- агрегированные остатки по складам и сырые JSON-поля для дальнейшего AI-анализа.
- цены по WB-ссылке: цена до скидки, цена по акции, флаг акции.
- конкурентов по ключевым запросам: ссылка, ссылка на 1 фото, цены до/после скидки, позиция в каталоге WB, рейтинг и краткое описание.
- в каждой строке конкурента сохраняются границы ценового сегмента источника: `source_price_segment_min` и `source_price_segment_max`.
- для конкурента сохраняются продавец из карточки WB: `competitor_supplier_name` и `competitor_supplier_id`.
- для конкурента сохраняются цвета источника и кандидата: `source_colors_json`, `competitor_colors_json`, а также флаг `same_color`.
- базовый фильтр ценового сегмента для конкурентов по умолчанию: `±35%` от цены источника после скидки.
- цвет больше не используется как блокирующий фильтр; `source_colors_json`, `competitor_colors_json` и `same_color` сохраняются только как справочные поля.
- цена источника для поиска конкурентов теперь берётся только из `wb_link_price_regular` / `wb_link_price_promo` после запуска `parse_wb_link_prices`; без этих полей source SKU будет пропущен.
- при наличии `OPENAI_API_KEY` можно включить AI-фильтр по фото: он сравнивает фото источника и конкурента и отсекает визуально нерелевантные кровати.

Поиск конкурентов теперь работает в browser-first режиме через Playwright:
- используется persistent browser profile;
- первый запрос на keyword идёт через UI WB, а не прямым `requests`;
- результаты забираются из внутренних XHR WB или из DOM страницы;
- профиль браузера переиспользуется между запусками.

Запуск:

```bash
python3 WB_sku_ai_analysis/create_table.py
python3 WB_sku_ai_analysis/create_competitor_table.py
python3 WB_sku_ai_analysis/fetch_wb_sku_ai_analysis.py
python3 WB_sku_ai_analysis/parse_wb_link_prices.py
python3 WB_sku_ai_analysis/fetch_wb_competitors.py --source-json WB_sku_ai_analysis/json_data/wb_sku_ai_analysis_YYYY-MM-DD_HH-MM-SS.json --keywords-json /path/to/keywords.json --no-headless --browser-profile-dir ~/.wb_playwright_profile --enable-photo-ai-filter --dry-run
```

JSON-результат сохраняется в `WB_sku_ai_analysis/json_data/`.

Формат `keywords.json`:

```json
{
  "180822057": [
    "кровать односпальная",
    "кровать деревянная 60х200"
  ]
}
```

Альтернатива для запуска из БД:

```bash
python3 WB_sku_ai_analysis/fetch_wb_competitors.py --use-db-latest --keywords-json /path/to/keywords.json --no-headless --browser-profile-dir ~/.wb_playwright_profile
```

Для AI-фильтра по фото:

```bash
export OPENAI_API_KEY=...
python3 WB_sku_ai_analysis/fetch_wb_competitors.py --use-db-latest --keywords-json /path/to/keywords.json --enable-photo-ai-filter
```

В результат конкурента добавляются поля:
- `photo_ai_is_competitor`
- `photo_ai_confidence`
- `photo_ai_reason`
- `photo_ai_model`

Рекомендация для первого запуска:
- использовать `--no-headless`;
- оставить тот же `--browser-profile-dir` для следующих прогонов;
- если WB покажет challenge, дождаться завершения в этом же профиле и только потом повторить сбор.
