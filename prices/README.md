# prices и скидки WB (list/goods/filter)

Выгрузка цен и скидок товаров Wildberries через API **GET /api/v2/list/goods/filter** (content-api.wildberries.ru).

- **config.py** — настройки (токен, БД, путь к `json_data`, limit=1000, интервал 0.65 сек между запросами).
- **fetch_prices.py** — пагинация по `offset` (limit=1000), сохранение в JSON и PostgreSQL.
- **database.py** — создание таблиц по `tables/reports/schema_supplier_prices.sql`, upsert цен с датой среза (1 день = 1 срез, история накапливается).

Запуск вручную из корня проекта:

```bash
cd "prices"
python -m fetch_prices
```

По расписанию: DAG **wb_supplier_prices_daily** в Airflow (ежедневно в 05:00, после остатков).

Переменные окружения: те же, что для «stocks» и «finance» (`WB_API_TOKEN` или `WB_API_KEY`, `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`). Для Content API нужен токен с доступом к категории «Контент» (цены и скидки).

**Эндпоинт:** https://content-api.wildberries.ru/api/v2/list/goods/filter  
**Лимиты API:** 10 запросов за 6 сек, интервал между запросами не менее 600 мс.
