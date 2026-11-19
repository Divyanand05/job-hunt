"""
engine.py — Application Engine orchestrator.

Extends the existing job-hunter pipeline with application tracking.
Discovers → Scores → Prepares → Routes (manual queue or future auto-submit).

SUBMISSION POLICY: Default is DENY.
No adapter currently has can_submit=True.
Submission requires: adapter.can_submit + user env var + no unresolved questions.
"""
from __future__ import annotations

import logging
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

from job_hunter.collectors.base import JobListing
from job_hunter.pipeline.ranker import RankedJob, rank_jobs
from job_hunter.pipeline import normalize, filter_jobs
from job_hunter.pipeline.deduplicator import Deduplicator
from job_hunter.collectors import (
    HimalayasCollector,
    WeWorkRemotelyCollector,
    YCombinatorCollector,
    HiringCafeCollector,
)

from apply_agent.models import (
    ApplicationRecord,
    ApplicationStatus,
    AuditEvent,
    CANDIDATE_PROFILE,
)
from apply_agent.store import ApplicationStore
from apply_agent.adapters.manual import ManualQueueAdapter
from apply_agent.screener import generate_answers

logger = logging.getLogger(__name__)

# Minimum Gemini score to consider a job
MIN_SCORE: int = int(os.getenv("MIN_SCORE", "80"))


# ---------------------------------------------------------------------------
# Unsupported sources registry (displayed in health report)
# ---------------------------------------------------------------------------
UNSUPPORTED_SOURCES = [
    {"source": "linkedin",          "reason": "No public job search API — partner-gated only."},
    {"source": "indeed",            "reason": "Publisher-only APIs — no public read access."},
    {"source": "ziprecruiter",      "reason": "ZipSearch API shut down March 2025."},
    {"source": "wellfound",         "reason": "No public API or RSS feed."},
    {"source": "welcometothejungle","reason": "No public API or RSS feed."},
]


# ---------------------------------------------------------------------------
def run_discovery(dry_run: bool = False) -> tuple[list[JobListing], list[dict]]:
    """Run all collectors and return (jobs, health_report)."""
    collectors = [
        HimalayasCollector(),
        WeWorkRemotelyCollector(),
        YCombinatorCollector(),
        HiringCafeCollector(),
    ]

    all_jobs: list[JobListing] = []
    health: list[dict] = []

    for collector in collectors:
        logger.info("Collecting: %s", collector.source_name)
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
def _ranked_to_record(ranked: RankedJob, adapter_name: str = "manual") -> ApplicationRecord:
    """Convert a RankedJob into a new ApplicationRecord."""
    job = ranked.job
    return ApplicationRecord(
        fingerprint=job.fingerprint(),
        job_title=job.title,
        company=job.company,
        source=job.source,
        apply_url=job.url,
        score=ranked.score,
        resume_used=ranked.resume_used,
        status=ApplicationStatus.SHORTLISTED,
        cover_note=ranked.cover_note,
        adapter=adapter_name,
        job_location=job.location,
        job_salary=job.salary,
        posted_at=job.posted_at,
        match_reasons=ranked.match_reasons,
        missing_skills=ranked.missing_skills,
    )


# ---------------------------------------------------------------------------
def run_pipeline(
    store: ApplicationStore,
    dedup_db: Path,
    dry_run: bool = False,
    min_score: int = MIN_SCORE,
) -> dict:
    """
    Full discovery → score → prepare → route pipeline.

    Returns a summary dict with counts and health report.
    """
    start = datetime.now(timezone.utc)
    adapter = ManualQueueAdapter()

    # 1. Discover
    raw_jobs, health = run_discovery(dry_run=dry_run)
    logger.info("Discovered %d raw jobs", len(raw_jobs))

    # 2. Normalize
    normalised = normalize(raw_jobs)

    # 3. Dedup (seen_jobs.db — existing pipeline)
    with Deduplicator(dedup_db, dry_run=dry_run) as dedup:
        new_jobs = dedup.filter_new(normalised)
        logger.info("After seen_jobs dedup: %d new", len(new_jobs))

        # 4. Filter (freshness + role + location)
        filtered = filter_jobs(new_jobs)
        logger.info("After filter: %d jobs", len(filtered))

        # 5. Skip jobs already in apply_agent.db
        fresh = [j for j in filtered if not store.exists(j.fingerprint())]
        logger.info("After apply_agent dedup: %d fresh jobs", len(fresh))

        if not fresh:
            dedup.mark_seen([])
            summary = {
                "discovered": len(raw_jobs), "filtered": len(filtered),
                "shortlisted": 0, "prepared": 0,
                "pending_review": store.counts_by_status().get("pending_review", 0),
                "submitted": store.counts_by_status().get("submitted", 0),
                "health": health, "elapsed_seconds": 0,
            }
            return summary

        # 6. Split into primary pool (≤24h) and fallback pool (24–72h)
        primary = [j for j in fresh if j.is_recent(config.MAX_JOB_AGE_HOURS)]
        fallback = [j for j in fresh if not j.is_recent(config.MAX_JOB_AGE_HOURS)]
        logger.info("Primary pool (≤24h): %d | Fallback pool (24–72h): %d",
                    len(primary), len(fallback))

        # 7. Rank primary + fallback together (Gemini call)
        all_to_rank = primary + fallback
        ranked_all = rank_jobs(all_to_rank, top_n=len(all_to_rank)) if all_to_rank else []

        # 8. Apply tier-appropriate score thresholds
        shortlisted = []
        for r in ranked_all:
            is_fallback = r.job in fallback
            threshold = getattr(config, "FALLBACK_MIN_SCORE", 82) if is_fallback else min_score
            if r.score >= threshold:
                shortlisted.append(r)

        # Also force REVIEW_REQUIRED into pending regardless of score when uncertainty=high
        for r in ranked_all:
            if r not in shortlisted and getattr(r, "uncertainty", "low") == "high" and r.score >= 50:
                r.recommendation = "review"
                shortlisted.append(r)

        logger.info(
            "Shortlisted %d / %d ranked jobs (primary threshold=%d, fallback threshold=%d)",
            len(shortlisted), len(ranked_all), min_score,
            getattr(config, "FALLBACK_MIN_SCORE", 82),
        )

        # 8. Prepare each shortlisted job
        prepared_records: list[ApplicationRecord] = []
        for ranked in shortlisted:
            record = _ranked_to_record(ranked, adapter_name=adapter.name)

            # Generate screening answers
            if ranked.job.description:
                from job_hunter.pipeline.resume_selector import select_resume
                resume_text, _ = select_resume(ranked.job.title, ranked.job.description)
                answers = generate_answers(
                    ranked.job.title,
                    ranked.job.company,
                    ranked.job.description,
                    resume_text,
                )
                record.answers = answers

            if record.has_unresolved():
                record.flags.append("has_manual_review_items")

            # 9. Route through adapter (always → manual queue)
            record, events = adapter.prepare(record)

            # 10. Persist
            store.upsert(record, events)
            prepared_records.append(record)
            logger.info(
                "Prepared: [%s] %s @ %s (score=%d, unresolved=%s)",
                record.status.value,
                record.job_title,
                record.company,
                record.score,
                record.has_unresolved(),
            )

        # 11. Mark seen in dedup DB
        seen_jobs = [r.job for r in ranked_all]
        dedup.mark_seen(seen_jobs)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    counts = store.counts_by_status()

    summary = {
        "discovered": len(raw_jobs),
        "filtered": len(filtered),
        "shortlisted": len(shortlisted),
        "prepared": len(prepared_records),
        "pending_review": counts.get("pending_review", 0),
        "submitted": counts.get("submitted", 0),
        "health": health,
        "elapsed_seconds": elapsed,
    }
    logger.info(
        "Pipeline complete in %.1fs: %d discovered, %d shortlisted, %d prepared",
        elapsed, len(raw_jobs), len(shortlisted), len(prepared_records),
    )
    return summary
