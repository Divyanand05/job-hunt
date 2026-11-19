"""
filter.py — Filter jobs by freshness, role relevance and India accessibility.

Filtering rules (all must pass):
1. posted_at is within MAX_JOB_AGE_HOURS hours.
2. Title or description matches at least one TARGET_ROLE keyword.
3. Location is accessible from India (remote/worldwide/Indian city) — OR
   the job has no location restriction (assumed worldwide).
"""
from __future__ import annotations

import logging
import re
from typing import Sequence

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config
from job_hunter.collectors.base import JobListing

logger = logging.getLogger(__name__)

# Compiled patterns from config
_ROLE_PATTERN = re.compile(
    "|".join(re.escape(r) for r in config.TARGET_ROLES),
    re.IGNORECASE,
)
_LOCATION_PATTERN = re.compile(
    "|".join(re.escape(loc) for loc in config.TARGET_LOCATIONS),
    re.IGNORECASE,
)
_EXPERIENCE_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in config.EXPERIENCE_KEYWORDS),
    re.IGNORECASE,
)


def _is_india_accessible(job: JobListing) -> bool:
    """True if the job can be done from India."""
    combined = (job.location or "").lower() + " " + (job.description or "").lower()
    # Explicit India mention, remote, worldwide, or no restriction
    if _LOCATION_PATTERN.search(combined):
        return True
    # Jobs with no country restriction are open worldwide
    if job.remote:
        return True
    return False


def _matches_role(job: JobListing) -> bool:
    combined = (job.title or "") + " " + (job.description or "")
    return bool(_ROLE_PATTERN.search(combined))


def _is_entry_level(job: JobListing) -> bool:
    """True if the job appears to target freshers/entry-level.

    We do NOT reject jobs that lack experience keywords — many job
    descriptions simply don't mention seniority.  We use this as a
    ranking signal, not a hard filter.
    """
    combined = (
        (job.title or "")
        + " "
        + (job.description or "")
        + " "
        + (job.experience_level or "")
    )
    return bool(_EXPERIENCE_PATTERN.search(combined))


def filter_jobs(jobs: Sequence[JobListing]) -> list[JobListing]:
    """Apply all filters; return jobs that pass."""
    passed: list[JobListing] = []
    skipped_age = 0
    skipped_role = 0
    skipped_location = 0

    for job in jobs:
        if not job.is_recent(config.MAX_JOB_AGE_HOURS):
            skipped_age += 1
            continue
        if not _matches_role(job):
            skipped_role += 1
            continue
        if not _is_india_accessible(job):
            skipped_location += 1
            continue
        # Annotate entry-level flag on description for ranker context
        if _is_entry_level(job):
            job.description = (job.description or "") + "\n[entry-level-signal]"
        passed.append(job)

    logger.info(
        "Filter: %d passed | %d skipped (age) | %d skipped (role) | %d skipped (location)",
        len(passed), skipped_age, skipped_role, skipped_location,
    )
    return passed
