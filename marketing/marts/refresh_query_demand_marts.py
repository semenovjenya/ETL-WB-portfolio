"""Refresh materialized query demand/ad-share marts for marketing forecast layer."""
from __future__ import annotations

from datetime import datetime

from .query_demand_database import QueryDemandMartsDatabase


class QueryDemandMartsRefresher:
    def __init__(self) -> None:
        self.db = QueryDemandMartsDatabase()

    def refresh_marts(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        self.db.connect()
        try:
            self.db.create_tables()
            return self.db.refresh_marts(snapshot_hour=snapshot_hour)
        finally:
            self.db.close()

    def run(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        return self.refresh_marts(snapshot_hour=snapshot_hour)
