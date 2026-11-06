# promotions WB (calendar/promotions)

Выгрузка календаря акций через API **GET /api/v1/calendar/promotions**. Три уровня данных (см. `output/markdown/promotion/`):

1. **Список акций** — `GET /api/v1/calendar/promotions` (даты, тип).
2. **Подробности акции** — `GET /api/v1/calendar/promotions/details` → таблица **wb_calendar_promotions_details** (описание, преимущества, остатки в акции, ranging и т.д.) — см. `GET_api_v1_calendar_promotions_details.md`.
3. **Номенклатуры (SKU)** — `GET /api/v1/calendar/promotions/nomenclatures` → таблица **wb_calendar_promotions_nomenclatures** (id/nm_id, цена, скидка, inAction) — см. `GET_api_v1_calendar_promotions_nomenclatures.md`.

- **config.py** — токен (Продвижение), БД, URL списка, details и nomenclatures.
- **fetch_promotions.py** — список акций за период → `reports.wb_calendar_promotions`.
- **fetch_promotions_details.py** — подробности по ID акций (батчами до 100) → `reports.wb_calendar_promotions_details`.
- **fetch_promotions_nomenclatures.py** — номенклатуры по каждой акции → `reports.wb_calendar_promotions_nomenclatures`.
- **database.py** — создание таблиц, upsert акций, details и номенклатур.

**Запуск вручную:**

```bash
cd "promotions"
python -m fetch_promotions                    # список акций
python -m fetch_promotions --full             # полный снимок за период
python -m fetch_promotions --clear             # очистить все таблицы и выгрузить заново
python -m fetch_promotions_details             # подробности акций (details) по последнему срезу
python -m fetch_promotions_details --date 2025-03-01
python -m fetch_promotions_nomenclatures       # номенклатуры (SKU) по последнему срезу
python -m fetch_promotions_nomenclatures --date 2025-03-01
```

Переменные окружения: `WB_API_TOKEN` (токен Продвижения), `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`.
