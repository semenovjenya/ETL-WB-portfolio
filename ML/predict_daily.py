"""Daily scoring entrypoint for 1pager ML forecasts."""
from __future__ import annotations

try:
    from pipeline import run_daily_scoring
except ImportError:  # pragma: no cover
    from .pipeline import run_daily_scoring


def run() -> dict:
    return run_daily_scoring()
