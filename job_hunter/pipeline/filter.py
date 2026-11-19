"""
filter.py — Filter jobs by freshness, role relevance, India accessibility,
            and experience level.

Filtering rules (all must pass):
1. posted_at is within MAX_JOB_AGE_HOURS hours.
2. Title or description matches at least one TARGET_ROLE keyword.
3. Location is accessible from India (remote/worldwide/Indian city).
4. HARD GATE: Job must NOT require 2+ years experience.
   Jobs that explicitly require senior/mid/2+ years are rejected.
   Jobs with no experience mention are ALLOWED (assumed open to freshers).
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

# ── Compiled role / location patterns ────────────────────────────────────────
_ROLE_PATTERN = re.compile(
    "|".join(re.escape(r) for r in config.TARGET_ROLES),
    re.IGNORECASE,
)
_LOCATION_PATTERN = re.compile(
    "|".join(re.escape(loc) for loc in config.TARGET_LOCATIONS),
    re.IGNORECASE,
)

# ── Fresher / entry-level POSITIVE signals ───────────────────────────────────
_FRESHER_POSITIVE = re.compile(
    r"\b(fresher|fresh graduate|entry.?level|entry level|0.?1 year|"
    r"0 to 1|no experience|internship|intern|junior|associate|"
    r"graduate|new grad|2027|2026|recent graduate|campus hire|"
    r"trainee|apprentice)\b",
    re.IGNORECASE,
)

# ── Senior / experienced NEGATIVE signals — HARD REJECT ─────────────────────
# Only rejects when explicit years (2+) or senior titles are stated.
_SENIOR_PATTERN = re.compile(
    r"\b("
    r"[2-9]\+?\s*years?\s*(of\s*)?(experience|exp)|"
    r"[2-9]\+?\s*yrs?\s*(of\s*)?(experience|exp)|"
    r"minimum [2-9] years|at least [2-9] years|"
    r"senior\s+(engineer|developer|analyst|scientist|architect|data|ml|ai|backend|frontend)|"
    r"lead\s+(engineer|developer|analyst|backend|frontend|data|ml)|"
    r"staff\s+engineer|principal\s+engineer|"
    r"[5-9]\+?\s*years|10\+?\s*years"
    r")\b",
    re.IGNORECASE,
)


def _is_india_accessible(job: JobListing) -> bool:
    combined = (job.location or "").lower() + " " + (job.description or "").lower()
    if _LOCATION_PATTERN.search(combined):
        return True
    if job.remote:
        return True
    return False


def _matches_role(job: JobListing) -> bool:
    combined = (job.title or "") + " " + (job.description or "")
    return bool(_ROLE_PATTERN.search(combined))


def _is_too_senior(job: JobListing) -> bool:
    """
    Hard reject if the job EXPLICITLY requires 2+ years experience or
    is a senior/lead/staff/principal title.

    Jobs with NO experience mention are NOT rejected — they're assumed
    open to freshers.
    """
    combined = (job.title or "") + " " + (job.description or "") + " " + (job.experience_level or "")
    return bool(_SENIOR_PATTERN.search(combined))


def _is_fresher_role(job: JobListing) -> bool:
    """True if job has explicit fresher/entry-level/intern signals."""
    combined = (job.title or "") + " " + (job.description or "") + " " + (job.experience_level or "")
    return bool(_FRESHER_POSITIVE.search(combined))


def filter_jobs(jobs: Sequence[JobListing]) -> list[JobListing]:
    """Apply all filters; return jobs that pass."""
    passed: list[JobListing] = []
    skipped_age = 0
    skipped_role = 0
    skipped_location = 0
    skipped_senior = 0

    for job in jobs:
        # Gate 1: freshness
        if not job.is_recent(config.MAX_JOB_AGE_HOURS):
            skipped_age += 1
            continue

        # Gate 2: role match
        if not _matches_role(job):
            skipped_role += 1
            continue

        # Gate 3: India / remote accessible
        if not _is_india_accessible(job):
            skipped_location += 1
            continue

        # Gate 4 (NEW HARD GATE): reject explicitly senior roles
        if _is_too_senior(job):
            skipped_senior += 1
            continue

        # Annotate fresher signal for ranker (boosts score)
        if _is_fresher_role(job):
            job.description = (job.description or "") + "\n[entry-level-signal]"

        passed.append(job)

    logger.info(
        "Filter: %d passed | %d skipped (age) | %d skipped (role) | "
        "%d skipped (location) | %d skipped (too senior)",
        len(passed), skipped_age, skipped_role, skipped_location, skipped_senior,
    )
    return passed
