# sales_funnel WB по дням (90 дней)

Выгрузка воронки продаж **по дням** за последние 90 дней в таблицу **reports.wb_sales_funnel_products_daily**. API **POST /api/analytics/v3/sales-funnel/products** (seller-analytics-api.wildberries.ru) вызывается с периодом в один день (start=end=дата) для каждой даты. Лимит: 3 запроса/мин, интервал между запросами ≥20 сек.

**Скрипты и файлы:**

- **config.py** — токен WB, параметры БД, лимиты API (`REQUEST_INTERVAL_SEC`, `REQUESTS_PER_MINUTE`, `RETRY_DELAY_429`).
- **fetch_sales_funnel_90d_daily.py** — основной скрипт: цикл по 90 дням (конец = вчера), полная выгрузка всех карточек, которые WB API отдаёт за день, запись в БД.
- **database.py** — подключение к PostgreSQL, `ensure_daily_table_only()`, `get_loaded_daily_report_dates()`, `normalize_product_to_daily_row()`, `upsert_funnel_daily()`.

Скрипт больше не зависит от локальных `stocks/sales` для отбора товаров. Вместо этого он ходит в WB Funnel API напрямую и забирает все карточки за день через пагинацию `offset/limit`. При повторном запуске догружает только отсутствующие `report_date` в рабочем окне последних `N` дней. Схема таблицы: `tables/reports/schema_sales_funnel_daily.sql`.

**Запуск:**

```bash
cd "sales_funnel"
python3 -m fetch_sales_funnel_90d_daily              # 90 дней
python3 -m fetch_sales_funnel_90d_daily --days 30    # 30 дней
python3 -m fetch_sales_funnel_90d_daily --json       # 90 дней + JSON по каждому дню в json_data
```

Переменные окружения: `WB_API_TOKEN`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
