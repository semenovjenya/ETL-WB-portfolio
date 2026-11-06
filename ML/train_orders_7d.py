"""Train orders next 7d model."""
from __future__ import annotations

try:
    from config import Config
    from pipeline import train_target_model
except ImportError:  # pragma: no cover
    from .config import Config
    from .pipeline import train_target_model


def run() -> dict:
    return train_target_model(Config.ORDERS_TARGET)
