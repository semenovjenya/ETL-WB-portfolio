# Airflow для проекта ПАРСЕР API WB

Единый Airflow для ежедневного контура ETL и обновления витрин.

**UI:** http://localhost:8082  
**Логин:** admin / admin  

## Запуск

Из корня проекта:

```bash
cd "."
docker compose -f docker-compose.airflow.yml up -d
```

Подождите 30–60 секунд и откройте http://localhost:8082.

## Основной DAG запуска

Ежедневный запуск выполняется через **wb_daily_pipeline_master** (расписание: `30 7 * * *`, Europe/Moscow).

Этот DAG:
- последовательно триггерит source-DAG-и;
- ждёт их завершения;
- выполняет strict freshness gate;
- запускает `wb_mart_ai_sales_planning`.

## Режим source-DAG

Source-DAG-и работают в режиме `trigger-only` (`schedule=None`):
- `wb_supplier_stocks_daily`
- `wb_supplier_sales_daily`
- `wb_supplier_orders_daily`
- `wb_supplies_daily`
- `wb_supplier_prices_daily`
- `wb_sales_funnel_daily`
- `wb_report_detail_daily`
- `wb_tariffs_daily`
- `wb_calendar_promotions_daily`
- `wb_stocks_sales_daily_refresh`
- `wb_mart_ai_sales_planning`

Tenant DAG `wb_{tenant}_search_queries` теперь используется как umbrella ingestion для маркетинга:
- promotion campaigns;
- balance / budget / upd / payments;
- normquery clusters / bids / minus;
- fullstats и normquery stats;
- search-report stages.

Их можно запускать вручную из UI для отладки, но в боевом daily-контуре точка входа одна: `wb_daily_pipeline_master`.

## Остановка

```bash
docker compose -f docker-compose.airflow.yml down
```

## Ошибка `docker-credential-desktop not found`

В `~/.docker/config.json` замените `"credsStore": "desktop"` на `"credsStore": ""` и снова выполните команду запуска.
