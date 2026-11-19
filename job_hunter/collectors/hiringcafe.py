"""
hiringcafe.py — Collector for HiringCafe (hiring.cafe).

⚠️  WARNING: This collector uses an UNOFFICIAL, UNDOCUMENTED internal API
endpoint reverse-engineered from the site's browser requests.  It may
break without notice.  It is provided on a best-effort basis.  If it
fails, the system logs a clear error and continues with other sources.

The endpoint was verified functional as of November 2026 via the open-
source reference at: https://github.com/umur957/hiring-cafe-job-scraper

No login or API key is required.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from job_hunter.collectors.base import BaseCollector, JobListing

logger = logging.getLogger(__name__)

# Unofficial internal search endpoint (reverse-engineered from browser)
SEARCH_URL = "https://hiring.cafe/api/search"

# Browser-like headers to reduce block probability
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://hiring.cafe",
    "Referer": "https://hiring.cafe/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

ROLE_QUERIES = [
    "data analyst",
    "data engineer",
    "machine learning engineer",
    "python developer",
    "backend engineer",
]


class HiringCafeCollector(BaseCollector):
    source_name = "hiringcafe"
    unofficial = True  # prominently flagged

    # ------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        reraise=False,
    )
    def _post_search(self, query: str, page: int = 1) -> dict:
        payload = {
            "query": query,
            "search_state": {
                "workplace_types": ["Remote"],
                "commitment_types": [
                    "Full Time", "Part Time", "Contract", "Internship"
                ],
                "seniority_levels": ["No Experience Required", "Entry Level"],
                "posted_at": "last_7_days",
                "page": page,
                "page_size": 50,
            },
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(SEARCH_URL, json=payload, headers=HEADERS)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_date(raw: Any) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None

    # ------------------------------------------------------------------
    def _parse_job(self, raw: dict) -> JobListing | None:
        try:
            url = raw.get("apply_url") or raw.get("url", "")
            if not url:
                return None

            posted_at = self._parse_date(raw.get("posted_at") or raw.get("created_at"))
            if posted_at and posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)

            salary: str | None = None
            if raw.get("salary_min") and raw.get("salary_max"):
                curr = raw.get("salary_currency", "USD")
                salary = f"{curr} {raw['salary_min']:,} – {raw['salary_max']:,}"

            location = raw.get("location") or "Remote"
            remote = "remote" in location.lower() or raw.get("workplace_type", "").lower() == "remote"

            return JobListing(
                title=(raw.get("title") or "").strip(),
                company=(raw.get("source") or raw.get("company", "")).strip(),
                source="hiringcafe",
                url=url,
                posted_at=posted_at,
                location=location,
                remote=remote,
                salary=salary,
                description=(raw.get("description_clean") or raw.get("description_raw", ""))[:2000],
                experience_level=raw.get("seniority_level"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("HiringCafe: failed to parse job: %s", exc)
            return None

    # ------------------------------------------------------------------
    def collect(self) -> list[JobListing]:
        logger.warning(
            "HiringCafe collector uses an UNOFFICIAL API endpoint that may break "
            "without notice. Treat results as best-effort."
        )
        jobs: list[JobListing] = []
        seen_urls: set[str] = set()

        for query in ROLE_QUERIES:
            try:
                data = self._post_search(query, page=1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("HiringCafe: search '%s' failed: %s", query, exc)
                continue

            raw_jobs = data.get("jobs") or data.get("results") or []
            if not isinstance(raw_jobs, list):
                logger.warning("HiringCafe: unexpected response shape for '%s'", query)
                continue

            for raw in raw_jobs:
                job = self._parse_job(raw)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

            logger.info(
                "HiringCafe '%s': %d jobs (total so far: %d)",
                query, len(raw_jobs), len(jobs),
            )
            time.sleep(1)  # polite delay between queries

        logger.info("HiringCafe total collected: %d", len(jobs))
        return jobs
