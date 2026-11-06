from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tenants.runtime import tenant_environment  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a tenant-scoped python job in an isolated subprocess")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--module-dir", required=True)
    parser.add_argument("--action", required=True, choices=("callable", "fetcher-run", "fetcher-method", "fetcher-db-method", "class-attr"))
    parser.add_argument("--module-name", required=True)
    parser.add_argument("--attr-name", required=True)
    parser.add_argument("--kwargs-json", default=None)
    parser.add_argument("--result-path", default=None)
    return parser.parse_args()


def _load_payload(raw: str | None) -> Any:
    if raw:
        return json.loads(raw)
    if sys.stdin.isatty():
        return {}
    content = sys.stdin.read().strip()
    return json.loads(content) if content else {}


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _coerce_value(key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if key == "snapshot_hour":
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    if key in {"start_date", "end_date", "run_date"}:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value


def _import_attr(module_dir: str, module_name: str, attr_name: str) -> Any:
    module_path = PROJECT_ROOT / module_dir
    module_path_str = str(module_path)
    if module_path_str not in sys.path:
        sys.path.insert(0, module_path_str)
    for cached in (module_name, "config", "database"):
        if cached in sys.modules:
            del sys.modules[cached]
    importlib.invalidate_caches()
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def _invoke_callable(target: Any, payload: dict[str, Any]) -> Any:
    if not payload:
        return target()

    signature = inspect.signature(target)
    try:
        signature.bind(**payload)
    except TypeError as bind_error:
        supported_params = [
            param
            for param in signature.parameters.values()
            if param.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        ]
        if len(payload) == 1 and len(supported_params) == 1:
            sole_value = next(iter(payload.values()))
            param = supported_params[0]
            if param.kind == inspect.Parameter.POSITIONAL_ONLY:
                return target(sole_value)
            return target(**{param.name: sole_value})

        expected = ", ".join(signature.parameters.keys()) or "<no-args>"
        got = ", ".join(payload.keys()) or "<empty>"
        raise TypeError(
            f"Payload mismatch for {getattr(target, '__name__', repr(target))}: "
            f"expected params [{expected}], got keys [{got}]"
        ) from bind_error

    return target(**payload)


def main() -> None:
    args = parse_args()
    payload = _load_payload(args.kwargs_json)
    if not isinstance(payload, dict):
        raise SystemExit("Payload must be a JSON object")
    payload = {key: _coerce_value(key, value) for key, value in payload.items()}

    with tenant_environment(args.tenant_id, module_dir=args.module_dir):
        target = _import_attr(args.module_dir, args.module_name, args.attr_name)

        if args.action == "callable":
            result = _invoke_callable(target, payload)
        elif args.action == "fetcher-run":
            fetcher = target()
            result = fetcher.run(**payload)
        elif args.action == "fetcher-method":
            fetcher = target()
            method_name = payload.pop("method_name")
            method = getattr(fetcher, method_name)
            result = method(**payload)
        elif args.action == "fetcher-db-method":
            fetcher = target()
            method_name = payload.pop("method_name")
            fetcher.db.connect()
            try:
                method = getattr(fetcher.db, method_name)
                result = method(**payload)
            finally:
                if getattr(fetcher.db, "conn", None):
                    fetcher.db.close()
        else:
            class_attr_name = payload.get("class_attr_name")
            if not class_attr_name:
                raise SystemExit("class_attr action requires class_attr_name")
            result = getattr(target, class_attr_name)

    rendered_result = json.dumps({"result": _serialize(result)}, ensure_ascii=False)
    if args.result_path:
        Path(args.result_path).write_text(rendered_result, encoding="utf-8")
    else:
        sys.stdout.write(rendered_result)


if __name__ == "__main__":
    main()
