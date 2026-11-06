"""Generate SEO keywords per SKU with LLM."""
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

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

JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
SKU_TOKEN_RE = re.compile(r"[A-Za-z]*\d+[A-Za-z\d-]*")
SPACE_RE = re.compile(r"\s+")


def normalize_keyword(keyword: Any) -> str:
    return SPACE_RE.sub(" ", str(keyword or "").strip().lower())


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass
    match = JSON_OBJECT_RE.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def validate_keywords(raw_keywords: Any, payload: Dict[str, Any]) -> List[str]:
    seen = set()
    valid: List[str] = []
    vendor_tokens = {
        normalize_keyword(payload.get("source_vendor_code")),
        normalize_keyword(payload.get("source_supplier_article")),
    }
    for item in raw_keywords or []:
        keyword = SPACE_RE.sub(" ", str(item or "").strip())
        normalized = normalize_keyword(keyword)
        if not normalized:
            continue
        if normalized in seen:
            continue
        if normalized in vendor_tokens:
            continue
        if SKU_TOKEN_RE.fullmatch(keyword):
            continue
        word_count = len(normalized.split())
        if word_count < 2 or word_count > 6:
            continue
        seen.add(normalized)
        valid.append(keyword)
    return valid[:5]


def build_prompt_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": payload.get("source_title"),
        "subject_name": payload.get("source_subject_name"),
        "brand": payload.get("source_brand"),
        "description": payload.get("source_description"),
        "characteristics": payload.get("source_characteristics_json") or [],
    }


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


class SEOKeywordGenerator:
    """LLM-based keyword generator."""

    def __init__(self) -> None:
        self._client = None
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)

    def _ensure_client(self) -> None:
        Config.validate_openai()
        if self._client is not None:
            return
        if OpenAI is None:
            raise RuntimeError("Пакет openai не установлен")
        kwargs: Dict[str, Any] = {"api_key": Config.OPENAI_API_KEY}
        if Config.OPENAI_BASE_URL:
            kwargs["base_url"] = Config.OPENAI_BASE_URL
        self._client = OpenAI(**kwargs)

    def _call_llm(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_client()
        assert self._client is not None
        prompt_payload = build_prompt_payload(payload)
        prompt = (
            "Сгенерируй ровно 5 SEO ключей для поиска Wildberries.\n"
            "Требования: русский язык, 2-6 слов, без дублей, без артикулов/sku/кодовых обозначений, "
            "только реально релевантные запросы по товару.\n"
            "Верни только JSON в формате {\"keywords\": [\"...\", \"...\", \"...\", \"...\", \"...\"]}."
        )
        response = self._client.chat.completions.create(
            model=Config.WB_PRICE_AI_SEO_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Ты SEO-оптимизатор Wildberries. Возвращай только валидный JSON без пояснений.",
                },
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        f"Данные товара:\n{json.dumps(prompt_payload, ensure_ascii=False)}"
                    ),
                }
            ],
            max_tokens=Config.WB_PRICE_AI_SEO_MAX_OUTPUT_TOKENS,
            response_format={"type": "json_object"},
            timeout=Config.WB_PRICE_AI_SEO_TIMEOUT_SEC,
        )
        response_text = _extract_message_text(response.choices[0].message.content if response.choices else "")
        payload_json = _extract_json_object(response_text)
        return {
            "payload_json": payload_json,
            "raw_output_text": response_text,
            "model": Config.WB_PRICE_AI_SEO_MODEL,
        }

    def run_one(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db = WBPriceAIAnalysisDatabase()
        db.connect()
        try:
            db.create_tables()
            result = dict(payload)
            result.update(
                {
                    "keywords_json": [],
                    "keyword_count": 0,
                    "seo_model": Config.WB_PRICE_AI_SEO_MODEL,
                    "seo_prompt_version": Config.WB_PRICE_AI_SEO_PROMPT_VERSION,
                    "seo_status": "failed",
                    "seo_error": None,
                    "raw_response_json": None,
                }
            )
            last_error: Optional[str] = None
            for attempt in range(Config.WB_PRICE_AI_SEO_RETRIES + 1):
                try:
                    llm_result = self._call_llm(payload)
                    raw_json = llm_result.get("payload_json") or {"raw_output_text": llm_result["raw_output_text"]}
                    keywords = validate_keywords((llm_result.get("payload_json") or {}).get("keywords"), payload)
                    result["raw_response_json"] = raw_json
                    if len(keywords) == 5:
                        result["keywords_json"] = keywords
                        result["keyword_count"] = 5
                        result["seo_status"] = "success"
                        result["seo_error"] = None
                        break
                    last_error = f"LLM returned invalid keywords set (attempt {attempt + 1})"
                except Exception as exc:
                    last_error = str(exc)
            if result["seo_status"] != "success":
                result["seo_error"] = last_error or "Unknown SEO generation failure"
                result["keywords_json"] = []
                result["keyword_count"] = 0
            db.upsert_seo_row(result)
            path = os.path.join(
                Config.JSON_OUTPUT_DIR,
                f"seo_keywords_{result['run_date']}_{result['source_nm_id']}.json",
            )
            dump_json(path, result)
            return result
        finally:
            db.close()


def run_one(payload: Dict[str, Any]) -> Dict[str, Any]:
    generator = SEOKeywordGenerator()
    return generator.run_one(payload)
