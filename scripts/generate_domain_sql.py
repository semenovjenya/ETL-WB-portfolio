from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wb_schemas import (
    COMPAT_SCHEMA,
    DDL_FILE_SCHEMAS,
    TABLES_ROOT,
    rewrite_reports_sql,
)


CREATE_SCHEMA_RE = re.compile(r"^CREATE SCHEMA IF NOT EXISTS reports;\s*$", re.MULTILINE)
CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+reports\.([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
CREATE_MVIEW_RE = re.compile(
    r"CREATE\s+MATERIALIZED\s+VIEW\s+reports\.([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
CREATE_VIEW_RE = re.compile(
    r"CREATE(?:\s+OR\s+REPLACE)?\s+VIEW\s+reports\.([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _replace_create_schema(sql: str, schema: str) -> str:
    replaced = CREATE_SCHEMA_RE.sub(f"CREATE SCHEMA IF NOT EXISTS {schema};", sql)
    if replaced == sql:
        return f"CREATE SCHEMA IF NOT EXISTS {schema};\n\n{sql}"
    return replaced


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _parse_created_objects(sql: str) -> list[tuple[str, str]]:
    matches: list[tuple[int, str, str]] = []
    for pattern, kind in (
        (CREATE_TABLE_RE, "table"),
        (CREATE_MVIEW_RE, "materialized_view"),
        (CREATE_VIEW_RE, "view"),
    ):
        for match in pattern.finditer(sql):
            matches.append((match.start(), kind, match.group(1)))
    matches.sort(key=lambda item: item[0])
    return [(kind, name) for _, kind, name in matches]


def _migration_preamble(domain: str, created_objects: list[tuple[str, str]]) -> str:
    lines = [
        f"CREATE SCHEMA IF NOT EXISTS {domain};",
        f"CREATE SCHEMA IF NOT EXISTS {COMPAT_SCHEMA};",
        "",
    ]
    for kind, object_name in created_objects:
        if kind not in {"table", "materialized_view"}:
            continue
        ddl_kind = "TABLE" if kind == "table" else "MATERIALIZED VIEW"
        lines.extend(
            [
                "DO $$",
                "BEGIN",
                (
                    f"    IF to_regclass('{COMPAT_SCHEMA}.{object_name}') IS NOT NULL "
                    f"AND to_regclass('{domain}.{object_name}') IS NULL THEN"
                ),
                f"        EXECUTE 'ALTER {ddl_kind} {COMPAT_SCHEMA}.{object_name} SET SCHEMA {domain}';",
                "    END IF;",
                "END $$;",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n\n"


def _compat_sql(domain: str, created_objects: list[tuple[str, str]]) -> str:
    view_targets = _ordered_unique([name for kind, name in created_objects if kind in {"table", "view", "materialized_view"}])
    if not view_targets:
        return f"CREATE SCHEMA IF NOT EXISTS {COMPAT_SCHEMA};\n"

    lines = [f"CREATE SCHEMA IF NOT EXISTS {COMPAT_SCHEMA};", ""]
    for object_name in view_targets:
        lines.extend(
            [
                "DO $$",
                "DECLARE",
                "    _relkind \"char\";",
                "BEGIN",
                "    SELECT c.relkind",
                "      INTO _relkind",
                "      FROM pg_class c",
                "      JOIN pg_namespace n ON n.oid = c.relnamespace",
                f"     WHERE n.nspname = '{COMPAT_SCHEMA}'",
                f"       AND c.relname = '{object_name}';",
                "    IF _relkind = 'm' THEN",
                f"        EXECUTE 'DROP MATERIALIZED VIEW {COMPAT_SCHEMA}.{object_name} CASCADE';",
                "    ELSIF _relkind = 'v' THEN",
                f"        EXECUTE 'DROP VIEW {COMPAT_SCHEMA}.{object_name} CASCADE';",
                "    END IF;",
                "END $$;",
                f"CREATE OR REPLACE VIEW {COMPAT_SCHEMA}.{object_name} AS",
                f"SELECT * FROM {domain}.{object_name};",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def generate() -> None:
    source_dir = TABLES_ROOT / COMPAT_SCHEMA
    compat_dir = TABLES_ROOT / "compat_reports"
    compat_dir.mkdir(parents=True, exist_ok=True)

    for filename, domain in sorted(DDL_FILE_SCHEMAS.items()):
        source_path = source_dir / filename
        if not source_path.exists():
            continue

        original_sql = source_path.read_text(encoding="utf-8")
        created_objects = _parse_created_objects(original_sql)
        transformed_sql = rewrite_reports_sql(_replace_create_schema(original_sql, domain))
        transformed_sql = transformed_sql.replace("'reports.' ||", f"'{domain}.' ||")
        transformed_sql = transformed_sql.replace("ALTER TABLE reports.%I", f"ALTER TABLE {domain}.%I")
        final_domain_sql = _migration_preamble(domain, created_objects) + transformed_sql

        domain_path = TABLES_ROOT / domain / filename
        domain_path.parent.mkdir(parents=True, exist_ok=True)
        domain_path.write_text(final_domain_sql, encoding="utf-8")

        compat_path = compat_dir / filename
        compat_path.write_text(_compat_sql(domain, created_objects), encoding="utf-8")


if __name__ == "__main__":
    generate()
