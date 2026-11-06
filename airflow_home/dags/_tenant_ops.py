from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from tenants.runtime import build_tenant_env, resolve_tenant


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_tenant_job.py"


def _load_runner_result(result_path: Path) -> Any:
    if not result_path.exists():
        return None
    raw = result_path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    parsed = json.loads(raw)
    return parsed.get("result")


def run_tenant_job(
    *,
    tenant_id: str,
    module_dir: str,
    action: str,
    module_name: str,
    attr_name: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    tenant = resolve_tenant(tenant_id)
    env = build_tenant_env(tenant, module_dir=module_dir)
    command = [
        sys.executable,
        str(RUNNER_PATH),
        "--tenant-id",
        tenant_id,
        "--module-dir",
        module_dir,
        "--action",
        action,
        "--module-name",
        module_name,
        "--attr-name",
        attr_name,
    ]
    stdin_payload = json.dumps(payload or {}, ensure_ascii=False)
    logger.info("Tenant job: tenant=%s module=%s action=%s attr=%s", tenant.tenant_slug, module_name, action, attr_name)
    with tempfile.NamedTemporaryFile(prefix="tenant-job-result-", suffix=".json", delete=False) as result_file:
        result_path = Path(result_file.name)
    command.extend(["--result-path", str(result_path)])
    try:
        subprocess.run(
            command,
            input=stdin_payload,
            text=True,
            stdout=subprocess.DEVNULL,
            env=env,
            cwd=str(PROJECT_ROOT),
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Tenant job failed: tenant=%s module=%s attr=%s returncode=%s",
            tenant.tenant_slug,
            module_name,
            attr_name,
            exc.returncode,
        )
        raise
    try:
        return _load_runner_result(result_path)
    finally:
        result_path.unlink(missing_ok=True)
