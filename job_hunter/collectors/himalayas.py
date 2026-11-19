"""
himalayas.py — Collector for Himalayas.app.

Uses the official free public JSON API:
  https://himalayas.app/jobs/api/search

No API key required. Optional key (HIMALAYAS_API_KEY) raises rate limit
to 60 req/min personal allowance.

Field names verified against live API response November 2026.
Docs: https://himalayas.app/api
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import config
from job_hunter.collectors.base import BaseCollector, JobListing

logger = logging.getLogger(__name__)

SEARCH_URL = "https://himalayas.app/jobs/api/search"

# Expanded queries covering all fresher/intern/junior variants
ROLE_QUERIES = [
    # Data
    "data analyst",
    "junior data analyst",
    "analytics intern",
    "data engineer",
    "etl developer",
    # AI / ML
    "machine learning engineer",
    "ai engineer",
    "computer vision",
    "ml intern",
    # Python / Backend
    "python developer",
    "backend engineer",
    "junior software engineer",
    "software developer intern",
    # General
    "graduate engineer",
    "associate engineer",
]


def _parse_date(val: Any) -> Optional[datetime]:
    """Try Unix timestamp (int/str), ISO 8601, then RFC 822; return UTC-aware datetime or None."""
    if not val:
        return None
    s = str(val).strip()

    # Unix timestamp (Himalayas returns pubDate as a plain integer string)
    if s.isdigit() or (s.lstrip('-').isdigit()):
        try:
            ts = int(s)
            if 1_000_000_000 < ts < 9_999_999_999:  # plausible unix range
                return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            pass

    # ISO 8601
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    # RFC 822
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass

    return None


class HimalayasCollector(BaseCollector):
    source_name = "himalayas"
    unofficial = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._headers: dict[str, str] = {"Accept": "application/json"}
        if config.HIMALAYAS_API_KEY:
            self._headers["Authorization"] = f"Bearer {config.HIMALAYAS_API_KEY}"

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=False,
    )
    def _fetch_search(self, query: str, page: int = 1) -> dict:
        params = {"q": query, "page": page, "limit": 20}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(SEARCH_URL, params=params, headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    def _parse_job(self, raw: dict) -> Optional[JobListing]:
        try:
            # --- URL: try multiple field names from live API ---
            url = (
                raw.get("applicationLink")
                or raw.get("applyUrl")
                or raw.get("url")
                or raw.get("link")
                or raw.get("jobUrl")
                or ""
            )
            if not url:
                return None

            # --- Title ---
            title = (
                raw.get("title")
                or raw.get("jobTitle")
                or ""
            ).strip()
            if not title:
                return None

            # --- Company ---
            company = ""
            if isinstance(raw.get("company"), dict):
                company = raw["company"].get("name", "")
            if not company:
                company = raw.get("companyName") or raw.get("company") or "Unknown"
            if isinstance(company, dict):
                company = company.get("name", "Unknown")
            company = str(company).strip() or "Unknown"

            # --- Date: try all plausible field names ---
            posted_at = None
            for key in ("pubDate", "publishedAt", "createdAt", "updatedAt",
                        "postedAt", "posted_at", "datePosted", "created"):
                posted_at = _parse_date(raw.get(key))
                if posted_at:
                    break

            # --- Location ---
            location_restrictions: list = raw.get("locationRestrictions") or []
            if isinstance(location_restrictions, list) and location_restrictions:
                location = ", ".join(str(x) for x in location_restrictions)
            else:
                # Try other location fields
                location = (
                    raw.get("location")
                    or raw.get("locationName")
                    or "Remote (Worldwide)"
                )
                if isinstance(location, dict):
                    location = location.get("name", "Remote (Worldwide)")
            remote = True  # Himalayas is a remote job board

            # --- Salary ---
            salary: Optional[str] = None
            min_s = raw.get("minSalary") or raw.get("salaryMin")
            max_s = raw.get("maxSalary") or raw.get("salaryMax")
            if min_s and max_s:
                currency = raw.get("currency") or raw.get("salaryCurrency") or "USD"
                try:
                    salary = f"{currency} {int(float(min_s)):,} – {int(float(max_s)):,}"
                except (ValueError, TypeError):
                    pass

            # --- Description ---
            description = (
                raw.get("description")
                or raw.get("content")
                or raw.get("summary")
                or ""
            )
            if isinstance(description, dict):
                description = description.get("text") or description.get("html") or ""
            description = str(description)[:2000]

            # --- Experience level ---
            exp_level = (
                raw.get("seniority")
                or raw.get("experienceLevel")
                or raw.get("level")
                or None
            )

            return JobListing(
                title=title,
                company=company,
                source=self.source_name,
                url=url,
                posted_at=posted_at,
                location=str(location),
                remote=remote,
                salary=salary,
                description=description,
                experience_level=str(exp_level) if exp_level else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Himalayas: failed to parse job '%s': %s", raw.get("title", "?"), exc)
            return None

    def collect(self) -> list[JobListing]:
        jobs: list[JobListing] = []
        seen_urls: set[str] = set()

        for query in ROLE_QUERIES:
            try:
                data = self._fetch_search(query, page=1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Himalayas: search '%s' failed: %s", query, exc)
                continue

            raw_jobs = data.get("jobs") or data.get("results") or []
            if not isinstance(raw_jobs, list):
                logger.warning("Himalayas: unexpected response shape for '%s': %s", query, type(raw_jobs))
                continue

            count_before = len(jobs)
            for raw in raw_jobs:
                job = self._parse_job(raw)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

            logger.info(
                "Himalayas '%s': %d raw → %d new (total %d)",
                query, len(raw_jobs), len(jobs) - count_before, len(jobs),
            )

        logger.info("Himalayas total collected: %d", len(jobs))
        return jobs
