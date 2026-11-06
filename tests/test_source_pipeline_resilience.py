from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import types

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, relative_path: str):
    module_path = PROJECT_ROOT / relative_path
    module_dir = str(module_path.parent)
    project_root = str(PROJECT_ROOT)
    dags_root = str(PROJECT_ROOT / "airflow_home" / "dags")
    original_path = list(sys.path)
    sys.path.insert(0, module_dir)
    sys.path.insert(0, dags_root)
    sys.path.insert(0, project_root)
    for transient_name in ("config", "database"):
        sys.modules.pop(transient_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Не удалось создать spec для {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = original_path


def _load_package_module(package_name: str, module_leaf: str, relative_path: str):
    module_path = PROJECT_ROOT / relative_path
    module_dir = str(module_path.parent)
    parent_dir = str(module_path.parent.parent)
    project_root = str(PROJECT_ROOT)
    dags_root = str(PROJECT_ROOT / "airflow_home" / "dags")
    original_path = list(sys.path)
    sys.path.insert(0, parent_dir)
    sys.path.insert(1, module_dir)
    sys.path.insert(0, dags_root)
    sys.path.insert(0, project_root)
    for transient_name in ("config", "database"):
        sys.modules.pop(transient_name, None)
    package = types.ModuleType(package_name)
    package.__path__ = [module_dir]
    sys.modules[package_name] = package
    module_name = f"{package_name}.{module_leaf}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Не удалось создать spec для {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = original_path


db_tasks_module = _load_module(
    "daily_pipeline_db_tasks_test",
    "airflow_home/dags/_daily_pipeline/db_tasks.py",
)
_calculate_drop_pct = db_tasks_module._calculate_drop_pct
_is_critical_volume_drop = db_tasks_module._is_critical_volume_drop
_is_progress_ahead = db_tasks_module._is_progress_ahead


class _FakeCursor:
    def __init__(self, *, fetchall_responses, fetchone_responses=None):
        self.calls = []
        self._fetchall_responses = list(fetchall_responses)
        self._fetchone_responses = list(fetchone_responses or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self._fetchall_responses.pop(0)

    def fetchone(self):
        return self._fetchone_responses.pop(0)


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_sales_funnel_build_missing_report_dates_handles_gap_inside_window() -> None:
    module = _load_module(
        "sales_funnel_fetch_test",
        "sales_funnel/fetch_sales_funnel_90d_daily.py",
    )

    missing_dates = module.build_missing_report_dates(
        date(2026, 3, 1),
        date(2026, 3, 4),
        {date(2026, 3, 1), date(2026, 3, 3), date(2026, 3, 4)},
    )

    assert missing_dates == [date(2026, 3, 2)]


def test_sales_funnel_build_missing_report_dates_ignores_dates_outside_window() -> None:
    module = _load_module(
        "sales_funnel_fetch_test_outside",
        "sales_funnel/fetch_sales_funnel_90d_daily.py",
    )

    missing_dates = module.build_missing_report_dates(
        date(2026, 3, 2),
        date(2026, 3, 4),
        {date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 4)},
    )

    assert missing_dates == [date(2026, 3, 3)]


def test_marketing_campaign_filter_keeps_only_active_and_recently_finished() -> None:
    module = _load_module(
        "marketing_campaign_filter_status_test",
        "marketing/fetch_campaigns.py",
    )

    snapshot_date = date(2026, 5, 7)

    assert module.CampaignsFetcher._should_keep_promotion_item(
        status_value=11,
        change_time_value="2023-01-01T00:00:00+03:00",
        snapshot_date=snapshot_date,
    ) is True
    assert module.CampaignsFetcher._should_keep_promotion_item(
        status_value=7,
        change_time_value="2026-05-01T12:00:00+03:00",
        snapshot_date=snapshot_date,
    ) is True
    assert module.CampaignsFetcher._should_keep_promotion_item(
        status_value=7,
        change_time_value="2023-06-20T00:00:00+03:00",
        snapshot_date=snapshot_date,
    ) is False


def test_marketing_campaign_filter_drops_old_finished_details() -> None:
    module = _load_module(
        "marketing_campaign_filter_details_test",
        "marketing/fetch_campaigns.py",
    )

    snapshot_date = date(2026, 5, 7)

    assert module.CampaignsFetcher._should_keep_normalized_campaign(
        {
            "status": 11,
            "deleted_at": None,
            "updated_at": None,
            "started_at": datetime(2025, 9, 11, 0, 0, 0),
        },
        snapshot_date,
    ) is True
    assert module.CampaignsFetcher._should_keep_normalized_campaign(
        {
            "status": 7,
            "deleted_at": datetime(2026, 5, 1, 0, 0, 0),
            "updated_at": None,
            "started_at": None,
        },
        snapshot_date,
    ) is True
    assert module.CampaignsFetcher._should_keep_normalized_campaign(
        {
            "status": 7,
            "deleted_at": datetime(2023, 6, 20, 0, 0, 0),
            "updated_at": None,
            "started_at": None,
        },
        snapshot_date,
    ) is False


def test_report_detail_build_intervals_uses_fixed_31_day_windows() -> None:
    module = _load_module(
        "report_detail_fetch_test_intervals",
        "finance/fetch_report_detail.py",
    )

    intervals = module.build_report_detail_intervals(
        date(2026, 1, 1),
        date(2026, 2, 15),
        interval_days=31,
    )

    assert intervals == [
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 15)),
    ]


def test_report_detail_build_missing_intervals_returns_only_gaps() -> None:
    module = _load_module(
        "report_detail_fetch_test_missing",
        "finance/fetch_report_detail.py",
    )

    missing_intervals = module.build_missing_report_detail_intervals(
        date(2026, 1, 1),
        date(2026, 4, 5),
        {
            date(2026, 1, 31),
            date(2026, 4, 5),
        },
        interval_days=31,
    )

    assert missing_intervals == [
        (date(2026, 1, 1), date(2026, 1, 30)),
        (date(2026, 2, 1), date(2026, 3, 3)),
        (date(2026, 3, 4), date(2026, 4, 3)),
        (date(2026, 4, 4), date(2026, 4, 4)),
    ]


def test_report_detail_build_missing_intervals_returns_empty_when_no_gaps() -> None:
    module = _load_module(
        "report_detail_fetch_test_no_missing",
        "finance/fetch_report_detail.py",
    )

    missing_intervals = module.build_missing_report_detail_intervals(
        date(2026, 3, 1),
        date(2026, 3, 3),
        {date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)},
        interval_days=31,
    )

    assert missing_intervals == []


def test_report_detail_build_missing_intervals_keeps_sparse_gaps_separate() -> None:
    module = _load_module(
        "report_detail_fetch_test_sparse_missing",
        "finance/fetch_report_detail.py",
    )

    missing_intervals = module.build_missing_report_detail_intervals(
        date(2026, 3, 1),
        date(2026, 3, 5),
        {date(2026, 3, 1), date(2026, 3, 3), date(2026, 3, 5)},
        interval_days=31,
    )

    assert missing_intervals == [
        (date(2026, 3, 2), date(2026, 3, 2)),
        (date(2026, 3, 4), date(2026, 3, 4)),
    ]


def test_report_detail_build_missing_intervals_caps_long_gap_at_interval_days() -> None:
    module = _load_module(
        "report_detail_fetch_test_long_missing",
        "finance/fetch_report_detail.py",
    )

    missing_intervals = module.build_missing_report_detail_intervals(
        date(2026, 1, 1),
        date(2026, 2, 5),
        set(),
        interval_days=31,
    )

    assert missing_intervals == [
        (date(2026, 1, 1), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 5)),
    ]


def test_report_detail_default_window_uses_last_90_days_until_yesterday() -> None:
    module = _load_module(
        "report_detail_fetch_test_default_window",
        "finance/fetch_report_detail.py",
    )

    start_date, end_date = module.get_default_report_detail_window(date(2026, 3, 31))

    assert start_date == date(2025, 12, 31)
    assert end_date == date(2026, 3, 30)


def test_report_detail_dag_task_runs_fetcher_without_explicit_range(monkeypatch) -> None:
    module = _load_module(
        "source_groups_report_detail_test",
        "airflow_home/dags/_daily_pipeline/source_groups.py",
    )
    calls = []

    def fake_run_tenant_job(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(module, "run_tenant_job", fake_run_tenant_job)

    module.report_detail_fetch_report_data_task("tenant-id")

    assert calls == [
        {
            "tenant_id": "tenant-id",
            "module_dir": "finance",
            "action": "fetcher-run",
            "module_name": "fetch_report_detail",
            "attr_name": "ReportDetailFetcher",
            "payload": {},
        }
    ]


def test_search_queries_dag_contains_only_query_demand_marketing_tasks() -> None:
    module = _load_module(
        "dag_search_queries_query_demand_test",
        "airflow_home/dags/dag_search_queries.py",
    )

    class _Tenant:
        tenant_id = "tenant-id"
        tenant_slug = "tenant-slug"
        schedules = {"search_queries": "20 9 * * *"}

    dag = module.build_search_queries_dag(_Tenant())
    task_ids = set(dag.task_ids)

    assert "refresh_query_demand_marts" in task_ids
    assert "validate_query_demand_marts" in task_ids
    assert "fetch_marketing_campaigns" not in task_ids
    assert "fetch_marketing_stats" not in task_ids


def test_search_queries_dag_now_contains_only_search_branch_plus_query_demand_tasks() -> None:
    module = _load_module(
        "dag_search_queries_search_only_test",
        "airflow_home/dags/dag_search_queries.py",
    )

    class _Tenant:
        tenant_id = "tenant-id"
        tenant_slug = "tenant-slug"
        schedules = {"search_queries": "20 9 * * *"}

    dag = module.build_search_queries_dag(_Tenant())
    task_ids = set(dag.task_ids)

    assert "prepare_context" in task_ids
    assert "fetch_report" in task_ids
    assert "fetch_orders" in task_ids
    assert "join_branches" in task_ids
    assert "refresh_query_demand_marts" in task_ids
    assert "validate_query_demand_marts" in task_ids
    assert "validate_load" in task_ids
    assert "fetch_marketing_campaigns" not in task_ids
    assert "refresh_marketing_marts" not in task_ids


def test_search_queries_dag_prioritizes_orders_before_overview_stages() -> None:
    module = _load_module(
        "dag_search_queries_order_priority_test",
        "airflow_home/dags/dag_search_queries.py",
    )

    class _Tenant:
        tenant_id = "tenant-id"
        tenant_slug = "tenant-slug"
        schedules = {"search_queries": "20 9 * * *"}

    dag = module.build_search_queries_dag(_Tenant())

    assert "prepare_context" in dag.get_task("fetch_order_search_texts").upstream_task_ids
    assert "fetch_order_search_texts" in dag.get_task("fetch_orders").upstream_task_ids
    assert "fetch_orders" in dag.get_task("fetch_report").upstream_task_ids
    assert "fetch_report" in dag.get_task("fetch_details").upstream_task_ids
    assert "fetch_groups" in dag.get_task("join_branches").upstream_task_ids


def test_search_queries_stage_payload_keeps_rate_limit_seen() -> None:
    module = _load_module(
        "dag_search_queries_rate_limit_payload_test",
        "airflow_home/dags/dag_search_queries.py",
    )

    payload = module._next_stage_payload(
        {"snapshot_hour": "2026-06-23T20:00:00+03:00"},
        {"snapshot_hour": "2026-06-23T20:00:00+03:00", "rate_limited": True},
        "orders",
    )
    next_payload = module._next_stage_payload(
        payload,
        {"snapshot_hour": "2026-06-23T20:00:00+03:00", "orders_text_daily": 0},
        "orders_retry",
    )

    assert payload["rate_limited_seen"] is True
    assert next_payload["rate_limited_seen"] is True


def test_search_queries_secondary_stage_skip_result_after_rate_limit() -> None:
    module = _load_module(
        "dag_search_queries_secondary_skip_test",
        "airflow_home/dags/dag_search_queries.py",
    )

    result = module._secondary_stage_skip_result(
        {"snapshot_hour": "2026-06-23T20:00:00+03:00", "rate_limited_seen": True},
        "report",
    )

    assert result == {
        "snapshot_hour": "2026-06-23T20:00:00+03:00",
        "skipped": True,
        "skip_reason": "rate_limited_seen",
        "stage": "report",
    }
    assert module._secondary_stage_skip_result({"rate_limited_seen": False}, "report") is None


def test_search_queries_dag_is_not_created_without_explicit_schedule() -> None:
    module = _load_module(
        "dag_search_queries_schedule_guard_test",
        "airflow_home/dags/dag_search_queries.py",
    )

    class _Tenant:
        tenant_id = "tenant-id"
        tenant_slug = "tenant-slug"
        schedules = {}

    assert module.build_search_queries_dag(_Tenant()) is None


def test_marketing_marts_bootstrap_skips_destructive_ddl_when_all_marts_exist(monkeypatch) -> None:
    module = _load_package_module(
        "marketing_marts_db_skip_bootstrap_test_pkg",
        "database",
        "marketing/marts/database.py",
    )

    responses = [(name,) for name in module.MART_NAMES]
    executed = []
    ddl_calls = []

    class Cursor:
        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchone(self):
            return responses.pop(0)

    db = module.MarketingMartsDatabase()
    db.cursor = Cursor()

    monkeypatch.setattr(module, "execute_sql", lambda cursor, sql, params=None: cursor.execute(sql, params))
    monkeypatch.setattr(module, "execute_ddl_bundle", lambda *args, **kwargs: ddl_calls.append((args, kwargs)))

    states = db.create_tables()

    assert states == {name: True for name in module.MART_NAMES}
    assert ddl_calls == []
    assert len(executed) == len(module.MART_NAMES)


def test_marketing_marts_bootstrap_runs_ddl_only_when_all_marts_absent(monkeypatch) -> None:
    module = _load_package_module(
        "marketing_marts_db_bootstrap_test_pkg",
        "database",
        "marketing/marts/database.py",
    )

    responses = [(None,), (None,), (None,), (None,)] + [(name,) for name in module.MART_NAMES]
    ddl_calls = []

    class Cursor:
        def execute(self, sql, params=None):
            return None

        def fetchone(self):
            return responses.pop(0)

    db = module.MarketingMartsDatabase()
    db.cursor = Cursor()

    monkeypatch.setattr(module, "execute_sql", lambda cursor, sql, params=None: cursor.execute(sql, params))
    monkeypatch.setattr(module, "execute_ddl_bundle", lambda *args, **kwargs: ddl_calls.append((args, kwargs)))

    states = db.create_tables()

    assert len(ddl_calls) == 1
    assert states == {name: True for name in module.MART_NAMES}


def test_marketing_marts_refreshes_in_dependency_order(monkeypatch) -> None:
    module = _load_package_module(
        "marketing_marts_refresh_order_test_pkg",
        "database",
        "marketing/marts/database.py",
    )

    refreshes = []
    db = module.MarketingMartsDatabase()
    db.cursor = object()

    monkeypatch.setattr(db, "create_tables", lambda rebuild=False: {name: True for name in module.MART_NAMES})
    monkeypatch.setattr(module, "execute_sql", lambda cursor, sql, params=None: refreshes.append(sql))

    result = db.refresh_marts(snapshot_hour=datetime(2026, 4, 30, 9, 20), rebuild=False)

    assert refreshes == [f"REFRESH MATERIALIZED VIEW {name}" for name in module.MART_NAMES]
    assert result["refreshed_marts"] == list(module.MART_NAMES)
    assert result["rebuild"] is False


def test_search_queries_post_json_retries_transient_errors_until_success(monkeypatch) -> None:
    module = _load_module(
        "search_queries_retry_policy_test",
        "search_queries/fetch_search_queries.py",
    )

    class FakeDb:
        def upsert_api_requests(self, rows):
            self.rows = rows

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"items": []}}

    attempts = []

    def fake_post(*args, **kwargs):
        attempts.append((args, kwargs))
        if len(attempts) < 3:
            raise module.requests.exceptions.ConnectionError("temporary dns issue")
        return Response()

    sleeps = []
    fetcher = module.SearchQueriesFetcher()
    fetcher.db = FakeDb()
    fetcher.session = type("Session", (), {"post": staticmethod(fake_post)})()

    monkeypatch.setattr(fetcher, "_wait_rate_limit", lambda method_name: None)
    monkeypatch.setattr(fetcher, "_save_json", lambda **kwargs: None)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(module.random, "uniform", lambda a, b: 0.0)

    request_key, response = fetcher._post_json(
        method_name="search_texts",
        endpoint=module.Config.SEARCH_TEXTS_ENDPOINT,
        payload={"nmIds": [1, 2]},
        snapshot_hour=datetime(2026, 4, 30, 9, 0, tzinfo=module.MOSCOW_TZ),
        batch_index=1,
        top_order_by="orders",
    )

    assert request_key
    assert response == {"data": {"items": []}}
    assert len(attempts) == 3
    assert sleeps == [
        module.Config.SEARCH_TEXTS_RETRY_DELAY_429,
        module.Config.SEARCH_TEXTS_RETRY_DELAY_429,
    ]


def test_search_queries_search_texts_stage_uses_dedicated_batch_size(monkeypatch) -> None:
    module = _load_module(
        "search_queries_batch_size_test",
        "search_queries/fetch_search_queries.py",
    )

    fetcher = module.SearchQueriesFetcher()
    batches = []

    monkeypatch.setattr(fetcher, "_connect_db", lambda: None)
    monkeypatch.setattr(fetcher.db, "close", lambda: None)
    monkeypatch.setattr(fetcher, "_get_active_nm_ids", lambda: [1, 2, 3, 4, 5])
    monkeypatch.setattr(fetcher, "_fetch_search_texts", lambda snapshot_hour, periods, batch_index, nm_batch: (len(nm_batch), batches.append(list(nm_batch)) or {}))
    monkeypatch.setattr(module.Config, "SEARCH_TEXTS_NM_IDS_BATCH_SIZE", 2)

    result = fetcher.run_search_texts_stage(snapshot_hour=datetime(2026, 4, 30, 9, 0))

    assert batches == [[1, 2], [3, 4], [5]]
    assert result["search_texts"] == 5


def test_search_queries_order_search_texts_stage_fetches_orders_first(monkeypatch) -> None:
    module = _load_module(
        "search_queries_order_texts_test",
        "search_queries/fetch_search_queries.py",
    )

    fetcher = module.SearchQueriesFetcher()
    calls = []

    def fake_fetch_search_texts(snapshot_hour, periods, batch_index, nm_batch, top_order_by_values=None):
        calls.append((list(nm_batch), list(top_order_by_values or [])))
        return len(nm_batch), {nm_id: {"query"} for nm_id in nm_batch}

    monkeypatch.setattr(fetcher, "_connect_db", lambda: None)
    monkeypatch.setattr(fetcher.db, "close", lambda: None)
    monkeypatch.setattr(fetcher, "_get_active_nm_ids", lambda: [1, 2, 3])
    monkeypatch.setattr(fetcher, "_fetch_search_texts", fake_fetch_search_texts)
    monkeypatch.setattr(fetcher.db, "get_search_text_nm_ids_for_top_order_by", lambda **kwargs: set())
    monkeypatch.setattr(module.Config, "SEARCH_TEXTS_NM_IDS_BATCH_SIZE", 2)
    monkeypatch.setattr(module.Config, "ORDER_SEARCH_TEXT_TOP_ORDER_BY_VALUES", ["orders"])
    monkeypatch.setattr(module.Config, "ORDER_SEARCH_TEXTS_MAX_BATCHES_PER_RUN", 0)

    result = fetcher.run_order_search_texts_stage(snapshot_hour=datetime(2026, 4, 30, 9, 0))

    assert calls == [([1, 2], ["orders"]), ([3], ["orders"])]
    assert result["order_search_texts"] == 3
    assert result["nm_with_texts"] == 3


def test_search_queries_orders_stage_skips_completed_texts(monkeypatch) -> None:
    module = _load_module(
        "search_queries_orders_resume_test",
        "search_queries/fetch_search_queries.py",
    )

    fetcher = module.SearchQueriesFetcher()
    calls = []

    monkeypatch.setattr(fetcher, "_connect_db", lambda: None)
    monkeypatch.setattr(fetcher.db, "close", lambda: None)
    monkeypatch.setattr(
        fetcher.db,
        "get_search_texts_for_orders",
        lambda **kwargs: {11: ["done", "todo"], 22: ["already"]},
    )
    monkeypatch.setattr(
        fetcher.db,
        "get_completed_order_texts",
        lambda **kwargs: {11: {"done"}, 22: {"already"}},
    )

    def fake_fetch_orders_for_nm(*, snapshot_hour, periods, batch_index, nm_id, search_texts):
        calls.append((batch_index, nm_id, list(search_texts)))
        return 7, 7

    monkeypatch.setattr(fetcher, "_fetch_orders_for_nm", fake_fetch_orders_for_nm)

    result = fetcher.run_orders_stage(snapshot_hour=datetime(2026, 4, 30, 9, 0))

    assert calls == [(1, 11, ["todo"])]
    assert result["orders_total_daily"] == 7
    assert result["orders_text_daily"] == 7
    assert result["skipped_nm_ids"] == 1
    assert result["skipped_order_texts"] == 2


def test_search_queries_orders_stage_returns_progress_on_rate_limit(monkeypatch) -> None:
    module = _load_module(
        "search_queries_orders_rate_limit_test",
        "search_queries/fetch_search_queries.py",
    )

    fetcher = module.SearchQueriesFetcher()

    monkeypatch.setattr(fetcher, "_connect_db", lambda: None)
    monkeypatch.setattr(fetcher.db, "close", lambda: None)
    monkeypatch.setattr(
        fetcher.db,
        "get_search_texts_for_orders",
        lambda **kwargs: {11: ["done"], 22: ["todo"]},
    )
    monkeypatch.setattr(
        fetcher.db,
        "get_completed_order_texts",
        lambda **kwargs: {11: {"done"}},
    )

    def fake_fetch_orders_for_nm(*, snapshot_hour, periods, batch_index, nm_id, search_texts):
        raise module.RateLimitExceeded("orders: 429 Too Many Requests")

    monkeypatch.setattr(fetcher, "_fetch_orders_for_nm", fake_fetch_orders_for_nm)

    result = fetcher.run_orders_stage(snapshot_hour=datetime(2026, 4, 30, 9, 0))

    assert result["rate_limited"] is True
    assert result["next_nm_id"] == 22
    assert result["requested_nm_ids"] == 0
    assert result["skipped_nm_ids"] == 1
    assert result["skipped_order_texts"] == 1


def test_search_queries_report_stage_returns_progress_on_rate_limit(monkeypatch) -> None:
    module = _load_module(
        "search_queries_report_rate_limit_test",
        "search_queries/fetch_search_queries.py",
    )

    fetcher = module.SearchQueriesFetcher()

    monkeypatch.setattr(fetcher, "_connect_db", lambda: None)
    monkeypatch.setattr(fetcher.db, "close", lambda: None)
    monkeypatch.setattr(fetcher, "_get_active_nm_ids", lambda: [1, 2])

    def fake_fetch_report(snapshot_hour, periods, batch_index, nm_batch):
        raise module.RateLimitExceeded("report: 429 Too Many Requests")

    monkeypatch.setattr(fetcher, "_fetch_report", fake_fetch_report)

    result = fetcher.run_report_stage(snapshot_hour=datetime(2026, 4, 30, 9, 0))

    assert result["rate_limited"] is True
    assert result["report_groups"] == 0
    assert result["subject_ids"] == 0
    assert result["next_batch_index"] == 1


def test_daily_pipeline_source_groups_now_include_marketing_fetchers() -> None:
    module = _load_module(
        "source_groups_marketing_list_test",
        "airflow_home/dags/_daily_pipeline/source_groups.py",
    )

    builder_names = [builder.__name__ for builder in module.SOURCE_GROUP_BUILDERS]

    assert "build_marketing_campaigns_group" in builder_names
    assert "build_marketing_stats_group" in builder_names
    assert "build_marketing_normquery_group" in builder_names
    assert "build_marketing_normquery_stats_group" in builder_names
    assert "build_calendar_promotions_group" in builder_names


def test_daily_pipeline_source_groups_keep_full_marketing_query_sequence() -> None:
    module = _load_module(
        "source_groups_marketing_order_test",
        "airflow_home/dags/_daily_pipeline/source_groups.py",
    )

    builder_names = [builder.__name__ for builder in module.SOURCE_GROUP_BUILDERS]

    assert builder_names.index("build_marketing_campaigns_group") < builder_names.index("build_marketing_stats_group")
    assert builder_names.index("build_marketing_stats_group") < builder_names.index("build_marketing_normquery_group")
    assert builder_names.index("build_marketing_normquery_group") < builder_names.index("build_marketing_normquery_stats_group")


def test_daily_pipeline_dag_places_marketing_query_pipeline_before_other_marts() -> None:
    module = _load_module(
        "dag_daily_pipeline_marketing_chain_test",
        "airflow_home/dags/dag_daily_pipeline_master.py",
    )

    class _Tenant:
        tenant_id = "tenant-id"
        tenant_slug = "tenant-slug"
        schedules = {"daily_pipeline_master": "30 7 * * *"}

    dag = module.build_daily_pipeline_dag(_Tenant())
    task_ids = set(dag.task_ids)

    assert "marketing_normquery.prepare_pairs" in task_ids
    assert "marketing_normquery.fetch_batches" in task_ids
    assert "marketing_normquery_stats.fetch_v0_batches" in task_ids
    assert "marketing_normquery_stats.fetch_v1_batches" in task_ids
    assert "strict_freshness_gate_core" in task_ids
    assert "validate_source_quality_core" in task_ids
    assert "strict_freshness_gate_marketing" in task_ids
    assert "validate_marketing_sources" in task_ids
    assert "marketing_branch_outcome" in task_ids
    assert "refresh_marketing_marts" in task_ids
    assert "validate_marketing_marts" in task_ids

    marketing_normquery_stats_finalize = dag.get_task("marketing_normquery_stats.finalize")
    report_detail_check_progress = dag.get_task("report_detail.check_progress")
    strict_freshness_gate_core = dag.get_task("strict_freshness_gate_core")
    validate_source_quality_core = dag.get_task("validate_source_quality_core")
    strict_freshness_gate_marketing = dag.get_task("strict_freshness_gate_marketing")
    validate_marketing_sources = dag.get_task("validate_marketing_sources")
    refresh_marketing_marts = dag.get_task("refresh_marketing_marts")
    validate_marketing_marts = dag.get_task("validate_marketing_marts")
    marketing_branch_outcome = dag.get_task("marketing_branch_outcome")
    refresh_mart = dag.get_task("refresh_mart_ai_sales_planning")

    assert report_detail_check_progress.upstream_task_ids == {"sales_funnel.fetch_funnel_90d_daily"}
    assert marketing_normquery_stats_finalize.downstream_task_ids == {"strict_freshness_gate_marketing"}
    assert validate_source_quality_core.task_id in strict_freshness_gate_core.downstream_task_ids
    assert validate_marketing_sources.task_id in strict_freshness_gate_marketing.downstream_task_ids
    assert validate_marketing_marts.task_id in refresh_marketing_marts.downstream_task_ids
    assert marketing_branch_outcome.task_id in validate_marketing_marts.downstream_task_ids
    assert refresh_mart.task_id in validate_source_quality_core.downstream_task_ids


def test_report_detail_deduplicates_only_by_rrd_id_not_by_srid() -> None:
    module = _load_module(
        "report_detail_database_test_dedup",
        "finance/database.py",
    )

    rows = [
        {"rrd_id": 1, "srid": "same"},
        {"rrd_id": 2, "srid": "same"},
        {"rrd_id": 2, "srid": "same"},
    ]

    deduped = module.ReportDetailDatabase._deduplicate_valid_data(rows)

    assert deduped == [
        {"rrd_id": 1, "srid": "same"},
        {"rrd_id": 2, "srid": "same"},
    ]


def test_overlap_cursor_is_clamped_to_minimum_date() -> None:
    stocks_module = _load_module("stocks_fetch_test", "stocks/fetch_stocks.py")
    sales_module = _load_module("sales_fetch_test", "sales/fetch_sales.py")
    orders_module = _load_module("orders_fetch_test", "orders/fetch_orders.py")

    minimum_dt = datetime(2025, 12, 31, 0, 0, 0)
    cursor_dt = minimum_dt + timedelta(seconds=1)

    assert stocks_module.compute_overlap_date_from(cursor_dt, minimum_dt) == minimum_dt
    assert sales_module.compute_overlap_date_from(cursor_dt, minimum_dt) == minimum_dt
    assert orders_module.compute_overlap_date_from(cursor_dt, minimum_dt) == minimum_dt


def test_overlap_cursor_subtracts_two_seconds_when_safe() -> None:
    sales_module = _load_module("sales_fetch_test_safe", "sales/fetch_sales.py")

    minimum_dt = datetime(2025, 12, 31, 0, 0, 0)
    cursor_dt = datetime(2026, 1, 5, 12, 0, 10)

    assert sales_module.compute_overlap_date_from(cursor_dt, minimum_dt) == datetime(2026, 1, 5, 12, 0, 8)


def test_progress_ahead_detection_respects_tolerance() -> None:
    max_loaded = datetime(2026, 3, 31, 12, 0, 0)

    assert _is_progress_ahead(max_loaded + timedelta(minutes=6), max_loaded) is True
    assert _is_progress_ahead(max_loaded + timedelta(minutes=4, seconds=59), max_loaded) is False
    assert _is_progress_ahead(None, max_loaded) is False


def test_source_quality_report_detail_dq_uses_progress_completion(monkeypatch) -> None:
    cursor = _FakeCursor(
        fetchall_responses=[
            [],  # sales_funnel missing dates
            [],  # report_detail missing dates
            [],  # supplier_stocks volume history
            [],  # supplier_sales volume history
            [],  # supplier_orders volume history
            [],  # sales_funnel volume history
        ],
        fetchone_responses=[
            (None, None),
            (None, None),
            (None, None),
        ],
    )

    @contextmanager
    def fake_tenant_connection(tenant_id):
        yield _FakeConn(cursor)

    monkeypatch.setattr(db_tasks_module, "today_moscow", lambda: date(2026, 4, 6))
    monkeypatch.setattr(db_tasks_module, "_tenant_connection", fake_tenant_connection)

    db_tasks_module.validate_source_quality_task("tenant-id")

    assert any("wb_report_detail_progress" in sql for sql, _params in cursor.calls)


def test_source_quality_report_detail_missing_date_fails(monkeypatch) -> None:
    cursor = _FakeCursor(
        fetchall_responses=[
            [],  # sales_funnel missing dates
            [(date(2026, 4, 5),)],  # report_detail missing dates
            [],  # supplier_stocks volume history
            [],  # supplier_sales volume history
            [],  # supplier_orders volume history
            [],  # sales_funnel volume history
        ],
        fetchone_responses=[
            (None, None),
            (None, None),
            (None, None),
        ],
    )

    @contextmanager
    def fake_tenant_connection(tenant_id):
        yield _FakeConn(cursor)

    monkeypatch.setattr(db_tasks_module, "today_moscow", lambda: date(2026, 4, 6))
    monkeypatch.setattr(db_tasks_module, "_tenant_connection", fake_tenant_connection)

    with pytest.raises(ValueError, match="report_detail.*2026-04-05"):
        db_tasks_module.validate_source_quality_task("tenant-id")


def test_critical_volume_drop_detects_more_than_eighty_percent_fall() -> None:
    assert _is_critical_volume_drop(19, 100) is True
    assert _is_critical_volume_drop(20, 100) is False
    assert _is_critical_volume_drop(0, 0) is False
    assert _calculate_drop_pct(20, 100) == -80.0
