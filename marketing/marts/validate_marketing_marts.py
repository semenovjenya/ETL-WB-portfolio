"""Validate and debug materialized marts for marketing forecast layer."""
from __future__ import annotations

from datetime import datetime

from .database import MarketingMartsDatabase


class MarketingMartsValidator:
    def __init__(self) -> None:
        self.db = MarketingMartsDatabase()

    def validate_marts(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        self.db.connect()
        try:
            return self.db.validate_marts(snapshot_hour=snapshot_hour)
        finally:
            self.db.close()

    def debug_marts(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        self.db.connect()
        try:
            return self.db.debug_marts(snapshot_hour=snapshot_hour)
        finally:
            self.db.close()

    def run(self, snapshot_hour: datetime | None = None) -> dict[str, object]:
        return self.validate_marts(snapshot_hour=snapshot_hour)
