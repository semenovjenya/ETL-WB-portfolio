from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tenants.runtime import build_tenant_env, resolve_tenant  # noqa: E402


PORT_RE = re.compile(r":(\d+)\s*$")


def resolve_host_db_port(container_name: str) -> int:
    result = subprocess.run(
        ["docker", "port", container_name, "5432/tcp"],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        match = PORT_RE.search(line.strip())
        if match:
            return int(match.group(1))
    raise RuntimeError(
        f"Container {container_name} does not publish 5432/tcp to the host; "
        "a host browser-worker cannot reach this tenant database"
    )


def build_host_worker_env(
    tenant_id: str,
    *,
    headless: bool = False,
    worker_name: str | None = None,
    browser_profile_dir: str | None = None,
) -> dict[str, str]:
    tenant = resolve_tenant(tenant_id)
    env = build_tenant_env(tenant, module_dir="wb_price_ai_analysis")
    host_port = resolve_host_db_port(tenant.db_container_name)
    env.update(
        {
            "DB_HOST": "localhost",
            "POSTGRES_HOST": "localhost",
            "DB_PORT": str(host_port),
            "POSTGRES_PORT": str(host_port),
            "DATABASE_URL": "",
            "PG_DSN": "",
            "WB_PRICE_AI_HOST_WORKER_ID": f"{tenant.tenant_slug}:{worker_name or os.getpid()}",
        }
    )
    if headless:
        env["WB_PRICE_AI_COMPETITOR_HEADLESS"] = "true"
    if browser_profile_dir:
        env["WB_PRICE_AI_COMPETITOR_BROWSER_PROFILE_DIR"] = str(
            Path(browser_profile_dir).expanduser().resolve()
        )
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GUI browser worker for one tenant from the host")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--canary-nm-id", type=int, default=None)
    mode.add_argument(
        "--rebuild-batch-id",
        default=None,
        help="Rebuild compatibility rows and analysis for an existing SERP batch",
    )
    parser.add_argument(
        "--worker-name",
        default=None,
        help="Stable worker label used in queue ownership and heartbeat monitoring",
    )
    parser.add_argument(
        "--browser-profile-dir",
        default=None,
        help="Dedicated persistent Playwright profile; required when workers run in parallel",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Playwright without opening a visible browser window",
    )
    parser.add_argument(
        "--include-legacy-competitor-jobs",
        action="store_true",
        help="Also process the old wb_price_ai competitor queue",
    )
    args = parser.parse_args()

    if args.rebuild_batch_id is not None:
        command = [
            sys.executable,
            str(PROJECT_ROOT / "wb_price_ai_analysis" / "serp_snapshot.py"),
            "--rebuild-batch-id",
            args.rebuild_batch_id,
        ]
    elif args.canary_nm_id is not None:
        command = [
            sys.executable,
            str(PROJECT_ROOT / "wb_price_ai_analysis" / "serp_snapshot.py"),
            "--canary-nm-id",
            str(args.canary_nm_id),
        ]
    else:
        command = [sys.executable, str(PROJECT_ROOT / "wb_price_ai_analysis" / "run_host_competitor_worker.py")]
        if not args.include_legacy_competitor_jobs:
            command.append("--serp-only")
        if args.once:
            command.append("--once")
        if args.poll_interval is not None:
            command.extend(["--poll-interval", str(args.poll_interval)])
    completed = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT / "wb_price_ai_analysis"),
        env=build_host_worker_env(
            args.tenant_id,
            headless=args.headless,
            worker_name=args.worker_name,
            browser_profile_dir=args.browser_profile_dir,
        ),
        check=False,
    )
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
