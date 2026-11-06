"""Grade visual match for shortlisted competitors with OpenAI Vision."""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

from competitor_pipeline import parse_vision_response_text
from config import Config
from database import WBPriceAIAnalysisDatabase, dump_json
from finalize_price_ai_row import build_candidate_pool, select_top_unique_competitors

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


class VisionScorer:
    def __init__(self) -> None:
        self._client = None
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def _ensure_client(self) -> None:
        Config.validate_vision_openai()
        if self._client is not None:
            return
        if OpenAI is None:
            raise RuntimeError("Пакет openai не установлен")
        kwargs: Dict[str, Any] = {"api_key": Config.get_vision_openai_api_key()}
        base_url = Config.get_vision_openai_base_url()
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    def _call_vision(self, source_row: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_client()
        assert self._client is not None
        response = self._client.chat.completions.create(
            model=Config.WB_PRICE_AI_VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты оцениваешь визуальную аналогичность товаров Wildberries. "
                        "Игнорируй фон, интерьер, текстовые маркетинговые плашки и декор. "
                        "Смотри только на тип товара, форм-фактор, конструкцию и сценарий использования. "
                        "Возвращай только валидный JSON без пояснений."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Оцени визуальную аналогичность source и competitor. "
                                "Верни JSON строго формата "
                                "{\"vision_score\": 0.0-1.0, "
                                "\"vision_grade\": \"absolute_analog|close_analog|similar_market_item|not_analog\", "
                                "\"vision_reason\": \"краткая причина на русском\", "
                                "\"visual_signals_json\": {\"same_form_factor\": true/false/null, "
                                "\"same_visual_type\": true/false/null, "
                                "\"same_use_case\": true/false/null, "
                                "\"notable_differences\": []}}.\n\n"
                                f"source_title={source_row.get('source_title')!r}\n"
                                f"source_subject_name={source_row.get('source_subject_name')!r}\n"
                                f"competitor_title={row.get('competitor_title')!r}\n"
                                f"competitor_subject_name={row.get('competitor_subject_name')!r}\n"
                                f"text_relevance_score={row.get('relevance_score')!r}\n"
                                f"text_relevance_verdict={row.get('relevance_verdict')!r}\n"
                                f"matched_attributes_json={json.dumps(row.get('matched_attributes_json') or {}, ensure_ascii=False)}"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": str(source_row["source_main_photo_url"])},
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": str(row["competitor_main_photo_url"])},
                        },
                    ],
                },
            ],
            max_tokens=Config.WB_PRICE_AI_VISION_MAX_OUTPUT_TOKENS,
            response_format={"type": "json_object"},
            timeout=Config.WB_PRICE_AI_VISION_TIMEOUT_SEC,
        )
        text = _extract_message_text(response.choices[0].message.content if response.choices else "")
        payload = parse_vision_response_text(text)
        if payload is None:
            raise RuntimeError("Vision scorer вернул невалидный JSON")
        payload["vision_model"] = Config.WB_PRICE_AI_VISION_MODEL
        payload["vision_prompt_version"] = Config.WB_PRICE_AI_VISION_PROMPT_VERSION
        payload["raw_response_json"] = {"content": text}
        return payload


def _initial_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(payload)
    result.update(
        {
            "vision_status": "failed",
            "vision_error": None,
            "vision_rows_written": 0,
            "vision_checked_count": 0,
            "vision_absolute_count": 0,
            "vision_close_count": 0,
            "vision_similar_count": 0,
            "vision_not_analog_count": 0,
        }
    )
    return result


def _build_shortlist(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pool = build_candidate_pool(rows, Config.WB_PRICE_AI_RELEVANCE_THRESHOLD)["pool"]
    return select_top_unique_competitors(pool, Config.WB_PRICE_AI_VISION_LIMIT_PER_SKU)


def run_one(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = _initial_result(payload)
    if payload.get("filter_status") != "success":
        result["vision_status"] = "skipped_missing_filter"
        return result

    Config.validate_db()
    scorer = VisionScorer()
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        run_date = datetime.fromisoformat(f"{payload['run_date']}T00:00:00").date()
        source_nm_id = int(payload["source_nm_id"])
        candidates = db.get_final_candidates(run_date, source_nm_id)
        shortlist = _build_shortlist(candidates)
        if not shortlist:
            db.delete_vision_rows(payload["run_date"], source_nm_id)
            result["vision_status"] = "success"
            return result

        source_row = {
            "source_title": payload.get("source_title"),
            "source_subject_name": payload.get("source_subject_name"),
            "source_main_photo_url": payload.get("source_main_photo_url"),
        }
        rows_to_write: List[Dict[str, Any]] = []
        errors: List[str] = []
        grade_counts = defaultdict(int)

        for row in shortlist:
            competitor_nm_id = int(row["competitor_nm_id"])
            if not source_row.get("source_main_photo_url") or not row.get("competitor_main_photo_url"):
                payload_json = {
                    "vision_score": None,
                    "vision_grade": None,
                    "vision_reason": "Отсутствует source или competitor photo",
                    "visual_signals_json": {},
                    "vision_model": Config.WB_PRICE_AI_VISION_MODEL,
                    "vision_prompt_version": Config.WB_PRICE_AI_VISION_PROMPT_VERSION,
                    "raw_response_json": None,
                }
                vision_status = "skipped_missing_photo"
                vision_error = None
            else:
                try:
                    payload_json = scorer._call_vision(source_row, row)
                    vision_status = "success"
                    vision_error = None
                    result["vision_checked_count"] += 1
                    if payload_json.get("vision_grade"):
                        grade_counts[str(payload_json["vision_grade"])] += 1
                except Exception as exc:
                    vision_status = "failed"
                    vision_error = str(exc)
                    errors.append(str(exc))
                    payload_json = {
                        "vision_score": None,
                        "vision_grade": None,
                        "vision_reason": "Vision scorer недоступен",
                        "visual_signals_json": {},
                        "vision_model": Config.WB_PRICE_AI_VISION_MODEL,
                        "vision_prompt_version": Config.WB_PRICE_AI_VISION_PROMPT_VERSION,
                        "raw_response_json": None,
                    }

            for candidate_row in (candidate for candidate in candidates if int(candidate["competitor_nm_id"]) == competitor_nm_id):
                rows_to_write.append(
                    {
                        "run_date": payload["run_date"],
                        "source_nm_id": source_nm_id,
                        "keyword": candidate_row["keyword"],
                        "competitor_nm_id": competitor_nm_id,
                        "vision_score": payload_json.get("vision_score"),
                        "vision_grade": payload_json.get("vision_grade"),
                        "vision_reason": payload_json.get("vision_reason"),
                        "visual_signals_json": payload_json.get("visual_signals_json") or {},
                        "vision_model": payload_json.get("vision_model"),
                        "vision_prompt_version": payload_json.get("vision_prompt_version"),
                        "vision_status": vision_status,
                        "vision_error": vision_error,
                        "raw_response_json": payload_json.get("raw_response_json"),
                    }
                )

        db.delete_vision_rows(payload["run_date"], source_nm_id)
        written = db.upsert_vision_rows(rows_to_write)
        result["vision_rows_written"] = written
        result["vision_absolute_count"] = grade_counts["absolute_analog"]
        result["vision_close_count"] = grade_counts["close_analog"]
        result["vision_similar_count"] = grade_counts["similar_market_item"]
        result["vision_not_analog_count"] = grade_counts["not_analog"]
        result["vision_status"] = "success" if not errors else "partial"
        result["vision_error"] = "; ".join(sorted(set(errors))) if errors else None

        path = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"competitor_vision_{payload['run_date']}_{payload['source_nm_id']}.json",
        )
        dump_json(
            path,
            {
                "generated_at": datetime.now().isoformat(),
                "source_nm_id": payload["source_nm_id"],
                "rows_written": written,
                "vision_checked_count": result["vision_checked_count"],
                "vision_absolute_count": result["vision_absolute_count"],
                "vision_close_count": result["vision_close_count"],
                "vision_similar_count": result["vision_similar_count"],
                "vision_not_analog_count": result["vision_not_analog_count"],
                "data": rows_to_write,
            },
        )
        return result
    finally:
        db.close()
