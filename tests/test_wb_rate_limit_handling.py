from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


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


def _make_jwt(payload: dict[str, object]) -> str:
    import base64
    import json

    def _encode(value: dict[str, object]) -> str:
        raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return ".".join(
        [
            _encode({"alg": "ES256", "typ": "JWT"}),
            _encode(payload),
            "signature",
        ]
    )


def test_wb_token_mode_detection_supports_base_and_personal_tokens() -> None:
    module = _load_module("wb_api_support_token_mode_test", "wb_api_support.py")

    assert module.detect_wb_token_mode(_make_jwt({"acc": 1})) == module.TOKEN_MODE_BASE
    assert module.detect_wb_token_mode(_make_jwt({"acc": 3})) == module.TOKEN_MODE_PERSONAL
    assert module.resolve_wb_token_mode(_make_jwt({"acc": 4}), "auto-detect") == module.TOKEN_MODE_SERVICE


def test_sales_funnel_fetcher_uses_limit_headers_for_429_wait() -> None:
    module = _load_module("sales_funnel_fetch_test_headers", "sales_funnel/fetch_sales_funnel_90d_daily.py")

    fetcher = module.SalesFunnelFetcher()

    class _Resp:
        headers = {
            "Retry-After": "45",
            "X-Ratelimit-Reset": "30",
        }

    wait = fetcher._retry_wait_for_429(_Resp(), attempt=0)

    assert wait == 45.0


def test_sales_funnel_fetcher_backoff_grows_without_limit_headers() -> None:
    module = _load_module("sales_funnel_fetch_test_no_headers", "sales_funnel/fetch_sales_funnel_90d_daily.py")

    previous_token = module.Config.WB_API_TOKEN
    previous_mode = module.Config.WB_API_TOKEN_MODE
    try:
        module.Config.WB_API_TOKEN = _make_jwt({"acc": 1})
        module.Config.WB_API_TOKEN_MODE = "auto-detect"
        fetcher = module.SalesFunnelFetcher()

        class _Resp:
            headers = {}

        wait = fetcher._retry_wait_for_429(_Resp(), attempt=2)

        assert wait == float(module.Config.BASE_TOKEN_RETRY_DELAY_429)
    finally:
        module.Config.WB_API_TOKEN = previous_token
        module.Config.WB_API_TOKEN_MODE = previous_mode


def test_sales_funnel_fetcher_adds_client_secret_header_when_present() -> None:
    module = _load_module("sales_funnel_fetch_test_secret", "sales_funnel/fetch_sales_funnel_90d_daily.py")

    previous_secret = module.Config.WB_API_CLIENT_SECRET
    previous_token = module.Config.WB_API_TOKEN
    try:
        module.Config.WB_API_TOKEN = "token-value"
        module.Config.WB_API_CLIENT_SECRET = "secret-value"
        fetcher = object.__new__(module.SalesFunnelFetcher)

        headers = fetcher._get_headers()

        assert headers["Authorization"] == "token-value"
        assert headers["X-Client-Secret"] == "secret-value"
    finally:
        module.Config.WB_API_CLIENT_SECRET = previous_secret
        module.Config.WB_API_TOKEN = previous_token


def test_marketing_campaigns_fetcher_uses_limit_headers_for_429_wait() -> None:
    module = _load_module("marketing_campaigns_fetch_test_headers", "marketing/fetch_campaigns.py")

    fetcher = module.CampaignsFetcher()

    class _Resp:
        headers = {
            "X-Ratelimit-Retry": "75",
            "Retry-After": "60",
        }

    wait = fetcher._retry_wait_for_429(_Resp(), attempt=0)

    assert wait == 75.0


def test_marketing_campaigns_fetcher_backoff_grows_without_limit_headers() -> None:
    module = _load_module("marketing_campaigns_fetch_test_no_headers", "marketing/fetch_campaigns.py")

    previous_token = module.Config.WB_API_TOKEN
    previous_mode = module.Config.WB_API_TOKEN_MODE
    try:
        module.Config.WB_API_TOKEN = _make_jwt({"acc": 1})
        module.Config.WB_API_TOKEN_MODE = "auto-detect"
        fetcher = module.CampaignsFetcher()

        class _Resp:
            headers = {}

        wait = fetcher._retry_wait_for_429(_Resp(), attempt=1)

        assert wait == float(module.Config.BASE_TOKEN_RETRY_DELAY_429)
    finally:
        module.Config.WB_API_TOKEN = previous_token
        module.Config.WB_API_TOKEN_MODE = previous_mode


def test_marketing_stats_fetcher_adds_client_secret_header_when_present() -> None:
    module = _load_module("marketing_stats_fetch_test_secret", "marketing/fetch_marketing_stats.py")

    previous_secret = module.Config.WB_API_CLIENT_SECRET
    previous_token = module.Config.WB_API_TOKEN
    try:
        module.Config.WB_API_TOKEN = "token-value"
        module.Config.WB_API_CLIENT_SECRET = "secret-value"
        fetcher = object.__new__(module.MarketingStatsFetcher)

        headers = fetcher._get_headers()

        assert headers["Authorization"] == "token-value"
        assert headers["X-Client-Secret"] == "secret-value"
    finally:
        module.Config.WB_API_CLIENT_SECRET = previous_secret
        module.Config.WB_API_TOKEN = previous_token


def test_marketing_stats_fetcher_defers_long_basic_token_retry(monkeypatch) -> None:
    module = _load_module(
        "marketing_stats_fetch_test_long_retry",
        "marketing/fetch_marketing_stats.py",
    )
    fetcher = object.__new__(module.MarketingStatsFetcher)
    fetcher.token_mode = "base"
    fetcher.retry_delay_429 = 300.0
    fetcher.last_rate_limit = None

    class _Resp:
        status_code = 429
        headers = {
            "X-Ratelimit-Retry": "3399",
            "X-Ratelimit-Limit": "1",
        }

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: _Resp())
    monkeypatch.setattr(
        module.time,
        "sleep",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must defer")),
    )

    result = fetcher._get("https://advert-api.wildberries.ru/adv/v3/fullstats")

    assert result is None
    assert fetcher.last_rate_limit["retry"] == 3399.0
    assert fetcher.last_rate_limit["deferred"] is True
    assert fetcher.last_rate_limit["token_mode"] == "base"
