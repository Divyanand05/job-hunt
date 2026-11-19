"""
filter.py — Eligibility-based job filter.

Three-tier eligibility:
  ELIGIBLE         — clearly suitable, proceed to Gemini scoring
  REVIEW_REQUIRED  — uncertain (unspecified experience, 24–72h age), include at higher score bar
  INELIGIBLE       — hard reject (explicit 2+ years, senior title, incompatible location)

Hard rejects never reach Gemini.
REVIEW_REQUIRED jobs reach Gemini but are flagged for manual review if score < PRIORITY_SCORE.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config
from job_hunter.collectors.base import JobListing

logger = logging.getLogger(__name__)


class Eligibility(str, Enum):
    ELIGIBLE         = "eligible"
    REVIEW_REQUIRED  = "review_required"
    INELIGIBLE       = "ineligible"


@dataclass
class FilteredJob:
    job: JobListing
    eligibility: Eligibility
    flags: list[str]          # human-readable reasons


# ── Role pattern — 30+ terms covering all fresher/intern/junior variants ─────
_ROLE_PATTERN = re.compile(
    r"\b("
    r"data analyst|junior data analyst|bi analyst|analytics intern|"
    r"data analytics|business analyst|analytics engineer|"
    r"data engineer|junior data engineer|etl developer|"
    r"data engineering intern|data pipeline|"
    r"ai engineer|ml engineer|machine learning engineer|"
    r"applied ai|computer vision|ml intern|ai intern|"
    r"python developer|python intern|software engineer|"
    r"backend developer|backend engineer|backend intern|"
    r"api developer|associate software engineer|"
    r"graduate engineer|software developer intern|"
    r"software engineer intern|junior software engineer|"
    r"junior developer|junior engineer|junior backend|"
    r"graduate trainee|engineer trainee|junior analyst|"
    r"data science|data scientist|analytics"
    r")\b",
    re.IGNORECASE,
)

# ── Location pattern ──────────────────────────────────────────────────────────
_LOCATION_PATTERN = re.compile(
    r"\b("
    r"remote|chennai|bengaluru|bangalore|hyderabad|india|"
    r"worldwide|anywhere|global|work from home|wfh|"
    r"india.?eligible|open to india|india.?based"
    r")\b",
    re.IGNORECASE,
)

# ── Explicit India-blocking patterns ─────────────────────────────────────────
_INDIA_BLOCK = re.compile(
    r"\b("
    r"must be (located|based|residing) in (the )?(us|uk|canada|australia|europe|eu)|"
    r"us (citizens?|residents?|only)|uk only|canada only|"
    r"must have (us|uk) work (authorization|authorisation|permit)|"
    r"no (visa|sponsorship) (available|provided)|"
    r"authorized to work in the (us|united states|uk|united kingdom)"
    r")\b",
    re.IGNORECASE,
)

# ── Fresher POSITIVE signals ──────────────────────────────────────────────────
_FRESHER_POSITIVE = re.compile(
    r"\b("
    r"fresher|fresh graduate|entry.?level|0.?1 year|0 to 1 year|"
    r"no experience required|no prior experience|no experience needed|"
    r"internship|intern|junior|associate|graduate|new grad|2027|2026|"
    r"recent graduate|campus hire|trainee|apprentice"
    r")\b",
    re.IGNORECASE,
)

# ── Hard-reject senior patterns ───────────────────────────────────────────────
_SENIOR_HARD = re.compile(
    r"\b("
    r"[2-9]\+?\s*years?\s*(of\s*)?(experience|exp)\b|"
    r"[2-9]\+?\s*yrs?\s*(of\s*)?(experience|exp)\b|"
    r"minimum\s+[2-9]\s+years|at\s+least\s+[2-9]\s+years|"
    r"[2-9]\+\s*yr\b|"
    r"senior\s+(engineer|developer|analyst|scientist|architect|data|ml|ai|backend|frontend|software)|"
    r"lead\s+(engineer|developer|analyst|backend|frontend|data|ml|software)|"
    r"staff\s+engineer|principal\s+engineer|principal\s+architect|"
    r"[5-9]\+?\s*years|10\+?\s*years|"
    r"director\s+of\s+engineering|vp\s+of\s+engineering|head\s+of\s+engineering|"
    r"engineering\s+manager"
    r")\b",
    re.IGNORECASE,
)

# ── 1-year requirement: eligible but flag for review ─────────────────────────
_ONE_YEAR = re.compile(
    r"\b(1\+?\s*year|one year|12\s*months)\s*(of\s*)?(experience|exp)\b",
    re.IGNORECASE,
)


def _check_location(job: JobListing) -> Eligibility:
    combined = (job.location or "") + " " + (job.description or "")
    # Explicit India block → INELIGIBLE
    if _INDIA_BLOCK.search(combined):
        return Eligibility.INELIGIBLE
    # India / remote accessible → ELIGIBLE
    if _LOCATION_PATTERN.search(combined):
        return Eligibility.ELIGIBLE
    # Remote flag but no other location restriction → ELIGIBLE (worldwide)
    if job.remote:
        return Eligibility.ELIGIBLE
    # Has a non-remote location not in our list → check description more carefully
    loc = (job.location or "").strip()
    if loc and not _LOCATION_PATTERN.search(loc):
        return Eligibility.REVIEW_REQUIRED
    return Eligibility.REVIEW_REQUIRED


def _check_experience(job: JobListing) -> tuple[Eligibility, list[str]]:
    combined = (job.title or "") + " " + (job.description or "") + " " + (job.experience_level or "")
    flags = []

    # Hard reject: 2+ years or senior title
    if _SENIOR_HARD.search(combined):
        return Eligibility.INELIGIBLE, ["requires_2plus_years_or_senior_title"]

    # Positive: explicit fresher/intern signals
    if _FRESHER_POSITIVE.search(combined):
        return Eligibility.ELIGIBLE, ["explicit_fresher_signal"]

    # 1-year requirement: allow but flag
    if _ONE_YEAR.search(combined):
        flags.append("requires_1_year_experience")
        return Eligibility.REVIEW_REQUIRED, flags

    # No experience mentioned: neither confirm nor deny → REVIEW_REQUIRED
    # (Do NOT assume open to freshers — this is W7 fix)
    flags.append("experience_requirement_unspecified")
    return Eligibility.REVIEW_REQUIRED, flags


def assess_eligibility(job: JobListing, age_hours: float) -> FilteredJob:
    """
    Assess a single job's eligibility.

    Returns a FilteredJob with ELIGIBLE, REVIEW_REQUIRED, or INELIGIBLE.
    """
    flags: list[str] = []

    # --- Age check ---
    if age_hours > config.FALLBACK_AGE_HOURS:
        return FilteredJob(job, Eligibility.INELIGIBLE, ["too_old"])

    if age_hours > config.MAX_JOB_AGE_HOURS:
        flags.append("fallback_pool_24_72h")
        # Will be treated at higher score bar in engine

    # --- Role match ---
    combined = (job.title or "") + " " + (job.description or "")
    if not _ROLE_PATTERN.search(combined):
        return FilteredJob(job, Eligibility.INELIGIBLE, ["role_mismatch"])

    # --- Location ---
    loc_eligibility = _check_location(job)
    if loc_eligibility == Eligibility.INELIGIBLE:
        return FilteredJob(job, Eligibility.INELIGIBLE, ["india_ineligible"])
    if loc_eligibility == Eligibility.REVIEW_REQUIRED:
        flags.append("location_unspecified")

    # --- Experience ---
    exp_eligibility, exp_flags = _check_experience(job)
    flags.extend(exp_flags)
    if exp_eligibility == Eligibility.INELIGIBLE:
        return FilteredJob(job, Eligibility.INELIGIBLE, exp_flags)

    # --- Determine overall eligibility ---
    # Only REVIEW_REQUIRED flags (not positive ones) trigger review
    review_flags = [f for f in flags if f not in ("explicit_fresher_signal",)]
    if review_flags:
        overall = Eligibility.REVIEW_REQUIRED
    else:
        overall = Eligibility.ELIGIBLE

    # Annotate fresher signal for ranker
    if "explicit_fresher_signal" in flags or exp_eligibility == Eligibility.ELIGIBLE:
        job.description = (job.description or "") + "\n[entry-level-signal]"

    return FilteredJob(job, overall, flags)


def filter_jobs(jobs: Sequence[JobListing]) -> list[JobListing]:
    """
    Legacy interface: return all ELIGIBLE + REVIEW_REQUIRED jobs as a flat list.

    INELIGIBLE jobs are dropped. The job's description is annotated with
    eligibility flags for the ranker.
    """
    passed: list[JobListing] = []
    counts = {e: 0 for e in Eligibility}

    for job in jobs:
        age = job.age_hours() if job.posted_at else float("inf")
        result = assess_eligibility(job, age if age is not None else float("inf"))
        counts[result.eligibility] += 1

        if result.eligibility == Eligibility.INELIGIBLE:
            continue

        # Annotate flags onto description so ranker can see them
        if result.flags:
            flag_str = " ".join(f"[{f}]" for f in result.flags)
            job.description = (job.description or "") + "\n" + flag_str

        passed.append(job)

    logger.info(
        "Filter: %d eligible | %d review_required | %d ineligible",
        counts[Eligibility.ELIGIBLE],
        counts[Eligibility.REVIEW_REQUIRED],
        counts[Eligibility.INELIGIBLE],
    )
    return passed
