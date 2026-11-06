"""Score competitor relevance with LLM for one SKU."""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from competitor_pipeline import normalize_relevance_payload
from config import Config
from database import WBPriceAIAnalysisDatabase, dump_json

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _extract_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif hasattr(item, "text"):
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(part for part in parts if part)
    return str(content or "")


class RelevanceScorer:
    def __init__(self) -> None:
        self._client = None
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def _ensure_client(self) -> None:
        Config.validate_relevance_openai()
        if self._client is not None:
            return
        if OpenAI is None:
            raise RuntimeError("Пакет openai не установлен")
        kwargs: Dict[str, Any] = {"api_key": Config.get_relevance_openai_api_key()}
        base_url = Config.get_relevance_openai_base_url()
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    def _call_llm(self, row: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_client()
        assert self._client is not None
        prompt_payload = {
            "keyword": row.get("keyword"),
            "source": {
                "title": row.get("source_title"),
                "subject_name": row.get("source_subject_name"),
                "price_promo": row.get("source_price_promo"),
                "subject_norm": row.get("source_subject_norm"),
                "subtype": row.get("source_subtype"),
                "dimensions": row.get("source_dimensions_json"),
                "material": row.get("source_material"),
                "shape": row.get("source_shape"),
                "platform": row.get("source_platform"),
                "connection_type": row.get("source_connection_type"),
                "bed_type": row.get("source_bed_type"),
                "sleep_size": row.get("source_sleep_size_json"),
            },
            "competitor": {
                "title": row.get("competitor_title"),
                "subject_name": row.get("competitor_subject_name"),
                "price_promo": row.get("competitor_price_promo"),
                "subject_norm": row.get("competitor_subject_norm"),
                "subtype": row.get("competitor_subtype"),
                "dimensions": row.get("competitor_dimensions_json"),
                "material": row.get("competitor_material"),
                "shape": row.get("competitor_shape"),
                "platform": row.get("competitor_platform"),
                "connection_type": row.get("competitor_connection_type"),
                "bed_type": row.get("competitor_bed_type"),
                "sleep_size": row.get("competitor_sleep_size_json"),
            },
            "hard_filter_flags": row.get("hard_filter_flags_json") or {},
        }
        response = self._client.chat.completions.create(
            model=Config.WB_PRICE_AI_RELEVANCE_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты оцениваешь релевантность товаров-конкурентов на Wildberries. "
                        "Возвращай только валидный JSON без пояснений. "
                        "Не придумывай новые правила, оцени только данную пару source/competitor."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Оцени, является ли competitor реальным конкурентом для source. "
                        "Верни JSON строго формата "
                        "{\"relevance_score\": 0.0-1.0, \"relevance_verdict\": true/false, "
                        "\"relevance_reason\": \"короткая причина на русском\", "
                        "\"matched_attributes_json\": {\"same_type\": true/false, \"notes\": []}}.\n\n"
                        f"Данные пары:\n{json.dumps(prompt_payload, ensure_ascii=False)}"
                    ),
                },
            ],
            max_tokens=Config.WB_PRICE_AI_RELEVANCE_MAX_OUTPUT_TOKENS,
            response_format={"type": "json_object"},
            timeout=Config.WB_PRICE_AI_RELEVANCE_TIMEOUT_SEC,
        )
        text = _extract_message_text(response.choices[0].message.content if response.choices else "")
        payload = normalize_relevance_payload(json.loads(text))
        if payload is None:
            raise RuntimeError("LLM relevance вернул невалидный JSON")
        payload["llm_model"] = Config.WB_PRICE_AI_RELEVANCE_MODEL
        payload["llm_prompt_version"] = Config.WB_PRICE_AI_RELEVANCE_PROMPT_VERSION
        return payload


def _initial_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(payload)
    result.update(
        {
            "llm_status": "failed",
            "llm_error": None,
            "llm_rows_written": 0,
            "llm_checked_count": 0,
            "llm_kept_count": 0,
        }
    )
    return result


def run_one(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = _initial_result(payload)
    if payload.get("filter_status") != "success":
        result["llm_status"] = "skipped_missing_filter"
        return result

    Config.validate_db()
    scorer = RelevanceScorer()
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        run_date = datetime.fromisoformat(f"{payload['run_date']}T00:00:00").date()
        candidates = db.get_filtered_candidates_for_llm(run_date, int(payload["source_nm_id"]))
        if not candidates:
            db.delete_relevance_rows(payload["run_date"], int(payload["source_nm_id"]))
            result["llm_status"] = "success"
            result["llm_rows_written"] = 0
            return result

        by_competitor: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in candidates:
            by_competitor[int(row["competitor_nm_id"])].append(row)

        rows_to_write: List[Dict[str, Any]] = []
        llm_errors: List[str] = []
        for competitor_nm_id, grouped_rows in by_competitor.items():
            representative = grouped_rows[0]
            try:
                payload_json = scorer._call_llm(representative)
                llm_status = "success"
                llm_error = None
                result["llm_checked_count"] += 1
                accepted = bool(payload_json.get("relevance_verdict")) or (
                    payload_json.get("relevance_score") is not None
                    and float(payload_json["relevance_score"]) >= Config.WB_PRICE_AI_RELEVANCE_THRESHOLD
                )
                if accepted:
                    result["llm_kept_count"] += 1
            except Exception as exc:
                llm_status = "failed"
                llm_error = str(exc)
                payload_json = {
                    "relevance_score": None,
                    "relevance_verdict": None,
                    "relevance_reason": "LLM relevance недоступен",
                    "matched_attributes_json": {},
                    "raw_response_json": None,
                    "llm_model": Config.WB_PRICE_AI_RELEVANCE_MODEL,
                    "llm_prompt_version": Config.WB_PRICE_AI_RELEVANCE_PROMPT_VERSION,
                }
                llm_errors.append(str(exc))
            for row in grouped_rows:
                rows_to_write.append(
                    {
                        "run_date": payload["run_date"],
                        "source_nm_id": int(payload["source_nm_id"]),
                        "keyword": row["keyword"],
                        "competitor_nm_id": competitor_nm_id,
                        "relevance_score": payload_json.get("relevance_score"),
                        "relevance_verdict": payload_json.get("relevance_verdict"),
                        "relevance_reason": payload_json.get("relevance_reason"),
                        "matched_attributes_json": payload_json.get("matched_attributes_json") or {},
                        "llm_model": payload_json.get("llm_model"),
                        "llm_prompt_version": payload_json.get("llm_prompt_version"),
                        "llm_status": llm_status,
                        "llm_error": llm_error,
                        "raw_response_json": payload_json.get("raw_response_json"),
                    }
                )

        db.delete_relevance_rows(payload["run_date"], int(payload["source_nm_id"]))
        written = db.upsert_relevance_rows(rows_to_write)
        result["llm_status"] = "success" if not llm_errors else "partial"
        result["llm_error"] = "; ".join(sorted(set(llm_errors))) if llm_errors else None
        result["llm_rows_written"] = written
        path = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"competitor_relevance_{payload['run_date']}_{payload['source_nm_id']}.json",
        )
        dump_json(
            path,
            {
                "generated_at": datetime.now().isoformat(),
                "source_nm_id": payload["source_nm_id"],
                "rows_written": written,
                "llm_checked_count": result["llm_checked_count"],
                "llm_kept_count": result["llm_kept_count"],
                "data": rows_to_write,
            },
        )
        return result
    finally:
        db.close()
