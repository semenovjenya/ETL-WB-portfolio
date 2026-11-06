#!/usr/bin/env python3
"""
Query RAG (pgvector) for WB API docs. Uses embedding + similarity search only.
"""
import json
import os
from pathlib import Path

import psycopg
from openai import OpenAI


EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


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


def get_embedding(client: OpenAI, text: str) -> list[float]:
    r = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return r.data[0].embedding


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.10f}" for v in vector) + "]"


def rag_query(pg_dsn: str, query: str, limit: int = 15) -> list[dict]:
    load_dotenv(Path(".env"))
    pg_dsn = os.getenv("PG_DSN", pg_dsn)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY required")
    client = OpenAI(base_url="https://polza.ai/api/v1", api_key=api_key)
    embedding = get_embedding(client, query)
    vec = vector_literal(embedding)
    sql = """
    SELECT source_path, method, endpoint, section, content
    FROM doc_chunks
    ORDER BY embedding <=> %s::vector
    LIMIT %s;
    """
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (vec, limit))
            rows = cur.fetchall()
    return [
        {"source": r[0], "method": r[1], "endpoint": r[2], "section": r[3], "content": r[4]}
        for r in rows
    ]


def main():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    queries = [
        "Описание метода: можно получить отчёт максимум за 31 день 8 дней 365 дней",
        "максимум за 8 дней платное хранение paid_storage",
        "365 дней доля бренда brand-share",
        "последнюю неделю sales-funnel аналитика",
        "период максимум 7 суток search-report",
        "информация хранится 90 дней supplier sales orders",
    ]
    pg_dsn = os.environ.get("PG_DSN", "postgresql://admin:admin@localhost:55433/wb_docs")
    client = OpenAI(base_url="https://polza.ai/api/v1", api_key=os.environ["OPENAI_API_KEY"])
    seen = set()
    all_rows = []
    for q in queries:
        vec = vector_literal(get_embedding(client, q))
        with psycopg.connect(pg_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT source_path, method, endpoint, section, content
                    FROM doc_chunks
                    ORDER BY embedding <=> %s::vector LIMIT 15
                """, (vec,))
                rows = cur.fetchall()
        for r in rows:
            key = (r[1], r[2], r[3], r[4][:200])
            if key not in seen:
                seen.add(key)
                all_rows.append(r)
    print("=== RAG results: лимиты статистики по дням ===\n")
    for i, r in enumerate(all_rows):
        print(f"--- [{i+1}] {r[1]} {r[2]} | {r[3]} ---")
        print(r[4][:700])
        print()


if __name__ == "__main__":
    main()
