"""Refresh materialized marts for marketing forecast layer."""
from __future__ import annotations

from datetime import datetime

from .database import MarketingMartsDatabase


class MarketingMartsRefresher:
    def __init__(self) -> None:
        self.db = MarketingMartsDatabase()

    def refresh_marts(self, snapshot_hour: datetime | None = None, *, rebuild: bool = False) -> dict[str, object]:
        self.db.connect()
        try:
            return self.db.refresh_marts(snapshot_hour=snapshot_hour, rebuild=rebuild)
        finally:
            self.db.close()

    def rebuild_marts(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        return self.refresh_marts(snapshot_hour=snapshot_hour, rebuild=True)

    def run(self, snapshot_hour: datetime | None = None, rebuild: bool = False) -> dict[str, object]:
        return self.refresh_marts(snapshot_hour=snapshot_hour, rebuild=rebuild)
