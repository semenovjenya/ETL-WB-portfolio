#!/usr/bin/env python3
"""
Build embeddings from parsed WB markdown docs and upsert into pgvector.

Usage:
  python scripts/embed_to_pgvector.py --root output/markdown
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import psycopg
from openai import OpenAI


EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


@dataclass
class ChunkRecord:
    chunk_id: str
    source_path: str
    doc_id: str | None
    method: str | None
    endpoint: str | None
    section: str
    chunk_index: int
    content: str
    meta: dict


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed markdown files into pgvector.")
    parser.add_argument("--root", type=Path, default=Path("output/markdown"), help="Root folder with markdown files.")
    parser.add_argument("--chunk-size", type=int, default=1800, help="Chunk size in characters.")
    parser.add_argument("--chunk-overlap", type=int, default=200, help="Chunk overlap in characters.")
    parser.add_argument("--max-section-chars", type=int, default=12000, help="Hard cap for each section text.")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size.")
    parser.add_argument("--limit-files", type=int, default=0, help="Optional limit of markdown files.")
    parser.add_argument("--file", type=Path, action="append", dest="files", help="Specific markdown file(s) to process (path relative to cwd or absolute).")
    parser.add_argument("--dry-run", action="store_true", help="Parse and chunk only, skip embedding and DB writes.")
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress.")
    return parser.parse_args()


def get_markdown_files(root: Path, limit_files: int = 0) -> list[Path]:
    files = sorted(
        [p for p in root.rglob("*.md") if p.name != "_index.md"],
        key=lambda p: str(p),
    )
    if limit_files > 0:
        return files[:limit_files]
    return files


def parse_header_metadata(lines: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("**") or ":**" not in stripped:
            continue
        match = re.match(r"\*\*(.+?):\*\*\s*(.*)$", stripped)
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        meta[key] = value
    return meta


def parse_method_and_endpoint(title_line: str) -> tuple[str | None, str | None]:
    match = re.match(r"#\s+([A-Z]+)\s+(.+)$", title_line.strip())
    if not match:
        return None, None
    return match.group(1).strip(), match.group(2).strip()


def split_markdown_into_sections(text: str) -> tuple[dict[str, str], str | None, str | None]:
    lines = text.splitlines()
    if not lines:
        return {}, None, None

    title_line = lines[0].strip()
    method, endpoint = parse_method_and_endpoint(title_line)
    section_blocks: dict[str, list[str]] = {"metadata": []}
    current_section = "metadata"

    for line in lines[1:]:
        if line.startswith("## "):
            current_section = line[3:].strip() or "unnamed"
            section_blocks.setdefault(current_section, [])
            continue
        section_blocks.setdefault(current_section, []).append(line)

    normalized = {k: "\n".join(v).strip() for k, v in section_blocks.items()}
    return normalized, method, endpoint


def split_text_with_overlap(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not cleaned:
        return []

    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        start = max(0, end - chunk_overlap)
    return chunks


def build_chunk_records(
    root: Path,
    file_path: Path,
    chunk_size: int,
    chunk_overlap: int,
    max_section_chars: int,
) -> list[ChunkRecord]:
    raw = file_path.read_text(encoding="utf-8")
    sections, method, endpoint = split_markdown_into_sections(raw)
    header_meta = parse_header_metadata(raw.splitlines()[:30])
    doc_id = header_meta.get("Doc ID")
    rel_path = str(file_path.relative_to(root))
    records: list[ChunkRecord] = []

    for section_name, section_text in sections.items():
        if not section_text:
            continue
        safe_section_text = section_text[:max_section_chars].strip()
        if not safe_section_text:
            continue
        chunks = split_text_with_overlap(
            text=safe_section_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        for chunk_index, chunk_content in enumerate(chunks):
            identity = f"{rel_path}|{section_name}|{chunk_index}"
            chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            records.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    source_path=rel_path,
                    doc_id=doc_id,
                    method=method,
                    endpoint=endpoint,
                    section=section_name,
                    chunk_index=chunk_index,
                    content=chunk_content,
                    meta={
                        "model": EMBEDDING_MODEL,
                        "parser_version": header_meta.get("Версия парсера"),
                        "updated_at": header_meta.get("Обновлено (UTC)"),
                        "language": header_meta.get("Язык"),
                        "full_url": header_meta.get("Полный URL"),
                        "documentation": header_meta.get("Документация"),
                    },
                )
            )

    return records


def batched(items: list[ChunkRecord], size: int) -> Iterator[list[ChunkRecord]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.10f}" for value in vector) + "]"


def ensure_env() -> tuple[str, str]:
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    pg_dsn = os.getenv("PG_DSN", "").strip()
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY is required.")
    if not pg_dsn:
        raise RuntimeError("PG_DSN is required.")
    return openai_key, pg_dsn


def upsert_records(conn: psycopg.Connection, records: Iterable[tuple[ChunkRecord, list[float]]]) -> int:
    sql = """
    INSERT INTO doc_chunks (
        chunk_id,
        source_path,
        doc_id,
        method,
        endpoint,
        section,
        chunk_index,
        content,
        meta,
        embedding
    )
    VALUES (
        %(chunk_id)s,
        %(source_path)s,
        %(doc_id)s,
        %(method)s,
        %(endpoint)s,
        %(section)s,
        %(chunk_index)s,
        %(content)s,
        %(meta)s::jsonb,
        %(embedding)s::vector
    )
    ON CONFLICT (chunk_id) DO UPDATE SET
        source_path = EXCLUDED.source_path,
        doc_id = EXCLUDED.doc_id,
        method = EXCLUDED.method,
        endpoint = EXCLUDED.endpoint,
        section = EXCLUDED.section,
        chunk_index = EXCLUDED.chunk_index,
        content = EXCLUDED.content,
        meta = EXCLUDED.meta,
        embedding = EXCLUDED.embedding;
    """
    rows = []
    for record, embedding in records:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Unexpected embedding size {len(embedding)} for {record.chunk_id}")
        rows.append(
            {
                "chunk_id": record.chunk_id,
                "source_path": record.source_path,
                "doc_id": record.doc_id,
                "method": record.method,
                "endpoint": record.endpoint,
                "section": record.section,
                "chunk_index": record.chunk_index,
                "content": record.content,
                "meta": json.dumps(record.meta, ensure_ascii=False),
                "embedding": vector_literal(embedding),
            }
        )

    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    load_dotenv(Path(".env"))

    if not root.exists():
        raise FileNotFoundError(f"Root folder does not exist: {root}")

    if args.files:
        files = []
        for f in args.files:
            p = f.resolve()
            if not p.exists():
                raise FileNotFoundError(f"File not found: {p}")
            if p.suffix.lower() != ".md":
                raise ValueError(f"Not a markdown file: {p}")
            files.append(p)
        files.sort(key=lambda p: str(p))
    else:
        files = get_markdown_files(root, limit_files=args.limit_files)
    if not files:
        print(f"No markdown files found in {root}")
        return 0

    all_records: list[ChunkRecord] = []
    for file_path in files:
        records = build_chunk_records(
            root=root,
            file_path=file_path,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            max_section_chars=args.max_section_chars,
        )
        all_records.extend(records)
        if args.verbose:
            print(f"[chunked] {file_path} -> {len(records)} chunks")

    print(f"Files: {len(files)}")
    print(f"Chunks: {len(all_records)}")

    if args.dry_run:
        print("Dry-run mode: skipped embeddings and DB writes.")
        return 0

    openai_key, pg_dsn = ensure_env()
    client = OpenAI(
        base_url="https://polza.ai/api/v1",
        api_key=openai_key,
    )

    inserted = 0
    with psycopg.connect(pg_dsn) as conn:
        for batch_num, batch in enumerate(batched(all_records, args.batch_size), start=1):
            payload = [item.content for item in batch]
            response = client.embeddings.create(model=EMBEDDING_MODEL, input=payload)
            vectors = [item.embedding for item in response.data]
            inserted += upsert_records(conn, zip(batch, vectors))
            conn.commit()
            print(f"[batch {batch_num}] upserted {len(batch)} chunks")

    print(f"Done. Upserted chunks: {inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
