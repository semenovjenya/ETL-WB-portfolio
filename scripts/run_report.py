#!/usr/bin/env python3
"""
Генерация готовых отчётов из витрины mart_ai_sales_planning.

Подключение к БД: переменные окружения DB_HOST, DB_NAME, DB_USER, DB_PASSWORD
(или DATABASE_URL / PG_DSN). .env подгружается из корня проекта.

Использование:
  python scripts/run_report.py products   # отчёт по товарам → CSV + MD
  python scripts/run_report.py stocks     # отчёт по остаткам/пополнению → CSV + MD
"""

import csv
import os
import sys
from datetime import datetime
from pathlib import Path

# корень проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# загрузка .env из корня
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import psycopg2
from psycopg2.extras import RealDictCursor


def get_conn():
    host = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST")
    port = int(os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or "5432")
    dbname = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB")
    user = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
    password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")
    if os.getenv("DATABASE_URL"):
        return psycopg2.connect(os.getenv("DATABASE_URL"))
    if not all([host, dbname, user]):
        raise RuntimeError("Задайте DB_HOST, DB_NAME, DB_USER (или DATABASE_URL) в .env")
    return psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user, password=password or None
    )


REPORTS = {
    "products": {
        "query": "SELECT * FROM reports.v_report_products ORDER BY COALESCE(buyout_sum_day, 0) DESC, nm_id",
        "title": "Отчёт по товарам",
        "filename": "report_products",
    },
    "stocks": {
        "query": """
        SELECT * FROM reports.v_report_stocks_reorder
        ORDER BY
          CASE reorder_flag WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 WHEN 'no_sales' THEN 3 ELSE 4 END,
          days_of_stock ASC NULLS FIRST,
          reorder_qty_recommended DESC
        """,
        "title": "Отчёт по остаткам и пополнению",
        "filename": "report_stocks_reorder",
    },
}


def _fmt(val):
    if val is None:
        return ""
    if isinstance(val, (int, float)) and isinstance(val, bool) is False:
        if isinstance(val, float):
            return round(val, 2) if val == val else ""  # skip NaN
        return val
    if hasattr(val, "isoformat"):
        return val.isoformat()[:10] if hasattr(val, "day") else str(val)
    return str(val)


def write_csv(rows, path, encoding="utf-8-sig"):
    if not rows:
        return
    with open(path, "w", newline="", encoding=encoding) as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(v) for k, v in r.items()})


def write_md(rows, path, title, max_rows=500):
    if not rows:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\nДанных нет.\n")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"*Сформировано: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n")
        heads = list(rows[0].keys())
        f.write("| " + " | ".join(heads) + " |\n")
        f.write("| " + " | ".join("---" for _ in heads) + " |\n")
        for r in rows[:max_rows]:
            f.write("| " + " | ".join(str(_fmt(r.get(h, ""))) for h in heads) + " |\n")
        if len(rows) > max_rows:
            f.write(f"\n*Показано первых {max_rows} из {len(rows)} строк. Полные данные в CSV.*\n")
        f.write(f"\n*Всего строк: {len(rows)}*\n")


def run(report_key: str):
    if report_key not in REPORTS:
        print(f"Доступные отчёты: {', '.join(REPORTS)}")
        sys.exit(1)
    cfg = REPORTS[report_key]
    out_dir = PROJECT_ROOT / "tables" / "reports" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    date_suffix = datetime.now().strftime("%Y-%m-%d")
    base = out_dir / f"{cfg['filename']}_{date_suffix}"

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(cfg["query"])
            rows = cur.fetchall()
    finally:
        conn.close()

    csv_path = base.with_suffix(".csv")
    md_path = base.with_suffix(".md")
    write_csv(rows, csv_path)
    write_md(rows, md_path, cfg["title"])
    print(f"Отчёт: {cfg['title']}")
    print(f"  Строк: {len(rows)}")
    print(f"  CSV:  {csv_path}")
    print(f"  MD:   {md_path}")


if __name__ == "__main__":
    report = (sys.argv[1] or "products").strip().lower()
    run(report)
