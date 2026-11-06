# sales и возвраты WB (supplier/sales)

Выгрузка продаж и возвратов через API **GET /api/v1/supplier/sales** (statistics-api.wildberries.ru). 1 строка = 1 заказ = 1 единица товара. Пагинация по `dateFrom`/`lastChangeDate`, до 80000 строк за запрос.

- **config.py** — токен, БД, `SALES_INITIAL_DAYS` (90), лимит 1 запрос/мин.
- **fetch_sales.py** — пагинация, сохранение в JSON и PostgreSQL с датой среза (1 день = 1 срез).
- **database.py** — таблицы по `tables/reports/schema_supplier_sales.sql`, upsert по `(srid, snapshot_date)`.

**Логика выгрузки:** первая выгрузка — за последние 90 дней (`dateFrom` = сегодня − 90 дней). Дальше — ежедневные инкрементальные выгрузки с последнего сохранённого `lastChangeDate`.

**Запуск вручную:**

```bash
cd "sales"
python -m fetch_sales           # первая: 90 дней; далее: продолжение с прогресса
python -m fetch_sales --full    # принудительно снимок за последние 90 дней
python -m fetch_sales --clear   # очистить таблицы и прогресс, выгрузить заново за 90 дней
```

**По расписанию:** DAG **wb_supplier_sales_daily** в Airflow (http://localhost:8082, ежедневно в 05:00).

Переменные окружения: `WB_API_TOKEN`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
