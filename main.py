"""
main.py — Orchestrator for the AI Job Hunter pipeline.

Usage:
  python main.py              # normal run
  DRY_RUN=true python main.py # collect & rank without sending email or writing DB

Pipeline:
  1. Collect jobs from each enabled source
  2. Normalise (reject jobs without verifiable dates)
  3. Deduplicate against previous runs
  4. Filter by freshness, role and India accessibility
  5. Rank top N via Gemini
  6. Send HTML email via Gmail SMTP
  7. Mark sent jobs as seen in SQLite

Sources that are unsupported or deprecated are clearly reported.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import config
from job_hunter.collectors import (
    HimalayasCollector,
    WeWorkRemotelyCollector,
    YCombinatorCollector,
    HiringCafeCollector,
)
from job_hunter.collectors.base import JobListing
from job_hunter.pipeline import normalize, filter_jobs, rank_jobs
from job_hunter.pipeline.deduplicator import Deduplicator
from job_hunter.email_sender import send_email

if TYPE_CHECKING:
    from job_hunter.pipeline.ranker import RankedJob

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(
        open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)
    )],
)
logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Unsupported sources — clearly documented
# ---------------------------------------------------------------------------
UNSUPPORTED_SOURCES = [
    {
        "source": "linkedin",
        "reason": "No public job search API. The Job Posting API requires approved partner access.",
    },
    {
        "source": "indeed",
        "reason": "Indeed's APIs are publisher-only (posting jobs, not reading them). No free public search API.",
    },
    {
        "source": "ziprecruiter",
        "reason": "ZipSearch public API was deprecated and shut down on 31 March 2025.",
    },
    {
        "source": "wellfound",
        "reason": "No public API or RSS feed. Access requires login or paid scraping tools.",
    },
    {
        "source": "welcometothejungle",
        "reason": "No public API or RSS feed. Only accessible via paid third-party actors.",
    },
]


# ---------------------------------------------------------------------------
def run_collectors() -> tuple[list[JobListing], list[dict]]:
    """Run all collectors and return (all_jobs, health_report)."""
    collectors = [
        HimalayasCollector(),
        WeWorkRemotelyCollector(),
        YCombinatorCollector(),
        HiringCafeCollector(),
    ]

    all_jobs: list[JobListing] = []
    health: list[dict] = []

    for collector in collectors:
        logger.info("Running collector: %s", collector.source_name)
        try:
            jobs = collector.collect()
            all_jobs.extend(jobs)
            health.append({
                "source": collector.source_name,
                "status": "ok",
                "jobs_fetched": len(jobs),
                "unofficial": collector.unofficial,
            })
        except Exception as exc:  # noqa: BLE001
            logger.error("Collector %s failed: %s", collector.source_name, exc)
            health.append({
                "source": collector.source_name,
                "status": "error",
                "error": str(exc),
                "jobs_fetched": 0,
                "unofficial": collector.unofficial,
            })

    # Append unsupported source notices
    for item in UNSUPPORTED_SOURCES:
        health.append({
            "source": item["source"],
            "status": "unsupported",
            "error": item["reason"],
            "jobs_fetched": 0,
            "unofficial": False,
        })

    return all_jobs, health


# ---------------------------------------------------------------------------
def print_health_report(health: list[dict]) -> None:
    logger.info("=" * 60)
    logger.info("SOURCE HEALTH REPORT")
    logger.info("=" * 60)
    for h in health:
        status = h.get("status", "unknown")
        source = h.get("source", "?")
        unofficial = " [UNOFFICIAL]" if h.get("unofficial") else ""
        if status == "ok":
            logger.info("  ✅ %-24s %d jobs fetched%s", source, h.get("jobs_fetched", 0), unofficial)
        elif status == "unsupported":
            logger.warning("  ⛔ %-24s UNSUPPORTED — %s", source, h.get("error", ""))
        else:
            logger.error("  ❌ %-24s ERROR — %s%s", source, h.get("error", ""), unofficial)
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
def main() -> None:
    start = datetime.now(timezone.utc)
    logger.info(
        "AI Job Hunter starting at %s (dry_run=%s)",
        start.isoformat(),
        config.DRY_RUN,
    )

    # 1. Collect
    raw_jobs, health = run_collectors()
    logger.info("Collected %d raw jobs from all sources", len(raw_jobs))

    # 2. Normalise
    normalised = normalize(raw_jobs)

    # 3. Deduplicate + filter
    with Deduplicator(config.DB_PATH, dry_run=config.DRY_RUN) as dedup:
        new_jobs = dedup.filter_new(normalised)
        logger.info("After dedup: %d new jobs", len(new_jobs))

        # 4. Filter by freshness, role, location
        filtered = filter_jobs(new_jobs)
        logger.info("After filter: %d jobs", len(filtered))

        if not filtered:
            logger.info("No new matching jobs this run. Email not sent.")
            print_health_report(health)
            return

        # 5. Rank
        top_jobs: list[RankedJob] = rank_jobs(filtered, top_n=config.MAX_JOBS_PER_EMAIL)

        # 6. Email
        send_email(top_jobs, health, dry_run=config.DRY_RUN)

        # 7. Mark seen (skipped in dry_run)
        dedup.mark_seen([r.job for r in top_jobs])

    print_health_report(health)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("Run completed in %.1f seconds", elapsed)


if __name__ == "__main__":
    main()
