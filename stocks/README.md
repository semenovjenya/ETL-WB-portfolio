# stocks на складах WB (supplier/stocks)

Выгрузка остатков товаров на складах Wildberries через API **GET /api/v1/supplier/stocks** (statistics-api.wildberries.ru).

- **config.py** — настройки (токен, БД, путь к `json_data`, лимит 1 запрос/мин).
- **fetch_stocks.py** — пагинация по `dateFrom`/`lastChangeDate`, сохранение в JSON и PostgreSQL.
- **database.py** — создание таблиц по `tables/reports/schema_supplier_stocks.sql`, upsert остатков с датой среза (1 день = 1 срез, история накапливается).

Запуск вручную из корня проекта:

```bash
cd "stocks"
python -m fetch_stocks           # продолжить с последнего прогресса
python -m fetch_stocks --full    # полный снимок с начальной даты
```

По расписанию: DAG **wb_supplier_stocks_daily** в Airflow (http://localhost:8082, ежедневно в 04:00).

Переменные окружения: те же, что для «finance» (`WB_API_TOKEN`, `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`).

**История по дням:** в таблице есть колонка `snapshot_date`; каждый запуск пишет срез на сегодня. Если таблица уже была создана без неё, один раз выполните миграцию: `psql -h ... -U ... -d wb_docs -f tables/reports/migrate_supplier_stocks_add_snapshot_date.sql`.
