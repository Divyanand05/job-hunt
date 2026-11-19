"""
apply_main.py — Entry point for the AI Auto-Apply Agent.

Extends the existing main.py pipeline with:
  - Application tracking (apply_agent.db)
  - Screening answer generation
  - Manual review queue routing
  - Updated email notifications with queue summary

Usage:
  python apply_main.py              # normal run
  DRY_RUN=true python apply_main.py # no DB writes, no email

Scheduled via GitHub Actions 3x daily.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import config
from apply_agent.engine import run_pipeline
from apply_agent.store import ApplicationStore
from apply_agent.models import ApplicationStatus
from job_hunter.email_sender.gmail import send_email
from job_hunter.pipeline.ranker import RankedJob, rank_jobs
from job_hunter.collectors.base import JobListing

# ---------------------------------------------------------------------------
# Logging — UTF-8 safe (Windows compatible)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)
        )
    ],
)
logger = logging.getLogger("apply_main")

APPLY_DB_PATH = config.DATA_DIR / "apply_agent.db"


def _build_notification_ranked_jobs(store: ApplicationStore) -> list[RankedJob]:
    """
    Build RankedJob list from PENDING_REVIEW records for email notification.
    Uses up to MAX_JOBS_PER_EMAIL most recent un-notified jobs.
    """
    pending = store.pending_notification()
    top = pending[: config.MAX_JOBS_PER_EMAIL]

    ranked_jobs = []
    for record in top:
        job = JobListing(
            title=record.job_title,
            company=record.company,
            source=record.source,
            url=record.apply_url,
            posted_at=record.posted_at,
            location=record.job_location,
            salary=record.job_salary,
        )
        ranked = RankedJob(
            job=job,
            score=record.score,
            match_reasons=record.match_reasons,
            missing_skills=record.missing_skills,
            cover_note=record.cover_note,
            resume_used=record.resume_used,
        )
        ranked_jobs.append(ranked)
    return ranked_jobs


def main() -> None:
    start = datetime.now(timezone.utc)
    logger.info(
        "AI Auto-Apply Agent starting at %s (dry_run=%s)",
        start.isoformat(),
        config.DRY_RUN,
    )

    with ApplicationStore(APPLY_DB_PATH, dry_run=config.DRY_RUN) as store:
        # Run the full pipeline
        summary = run_pipeline(
            store=store,
            dedup_db=config.DB_PATH,
            dry_run=config.DRY_RUN,
            min_score=int(__import__("os").getenv("MIN_SCORE", "80")),
        )

        health = summary["health"]

        # Build notification email
        ranked_jobs = _build_notification_ranked_jobs(store)
        counts = store.counts_by_status()
        pending_count = counts.get("pending_review", 0)

        if ranked_jobs:
            subject = (
                f"[Job Agent] {len(ranked_jobs)} new match"
                f"{'es' if len(ranked_jobs) != 1 else ''}"
                f" | {pending_count} awaiting review"
                f" — {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}"
            )
            send_email(ranked_jobs, health, subject=subject, dry_run=config.DRY_RUN)

            # Mark notified
            if not config.DRY_RUN:
                for record in store.pending_notification()[: config.MAX_JOBS_PER_EMAIL]:
                    store.mark_notified(record.id)
        else:
            logger.info("No new matches to notify about this run.")

        # Print summary
        logger.info("=" * 60)
        logger.info("RUN SUMMARY")
        logger.info("=" * 60)
        logger.info("  Discovered:     %d", summary["discovered"])
        logger.info("  After filter:   %d", summary["filtered"])
        logger.info("  Shortlisted:    %d (score >= %s)", summary["shortlisted"], __import__("os").getenv("MIN_SCORE", "80"))
        logger.info("  Prepared:       %d", summary["prepared"])
        logger.info("  Pending review: %d", pending_count)
        logger.info("  Submitted:      %d", counts.get("submitted", 0))
        logger.info("  Total tracked:  %d", sum(counts.values()))
        logger.info("=" * 60)

        # Source health
        for h in health:
            status = h.get("status", "?")
            source = h.get("source", "?")
            if status == "ok":
                logger.info("  OK  %-24s %d jobs", source, h.get("jobs_fetched", 0))
            elif status == "unsupported":
                logger.warning("  --  %-24s UNSUPPORTED: %s", source, h.get("error", ""))
            else:
                logger.error("  ERR %-24s %s", source, h.get("error", ""))

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("Run completed in %.1f seconds", elapsed)


if __name__ == "__main__":
    main()
