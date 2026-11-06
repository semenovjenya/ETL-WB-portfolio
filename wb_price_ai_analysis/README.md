# WB Price AI Analysis

Новый pipeline строит per-SKU AI-витрину цен и конкурентов поверх `reports.wb_sku_ai_analysis`.

Поток:
- общий source snapshot через `WB_sku_ai_analysis`;
- `prepare_active_skus.py` подготавливает один payload на `nm_id`;
- `generate_seo_keywords.py` генерирует 5 SEO-ключей;
- `fetch_raw_competitors_per_sku.py` собирает raw candidates по одному SKU и пишет `competitors_raw`;
- `normalize_candidate_attributes_per_sku.py` раскладывает source/candidate в нормализованные признаки;
- `apply_hard_filters_per_sku.py` применяет category-aware hard filters и выбирает top-N для relevance;
- `score_relevance_with_llm_per_sku.py` оценивает top candidates через LLM;
- `grade_visual_match_per_sku.py` дополнительно оценивает shortlist через OpenAI Vision и пишет visual grade/score/reason;
- `finalize_price_ai_row.py` собирает final mart `1 row per SKU` из relevance-aware слоя;
- `merge_run_stats.py` пишет run summary JSON.

Таблицы:
- `reports.wb_price_ai_seo_keywords`
- `reports.wb_price_ai_competitors_raw`
- `reports.wb_price_ai_competitor_features`
- `reports.wb_price_ai_competitors_filtered`
- `reports.wb_price_ai_competitor_relevance`
- `reports.wb_price_ai_competitor_vision`
- `reports.wb_price_ai_analysis`
- `reports.v_wb_price_ai_analysis_latest`

Канонический ежедневный SERP-контур хранится в `analytics_ai`:
- `wb_serp_runs` — один доказуемый запуск поиска на `SKU × запрос`;
- `wb_serp_query_sets` — закреплённый набор запросов для каждого SKU;
- `wb_serp_items` — все появления карточек, включая рекламу, органику и нашу карточку;
- `wb_serp_jobs` — очередь host browser-worker;
- `wb_serp_worker_heartbeats` — liveness host worker между заданиями;
- `mart_serp_query_daily` — дневная витрина по запросам;
- `mart_serp_competitors_daily` — все конкуренты выше нашей органической карточки;
- `v_wb_serp_competitors_latest` — последний валидный SERP-снимок конкурентов по SKU;
- `mart_price_context_daily` — дневной price context по SKU.

Для `demo` DAG `wb_demo_serp_snapshot` запускается ежедневно в 10:30 по Москве.
При первом появлении SKU он выбирает до пяти запросов: сначала запросы с заказами,
затем с частотностью, после чего дополняет набор последней успешной SEO-генерацией.
Набор сохраняется в `wb_serp_query_sets` и переиспользуется без ежедневной
перегенерации, чтобы позиции были сопоставимы между датами. Поиск идёт до
органического появления нашей карточки, но не далее 200 позиций. Рекламное
появление не считается SEO-позицией.

Карточка считается конкурентом по структурной релевантности товара. Отличие цены
не делает её невалидной: `price_peer` отдельно отмечает карточки в коридоре ±35%,
а остальные валидные товары получают `market_competitor`. В compatibility-слой
попадают только карточки, которые реально были выше нашей органической позиции.
Если наша карточка не найдена, строки «выше нас» не строятся.

Важно:
- основная цена нашей карточки в `wb_price_ai_analysis` берётся из отчёта цен продавца WB;
- покупательские цены хранятся отдельно: SERP даёт эффективную/Wallet-цену, а обычная цена сайта дополнительно читается со страницы нашей карточки;
- `source_platform_discount_percent`, `source_wallet_discount_percent` и `source_report_to_site_discount_percent` объясняют разницу между отчётом и сайтом, когда соответствующие уровни цены доступны;
- competitor stage рассчитан на host runtime с GUI и persistent Playwright profile;
- в Docker Airflow только `fetch_raw_competitors_per_sku` ставит job в PostgreSQL queue и ждёт host worker;
- все stage после raw-search (`normalize/filter/relevance/vision/finalize`) выполняются в обычном Airflow runtime без GUI;
- SEO по умолчанию идёт через `https://polza.ai/api/v1`;
- модель SEO по умолчанию: `openai/gpt-5.4`.

Host-runner pipeline:
- Docker Airflow task `fetch_raw_competitors_per_sku` ставит `pending` job в `reports.wb_price_ai_competitor_jobs`;
- host worker на основной машине забирает job, запускает browser-first raw-search конкурентов и пишет результат обратно в БД;
- Airflow polling читает `completed/failed` job и передаёт payload дальше в `normalize -> filter -> relevance -> finalize`.

Команда для host worker:

```bash
python3 scripts/run_tenant_host_worker.py --tenant-id demo-964857b7ff1d --headless
```

Для параллельного второго worker обязательно задаются отдельные worker ID и
Playwright profile, чтобы два Chromium-процесса не блокировали один каталог:

```bash
python3 scripts/run_tenant_host_worker.py \
  --tenant-id demo-964857b7ff1d \
  --headless \
  --worker-name worker-2 \
  --browser-profile-dir .
```

По умолчанию tenant-wrapper обрабатывает только новую SERP-очередь. Чтобы также
забирать старые `wb_price_ai_competitor_jobs`, добавьте
`--include-legacy-competitor-jobs`.

Для разового теста одной job:

```bash
python3 scripts/run_tenant_host_worker.py --tenant-id demo-964857b7ff1d --once
```

Ручной повтор снимка за тот же день должен получать новое `observed_at`, чтобы
не переиспользовать детерминированный batch уже завершённого расписания:

```bash
airflow dags trigger wb_demo_serp_snapshot \
  --conf '{"observed_at":"2026-07-21T16:00:00+03:00"}'
```

Обёртка сама берёт tenant secrets и определяет опубликованный host-порт PostgreSQL,
не передавая Docker hostname в host-side Playwright process.
На macOS автозапуск через LaunchAgent требует разрешения на доступ к `Documents`;
без него worker нужно держать запущенным из Terminal/Codex с таким разрешением.

Сохранённый канонический batch можно повторно спроецировать в price-analysis без
повторного открытия WB функцией `serp_snapshot.rebuild_serp_analysis_batch`. Это
нужно для backfill после изменения правил фильтрации; исходные SERP runs/items при
этом не меняются.

Полезные env:
- `WB_PRICE_AI_HOST_RUNNER_ENABLED=true`
- `WB_PRICE_AI_HOST_RUNNER_POLL_INTERVAL_SEC=5`
- `WB_PRICE_AI_HOST_RUNNER_TIMEOUT_SEC=3600`
- `WB_PRICE_AI_HOST_RUNNER_STALE_SEC=1800`
- `WB_PRICE_AI_HOST_WORKER_ID=<hostname-or-label>`
- `WB_PRICE_AI_RELEVANCE_OPENAI_API_KEY=<key>`
- `WB_PRICE_AI_RELEVANCE_MODEL=gpt-4o-mini`
- `WB_PRICE_AI_RELEVANCE_THRESHOLD=0.75`
- `WB_PRICE_AI_VISION_OPENAI_API_KEY=<key>`
- `WB_PRICE_AI_VISION_MODEL=gpt-4o-mini`
- `WB_PRICE_AI_VISION_PROMPT_VERSION=v1`
- `WB_PRICE_AI_VISION_LIMIT_PER_SKU=3`
- `WB_PRICE_AI_NORMALIZATION_VERSION=v1`
- `WB_PRICE_AI_FILTER_VERSION=v1`
- `WB_PRICE_AI_PIPELINE_VERSION=v2`
- `WB_SERP_MAX_QUERIES_PER_SKU=5`
- `WB_SERP_QUERY_MAX_AGE_DAYS=14`
- `WB_SERP_MAX_POSITIONS=200`
- `WB_SERP_MAX_PAGES=5`
- `WB_SERP_DEST=-1257786`
- `WB_SERP_MIN_COMPLETION_RATIO=0.80`
- `WB_SERP_JOB_TIMEOUT_SEC=7200`
