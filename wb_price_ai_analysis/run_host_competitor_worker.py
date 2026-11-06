"""Host-side worker for wb_price_ai_analysis competitor jobs."""
import argparse
import logging
import time
from typing import Optional

from config import Config
from database import WBPriceAIAnalysisDatabase
from fetch_raw_competitors_per_sku import _run_direct
from serp_snapshot import run_serp_direct

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def process_one_job(
    db: WBPriceAIAnalysisDatabase,
    worker_id: str,
    *,
    serp_only: bool = False,
) -> bool:
    serp_job = db.claim_next_serp_job(
        worker_id=worker_id,
        stale_after_seconds=Config.WB_SERP_WORKER_STALE_SEC,
    )
    if serp_job:
        job_id = int(serp_job["id"])
        payload = serp_job.get("payload_json") or {}
        logger.info(
            "Host worker claimed SERP job id=%s source_nm_id=%s batch_id=%s attempt=%s",
            job_id,
            payload.get("source_nm_id"),
            payload.get("batch_id"),
            serp_job.get("attempts"),
        )
        try:
            def heartbeat() -> None:
                db.touch_serp_job(job_id)
                db.touch_serp_worker(worker_id)

            result = run_serp_direct(payload, heartbeat=heartbeat)
            db.complete_serp_job(job_id, result)
            logger.info(
                "Host worker completed SERP job id=%s source_nm_id=%s status=%s completed=%s/%s",
                job_id,
                payload.get("source_nm_id"),
                result.get("status"),
                result.get("completed_runs"),
                result.get("planned_runs"),
            )
        except Exception as exc:
            logger.exception("Host worker failed SERP job id=%s", job_id)
            result = {
                "batch_id": payload.get("batch_id"),
                "source_nm_id": payload.get("source_nm_id"),
                "status": "failed",
                "error": str(exc),
                "planned_runs": len(payload.get("query_specs") or []),
                "completed_runs": 0,
            }
            db.fail_serp_job(job_id, str(exc), result)
        return True

    if serp_only:
        return False

    job = db.claim_next_competitor_job(
        worker_id=worker_id,
        stale_after_seconds=Config.WB_PRICE_AI_HOST_RUNNER_STALE_SEC,
    )
    if not job:
        return False
    job_id = int(job["id"])
    payload = job.get("payload_json") or {}
    logger.info(
        "Host worker claimed competitor job id=%s source_nm_id=%s run_date=%s attempt=%s",
        job_id,
        payload.get("source_nm_id"),
        payload.get("run_date"),
        job.get("attempts"),
    )
    try:
        db.touch_competitor_job(job_id)
        result = _run_direct(payload)
        db.complete_competitor_job(job_id, result)
        logger.info(
            "Host worker completed competitor job id=%s source_nm_id=%s status=%s rows_written=%s",
            job_id,
            payload.get("source_nm_id"),
            result.get("raw_status"),
            result.get("raw_rows_written"),
        )
    except Exception as exc:
        logger.exception("Host worker failed competitor job id=%s", job_id)
        db.fail_competitor_job(
            job_id,
            str(exc),
            {
                **payload,
                "raw_status": "failed",
                "raw_error": str(exc),
                "raw_rows_written": 0,
                "raw_unique_competitors": 0,
                "raw_stats": {},
            },
        )
    return True


def run_worker(
    once: bool = False,
    poll_interval: Optional[float] = None,
    *,
    serp_only: bool = False,
) -> int:
    Config.validate_db()
    Config.validate_host_browser_runtime()
    interval = poll_interval if poll_interval is not None else Config.WB_PRICE_AI_HOST_RUNNER_POLL_INTERVAL_SEC
    db = WBPriceAIAnalysisDatabase()
    db.connect()
    try:
        db.create_tables()
        db.touch_serp_worker(Config.WB_PRICE_AI_HOST_WORKER_ID)
        processed = 0
        while True:
            db.touch_serp_worker(Config.WB_PRICE_AI_HOST_WORKER_ID)
            handled = process_one_job(
                db,
                Config.WB_PRICE_AI_HOST_WORKER_ID,
                serp_only=serp_only,
            )
            if handled:
                processed += 1
                if once:
                    return processed
                continue
            if once:
                return processed
            time.sleep(max(interval, 1.0))
    finally:
        if db.cursor:
            db.touch_serp_worker(Config.WB_PRICE_AI_HOST_WORKER_ID, status="stopped")
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run host-side worker for wb_price_ai_analysis competitor jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one queued competitor job and exit")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Seconds to sleep between queue polls in daemon mode",
    )
    parser.add_argument(
        "--serp-only",
        action="store_true",
        help="Process only canonical SERP jobs; leave the legacy competitor queue untouched",
    )
    args = parser.parse_args()
    processed = run_worker(
        once=args.once,
        poll_interval=args.poll_interval,
        serp_only=args.serp_only,
    )
    logger.info("Host worker finished, processed jobs: %s", processed)


if __name__ == "__main__":
    main()
