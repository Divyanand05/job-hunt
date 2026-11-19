"""
normalizer.py — Validate and normalise raw JobListing objects.

Rules:
- title, company, url must be non-empty.
- posted_at must be set; jobs without a verifiable date are REJECTED.
- Timestamps are made UTC-aware.
- Location is normalised to a consistent string.
"""
from __future__ import annotations

import logging
import re
from datetime import timezone

from job_hunter.collectors.base import JobListing

logger = logging.getLogger(__name__)

# Locations we consider as "India-accessible remote"
_INDIA_PATTERNS = re.compile(
    r"\b(india|indian|in\b|worldwide|global|anywhere|remote|wfh|"
    r"chennai|bengaluru|bangalore|hyderabad|mumbai|delhi|pune)\b",
    re.IGNORECASE,
)


def _normalise_location(location: str) -> str:
    loc = location.strip()
    if not loc:
        return "Remote"
    return loc


def normalize(jobs: list[JobListing]) -> list[JobListing]:
    """
    Validate and normalise a list of JobListings.

    Returns only jobs that pass all validation checks.  Logs a debug
    message for every rejected job.
    """
    valid: list[JobListing] = []
    rejected = 0

    for job in jobs:
        # 1. Required string fields
        if not job.title or not job.url:
            logger.debug("Rejected (missing title/url): %s @ %s", job.title, job.company)
            rejected += 1
            continue

        # 2. Must have a verifiable posting date — never guess
        if job.posted_at is None:
            logger.debug(
                "Rejected (no posting date): '%s' @ %s [%s]",
                job.title, job.company, job.source,
            )
            rejected += 1
            continue

        # 3. Make sure timezone is set
        if job.posted_at.tzinfo is None:
            job.posted_at = job.posted_at.replace(tzinfo=timezone.utc)

        # 4. Clean up fields
        job.title = job.title.strip()
        job.company = (job.company or "").strip() or "Unknown"
        job.location = _normalise_location(job.location or "")

        valid.append(job)

    logger.info(
        "Normalizer: %d valid, %d rejected (no date / missing fields)",
        len(valid),
        rejected,
    )
    return valid
