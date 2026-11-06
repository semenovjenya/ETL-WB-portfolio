from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional


TOKEN_MODE_AUTO = "auto-detect"
TOKEN_MODE_BASE = "base"
TOKEN_MODE_PERSONAL = "personal"
TOKEN_MODE_SERVICE = "service"
TOKEN_MODE_UNKNOWN = "unknown"

_TOKEN_MODE_ALIASES = {
    "auto": TOKEN_MODE_AUTO,
    "auto-detect": TOKEN_MODE_AUTO,
    "autodetect": TOKEN_MODE_AUTO,
    "base": TOKEN_MODE_BASE,
    "personal": TOKEN_MODE_PERSONAL,
    "service": TOKEN_MODE_SERVICE,
    "unknown": TOKEN_MODE_UNKNOWN,
}
_ACC_TO_TOKEN_MODE = {
    1: TOKEN_MODE_BASE,
    3: TOKEN_MODE_PERSONAL,
    4: TOKEN_MODE_SERVICE,
}


def parse_positive_number(value: Any) -> Optional[float]:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def normalize_token_mode(mode: Optional[str]) -> str:
    if not mode:
        return TOKEN_MODE_AUTO
    return _TOKEN_MODE_ALIASES.get(str(mode).strip().lower(), TOKEN_MODE_UNKNOWN)


def decode_wb_token_payload(token: Optional[str]) -> dict[str, Any]:
    if not token:
        return {}
    parts = str(token).split(".")
    if len(parts) < 2:
        return {}
    try:
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(decoded.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def detect_wb_token_mode(token: Optional[str]) -> str:
    payload = decode_wb_token_payload(token)
    acc = payload.get("acc")
    try:
        acc_int = int(acc)
    except (TypeError, ValueError):
        return TOKEN_MODE_UNKNOWN
    return _ACC_TO_TOKEN_MODE.get(acc_int, TOKEN_MODE_UNKNOWN)


def resolve_wb_token_mode(token: Optional[str], configured_mode: Optional[str] = None) -> str:
    normalized = normalize_token_mode(configured_mode)
    if normalized != TOKEN_MODE_AUTO:
        return normalized
    detected = detect_wb_token_mode(token)
    return detected if detected != TOKEN_MODE_UNKNOWN else TOKEN_MODE_AUTO


def _first_header_value(headers: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in headers:
            return headers[name]
    return None


@dataclass(frozen=True)
class RateLimitSnapshot:
    retry: Optional[float]
    reset: Optional[float]
    retry_after: Optional[float]
    remaining: Optional[float]
    limit: Optional[float]

    @property
    def wait_hint(self) -> Optional[float]:
        candidates = [value for value in (self.retry, self.reset, self.retry_after) if value is not None]
        if not candidates:
            return None
        return max(candidates)


def extract_rate_limit_snapshot(headers: Mapping[str, Any]) -> RateLimitSnapshot:
    retry = parse_positive_number(
        _first_header_value(
            headers,
            (
                "X-Ratelimit-Retry",
                "x-ratelimit-retry",
                "X-Limit-Retry",
                "x-limit-retry",
            ),
        )
    )
    reset = parse_positive_number(
        _first_header_value(
            headers,
            (
                "X-Ratelimit-Reset",
                "x-ratelimit-reset",
                "X-Limit-Reset",
                "x-limit-reset",
            ),
        )
    )
    retry_after = parse_positive_number(
        _first_header_value(
            headers,
            (
                "Retry-After",
                "retry-after",
            ),
        )
    )
    remaining = parse_positive_number(
        _first_header_value(
            headers,
            (
                "X-Ratelimit-Remaining",
                "x-ratelimit-remaining",
                "X-Limit-Remaining",
                "x-limit-remaining",
            ),
        )
    )
    limit = parse_positive_number(
        _first_header_value(
            headers,
            (
                "X-Ratelimit-Limit",
                "x-ratelimit-limit",
                "X-Limit-Limit",
                "x-limit-limit",
            ),
        )
    )
    return RateLimitSnapshot(
        retry=retry,
        reset=reset,
        retry_after=retry_after,
        remaining=remaining,
        limit=limit,
    )
