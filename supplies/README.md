# supplies WB (supplies)

Выгрузка поставок через API **POST /api/v1/supplies** и **GET /api/v1/supplies/{ID}** (supplies-api.wildberries.ru). Список — до 1000 записей за запрос (limit/offset), фильтр по датам (createDate). Опционально: детали поставки и товары в поставке (отдельные запросы, лимит 30/мин).

- **config.py** — токен, БД, `SUPPLIES_INITIAL_DAYS` (90), интервал 2 сек. `FETCH_DETAILS` / `FETCH_GOODS` — вызов деталей и товаров по каждой поставке (по умолчанию выключено).
- **fetch_supplies.py** — пагинация по offset, сохранение в JSON и PostgreSQL с датой среза (1 день = 1 срез).
- **database.py** — таблицы по `tables/reports/schema_wb_supplies.sql`, уникальность по (snapshot_date, supply_id) или (snapshot_date, preorder_id).

**Логика выгрузки:** первая выгрузка — за последние 90 дней (dates.from / dates.till). Дальше — инкрементальные выгрузки с последнего сохранённого `last_create_date` (прогресс в БД и progress.json).

**Запуск вручную:**

```bash
cd "supplies"
python -m fetch_supplies           # первая: 90 дней; далее: продолжение с прогресса
python -m fetch_supplies --full    # принудительно снимок за последние 90 дней
python -m fetch_supplies --clear   # очистить таблицы и прогресс, выгрузить заново за 90 дней
```

**По расписанию:** DAG **wb_supplies_daily** в Airflow (ежедневно в 05:30).

Переменные окружения: `WB_API_TOKEN`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
