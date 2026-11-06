# Описание таблиц и представлений схемы `reports`

> Начиная с доменной миграции `reports` считается compatibility-слоем для чтения.
> Канонические DDL и физические объекты разложены по схемам `supply`, `sales`, `pricing`, `marketing`, `finance`, `analytics_ai`.
> Краткая карта соответствий: [tables/DOMAIN_SCHEMA_MAP.md](.)

Документ описывает назначение каждой таблицы и столбца в каталоге `tables/reports`. Данные загружаются из API Wildberries.

---

## Содержание

1. [sales_funnel](#воронка-продаж)
2. [Отчёт о реализации (report detail)](#отчёт-о-реализации-report-detail)
3. [orders и продажи поставщика](#заказы-и-продажи-поставщика)
4. [stocks поставщика](#остатки-поставщика)
5. [prices поставщика](#цены-поставщика)
6. [Сводка остатков и продаж](#сводка-остатков-и-продаж)
7. [marketing и продвижение](#маркетинг-и-продвижение)
8. [supplies](#поставки)
9. [tariffs WB](#тарифы-wb)
10. [Календарь акций](#календарь-акций)
11. [Витрина AI-планирования продаж](#витрина-ai-планирования-продаж)
12. [Представления (views)](#представления-views)

---

## sales_funnel

Источник: API analytics (sales-funnel/products, sales-funnel/products/history).

### `reports.wb_sales_funnel_products`

Один срез воронки за период по товарам (без разбивки по дням).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза отчёта |
| period_start | DATE | Начало периода воронки |
| period_end | DATE | Конец периода воронки |
| nm_id | BIGINT | Номенклатурный ID (артикул WB) |
| title | VARCHAR(1000) | Название товара |
| vendor_code | VARCHAR(255) | Артикул поставщика |
| brand_name | VARCHAR(255) | Бренд |
| subject_id | BIGINT | ID категории (предмета) |
| subject_name | VARCHAR(500) | Название категории |
| product_rating | DECIMAL(5,2) | Рейтинг товара |
| feedback_rating | DECIMAL(5,2) | Рейтинг отзывов |
| stocks_wb | INT | stocks на складах WB |
| stocks_mp | INT | stocks на маркетплейсе |
| balance_sum | DECIMAL(12,2) | Сумма остатков |
| open_count | INT | Просмотры карточки |
| cart_count | INT | Добавления в корзину |
| order_count | INT | orders |
| order_sum | DECIMAL(12,2) | Сумма заказов |
| buyout_count | INT | Выкупы |
| buyout_sum | DECIMAL(12,2) | Сумма выкупов |
| cancel_count | INT | Отмены |
| cancel_sum | DECIMAL(12,2) | Сумма отмен |
| avg_price | DECIMAL(12,2) | Средняя цена |
| avg_orders_count_per_day | DECIMAL(12,4) | Среднее кол-во заказов в день |
| share_order_percent | DECIMAL(5,2) | Доля заказов, % |
| add_to_wishlist | INT | Добавления в избранное |
| localization_percent | INT | Локализация, % |
| add_to_cart_percent | DECIMAL(5,2) | Конверсия в корзину, % |
| cart_to_order_percent | DECIMAL(5,2) | Конверсия корзина → заказ, % |
| buyout_percent | DECIMAL(5,2) | Процент выкупа, % |
| currency | VARCHAR(10) | Валюта |
| api_response | JSONB | Полный ответ API (опционально) |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_sales_funnel_products_daily`

Воронка по дням: одна строка = один nm_id на одну дату (API sales-funnel/products/history, день).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| report_date | DATE | Дата отчёта (день) |
| nm_id | BIGINT | Номенклатурный ID |
| title | VARCHAR(1000) | Название товара |
| vendor_code | VARCHAR(255) | Артикул поставщика |
| brand_name | VARCHAR(255) | Бренд |
| subject_id | BIGINT | ID категории |
| subject_name | VARCHAR(500) | Название категории |
| open_count | INT | Просмотры |
| cart_count | INT | В корзину |
| order_count | INT | orders |
| order_sum | DECIMAL(12,2) | Сумма заказов |
| buyout_count | INT | Выкупы |
| buyout_sum | DECIMAL(12,2) | Сумма выкупов |
| buyout_percent | DECIMAL(5,2) | Процент выкупа, % |
| add_to_cart_conversion | DECIMAL(5,2) | Конверсия просмотр → корзина, % |
| cart_to_order_conversion | DECIMAL(5,2) | Конверсия корзина → заказ, % |
| add_to_wishlist_count | INT | В избранное |
| currency | VARCHAR(10) | Валюта |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_sales_funnel_products_weekly`

Воронка по неделям: одна строка = один nm_id на одну неделю (aggregationLevel=week).

Столбцы совпадают с `wb_sales_funnel_products_daily`, вместо `report_date` — **report_week_start** (DATE) — дата начала недели.

### `reports.wb_sales_funnel_progress`

Служебная таблица прогресса загрузки воронки (период и дата среза).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | SERIAL | Первичный ключ |
| period_start | DATE | Начало периода |
| period_end | DATE | Конец периода |
| snapshot_date | DATE | Дата среза |
| updated_at | TIMESTAMPTZ | Время обновления |

---

## Отчёт о реализации (report detail)

Источник: API отчётов о продажах (реализация). Одна строка — одна позиция в отчёте.

### `reports.wb_report_detail_daily`

Детализация отчёта о реализации по дням/позициям.

| Столбец | Тип | Описание |
|--------|-----|----------|
| rrd_id | BIGINT | Первичный ключ (ID строки отчёта) |
| realizationreport_id | BIGINT | ID отчёта о реализации |
| srid | VARCHAR(255) | Уникальный идентификатор строки (srid) |
| date_from, date_to | DATE | Период отчёта |
| create_dt | TIMESTAMPTZ | Дата создания отчёта |
| currency_name | VARCHAR(50) | Валюта |
| suppliercontract_code | VARCHAR(255) | Код договора поставщика |
| gi_id | BIGINT | ID поставки (приёмки) |
| nm_id | BIGINT | Номенклатурный ID |
| subject_name | VARCHAR(500) | Категория (предмет) |
| brand_name | VARCHAR(255) | Бренд |
| sa_name | VARCHAR(255) | Название размера/артикула |
| ts_name | VARCHAR(100) | Размер |
| barcode | VARCHAR(255) | Штрихкод |
| doc_type_name | VARCHAR(255) | Тип документа |
| quantity | INTEGER | Количество |
| retail_price | DECIMAL(12,2) | Розничная цена |
| retail_amount | DECIMAL(12,2) | Сумма по розничной цене |
| sale_percent | DECIMAL(5,2) | Процент скидки продажи |
| commission_percent | DECIMAL(5,2) | Комиссия WB, % |
| retail_price_withdisc_rub | DECIMAL(12,2) | Цена с учётом скидки, руб |
| product_discount_for_report | DECIMAL(12,2) | Скидка на товар в отчёте |
| office_name | VARCHAR(255) | Офис |
| supplier_oper_name | VARCHAR(255) | Операция поставщика |
| order_dt | TIMESTAMPTZ | Дата заказа |
| sale_dt | TIMESTAMPTZ | Дата продажи (выкупа) |
| rr_dt | DATE | Дата отчёта о реализации |
| shk_id | BIGINT | ID штрихкода (ШК) |
| delivery_amount | DECIMAL(12,2) | Сумма доставки |
| return_amount | DECIMAL(12,2) | Сумма возврата |
| delivery_rub | DECIMAL(12,2) | Стоимость доставки, руб |
| gi_box_type_name | VARCHAR(255) | Тип короба приёмки |
| delivery_method | VARCHAR(255) | Способ доставки |
| supplier_promo | DECIMAL(12,2) | Промо поставщика |
| ppvz_spp_prc | DECIMAL(12,2) | СПП (субсидия WB), % |
| ppvz_kvw_prc_base, ppvz_kvw_prc | DECIMAL(12,2) | Базовый и фактический КВВ, % |
| sup_rating_prc_up | DECIMAL(12,2) | Надбавка за рейтинг, % |
| seller_promo_id | BIGINT | ID промо продавца |
| seller_promo_discount | DECIMAL(5,2) | Скидка промо продавца, % |
| loyalty_id | BIGINT | ID программы лояльности |
| loyalty_discount | DECIMAL(5,2) | Скидка лояльности, % |
| uuid_promocode | VARCHAR(255) | Промокод |
| sale_price_promocode_discount_prc | DECIMAL(5,2) | Скидка по промокоду, % |
| wibes_wb_discount_percent | DECIMAL(5,2) | Скидка WB, % |
| ppvz_sales_commission | DECIMAL(12,2) | Комиссия с продаж |
| ppvz_for_pay | DECIMAL(12,2) | К перечислению (итог к выплате) |
| ppvz_reward | DECIMAL(12,2) | Вознаграждение |
| acquiring_fee | DECIMAL(12,2) | Эквайринг, комиссия |
| acquiring_percent | DECIMAL(5,2) | Эквайринг, % |
| payment_processing | VARCHAR(255) | Платёжная система |
| acquiring_bank | VARCHAR(255) | Банк эквайринга |
| ppvz_vw, ppvz_vw_nds | DECIMAL(12,2) | Вознаграждение WB (с НДС/без) |
| ppvz_office_name | VARCHAR(255) | Офис ППВЗ |
| ppvz_office_id | BIGINT | ID офиса ППВЗ |
| ppvz_supplier_id | BIGINT | ID поставщика в системе WB |
| ppvz_supplier_name | VARCHAR(255) | Название поставщика |
| ppvz_inn | VARCHAR(50) | ИНН |
| declaration_number | VARCHAR(255) | Номер декларации |
| bonus_type_name | VARCHAR(255) | Тип бонуса |
| sticker_id | VARCHAR(255) | ID стикера |
| site_country | VARCHAR(100) | Страна сайта |
| srv_dbs | BOOLEAN | Признак ДБС |
| penalty | DECIMAL(12,2) | Штраф |
| additional_payment | DECIMAL(12,2) | Доп. платёж |
| rebill_logistic_cost | DECIMAL(12,2) | Перерасчёт логистики |
| rebill_logistic_org | VARCHAR(500) | Организация перерасчёта |
| storage_fee | DECIMAL(12,2) | Хранение |
| deduction | DECIMAL(12,2) | Удержание |
| acceptance | DECIMAL(12,2) | Приёмка |
| assembly_id | BIGINT | ID сборки |
| kiz | TEXT | КИЗ (маркировка) |
| report_type | INTEGER | Тип отчёта |
| is_legal_entity | BOOLEAN | Юрлицо |
| is_kgvp_v2 | INTEGER | Признак КГВП v2 |
| trbx_id | VARCHAR(255) | ID тарбокса |
| installment_cofinancing_amount | DECIMAL(12,2) | Рассрочка, софинансирование |
| cashback_amount | DECIMAL(12,2) | Кэшбэк сумма |
| cashback_discount | DECIMAL(12,2) | Кэшбэк скидка |
| cashback_commission_change | DECIMAL(12,2) | Изменение комиссии кэшбэка |
| order_uid | VARCHAR(255) | UID заказа |
| payment_schedule | INTEGER | График платежей |
| dlv_prc | DECIMAL(12,2) | Процент доставки |
| fix_tariff_date_from, fix_tariff_date_to | DATE | Период фикс. тарифа |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_report_detail_progress`

Прогресс загрузки отчёта о реализации: последняя обработанная дата.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | SERIAL | Первичный ключ |
| last_processed_date | DATE | Последняя обработанная дата (уникальная) |
| updated_at | TIMESTAMPTZ | Время обновления |

---

## orders и продажи поставщика

Источники: API supplier/orders, supplier/sales. Один срез в день (snapshot_date), история накапливается.

### `reports.wb_supplier_orders`

orders поставщика (каждый заказ/изменение — строка на дату среза).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза загрузки |
| date_ord | TIMESTAMPTZ | Дата заказа |
| last_change_date | TIMESTAMPTZ | Дата последнего изменения |
| warehouse_name | VARCHAR(255) | Склад |
| warehouse_type | VARCHAR(255) | Тип склада |
| country_name | VARCHAR(255) | Страна |
| oblast_okrug_name | VARCHAR(255) | Область/округ |
| region_name | VARCHAR(255) | Регион |
| supplier_article | VARCHAR(255) | Артикул поставщика |
| nm_id | BIGINT | Номенклатурный ID |
| barcode | VARCHAR(255) | Штрихкод |
| category | VARCHAR(500) | Категория |
| subject | VARCHAR(500) | Предмет (категория) |
| brand | VARCHAR(255) | Бренд |
| tech_size | VARCHAR(100) | Размер |
| income_id | BIGINT | ID поставки |
| is_supply | BOOLEAN | Признак поставки |
| is_realization | BOOLEAN | Признак реализации |
| total_price | DECIMAL(12,2) | Полочная цена |
| discount_percent | DECIMAL(5,2) | Скидка продавца, % |
| spp | DECIMAL(5,2) | СПП (субсидия WB Клуба), % |
| finished_price | DECIMAL(12,2) | Итоговая цена (с СПП) |
| price_with_disc | DECIMAL(12,2) | Цена со скидкой (без СПП) |
| is_cancel | BOOLEAN | Отмена заказа |
| cancel_date | TIMESTAMPTZ | Дата отмены |
| sticker | VARCHAR(255) | Стикер |
| g_number | VARCHAR(255) | Номер заказа (g_number) |
| srid | VARCHAR(500) | Уникальный ID строки заказа (srid) |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_supplier_sales`

sales и возвраты поставщика (каждая продажа/возврат — строка на дату среза).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза загрузки |
| date_ord | TIMESTAMPTZ | Дата заказа/продажи |
| last_change_date | TIMESTAMPTZ | Дата последнего изменения |
| warehouse_name | VARCHAR(255) | Склад |
| warehouse_type | VARCHAR(255) | Тип склада |
| country_name, oblast_okrug_name, region_name | VARCHAR | География |
| supplier_article | VARCHAR(255) | Артикул поставщика |
| nm_id | BIGINT | Номенклатурный ID |
| barcode | VARCHAR(255) | Штрихкод |
| category | VARCHAR(500) | Категория |
| subject | VARCHAR(500) | Предмет |
| brand | VARCHAR(255) | Бренд |
| tech_size | VARCHAR(100) | Размер |
| income_id | BIGINT | ID поставки |
| is_supply | BOOLEAN | Признак поставки |
| is_realization | BOOLEAN | Признак реализации |
| total_price | DECIMAL(12,2) | Полочная цена |
| discount_percent | DECIMAL(5,2) | Скидка продавца, % |
| spp | DECIMAL(5,2) | СПП, % |
| payment_sale_amount | DECIMAL(12,2) | Сумма к оплате (продажа) |
| for_pay | DECIMAL(12,2) | К перечислению |
| finished_price | DECIMAL(12,2) | Итоговая цена (с СПП) |
| price_with_disc | DECIMAL(12,2) | Цена со скидкой |
| sale_id | VARCHAR(255) | ID продажи |
| sticker | VARCHAR(255) | Стикер |
| g_number | VARCHAR(255) | Номер заказа |
| srid | VARCHAR(500) | Уникальный ID строки (srid) |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

Таблицы прогресса: `wb_supplier_orders_progress`, `wb_supplier_sales_progress` — хранят `last_change_date_from` и `updated_at` для инкрементальной загрузки.

---

## stocks поставщика

Источник: API supplier/stocks. Один срез в день по snapshot_date.

### `reports.wb_supplier_stocks`

stocks на складах WB (по barcode и складу на дату среза).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| last_change_date | TIMESTAMPTZ | Дата последнего изменения на WB |
| warehouse_name | VARCHAR(255) | Название склада |
| supplier_article | VARCHAR(255) | Артикул поставщика |
| nm_id | BIGINT | Номенклатурный ID |
| barcode | VARCHAR(255) | Штрихкод |
| quantity | INTEGER | Количество (доступно) |
| in_way_to_client | INTEGER | В пути к клиенту |
| in_way_from_client | INTEGER | В пути от клиента (возвраты) |
| quantity_full | INTEGER | Полное количество (с учётом в пути и т.д.) |
| category | VARCHAR(500) | Категория |
| subject | VARCHAR(500) | Предмет |
| brand | VARCHAR(255) | Бренд |
| tech_size | VARCHAR(100) | Размер |
| price | DECIMAL(12,2) | Цена |
| discount | DECIMAL(5,2) | Скидка, % |
| is_supply | BOOLEAN | Признак поставки |
| is_realization | BOOLEAN | Признак реализации |
| sc_code | VARCHAR(100) | Код склада |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

---

## prices поставщика

Источник: Content API (GET /api/v2/list/goods/filter). Один срез в день.

### `reports.wb_supplier_prices`

prices и скидки товаров WB на дату среза.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| nm_id | BIGINT | Номенклатурный ID |
| vendor_code | VARCHAR(255) | Артикул поставщика |
| currency_iso_code | VARCHAR(10) | Валюта |
| discount | DECIMAL(5,2) | Скидка продавца, % |
| club_discount | DECIMAL(5,2) | Скидка WB Клуба, % |
| editable_size_price | BOOLEAN | Редактируемая цена по размеру |
| is_bad_turnover | BOOLEAN | Низкая оборачиваемость |
| price | DECIMAL(12,2) | Базовая (полочная) цена |
| discounted_price | DECIMAL(12,2) | Цена со скидкой продавца |
| club_discounted_price | DECIMAL(12,2) | Цена со скидкой Клуба |
| sizes_json | JSONB | prices по размерам (JSON) |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

---

## Сводка остатков и продаж

Таблицы и представления, агрегирующие остатки и продажи по nm_id и складу на дату.

### `reports.wb_stocks_sales_daily`

Сводная таблица: остатки + продажи по nm_id и складу на дату среза. Заполняется ETL из `wb_supplier_stocks` и `wb_supplier_sales`.

| Столбец | Тип | Описание |
|--------|-----|----------|
| snapshot_date | DATE | Дата среза |
| nm_id | BIGINT | Номенклатурный ID |
| warehouse_name | VARCHAR(255) | Склад |
| stock_quantity | INTEGER | Остаток (доступно) |
| stock_quantity_full | INTEGER | Полный остаток |
| sales_count | INTEGER | Количество продаж за день |
| sales_amount | DECIMAL(12,2) | Сумма продаж за день (for_pay) |
| updated_at | TIMESTAMPTZ | Время обновления строки |

---

## marketing и продвижение

Источники: API Продвижения (normquery, fullstats, upd, balance, budget, кампании).

### `reports.wb_marketing_campaigns`

Рекламные кампании (поиск и медиа). Один срез на дату.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| campaign_type | VARCHAR(20) | Тип: 'promotion' (поиск) или 'media' |
| external_id | BIGINT | ID кампании в API (advertId) |
| name | VARCHAR(500) | Название кампании |
| status | INTEGER | Статус |
| type | INTEGER | Тип кампании |
| payment_type | VARCHAR(20) | Тип оплаты |
| brand | VARCHAR(255) | Бренд |
| created_at | TIMESTAMPTZ | Дата создания |
| updated_at | TIMESTAMPTZ | Дата обновления |
| started_at | TIMESTAMPTZ | Дата старта |
| deleted_at | TIMESTAMPTZ | Дата удаления |
| change_time | TIMESTAMPTZ | Время изменения |
| end_time | TIMESTAMPTZ | Время окончания |
| settings_json | JSONB | Настройки (JSON) |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_normquery_clusters`

Поисковые кластеры по кампаниям и номенклатуре (активные и исключённые). Снимок на дату.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| advert_id | BIGINT | ID рекламной кампании |
| nm_id | BIGINT | Номенклатурный ID |
| is_active | BOOLEAN | Активный (true) или исключённый (false) |
| norm_query | TEXT | Нормализованный поисковый запрос |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_normquery_bids`

Ставки по поисковым кластерам (в копейках).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| advert_id | BIGINT | ID кампании |
| nm_id | BIGINT | Номенклатурный ID |
| norm_query | TEXT | Поисковый запрос |
| bid | INTEGER | Ставка, копейки |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_normquery_minus`

Минус-фразы по кампаниям и номенклатуре.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| advert_id | BIGINT | ID кампании |
| nm_id | BIGINT | Номенклатурный ID |
| norm_query | TEXT | Минус-фраза |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_normquery_stats`

Статистика по поисковым кластерам за период (агрегат без разбивки по дням).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| period_from | DATE | Начало периода |
| period_to | DATE | Конец периода |
| advert_id | BIGINT | ID кампании |
| nm_id | BIGINT | Номенклатурный ID |
| norm_query | TEXT | Поисковый запрос |
| views | INTEGER | Показы |
| clicks | INTEGER | Клики |
| ctr | DECIMAL(12,4) | CTR, % |
| cpc | INTEGER | CPC, копейки |
| cpm | INTEGER | CPM, копейки |
| orders | INTEGER | orders |
| atbs | INTEGER | Добавления в корзину |
| avg_pos | DECIMAL(8,2) | Средняя позиция |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_normquery_stats_daily`

Статистика по поисковым кластерам по дням.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| stat_date | DATE | Дата |
| advert_id | BIGINT | ID кампании |
| nm_id | BIGINT | Номенклатурный ID |
| norm_query | TEXT | Поисковый запрос |
| views | INTEGER | Показы |
| clicks | INTEGER | Клики |
| ctr | DECIMAL(12,4) | CTR |
| cpc, cpm | DECIMAL(12,4) | CPC, CPM |
| orders | INTEGER | orders |
| shks | INTEGER | Выкупы (ШК) |
| atbs | INTEGER | В корзину |
| avg_pos | DECIMAL(8,2) | Средняя позиция |
| spend | DECIMAL(12,2) | Затраты |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_upd`

Фактические затраты по кампаниям за период (GET /adv/v1/upd).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| period_from | DATE | Начало периода |
| period_to | DATE | Конец периода |
| advert_id | BIGINT | ID кампании |
| camp_name | VARCHAR(500) | Название кампании |
| upd_sum | DECIMAL(12,2) | Сумма затрат |
| upd_time | TIMESTAMPTZ | Время |
| advert_type | INTEGER | Тип рекламы |
| payment_type | VARCHAR(100) | Тип оплаты |
| advert_status | INTEGER | Статус кампании |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_balance`

Баланс кабинета Продвижения (снимок на дату).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | SERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза (уникальная) |
| balance | DECIMAL(12,2) | Баланс |
| net | DECIMAL(12,2) | Нетто |
| bonus | DECIMAL(12,2) | Бонусы |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_budget`

Бюджет кампаний (снимок на дату).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| advert_id | BIGINT | ID кампании |
| cash | DECIMAL(12,2) | Денежный бюджет |
| netting | DECIMAL(12,2) | Зачёт |
| total | DECIMAL(12,2) | Итого бюджет |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_campaign_stats_daily`

Агрегированная статистика по кампаниям по дням (fullstats).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| stat_date | DATE | Дата |
| advert_id | BIGINT | ID кампании |
| views | INTEGER | Показы |
| clicks | INTEGER | Клики |
| ctr | DECIMAL(12,4) | CTR |
| cpc | DECIMAL(12,4) | CPC |
| orders | INTEGER | orders |
| shks | INTEGER | Выкупы |
| sum_spend | DECIMAL(12,2) | Затраты |
| atbs | INTEGER | В корзину |
| canceled | INTEGER | Отмены |
| cr | DECIMAL(12,4) | CR (конверсия) |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_campaign_nms`

Детализация кампаний по номенклатуре: какие nm_id в каких кампаниях, ставки.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| advert_id | BIGINT | ID кампании |
| nm_id | BIGINT | Номенклатурный ID |
| subject_id | INTEGER | ID категории |
| subject_name | VARCHAR(500) | Название категории |
| bid_search_kopecks | INTEGER | Ставка поиска, копейки |
| bid_recommendations_kopecks | INTEGER | Рекомендуемая ставка, копейки |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_marketing_campaign_stats_daily_nms`

Статистика по кампаниям по дням с разбивкой по nm_id (SKU).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| stat_date | DATE | Дата |
| advert_id | BIGINT | ID кампании |
| nm_id | BIGINT | Номенклатурный ID |
| nm_name | VARCHAR(500) | Название номенклатуры |
| views | INTEGER | Показы |
| clicks | INTEGER | Клики |
| ctr | DECIMAL(12,4) | CTR |
| cpc | DECIMAL(12,4) | CPC |
| orders | INTEGER | orders |
| shks | INTEGER | Выкупы |
| sum_spend | DECIMAL(12,2) | Затраты |
| atbs | INTEGER | В корзину |
| canceled | INTEGER | Отмены |
| cr | DECIMAL(12,4) | CR |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

---

## supplies

Источник: API supplies (supplies-api.wildberries.ru). Один срез в день.

### `reports.wb_supplies`

supplies (заголовки).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| supply_id | BIGINT | ID поставки |
| preorder_id | BIGINT | ID предзаказа (если не поставка) |
| create_date | TIMESTAMPTZ | Дата создания |
| supply_date | DATE | Плановая дата поставки |
| fact_date | TIMESTAMPTZ | Фактическая дата |
| updated_date | TIMESTAMPTZ | Дата обновления |
| status_id | SMALLINT | Статус поставки |
| phone | VARCHAR(50) | Телефон |
| box_type_id | SMALLINT | Тип короба |
| warehouse_id | INT | ID склада |
| warehouse_name | VARCHAR(255) | Название склада |
| actual_warehouse_id | INT | Фактический склад ID |
| actual_warehouse_name | VARCHAR(255) | Фактический склад название |
| transit_warehouse_id | INT | Транзитный склад ID |
| transit_warehouse_name | VARCHAR(255) | Транзитный склад название |
| acceptance_cost | DECIMAL(12,2) | Стоимость приёмки |
| paid_acceptance_coefficient | INT | Коэффициент платной приёмки |
| reject_reason | TEXT | Причина отказа |
| supplier_assign_name | VARCHAR(255) | Назначение поставщика |
| storage_coef | VARCHAR(50) | Коэффициент хранения |
| delivery_coef | VARCHAR(50) | Коэффициент доставки |
| quantity | INT | Количество |
| ready_for_sale_quantity | INT | Готово к продаже |
| accepted_quantity | INT | Принято |
| unloading_quantity | INT | Выгружено |
| depersonalized_quantity | INT | Обезличено |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_supplies_goods`

Товары в поставках (позиции).

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| supply_id | BIGINT | ID поставки |
| barcode | VARCHAR(255) | Штрихкод |
| vendor_code | VARCHAR(255) | Артикул поставщика |
| nm_id | BIGINT | Номенклатурный ID |
| need_kiz | BOOLEAN | Требуется КИЗ |
| tnved | VARCHAR(50) | ТНВЭД |
| tech_size | VARCHAR(100) | Размер |
| color | VARCHAR(255) | Цвет |
| supplier_box_amount | INT | Количество коробов поставщика |
| quantity | INT | Количество |
| ready_for_sale_quantity | INT | Готово к продаже |
| unloading_quantity | INT | Выгружено |
| accepted_quantity | INT | Принято |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

---

## tariffs WB

Источник: Common API (commission, box, pallet, return, acceptance/coefficients). Один срез в день по snapshot_date.

### `reports.wb_tariffs_commission`

Комиссия WB по родительским категориям.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза (уникальная) |
| report_json | JSONB | Ответ API (комиссии по категориям) |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_tariffs_box`

tariffs на остаток (короба) по складам.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза (уникальная) |
| response_json | JSONB | Ответ API |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_tariffs_pallet`

tariffs на остаток (паллеты) по складам.

Структура как у `wb_tariffs_box`: id, snapshot_date, response_json, last_synced_at.

### `reports.wb_tariffs_return`

Стоимость возврата продавцу по складам.

Структура: id, snapshot_date, response_json, last_synced_at.

### `reports.wb_tariffs_acceptance`

Коэффициенты приёмки на поставку по складам.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза (уникальная) |
| data_json | JSONB | Данные API |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.v_wb_tariffs_commission`

Нормализованное представление по комиссиям WB: одна строка = одна категория (`subject_id`) в один день.

| Столбец | Описание |
|--------|----------|
| snapshot_date | Дата среза |
| parent_id, parent_name | Родительская категория |
| subject_id, subject_name | Категория товара |
| kgvp_booking | Комиссия по модели Booking, % |
| kgvp_marketplace | Комиссия по модели Marketplace, % |
| kgvp_pickup | Комиссия по модели Pickup, % |
| kgvp_supplier | Комиссия по модели Supplier, % |
| kgvp_supplier_express | Комиссия Supplier Express, % |
| paid_storage_kgvp | Базовая комиссия, которая лучше всего совпадает с фактическим `commission_percent` в `wb_report_detail_daily` |

### `reports.v_wb_tariffs_box`

Нормализованные box-тарифы по складам: доставка, хранение и коэффициенты.

### `reports.v_wb_tariffs_pallet`

Нормализованные pallet-тарифы по складам: доставка и хранение.

### `reports.v_wb_tariffs_return`

Нормализованные тарифы возврата продавцу по складам.

### `reports.v_wb_tariffs_acceptance`

Нормализованные коэффициенты приёмки WB: дата, склад, тип короба, коэффициенты доставки и хранения.

### `reports.v_wb_tariffs_*_latest`

Удобные представления с последним доступным `snapshot_date` по каждому виду тарифов:

- `reports.v_wb_tariffs_commission_latest`
- `reports.v_wb_tariffs_box_latest`
- `reports.v_wb_tariffs_pallet_latest`
- `reports.v_wb_tariffs_return_latest`
- `reports.v_wb_tariffs_acceptance_latest`

### `reports.v_wb_unit_economics`

Витрина юнит-экономики по текущим ценам WB: одна строка = один `nm_id` из последнего среза `wb_supplier_prices`.

Ключевые поля:

| Столбец | Описание |
|--------|----------|
| nm_id | Артикул WB |
| vendor_code, brand_name | Метаданные товара |
| subject_id, subject_name | Категория товара |
| price_list | Цена без скидки |
| discounted_price | Текущая цена со скидкой |
| club_discounted_price | Цена по клубной скидке |
| price_current | Цена, от которой считается юнит-экономика (`club_discounted_price -> discounted_price -> price_list`) |
| tariff_commission_pct | Текущая комиссия WB из `v_wb_tariffs_commission_latest.paid_storage_kgvp`, % |
| actual_commission_pct_90d | Фактическая средняя комиссия за последние 90 дней, % |
| actual_acquiring_pct_90d | Фактический эквайринг за последние 90 дней, % |
| sold_units_90d | Продано единиц за 90 дней |
| returned_units_90d | Возвраты за 90 дней |
| return_rate_90d_pct | Доля возвратов от продаж, % |
| avg_delivery_rub_per_unit_90d | Средняя логистика на единицу, руб |
| avg_storage_rub_per_unit_90d | Среднее хранение на единицу, руб |
| avg_acceptance_rub_per_unit_90d | Средняя приёмка на единицу, руб |
| estimated_commission_rub | Оценочная комиссия WB в рублях по текущей цене |
| estimated_acquiring_rub | Оценочный эквайринг в рублях по текущей цене |
| estimated_other_costs_rub | Исторические средние прочие удержания на единицу |
| estimated_profit_before_cogs_rub | Оценочный профит одной продажи до себестоимости товара |
| estimated_margin_before_cogs_pct | Маржинальность до себестоимости товара, % |

### `reports.wb_unit_economics`

Физическая таблица-витрина с теми же колонками, что и `reports.v_wb_unit_economics`.

- Нужна для BI/SQL-клиентов, которые не показывают `VIEW` рядом с таблицами.
- Полностью пересобирается функцией `reports.refresh_wb_unit_economics()`.

---

## Календарь акций

Источник: API /api/v1/calendar/promotions. Один срез в день.

### `reports.wb_calendar_promotions`

Календарь акций WB: одна строка — одна акция на дату среза.

| Столбец | Тип | Описание |
|--------|-----|----------|
| id | BIGSERIAL | Первичный ключ |
| snapshot_date | DATE | Дата среза |
| promotion_id | BIGINT | ID акции |
| name | VARCHAR(500) | Название акции |
| start_date_time | TIMESTAMPTZ | Начало акции |
| end_date_time | TIMESTAMPTZ | Окончание акции |
| type | VARCHAR(100) | Тип акции |
| last_synced_at | TIMESTAMPTZ | Время последней синхронизации |

### `reports.wb_calendar_promotions_progress`

Прогресс загрузки календаря акций: граница по end_date_time и updated_at.

---

## Витрина AI-планирования продаж

Материализованное представление для ML/аналитики. Зерно: **один nm_id на одну дату (report_date)**. Обновляется через REFRESH MATERIALIZED VIEW CONCURRENTLY после загрузки исходных таблиц.

### `reports.mart_ai_sales_planning`

Содержит 14 логических блоков: идентификаторы и период → цены и скидки → воронка спроса → конверсии → эластичность → остатки → оборачиваемость → финансы → ML-фичи → целевые переменные → сезонность (A) → поставки (B) → маркетинг (C) → возвраты (D) → расширенная прибыльность (G+).

**Блок 0 — Идентификаторы и период**

| Столбец | Описание |
|--------|----------|
| report_date | Дата отчёта (день) |
| week_start | Начало недели (понедельник) |
| nm_id | Номенклатурный ID |
| vendor_code | Артикул поставщика |
| brand_name | Бренд |
| subject_name | Категория (предмет) |

**Блок 1 — prices и скидки**

| Столбец | Описание |
|--------|----------|
| price_raw | Полочная цена до скидок (carry-forward из wb_supplier_sales) |
| discount_pct | Скидка продавца, % |
| spp_pct | СПП (субсидия WB Клуба), % |
| price_final | Цена заказа = price_raw × (1 − discount%) |
| price_with_spp | Цена с учётом СПП = price_final × (1 − spp%) |
| price_sale | Контрольная цена из воронки (order_sum/order_count) |
| price_final_prev_week | Цена заказа неделю назад |
| price_change_pct | Изменение цены к предыдущей неделе, % |

**Блок 2 — Воронка спроса (дневные абсолюты)**

| Столбец | Описание |
|--------|----------|
| open_count | Просмотры карточки |
| cart_count | В корзину |
| order_count_day | orders за день |
| order_sum_day | Сумма заказов за день |
| buyout_count_day | Выкупы за день |
| buyout_sum_day | Сумма выкупов за день |
| cancel_count_day | Отмены за день |
| wishlist_count | В избранное |

**Блок 3 — Конверсии воронки**

| Столбец | Описание |
|--------|----------|
| open_to_cart_pct | Конверсия просмотр → корзина, % |
| cart_to_order_pct | Конверсия корзина → заказ, % |
| order_to_buyout_pct | Конверсия заказ → выкуп, % |
| is_conversion_anomaly | Флаг невалидной конверсии: хотя бы одна из `open_to_cart_pct`, `cart_to_order_pct`, `order_to_buyout_pct` вне диапазона 0–100 |
| cancel_rate_pct | Доля отмен от заказов, % |

**Блок 4 — Эластичность спроса**

| Столбец | Описание |
|--------|----------|
| order_count_prev_week | orders неделю назад |
| order_change_pct | Изменение заказов к предыдущей неделе, % |
| price_elasticity_point | Точечная эластичность (ΔQ% / ΔP%) |
| elasticity_rolling_4w | Скользящая эластичность за 28 дней |

**Блок 5 — stocks**

| Столбец | Описание |
|--------|----------|
| stock_qty | Остаток (carry-forward из wb_supplier_stocks) |
| stock_qty_full | Полный остаток |
| in_way_to_client | В пути к клиенту |
| in_way_from_client | В пути от клиента |
| stock_week_avg | Средний остаток за 7 дней |

**Блок 6 — Оборачиваемость запасов**

| Столбец | Описание |
|--------|----------|
| sales_per_day | Выкупы за день (дубль buyout_count_day) |
| sales_7d_sum | Сумма выкупов за 7 дней |
| sales_28d_avg_per_day | Среднее выкупов в день за 28 дней |
| days_of_stock | Дней запаса (остаток / sales_28d_avg_per_day) |
| stock_turnover_weekly | Оборачиваемость за неделю (sales_7d / stock_week_avg) |
| reorder_flag | Маркер пополнения: 'no_sales', 'critical', 'warning', 'ok' |

**Блок 7 — Финансы** (из wb_report_detail_daily)

| Столбец | Описание |
|--------|----------|
| revenue_gross | Выручка брутто |
| revenue_net | Выручка нетто (retail_price_withdisc_rub × quantity) |
| ppvz_for_pay | К перечислению |
| commission_pct | Комиссия WB, % |
| delivery_cost | Стоимость доставки |
| storage_fee | Хранение |
| penalty | Штрафы |
| net_profit_per_unit | Чистая прибыль на единицу (расчётная) |

**Блок 8 — ML-фичи (исторические признаки)**

| Столбец | Описание |
|--------|----------|
| sales_lag_1w, sales_lag_2w, sales_lag_4w | Выкупы за 7 дней 1/2/4 недели назад |
| sales_rolling_4w_avg | Скользящее среднее выкупов за 28 дней |
| sales_rolling_4w_std | Скользящее СКО выкупов за 28 дней |
| product_rating | Рейтинг товара |
| feedback_rating | Рейтинг отзывов |
| open_count_lag_1w | Просмотры неделю назад |
| open_count_rolling_7d | Сумма просмотров за 7 дней |

**Блок 9 — Целевые переменные (постфактум для обучения ML)**

| Столбец | Описание |
|--------|----------|
| target_orders_next_7d | orders за следующие 7 дней |
| target_buyouts_next_7d | Выкупы за следующие 7 дней |

**Блок A — Сезонность и акции**

| Столбец | Описание |
|--------|----------|
| week_of_year | Номер недели в году (ISO) |
| month_num | Номер месяца (1–12) |
| is_weekend | Признак выходного дня (суббота/воскресенье) |
| is_promo_period | Признак: дата попадает в акцию WB (из wb_calendar_promotions) |
| days_to_next_promo | Дней до начала следующей акции WB |
| yoy_orders_change_pct | Изменение заказов год-к-году (та же дата −364 дня), % |

**Блок B — supplies и пополнение**

| Столбец | Описание |
|--------|----------|
| last_supply_date | Дата последней завершённой поставки (carry-forward из wb_supplies) |
| days_since_last_supply | Дней с момента последней поставки |
| pending_supply_qty | Количество единиц в незакрытых поставках (fact_date IS NULL) |
| avg_supply_interval_days | Средний интервал между поставками, дней |
| reorder_qty_recommended | Рекомендуемый объём пополнения: `sales_28d_avg×44 − stock_qty − pending_supply_qty` (горизонт 30 дней + страховой запас 14 дней) |

**Блок C — marketing**

| Столбец | Описание |
|--------|----------|
| adv_spend_day | Расходы на рекламу за день, руб (из wb_marketing_campaign_stats_daily_nms) |
| adv_orders_day | orders с рекламы за день |
| has_active_campaign | Признак: по nm_id есть активная рекламная кампания в этот день |
| adv_cpo | Стоимость одного рекламного заказа (adv_spend_day / adv_orders_day), руб |
| adv_roas | Возврат на рекламные расходы (revenue_net / adv_spend_day) |

**Блок D — Возвраты**

| Столбец | Описание |
|--------|----------|
| return_count_day | Количество возвратов за день (из wb_report_detail_daily, doc_type = Возврат) |
| return_sum_day | Сумма возвратов за день, руб |
| net_sales_day | Чистые продажи за день = buyout_count_day − return_count_day |
| return_rate_30d | Процент возвратов за 30 дней (скользящий) от выкупов, % |

**Блок G+ — Расширенная прибыльность**

| Столбец | Описание |
|--------|----------|
| margin_pct | Маржинальность = net_profit_per_unit / price_final × 100, % |
| effective_commission_pct | Фактическая комиссия с учётом всех удержаний = (1 − ppvz_for_pay / revenue_net) × 100, % |

---

## Представления (views)

### `reports.v_stocks_sales_daily`

Сводка по nm_id и складу на дату среза остатков: базовая дата из `wb_supplier_stocks.snapshot_date`, продажи подтягиваются за ту же календарную дату из `wb_supplier_sales`. Столбцы: snapshot_date, nm_id, warehouse_name, stock_quantity, stock_quantity_full, sales_count, sales_amount.

### `reports.v_stocks_sales_daily_readable`

Удобная сводка остатков и продаж с названием товара, брендом и артикулом поставщика. Зерно: nm_id × склад × дата среза. В выборку попадают только склады с положительным остатком. sales — агрегат по nm_id на дату (без жёсткого джойна по складу). Столбцы: snapshot_date, nm_id, warehouse_name, subject, brand, supplier_article, stock_quantity, stock_quantity_full, sales_count, sales_amount, sales_warehouses.

---

*Документ сгенерирован по SQL-схемам в `tables/reports`. При изменении схем обновите описание.*
