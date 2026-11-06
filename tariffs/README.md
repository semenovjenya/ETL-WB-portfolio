# tariffs WB (common-api wb-tariffs)

Выгрузка тарифов Wildberries через API **common-api.wildberries.ru** (раздел wb-tariffs).

- **config.py** — настройки (токен, БД, путь к `json_data`, интервал между запросами).
- **fetch_tariffs.py** — запросы ко всем эндпоинтам тарифов, сохранение в JSON и PostgreSQL.
- **database.py** — создание таблиц по `tables/reports/schema_wb_tariffs.sql`, upsert по дате среза.

Эндпоинты:

| Метод | Описание |
|-------|----------|
| GET /api/v1/tariffs/commission | Комиссия WB по родительским категориям |
| GET /api/v1/tariffs/box | tariffs на остаток (короба) по складам |
| GET /api/v1/tariffs/pallet | tariffs на остаток (паллеты) по складам |
| GET /api/v1/tariffs/return | Стоимость возврата продавцу по складам |
| GET /api/tariffs/v1/acceptance/coefficients | Коэффициенты приёмки на поставку |

Запуск вручную из корня проекта:

```bash
cd "tariffs"
python -m fetch_tariffs
```

По расписанию: DAG **wb_tariffs_daily** в Airflow (ежедневно в 06:00).

Переменные окружения: `WB_API_TOKEN` или `WB_API_KEY`, `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`. Для common-api подходит токен с доступом к категории «Контент» или общий токен продавца.

**Документация API:** [output/markdown/wb-tariffs](../output/markdown/wb-tariffs/_index.md) и [dev.wildberries.ru/docs/openapi/wb-tariffs](https://dev.wildberries.ru/docs/openapi/wb-tariffs).
