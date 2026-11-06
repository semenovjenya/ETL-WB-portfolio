#!/usr/bin/env python3
"""
Парсер документации Wildberries API (dev.wildberries.ru/docs/openapi).
Делает то же, что skill wb-api-docs-parser: навигация, раскрытие секций, извлечение в markdown.

Использование:
  python scripts/parse_wb_api_docs.py analytics
  python scripts/parse_wb_api_docs.py --all
"""

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright

# Базовый URL документации
DOC_BASE = "https://dev.wildberries.ru/docs/openapi"
PARSER_VERSION = "2.0.0"

# Разделы и slug'и (из SKILL.md)
SECTION_SLUGS = [
    "api-information",
    "work-with-products",
    "analytics",
    "orders-fbs",
    "orders-dbs",
    "orders-fbw",
    "in-store-pickup",
    "promotion",
    "reports",
    "user-communication",
    "financial-reports-and-accounting",
    "wb-tariffs",
    "wbd",
]

# Базовый URL API по разделу (из SKILL.md)
# Русские названия подразделов (tag slug -> название)
ANALYTICS_TAG_NAMES = {
    "Voronka-prodazh": "sales_funnel",
    "Poiskovye-zaprosy-po-vashim-tovaram": "search_queries по вашим товарам",
    "Istoriya-ostatkov": "История остатков",
    "Analitika-prodavca-CSV": "Аналитика продавца CSV",
}

# Категория токена по умолчанию для раздела (если не найдена в блоке)
SLUG_TO_TOKEN_CATEGORY = {
    "work-with-products": "Контент",
    "analytics": "Аналитика",
    "orders-fbs": "Маркетплейс",
    "orders-dbs": "Маркетплейс",
    "orders-fbw": "supplies",
    "promotion": "Продвижение",
    "reports": "Отчёты",
    "user-communication": "Отзывы/Вопросы",
    "financial-reports-and-accounting": "Финансы",
}

SLUG_TO_BASE_URL = {
    "api-information": "https://common-api.wildberries.ru",
    "work-with-products": "https://content-api.wildberries.ru",
    "analytics": "https://seller-analytics-api.wildberries.ru",
    "orders-fbs": "https://marketplace-api.wildberries.ru",
    "orders-dbs": "https://marketplace-api.wildberries.ru",
    "orders-fbw": "https://supplies-api.wildberries.ru",
    "in-store-pickup": "https://marketplace-api.wildberries.ru",
    "promotion": "https://advert-api.wildberries.ru",
    "reports": "https://statistics-api.wildberries.ru",
    "user-communication": "https://feedbacks-api.wildberries.ru",
    "financial-reports-and-accounting": "https://finance-api.wildberries.ru",
    "wb-tariffs": "https://common-api.wildberries.ru",
    "wbd": "https://common-api.wildberries.ru",
}

# Категории токена по ключевым словам в тексте
TOKEN_CATEGORY_KEYWORDS = [
    ("Контент", "Контент"),
    ("Аналитика", "Аналитика"),
    ("prices и скидки", "prices и скидки"),
    ("Маркетплейс", "Маркетплейс"),
    ("Продвижение", "Продвижение"),
    ("любой токен", "Любой"),
]


def normalize_text(text: str, max_len: Optional[int] = None) -> str:
    """Очищает текст от UI-артефактов и нормализует пробелы."""
    if not text:
        return ""
    clean = text
    clean = re.sub(r"\s*collapse\s*expand\s*", " ", clean, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = re.sub(r"\s+([,.;:!?])", r"\1", clean)
    clean = re.sub(r"\s+\)", ")", clean)
    clean = re.sub(r"\(\s+", "(", clean)
    if max_len and len(clean) > max_len:
        return clean[:max_len].rstrip()
    return clean


def clean_schema_field(text: str) -> str:
    """Очищает названия полей схемы от примеров и мусора."""
    clean = normalize_text(text)
    clean = re.sub(r"Example:\s*[^|]+", "", clean, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip(" :-")
    return clean


def markdown_safe(text: str) -> str:
    """Экранирует символы, которые ломают markdown-таблицы."""
    return normalize_text(text).replace("|", r"\|")


def extract_error_codes(block_text: str) -> list[str]:
    """Извлекает HTTP-коды ошибок из текста блока метода."""
    found = {m for m in re.findall(r"\b([45]\d{2})\b", block_text)}
    if not found:
        return ["400", "401", "403", "429"]
    return sorted(found, key=int)


def format_json_string(raw: str) -> str:
    """Пытается красиво отформатировать JSON, иначе возвращает очищенную строку."""
    candidate = raw.strip()
    try:
        obj = json.loads(candidate)
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return normalize_text(candidate)


def extract_param_names_from_table_md(table_md: str) -> list[str]:
    """Достаёт имена параметров из markdown-таблицы."""
    if not table_md:
        return []
    result = []
    for line in table_md.splitlines():
        if not line.startswith("|"):
            continue
        if "---" in line or "Параметр" in line or "Parameter" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        name = clean_schema_field(cells[0])
        if name and name not in result:
            result.append(name)
    return result


def merge_param_names(*tables: str) -> list[str]:
    """Объединяет имена параметров из нескольких таблиц."""
    merged = []
    for table_md in tables:
        for name in extract_param_names_from_table_md(table_md):
            if name not in merged:
                merged.append(name)
    return merged


def endpoint_path_to_filename(method: str, path: str) -> str:
    """Формирует имя файла: GET_content_v2_object_parent_all.md"""
    method_upper = method.upper().strip()
    path_clean = path.strip().lstrip("/")
    # Путь: /api/v2/nm-report/downloads/file/{downloadId} -> api_v2_nm-report_downloads_file_downloadId
    path_part = path_clean.replace("/", "_")
    # Убрать фигурные скобки у path-параметров: {downloadId} -> downloadId
    path_part = re.sub(r"\{([^}]+)\}", r"\1", path_part)
    return f"{method_upper}_{path_part}.md"


def detect_token_category(text: str) -> str:
    """Определяет категорию токена по тексту авторизации."""
    for keyword, category in TOKEN_CATEGORY_KEYWORDS:
        if keyword in text:
            return category
    return "—"


def expand_all_sections(page, max_scrolls: int = 50) -> None:
    """Кликает по всем кнопкам 'Expand all' / 'Развернуть' / 'Показать все' с прокруткой."""
    expand_texts = [
        "Expand all",
        "Развернуть всё",
        "Развернуть все",
        "Показать все",
        "Show more",
        "Показать",
        "Show all",
    ]
    last_count = 0
    stable_rounds = 0

    for scroll_idx in range(max_scrolls):
        clicked = 0
        for text in expand_texts:
            try:
                buttons = page.get_by_role("button", name=re.compile(re.escape(text), re.I))
                for i in range(buttons.count()):
                    try:
                        btn = buttons.nth(i)
                        if btn.is_visible():
                            btn.scroll_into_view_if_needed()
                            btn.click(timeout=2000)
                            clicked += 1
                            time.sleep(0.3)
                    except Exception:
                        continue
            except Exception:
                pass

        # Клик по span/div с текстом "Expand all" (иногда не button)
        try:
            for selector in ['span:has-text("Expand all")', 'div:has-text("Expand all")', 'a:has-text("Expand all")']:
                loc = page.locator(selector)
                for i in range(min(loc.count(), 20)):
                    try:
                        el = loc.nth(i)
                        if el.is_visible():
                            el.scroll_into_view_if_needed()
                            el.click(timeout=1500)
                            clicked += 1
                            time.sleep(0.3)
                    except Exception:
                        continue
        except Exception:
            pass

        if clicked == 0 and last_count == 0:
            stable_rounds += 1
            if stable_rounds >= 2:
                break
        else:
            stable_rounds = 0
        last_count = clicked
        page.mouse.wheel(0, 2000)
        time.sleep(0.5)

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)


def get_page_html(page) -> str:
    """Возвращает полный HTML страницы для парсинга (Redocly рендерит контент в body)."""
    return page.evaluate("() => document.documentElement.outerHTML")


def extract_methods_from_html(
    html: str,
    doc_url: str,
    base_url: str,
    section_name: str,
    slug: str = "",
    analytics_tag_filter: str = "",
) -> list[dict]:
    """
    Извлекает данные по каждому API-методу из HTML страницы Redocly/Redoc.
    Поддерживает структуру WB: div[data-section-id] с span.http-verb и span.heading-endpoint / URL.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    methods = []
    method_pattern = re.compile(
        r"^\s*(get|post|put|patch|delete)\s+([^\s]+)\s*$",
        re.I,
    )
    path_only = re.compile(r"^\s*/(?:api/|[a-z0-9-]+/)[^\s]*\s*$", re.I)
    url_path_re = re.compile(r"https?://[^/]+(/[^\s<>'\"]+)")

    # Redocly WB: секции с data-section-id содержащие operation или paths
    section_divs = soup.find_all("div", attrs={"data-section-id": True})
    unique_ops = []
    seen = set()

    for div in section_divs:
        section_id = div.get("data-section-id", "")
        if "operation/" not in section_id and "paths/" not in section_id:
            continue
        method_val = "GET"
        method_span = div.find("span", class_=re.compile(r"http-verb", re.I)) or div.find("span", attrs={"type": re.compile(r"get|post|put|patch|delete", re.I)})
        if method_span:
            method_val = (method_span.get("type") or method_span.get_text(strip=True) or "get").upper()

        path_val = ""
        path_span = div.find("span", class_="heading-endpoint")
        if path_span:
            path_val = path_span.get_text(strip=True)
        if not path_val:
            for s in div.find_all("span"):
                t = s.get_text(strip=True)
                if t.startswith("http") and "wildberries.ru" in t and "/api" in t:
                    m_url = url_path_re.search(t)
                    if m_url:
                        path_val = m_url.group(1)
                    break

        if not path_val or not path_val.startswith("/"):
            continue
        key = (method_val, path_val)
        if key in seen:
            continue
        seen.add(key)
        unique_ops.append((method_val, path_val, div))

    for idx, (method, path, start_tag) in enumerate(unique_ops):
        full_url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        section_id = start_tag.get("data-section-id", "")
        subsection = section_name
        tag_part = ""
        if "tag/" in section_id:
            tag_part = section_id.split("tag/")[-1].split("/")[0]
            subsection = ANALYTICS_TAG_NAMES.get(tag_part) or tag_part.replace("-", " ").title()
        if analytics_tag_filter and tag_part and tag_part != analytics_tag_filter:
            continue
        description = ""
        limits_table = ""
        auth_text = ""
        query_params_table = ""
        path_params_table = ""
        request_body_table = ""
        request_example_json = ""
        response_200_table = ""
        response_200_json = ""
        error_codes = ["400", "401", "403", "429"]

        block_root = start_tag
        block_text = block_root.get_text(separator="\n", strip=True)
        tables = block_root.find_all("table")
        pres = block_root.find_all("pre")

        block_full_text = block_root.get_text(separator=" ", strip=True)
        if "Описание метода" in block_full_text:
            start = block_full_text.find("Описание метода")
            end = min(
                block_full_text.find("Лимит запросов", start) if "Лимит запросов" in block_full_text else len(block_full_text),
                block_full_text.find("Authorizations:", start) if "Authorizations:" in block_full_text else len(block_full_text),
                block_full_text.find("Request Body", start) if "Request Body" in block_full_text else len(block_full_text),
                start + 2500,
            )
            desc_raw = block_full_text[start:end].replace("Описание метода", "").strip()
            if len(desc_raw) > 30:
                description = normalize_text(desc_raw, max_len=2000)
        if not description:
            for p in block_root.find_all("p"):
                t = p.get_text(strip=True)
                clean_t = normalize_text(t, max_len=2000)
                if 50 <= len(clean_t) <= 1500 and "http" not in clean_t and not method_pattern.match(clean_t):
                    description = clean_t
                    break

        for table in tables:
            header = table.get_text()[:200]
            has_field_cells = table.find("td", attrs={"kind": "field"}) is not None
            if "Период" in header and "Лимит" in header:
                limits_table = table_to_markdown(table)
            elif has_field_cells:
                if "Request Body" in block_text and not request_body_table:
                    request_body_table = redoc_schema_table_to_markdown(table)
                elif not response_200_table and ("Response" in block_text or "Успешно" in block_text or "200" in block_text):
                    response_200_table = redoc_schema_table_to_markdown(table)
            elif "Параметр" in header or "Parameter" in header:
                if "query" in block_text.lower() or "Query" in header:
                    query_params_table = table_to_markdown(table)
                elif "path" in block_text.lower() or "Path" in header:
                    path_params_table = table_to_markdown(table)
                elif not request_body_table:
                    request_body_table = table_to_markdown(table)
            elif not response_200_table and ("Поле" in header or "Field" in header):
                response_200_table = table_to_markdown(table)

        for el in block_root.find_all(string=re.compile(r"HeaderApiKey|Authorizations?", re.I)):
            raw_auth = el.parent.get_text(separator=" ", strip=True) if el.parent else str(el)
            auth_text = normalize_text(raw_auth, max_len=400)
            break

        error_codes = extract_error_codes(block_text)

        redoc_jsons = redoc_json_to_string(block_root)
        if redoc_jsons:
            if method.upper() in ("POST", "PUT", "PATCH") and len(redoc_jsons) >= 1:
                request_example_json = format_json_string(redoc_jsons[0])[:15000]
            if len(redoc_jsons) >= 2:
                response_200_json = format_json_string(redoc_jsons[1])[:15000]
            elif len(redoc_jsons) == 1 and method.upper() not in ("POST", "PUT", "PATCH"):
                response_200_json = format_json_string(redoc_jsons[0])[:15000]

        for pre in pres:
            code = pre.get_text(strip=True)
            if code.startswith("{") or code.startswith("["):
                if not request_example_json and method.upper() in ("POST", "PUT", "PATCH"):
                    request_example_json = format_json_string(code)[:15000]
                elif not response_200_json:
                    response_200_json = format_json_string(code)[:15000]

        token_category = detect_token_category(auth_text) if auth_text else "—"
        if token_category == "—":
            token_category = SLUG_TO_TOKEN_CATEGORY.get(slug) or "—"

        param_names = merge_param_names(query_params_table, path_params_table, request_body_table, response_200_table)

        methods.append({
            "method": method,
            "path": path,
            "doc_id": f"{method.upper()}_{path}",
            "full_url": full_url,
            "base_url": base_url,
            "doc_url": doc_url,
            "section_name": section_name,
            "subsection": subsection,
            "token_category": token_category,
            "description": description or "Описание метода из документации WB.",
            "limits_table": limits_table,
            "auth_text": auth_text,
            "query_params_table": query_params_table,
            "path_params_table": path_params_table,
            "request_body_table": request_body_table,
            "request_example_json": request_example_json,
            "response_200_table": response_200_table,
            "response_200_json": response_200_json,
            "error_codes": error_codes,
            "params_names": param_names,
            "lang": "ru",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "parser_version": PARSER_VERSION,
            "has_json_example": bool(request_example_json or response_200_json),
        })

    return methods


def table_to_markdown(table) -> str:
    """Конвертирует HTML-таблицу в GFM markdown."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [markdown_safe(td.get_text(separator=" ", strip=True)) for td in tr.find_all(["th", "td"])]
        if cells:
            rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ""
    header = rows[0]
    sep = "|" + "|".join(["---"] * (header.count("|") - 1)) + "|"
    return "\n".join([header, sep] + rows[1:])


def redoc_schema_table_to_markdown(table) -> str:
    """Таблица Redoc с td[kind='field'] → markdown (Параметр | Тип | Обязательный | По умолчанию | Описание)."""
    header = "| Параметр | Тип | Обязательный | По умолчанию | Описание |"
    sep = "|----------|-----|--------------|--------------|----------|"
    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        first_td, second_td = tds[0], tds[1]
        param = first_td.get("title") or ""
        if not param:
            span = first_td.find("span", class_=re.compile(r"property-name", re.I))
            if span:
                param = span.get_text(strip=True)
        param = clean_schema_field(param)
        if not param:
            continue
        required = "да" if first_td.find(class_=re.compile(r"required|jcBVVs|hNZhLt", re.I)) or "required" in first_td.get_text() else "нет"
        cell2 = normalize_text(second_td.get_text(separator=" ", strip=True))
        default = "—"
        if "Default:" in cell2:
            m = re.search(r"Default:\s*([^\s]+)", cell2)
            if m:
                default = m.group(1).strip()[:20]
        type_part = cell2
        if "Default:" in type_part:
            type_part = type_part.split("Default:")[0].strip()
        desc_part = ""
        p_el = second_td.find("p")
        if p_el:
            desc_part = normalize_text(p_el.get_text(separator=" ", strip=True), max_len=300)
        if not desc_part and len(cell2) > 80:
            desc_part = normalize_text(cell2[80:280], max_len=200)
        type_clean = normalize_text(type_part, max_len=80) or "—"
        rows.append(
            f"| {markdown_safe(param)} | {markdown_safe(type_clean)} | {required} | {markdown_safe(default)} | {markdown_safe(desc_part or '—')} |"
        )
    if not rows:
        return ""
    return "\n".join([header, sep] + rows)


def _extract_first_json_like(s: str) -> str:
    """Из строки извлекает первый сбалансированный {...} или [...]."""
    start = -1
    for i, c in enumerate(s):
        if c in "{[":
            start = i
            break
    if start == -1:
        return ""
    depth = 0
    open_b = "{["
    close_b = "}]"
    for i in range(start, len(s)):
        if s[i] in open_b:
            depth += 1
        elif s[i] in close_b:
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return ""


def redoc_json_to_string(block_root) -> list[str]:
    """Извлекает JSON-подобные строки из блоков div.redoc-json (Request/Response samples)."""
    result = []
    for div in block_root.find_all("div", class_=re.compile(r"redoc-json", re.I)):
        code = div.find("code")
        if not code:
            continue
        raw = code.get_text(separator=" ", strip=True)
        raw = re.sub(r"\s*collapse\s*expand\s*", " ", raw, flags=re.I)
        raw = re.sub(r"\s+", " ", raw)
        extracted = _extract_first_json_like(raw)
        if len(extracted) > 20:
            result.append(format_json_string(extracted))
    return result


def method_to_markdown(data: dict) -> str:
    """Формирует markdown для одного метода по шаблону output-template."""
    method = data["method"]
    path = data["path"]
    doc_id = data.get("doc_id", f"{method.upper()}_{path}")
    base_url = data["base_url"]
    full_url = data["full_url"]
    doc_url = data["doc_url"]
    section = data["section_name"]
    subsection = data["subsection"]
    token = data["token_category"]
    desc = data["description"]
    limits = data["limits_table"]
    auth = data["auth_text"]
    query_t = data["query_params_table"]
    path_t = data["path_params_table"]
    body_t = data["request_body_table"]
    req_json = data["request_example_json"]
    resp_t = data["response_200_table"]
    resp_json = data["response_200_json"]
    errors = data["error_codes"]
    params_names = data.get("params_names", [])
    lang = data.get("lang", "ru")
    updated_at = data.get("updated_at", "")
    parser_version = data.get("parser_version", PARSER_VERSION)
    has_json_example = data.get("has_json_example", False)

    parts = [
        f"# {method} {path}",
        "",
        f"**Doc ID:** {doc_id}  ",
        f"**Раздел:** {section} → {subsection}  ",
        f"**Категория токена:** {token}  ",
        f"**Язык:** {lang}  ",
        f"**Базовый URL:** {base_url}  ",
        f"**Полный URL:** {full_url}  ",
        f"**Документация:** {doc_url}  ",
        f"**Версия парсера:** {parser_version}  ",
        f"**Обновлено (UTC):** {updated_at}  ",
        f"**Есть JSON-примеры:** {'да' if has_json_example else 'нет'}",
        "",
        "## Описание",
        "",
        desc,
        "",
    ]

    if limits:
        parts += ["## Лимиты", "", limits, ""]
    if auth:
        parts += ["## Авторизация", "", auth, ""]
    elif token != "—":
        parts += ["## Авторизация", "", f"Header ApiKey — токен для категории **{token}**.", ""]
    if query_t:
        parts += ["## Параметры запроса (query)", "", query_t, ""]
    if path_t:
        parts += ["## Параметры пути (path)", "", path_t, ""]
    if body_t:
        parts += ["## Тело запроса (application/json)", "", body_t, ""]
    if params_names:
        parts += ["## Параметры (кратко)", "", ", ".join(params_names), ""]
    if req_json:
        parts += ["## Пример запроса", "", "```json", req_json[:8000], "```", ""]
    if resp_t:
        parts += ["## Ответ 200 (Успешно)", "", resp_t, ""]
    if resp_json:
        parts += ["## Пример ответа 200", "", "```json", resp_json[:8000], "```", ""]
    parts += ["## Ответы с ошибками", ""]
    for code in errors:
        parts.append(f"- **{code}** — См. документацию WB")
    parts.append("")

    return "\n".join(parts)


def build_index_md(slug: str, section_title: str, base_url: str, methods: list[dict], output_dir: Path) -> str:
    """Собирает содержимое _index.md для раздела."""
    doc_url = f"{DOC_BASE}/{slug}"
    lines = [
        f"# {section_title} ({slug})",
        "",
        f"**Страница документации:** {doc_url}  ",
        f"**Базовый URL API:** {base_url}",
        "",
        "---",
        "",
        "## Список методов",
        "",
    ]
    current_subsection = None
    for m in methods:
        sub = m.get("subsection") or "Методы"
        if sub != current_subsection:
            current_subsection = sub
            lines.append(f"### {current_subsection}")
            lines.append("")
        filename = endpoint_path_to_filename(m["method"], m["path"])
        lines.append(f"- [{m['method']} {m['path']}](./{filename}) — {m['description'][:80]}...")
        lines.append("")
    return "\n".join(lines)


def run_parser(
    slug: str,
    output_root: Path,
    headless: bool = True,
    debug: bool = False,
    doc_url_override: str = "",
    analytics_tag_filter: str = "",
) -> int:
    """Запускает парсер для одного раздела. Возвращает количество сохранённых методов."""
    url = doc_url_override or f"{DOC_BASE}/{slug}"
    base_url = SLUG_TO_BASE_URL.get(slug, "https://common-api.wildberries.ru")
    out_dir = output_root / "markdown" / slug
    if analytics_tag_filter:
        out_dir = out_dir / analytics_tag_filter
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
        )
        page = context.new_page()
        page.goto(url, wait_until="load", timeout=120000)
        page.wait_for_timeout(5000)
        expand_all_sections(page)
        page.wait_for_timeout(1500)
        html = get_page_html(page)
        if debug:
            debug_file = output_root / "markdown" / f"{slug}_debug.html"
            debug_file.write_text(html, encoding="utf-8")
            print(f"  [debug] HTML сохранён: {debug_file}")
        browser.close()

    section_title = {
        "analytics": "Аналитика и данные",
        "wb-tariffs": "tariffs",
    }.get(slug, slug.replace("-", " ").title())
    methods = extract_methods_from_html(
        html,
        url,
        base_url,
        section_title,
        slug,
        analytics_tag_filter=analytics_tag_filter,
    )

    for data in methods:
        md = method_to_markdown(data)
        filename = endpoint_path_to_filename(data["method"], data["path"])
        (out_dir / filename).write_text(md, encoding="utf-8")

    index_content = build_index_md(slug, section_title, base_url, methods, out_dir)
    (out_dir / "_index.md").write_text(index_content, encoding="utf-8")
    return len(methods)


def main():
    parser = argparse.ArgumentParser(description="Парсер документации WB API (dev.wildberries.ru/docs/openapi)")
    parser.add_argument(
        "slug",
        nargs="?",
        default=None,
        help=(
            "Slug раздела (например analytics) или полный URL вида "
            "https://dev.wildberries.ru/docs/openapi/analytics#tag/Poiskovye-zaprosy-po-vashim-tovaram"
        ),
    )
    parser.add_argument("--all", action="store_true", help="Парсить все разделы из списка")
    parser.add_argument("-o", "--output", type=Path, default=Path("output"), help="Корень для output (по умолчанию output)")
    parser.add_argument("--no-headless", action="store_true", help="Запустить браузер в видимом режиме")
    parser.add_argument("--debug", action="store_true", help="Сохранить HTML страницы в output/markdown/{slug}_debug.html")
    args = parser.parse_args()

    urls_by_slug = {}
    tag_filter_by_slug = {}

    if args.all:
        slugs = SECTION_SLUGS
    elif args.slug:
        if args.slug.startswith("http://") or args.slug.startswith("https://"):
            parsed = urlparse(args.slug)
            path = parsed.path.rstrip("/")
            prefix = "/docs/openapi/"
            if not path.startswith(prefix):
                print("URL должен быть вида https://dev.wildberries.ru/docs/openapi/<slug>#...")
                return 1
            slug_from_url = path[len(prefix) :]
            if slug_from_url not in SECTION_SLUGS:
                print(f"Неизвестный slug в URL: {slug_from_url}. Доступные: {', '.join(SECTION_SLUGS)}")
                return 1
            slugs = [slug_from_url]
            urls_by_slug[slug_from_url] = args.slug
            if parsed.fragment.startswith("tag/"):
                tag_filter_by_slug[slug_from_url] = parsed.fragment.split("tag/")[-1]
        else:
            if args.slug not in SECTION_SLUGS:
                print(f"Неизвестный slug. Доступные: {', '.join(SECTION_SLUGS)}")
                return 1
            slugs = [args.slug]
    else:
        parser.print_help()
        return 0

    root = Path(__file__).resolve().parent.parent
    output_root = args.output if args.output.is_absolute() else root / args.output
    total = 0
    for slug in slugs:
        print(f"Парсинг: {DOC_BASE}/{slug}")
        try:
            output_dir = output_root / "markdown" / slug
            if slug in tag_filter_by_slug:
                output_dir = output_dir / tag_filter_by_slug[slug]
            n = run_parser(
                slug,
                output_root,
                headless=not args.no_headless,
                debug=args.debug,
                doc_url_override=urls_by_slug.get(slug, ""),
                analytics_tag_filter=tag_filter_by_slug.get(slug, ""),
            )
            total += n
            print(f"  -> сохранено методов: {n}, директория: {output_dir}")
        except Exception as e:
            print(f"  -> ошибка: {e}")
    print(f"Всего методов: {total}")
    return 0


if __name__ == "__main__":
    exit(main())
