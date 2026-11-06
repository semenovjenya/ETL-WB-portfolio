from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_progress_state(path: str | Path) -> dict[str, Any]:
    progress_path = Path(path)
    if not progress_path.exists():
        return {}
    try:
        raw = progress_path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_progress_state(path: str | Path, payload: dict[str, Any]) -> None:
    progress_path = Path(path)
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_progress_state(path: str | Path) -> None:
    progress_path = Path(path)
    if progress_path.exists():
        progress_path.unlink()
