"""LLM explanation entrypoint for 1pager ML forecasts."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

try:
    from config import Config
    from database import OnePagerMLDatabase
    from pipeline import _build_explanation_payload, build_empty_explanation_row
except ImportError:  # pragma: no cover
    from .config import Config
    from .database import OnePagerMLDatabase
    from .pipeline import _build_explanation_payload, build_empty_explanation_row

logger = logging.getLogger(__name__)
_JSON_RE = re.compile(r"\{.*\}", re.S)


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(getattr(item, "text", "") or getattr(item, "content", "") or item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _extract_json_object(text: str) -> dict[str, Any]:
    match = _JSON_RE.search(text.strip())
    if not match:
        raise ValueError("LLM did not return a JSON object")
    payload = json.loads(match.group(0))
    expected = {"reason_summary", "reason_1", "reason_2", "reason_3"}
    missing = expected - set(payload)
    if missing:
        raise ValueError(f"Explanation JSON is missing keys: {sorted(missing)}")
    return {key: payload.get(key) for key in sorted(expected)}


class ForecastExplainer:
    def __init__(self) -> None:
        self._client = None
        self._prompt = Config.PROMPT_PATH.read_text(encoding="utf-8").strip()

    def _ensure_client(self) -> None:
        Config.validate_openai()
        if self._client is not None:
            return
        if OpenAI is None:
            raise RuntimeError("openai package is not installed")
        kwargs: dict[str, Any] = {"api_key": Config.OPENAI_API_KEY}
        if Config.OPENAI_BASE_URL:
            kwargs["base_url"] = Config.OPENAI_BASE_URL
        self._client = OpenAI(**kwargs)

    def explain_row(self, row: dict[str, Any]) -> dict[str, Any]:
        self._ensure_client()
        assert self._client is not None
        response = self._client.chat.completions.create(
            model=Config.EXPLAIN_MODEL,
            messages=[
                {"role": "system", "content": self._prompt},
                {
                    "role": "user",
                    "content": json.dumps(_build_explanation_payload(row), ensure_ascii=False),
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=Config.EXPLAIN_MAX_TOKENS,
            timeout=Config.EXPLAIN_TIMEOUT_SEC,
        )
        text = _extract_message_text(response.choices[0].message.content if response.choices else "")
        payload = _extract_json_object(text)
        return {
            "report_date": row["report_date"],
            "nm_id": int(row["nm_id"]),
            "sku": row.get("sku") or row.get("forecast_sku"),
            "model_version": row["model_version"],
            "reason_summary": payload["reason_summary"],
            "reason_1": payload["reason_1"],
            "reason_2": payload["reason_2"],
            "reason_3": payload["reason_3"],
            "llm_model": Config.EXPLAIN_MODEL,
            "prompt_version": Config.EXPLAIN_PROMPT_VERSION,
            "source_features_hash": build_empty_explanation_row(row, llm_model=Config.EXPLAIN_MODEL)["source_features_hash"],
        }


def run() -> dict[str, Any]:
    Config.ensure_runtime_dirs()
    db = OnePagerMLDatabase()
    db.connect()
    db.create_tables()
    try:
        report_date = db.get_latest_complete_report_date()
        if report_date is None:
            return {"status": "skipped", "reason": "no_scoring_date"}
        model_version = db.get_latest_model_version(report_date)
        if model_version is None:
            return {"status": "skipped", "reason": "no_forecasts", "report_date": str(report_date)}

        rows = db.fetch_explanation_source_rows(report_date, model_version)
        if not rows:
            return {"status": "skipped", "reason": "no_rows_for_explanation", "report_date": str(report_date), "model_version": model_version}

        explanation_rows = []
        failed = 0
        explainer = None
        llm_available = bool(Config.OPENAI_API_KEY and OpenAI is not None)
        if llm_available:
            explainer = ForecastExplainer()

        for row in rows:
            if explainer is None:
                explanation_rows.append(build_empty_explanation_row(row, llm_model=Config.EXPLAIN_MODEL))
                failed += 1
                continue
            try:
                explanation_rows.append(explainer.explain_row(row))
            except Exception as exc:  # pragma: no cover
                logger.warning("LLM explanation failed for nm_id=%s report_date=%s: %s", row.get("nm_id"), row.get("report_date"), exc)
                explanation_rows.append(build_empty_explanation_row(row, llm_model=Config.EXPLAIN_MODEL))
                failed += 1

        written = db.upsert_explanation_rows(explanation_rows)
        payload = {
            "status": "success" if failed == 0 else "partial",
            "report_date": str(report_date),
            "model_version": model_version,
            "rows_written": written,
            "failed_rows": failed,
        }
        output_path = Config.JSON_OUTPUT_DIR / f"daily_explanations_{report_date}.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload
    finally:
        db.close()
