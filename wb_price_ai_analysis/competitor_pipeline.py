"""Helpers for multi-stage competitor pipeline in wb_price_ai_analysis."""
from __future__ import annotations

import json
import math
import re
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

SPACE_RE = re.compile(r"\s+")
DIMENSION_RE = re.compile(r"(?<!\d)(\d{2,4})\s*[xх×*]\s*(\d{2,4})(?:\s*[xх×*]\s*(\d{1,3}))?")
JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
VISION_GRADES = (
    "absolute_analog",
    "close_analog",
    "similar_market_item",
    "not_analog",
)

BED_TYPE_PATTERNS = {
    "single": ("односпаль", "single"),
    "double": ("двуспаль", "double"),
    "semi_double": ("полутор", "полутора"),
}
MATERIAL_PATTERNS = {
    "pine": ("сосн", "pine"),
    "birch": ("берез", "birch"),
    "oak": ("дуб", "oak"),
    "metal": ("металл", "metal"),
    "plastic": ("пластик", "plastic"),
    "mdf": ("мдф", "mdf", "mdf "),
    "chipboard": ("лдсп", "дсп", "chipboard"),
    "fabric": ("ткан", "велюр", "рогож", "fabric"),
}
SHAPE_PATTERNS = {
    "rectangular": ("прямоуголь", "rectangular"),
    "oval": ("оваль", "oval"),
    "round": ("кругл", "round"),
    "square": ("квадрат", "square"),
}
PLATFORM_PATTERNS = {
    "ps5": ("ps5", "playstation 5", "play station 5"),
    "ps4": ("ps4", "playstation 4", "пс 4", "для 4"),
    "ps3": ("ps3", "playstation 3", "пс 3", "для 3"),
    "xbox": ("xbox", "иксбокс"),
    "switch": ("switch", "нинтендо"),
    "pc": ("пк", "pc", "компьют"),
    "phone": ("телефон", "смартфон", "android", "ios", "айфон"),
}
CONNECTION_PATTERNS = {
    "wireless": ("беспровод", "bluetooth", "радио", "wireless"),
    "wired": ("провод", "usb", "wired"),
}
TIE_SUBTYPE_PATTERNS = {
    "velcro": ("липуч", "velcro"),
    "plastic": ("хомут", "пластик"),
    "nylon": ("нейлон", "кабельн"),
}

SUBJECT_NORMALIZATION = {
    "кровати": "beds",
    "кровати детские": "kids_beds",
    "кровати двухъярусные": "bunk_beds",
    "столешницы для стола": "tabletops",
    "стяжка": "cable_ties",
    "геймпады": "gamepads",
    "принтеры портативные": "portable_printers",
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return SPACE_RE.sub(" ", str(value).strip().lower())


def _clean_text(value: Any) -> Optional[str]:
    text = SPACE_RE.sub(" ", str(value or "").strip())
    return text or None


def _iter_text_chunks(*values: Any) -> Iterable[str]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                yield value
            continue
        if isinstance(value, (list, tuple, set)):
            for item in value:
                yield from _iter_text_chunks(item)
            continue
        if isinstance(value, dict):
            for item in value.values():
                yield from _iter_text_chunks(item)
            continue
        text = str(value).strip()
        if text:
            yield text


def _join_text(*values: Any) -> str:
    return " ".join(chunk for chunk in _iter_text_chunks(*values) if chunk).strip()


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


def _match_token(text: str, mapping: Dict[str, Sequence[str]]) -> Optional[str]:
    normalized = normalize_text(text)
    if not normalized:
        return None
    for label, tokens in mapping.items():
        if any(token in normalized for token in tokens):
            return label
    return None


def extract_dimensions(text: Any) -> Optional[List[int]]:
    normalized = normalize_text(text)
    if not normalized:
        return None
    match = DIMENSION_RE.search(normalized)
    if not match:
        return None
    dims = [int(match.group(1)), int(match.group(2))]
    if match.group(3):
        dims.append(int(match.group(3)))
    return dims


def extract_dimensions_from_many(*values: Any) -> Optional[List[int]]:
    for chunk in _iter_text_chunks(*values):
        dims = extract_dimensions(chunk)
        if dims:
            return dims
    return None


def extract_subject_norm(subject_name: Any) -> Optional[str]:
    normalized = normalize_text(subject_name)
    return SUBJECT_NORMALIZATION.get(normalized) or (normalized or None)


def extract_bed_type(text: Any) -> Optional[str]:
    return _match_token(str(text or ""), BED_TYPE_PATTERNS)


def extract_material(*values: Any) -> Optional[str]:
    return _match_token(_join_text(*values), MATERIAL_PATTERNS)


def extract_shape(*values: Any) -> Optional[str]:
    return _match_token(_join_text(*values), SHAPE_PATTERNS)


def extract_platforms(*values: Any) -> List[str]:
    text = normalize_text(_join_text(*values))
    if not text:
        return []
    found: List[str] = []
    for label, tokens in PLATFORM_PATTERNS.items():
        if any(token in text for token in tokens):
            found.append(label)
    return found


def extract_connection_type(*values: Any) -> Optional[str]:
    return _match_token(_join_text(*values), CONNECTION_PATTERNS)


def extract_tie_subtype(*values: Any) -> Optional[str]:
    return _match_token(_join_text(*values), TIE_SUBTYPE_PATTERNS)


def extract_color_family(*values: Any) -> Optional[str]:
    text = normalize_text(_join_text(*values))
    if not text:
        return None
    for family, tokens in {
        "white": ("бел", "white"),
        "black": ("черн", "black"),
        "gray": ("сер", "gray", "grey"),
        "beige": ("беж", "натурал", "natural", "сосна"),
        "brown": ("корич", "орех", "венге", "wenge", "oak", "дуб"),
        "pink": ("роз", "pink"),
    }.items():
        if any(token in text for token in tokens):
            return family
    return None


def compatible_dimensions(source_dims: Optional[Sequence[int]], competitor_dims: Optional[Sequence[int]], tolerance: float = 0.15) -> Optional[bool]:
    if not source_dims or not competitor_dims:
        return None
    if len(source_dims) != len(competitor_dims):
        return False
    for source_value, competitor_value in zip(source_dims, competitor_dims):
        if source_value <= 0 or competitor_value <= 0:
            return False
        delta = abs(source_value - competitor_value) / float(source_value)
        if delta > tolerance:
            return False
    return True


def compatible_platforms(source_platforms: Sequence[str], competitor_platforms: Sequence[str]) -> Optional[bool]:
    source = set(source_platforms or [])
    competitor = set(competitor_platforms or [])
    if not source or not competitor:
        return None
    return bool(source & competitor)


def safe_mean(values: Sequence[float]) -> Optional[float]:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return round(mean(numbers), 4)


def safe_percentile(values: Sequence[float], percentile: float) -> Optional[float]:
    numbers = sorted(float(value) for value in values if value is not None)
    if not numbers:
        return None
    if len(numbers) == 1:
        return round(numbers[0], 2)
    clamped = min(100.0, max(0.0, float(percentile)))
    position = (len(numbers) - 1) * (clamped / 100.0)
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return round(numbers[lower_index], 2)
    lower_value = numbers[lower_index]
    upper_value = numbers[upper_index]
    weight = position - lower_index
    return round(lower_value + (upper_value - lower_value) * weight, 2)


def build_source_features(payload: Dict[str, Any]) -> Dict[str, Any]:
    text = _join_text(
        payload.get("source_title"),
        payload.get("source_description"),
        payload.get("source_subject_name"),
        payload.get("source_characteristics_json"),
        payload.get("source_sizes_json"),
        payload.get("source_tags_json"),
    )
    subject_norm = extract_subject_norm(payload.get("source_subject_name"))
    dimensions = extract_dimensions_from_many(
        payload.get("source_title"),
        payload.get("source_description"),
        payload.get("source_characteristics_json"),
        payload.get("source_sizes_json"),
    )
    return {
        "source_subject_norm": subject_norm,
        "source_subtype": extract_tie_subtype(text) if subject_norm == "cable_ties" else None,
        "source_dimensions_json": dimensions,
        "source_material": extract_material(text),
        "source_shape": extract_shape(text),
        "source_platform": extract_platforms(text),
        "source_connection_type": extract_connection_type(text),
        "source_bed_type": extract_bed_type(text) if "bed" in (subject_norm or "") or subject_norm == "beds" else None,
        "source_sleep_size_json": dimensions[:2] if dimensions and len(dimensions) >= 2 and subject_norm in {"beds", "kids_beds", "bunk_beds"} else None,
        "source_color_family": extract_color_family(payload.get("source_characteristics_json"), payload.get("source_title")),
    }


def build_competitor_features(raw_row: Dict[str, Any]) -> Dict[str, Any]:
    detail = raw_row.get("detail_payload_json") or {}
    text = _join_text(
        raw_row.get("competitor_title"),
        raw_row.get("competitor_description_short"),
        raw_row.get("competitor_subject_name"),
        detail,
    )
    subject_norm = extract_subject_norm(raw_row.get("competitor_subject_name"))
    dimensions = extract_dimensions_from_many(
        raw_row.get("competitor_title"),
        detail.get("name"),
        detail,
    )
    return {
        "competitor_subject_norm": subject_norm,
        "competitor_subtype": extract_tie_subtype(text) if subject_norm == "cable_ties" else None,
        "competitor_dimensions_json": dimensions,
        "competitor_material": extract_material(text),
        "competitor_shape": extract_shape(text),
        "competitor_platform": extract_platforms(text),
        "competitor_connection_type": extract_connection_type(text),
        "competitor_bed_type": extract_bed_type(text) if "bed" in (subject_norm or "") or subject_norm == "beds" else None,
        "competitor_sleep_size_json": dimensions[:2] if dimensions and len(dimensions) >= 2 and subject_norm in {"beds", "kids_beds", "bunk_beds"} else None,
        "competitor_color_family": extract_color_family(raw_row.get("competitor_colors_json"), raw_row.get("competitor_title")),
    }


def determine_filter_profile(source_subject_norm: Optional[str]) -> str:
    if source_subject_norm in {"beds", "kids_beds", "bunk_beds"}:
        return "beds"
    if source_subject_norm == "tabletops":
        return "tabletops"
    if source_subject_norm == "cable_ties":
        return "cable_ties"
    if source_subject_norm == "gamepads":
        return "gamepads"
    return "generic_same_subject_price"


def apply_hard_filter(raw_row: Dict[str, Any], features: Dict[str, Any]) -> Dict[str, Any]:
    source_subject = features.get("source_subject_norm")
    competitor_subject = features.get("competitor_subject_norm")
    profile = determine_filter_profile(source_subject)
    flags: Dict[str, Any] = {
        "same_subject": source_subject == competitor_subject if source_subject and competitor_subject else None,
        "within_price_segment": bool(raw_row.get("within_price_segment")),
        "source_subject_norm": source_subject,
        "competitor_subject_norm": competitor_subject,
        "structural_compatible": False,
    }
    if source_subject and competitor_subject and source_subject != competitor_subject:
        return {
            "passed_hard_filters": False,
            "hard_filter_reason": "subject_mismatch",
            "hard_filter_flags_json": flags,
            "filter_profile": profile,
        }

    if profile == "beds":
        bed_type_match = None
        if features.get("source_bed_type") and features.get("competitor_bed_type"):
            bed_type_match = features["source_bed_type"] == features["competitor_bed_type"]
            if not bed_type_match:
                flags["bed_type_match"] = False
                return {
                    "passed_hard_filters": False,
                    "hard_filter_reason": "bed_type_mismatch",
                    "hard_filter_flags_json": flags,
                    "filter_profile": profile,
                }
        size_match = compatible_dimensions(features.get("source_sleep_size_json"), features.get("competitor_sleep_size_json"), tolerance=0.05)
        flags["bed_type_match"] = bed_type_match
        flags["sleep_size_match"] = size_match
        if size_match is False:
            return {
                "passed_hard_filters": False,
                "hard_filter_reason": "sleep_size_mismatch",
                "hard_filter_flags_json": flags,
                "filter_profile": profile,
            }

    elif profile == "tabletops":
        shape_match = None
        if features.get("source_shape") and features.get("competitor_shape"):
            shape_match = features["source_shape"] == features["competitor_shape"]
            if not shape_match:
                flags["shape_match"] = False
                return {
                    "passed_hard_filters": False,
                    "hard_filter_reason": "shape_mismatch",
                    "hard_filter_flags_json": flags,
                    "filter_profile": profile,
                }
        dims_match = compatible_dimensions(features.get("source_dimensions_json"), features.get("competitor_dimensions_json"), tolerance=0.25)
        flags["shape_match"] = shape_match
        flags["dimensions_match"] = dims_match
        if dims_match is False:
            return {
                "passed_hard_filters": False,
                "hard_filter_reason": "dimensions_mismatch",
                "hard_filter_flags_json": flags,
                "filter_profile": profile,
            }

    elif profile == "cable_ties":
        subtype_match = None
        if features.get("source_subtype") and features.get("competitor_subtype"):
            subtype_match = features["source_subtype"] == features["competitor_subtype"]
            if not subtype_match:
                flags["subtype_match"] = False
                return {
                    "passed_hard_filters": False,
                    "hard_filter_reason": "subtype_mismatch",
                    "hard_filter_flags_json": flags,
                    "filter_profile": profile,
                }
        flags["subtype_match"] = subtype_match

    elif profile == "gamepads":
        platform_match = compatible_platforms(features.get("source_platform") or [], features.get("competitor_platform") or [])
        if platform_match is False:
            flags["platform_match"] = False
            return {
                "passed_hard_filters": False,
                "hard_filter_reason": "platform_mismatch",
                "hard_filter_flags_json": flags,
                "filter_profile": profile,
            }
        connection_match = None
        if features.get("source_connection_type") and features.get("competitor_connection_type"):
            connection_match = features["source_connection_type"] == features["competitor_connection_type"]
            if not connection_match:
                flags["connection_match"] = False
                return {
                    "passed_hard_filters": False,
                    "hard_filter_reason": "connection_type_mismatch",
                    "hard_filter_flags_json": flags,
                    "filter_profile": profile,
                }
        flags["platform_match"] = platform_match
        flags["connection_match"] = connection_match

    flags["structural_compatible"] = True
    return {
        "passed_hard_filters": True,
        "hard_filter_reason": "accepted_structural",
        "hard_filter_flags_json": flags,
        "filter_profile": profile,
    }


def select_top_unique_rows(rows: Sequence[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    best_rows: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        competitor_nm_id = int(row["competitor_nm_id"])
        current = best_rows.get(competitor_nm_id)
        if current is None:
            best_rows[competitor_nm_id] = dict(row)
            continue
        candidate_key = (
            row.get("keyword_order") or 10**9,
            row.get("catalog_position_absolute") or 10**9,
            abs(row.get("price_delta_percent") or 10**9),
            -(row.get("competitor_rating") or 0),
            -(row.get("competitor_feedbacks") or 0),
            competitor_nm_id,
        )
        current_key = (
            current.get("keyword_order") or 10**9,
            current.get("catalog_position_absolute") or 10**9,
            abs(current.get("price_delta_percent") or 10**9),
            -(current.get("competitor_rating") or 0),
            -(current.get("competitor_feedbacks") or 0),
            competitor_nm_id,
        )
        if candidate_key < current_key:
            best_rows[competitor_nm_id] = dict(row)
    ordered = sorted(
        best_rows.values(),
        key=lambda row: (
            row.get("keyword_order") or 10**9,
            row.get("catalog_position_absolute") or 10**9,
            abs(row.get("price_delta_percent") or 10**9),
            -(row.get("competitor_rating") or 0),
            -(row.get("competitor_feedbacks") or 0),
            row["competitor_nm_id"],
        ),
    )
    return ordered[:limit]


def normalize_relevance_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    score = payload.get("relevance_score")
    verdict = payload.get("relevance_verdict")
    reason = _clean_text(payload.get("relevance_reason"))
    try:
        score_value = float(score) if score is not None else None
    except Exception:
        score_value = None
    if score_value is not None:
        score_value = max(0.0, min(1.0, score_value))
    if verdict is not None:
        verdict = bool(verdict)
    return {
        "relevance_score": score_value,
        "relevance_verdict": verdict,
        "relevance_reason": reason,
        "matched_attributes_json": payload.get("matched_attributes_json") or {},
        "raw_response_json": payload,
    }


def parse_relevance_response_text(text: str) -> Optional[Dict[str, Any]]:
    return normalize_relevance_payload(_extract_json_object(text))


def vision_grade_priority(grade: Optional[str]) -> int:
    order = {
        "absolute_analog": 0,
        "close_analog": 1,
        "similar_market_item": 2,
        "not_analog": 3,
    }
    return order.get(str(grade or "").strip(), 99)


def normalize_vision_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    score = payload.get("vision_score")
    grade = _clean_text(payload.get("vision_grade"))
    reason = _clean_text(payload.get("vision_reason"))
    visual_signals = payload.get("visual_signals_json") or {}
    try:
        score_value = float(score) if score is not None else None
    except Exception:
        score_value = None
    if score_value is not None:
        score_value = max(0.0, min(1.0, score_value))
    if grade not in VISION_GRADES:
        return None
    if not isinstance(visual_signals, dict):
        visual_signals = {}
    return {
        "vision_score": score_value,
        "vision_grade": grade,
        "vision_reason": reason,
        "visual_signals_json": visual_signals,
        "raw_response_json": payload,
    }


def parse_vision_response_text(text: str) -> Optional[Dict[str, Any]]:
    return normalize_vision_payload(_extract_json_object(text))
