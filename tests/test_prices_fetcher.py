from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from datetime import date, datetime


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, relative_path: str):
    module_path = PROJECT_ROOT / relative_path
    module_dir = str(module_path.parent)
    project_root = str(PROJECT_ROOT)
    original_path = list(sys.path)
    sys.path.insert(0, module_dir)
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


def test_prices_fetcher_uses_limit_headers_for_429_wait() -> None:
    module = _load_module("prices_fetch_test_headers", "prices/fetch_prices.py")

    fetcher = module.PricesFetcher()

    class _Resp:
        headers = {
            "X-Ratelimit-Retry": "75",
            "X-Limit-Reset": "30",
        }

    wait = fetcher._retry_wait_for_429(_Resp(), attempt=0)

    assert wait == 75.0


def test_prices_fetcher_adds_client_secret_header_when_present() -> None:
    module = _load_module("prices_fetch_test_secret", "prices/fetch_prices.py")

    previous_secret = module.Config.WB_API_CLIENT_SECRET
    previous_token = module.Config.WB_API_TOKEN
    try:
        module.Config.WB_API_TOKEN = "token-value"
        module.Config.WB_API_CLIENT_SECRET = "secret-value"
        fetcher = object.__new__(module.PricesFetcher)

        headers = fetcher._get_headers()

        assert headers["Authorization"] == "token-value"
        assert headers["X-Client-Secret"] == "secret-value"
    finally:
        module.Config.WB_API_CLIENT_SECRET = previous_secret
        module.Config.WB_API_TOKEN = previous_token


def test_prices_fetcher_persists_progress_by_snapshot_date(tmp_path) -> None:
    module = _load_module("prices_fetch_test_progress", "prices/fetch_prices.py")

    previous_progress_file = module.Config.PROGRESS_FILE
    try:
        module.Config.PROGRESS_FILE = str(tmp_path / "prices-progress.json")
        fetcher = module.PricesFetcher()
        snapshot_date = date(2026, 5, 6)
        snapshot_hour = datetime(2026, 5, 6, 7, 0, 0)

        fetcher._save_progress_state(
            snapshot_date,
            snapshot_hour,
            offset=2000,
            page=2,
            total_items=2000,
        )

        assert fetcher._load_progress_state(snapshot_date) == {
            "offset": 2000,
            "page": 2,
            "total_items": 2000,
        }

        fetcher._clear_progress_state()
        assert fetcher._load_progress_state(snapshot_date) is None
    finally:
        module.Config.PROGRESS_FILE = previous_progress_file
