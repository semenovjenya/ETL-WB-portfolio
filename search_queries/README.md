# search_queries WB

Выгрузка раздела **search_queries по вашим товарам** через методы:

- `POST /api/v2/search-report/report`
- `POST /api/v2/search-report/table/groups`
- `POST /api/v2/search-report/table/details`
- `POST /api/v2/search-report/product/search-texts`
- `POST /api/v2/search-report/product/orders`

## Что делает модуль

- берёт активные `nm_id` из `reports.wb_supplier_sales` и `reports.wb_supplier_stocks`
- строит срез по последним `N` полным дням, по умолчанию `7`
- выгружает обзор, группы, детали, поисковые тексты и дневные заказы по текстам
- сохраняет сырые JSON-ответы в `json_data`
- пишет нормализованные данные в таблицы `reports.wb_search_query_*`

## Файлы

- `config.py` — токен, БД, лимиты API и параметры периода
- `database.py` — таблицы и upsert в PostgreSQL
- `fetch_search_queries.py` — основной fetcher

Схема таблиц: `tables/reports/schema_wb_search_queries.sql`

## Запуск вручную

```bash
cd "search_queries"
python3 -m fetch_search_queries
python3 -m fetch_search_queries --snapshot-hour 2026-03-20T12:00:00+03:00
```

## Ограничения

- лимит API WB: `3 запроса в минуту`
- `product/orders` принимает период максимум `7` дней
- `product/search-texts` и `product/orders` могут генерировать много запросов, если активных `nm_id` много

Главные настройки можно менять через env:

- `WB_SEARCH_PERIOD_DAYS`
- `WB_SEARCH_MAX_ACTIVE_NM_IDS`
- `WB_SEARCH_NM_IDS_BATCH_SIZE`
- `WB_SEARCH_TEXTS_LIMIT`
- `WB_SEARCH_TOP_ORDER_BY_VALUES`
- `WB_SEARCH_ORDER_SEARCH_TEXT_TOP_ORDER_BY_VALUES` — какие `topOrderBy` сначала брать для `product/orders`, по умолчанию `orders`
- `WB_SEARCH_ORDER_TEXTS_MAX_BATCHES_PER_RUN` — сколько batch-ей order-текстов брать за запуск, по умолчанию `1`
- `WB_SEARCH_ORDERS_MAX_NM_PER_RUN` — сколько новых `nm_id` отправлять в `product/orders` за запуск, по умолчанию `1`
- `WB_SEARCH_STOP_ON_429` — завершать этап с `rate_limited=true` на первом 429, по умолчанию `true`
