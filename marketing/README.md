# marketingовые кампании WB (Продвижение)

Выгрузка активных и неактивных маркетинговых кампаний продавца через API **Продвижение** (advert-api.wildberries.ru).

- **Рекламные кампании поиска** (ручная/единая ставка): список ID — `GET /adv/v1/promotion/count`; детали — `GET /api/advert/v2/adverts?ids=...` (до 50 ID за запрос).
- **Медиакампании (WB Медиа):** список с пагинацией — `GET /adv/v1/adverts` (limit/offset).

Статусы кампаний (например: 4 — готово к запуску, 7 — завершена, 8 — отклонена, **9 — активна**, 11 — пауза) хранятся в таблице; активные и неактивные можно отфильтровать по полю `status`.

- **config.py** — настройки (токен, БД, пути к `json_data`, лимиты запросов).
- **database.py** — создание таблиц по `schema_wb_marketing_campaigns.sql` и `schema_wb_marketing_analytics.sql`, upsert кампаний и аналитики.
- **fetch_campaigns.py** — запросы к API кампаний, сохранение в JSON и PostgreSQL.
- **fetch_normquery.py** — поисковые кластеры (active/excluded), ставки по кластерам, минус-фразы (POST normquery/list, get-bids, get-minus). Данные для аналитики, не по подписке.
- **fetch_marketing_stats.py** — баланс кабинета, бюджет кампаний, фактические затраты (upd), пополнения (payments), полная статистика по кампаниям (fullstats) за период.

Таблицы аналитики (`tables/marketing/schema_wb_marketing_analytics.sql`): `wb_marketing_normquery_clusters`, `wb_marketing_normquery_bids`, `wb_marketing_normquery_minus`, `wb_marketing_normquery_stats`, `wb_marketing_normquery_stats_daily`, `wb_marketing_upd`, `wb_marketing_payments`, `wb_marketing_balance`, `wb_marketing_budget`, `wb_marketing_campaign_stats_daily`. **Детализация по SKU (nm_id):** `wb_marketing_campaign_nms` — состав кампаний по номенклатурам (advert_id, nm_id, subject, ставки); `wb_marketing_campaign_stats_daily_nms` — дневная статистика по кампаниям с разбивкой по nm_id (из fullstats).

Запуск вручную из корня проекта:

```bash
cd "marketing"
python -m fetch_campaigns           # снимок кампаний на сегодня
python -m fetch_campaigns --include-media
python -m fetch_campaigns --full     # то же (флаг по аналогии с Остатками)
python -m fetch_normquery           # кластеры, ставки, минус-фразы на сегодня
python -m fetch_marketing_stats     # баланс, бюджет, upd, fullstats (по умолчанию за 31 день)
python -m fetch_marketing_stats --days 7 --no-fullstats   # только баланс, бюджет, upd, payments за неделю
python -m fetch_normquery_stats --days 7                  # статистика по кластерам (v0 и v1) за 7 дней
```
**Почему часть таблиц может быть пустой:**  
- `wb_marketing_normquery_bids` — заполняется, только если в API есть ставки по кластерам (для кампаний с ручной ставкой по кластерам); при CPM или отсутствии ставок остаётся пустой.  
- `wb_marketing_normquery_stats` и `wb_marketing_normquery_stats_daily` — заполняются скриптом `fetch_normquery_stats`. Метод v0 работает только для кампаний с оплатой CPM (за показы).

По расписанию: tenant DAG **wb_{tenant}_search_queries** используется как umbrella ingestion для marketing + search-report.

Переменные окружения: `WB_API_TOKEN` (или `WB_API_KEY`), `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
