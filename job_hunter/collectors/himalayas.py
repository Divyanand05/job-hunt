"""
himalayas.py — Collector for Himalayas.app.

Uses the official free public JSON API:
  https://himalayas.app/jobs/api/search

No API key required.  An optional key (HIMALAYAS_API_KEY) raises the rate
limit from shared to 60 req/min personal allowance.

Docs: https://himalayas.app/api
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

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
RSS_URL = "https://himalayas.app/jobs/rss"

# Keyword → Himalayas search query mapping
ROLE_QUERIES = [
    "data analyst",
    "data engineer",
    "machine learning engineer",
    "python developer",
    "backend engineer",
]

COUNTRY_CODES = ["IN"]  # India


class HimalayasCollector(BaseCollector):
    source_name = "himalayas"
    unofficial = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._headers: dict[str, str] = {"Accept": "application/json"}
        if config.HIMALAYAS_API_KEY:
            self._headers["Authorization"] = f"Bearer {config.HIMALAYAS_API_KEY}"

    # ------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=False,
    )
    def _fetch_search(self, query: str, page: int = 1) -> dict:
        # Search without country filter first (broader), then filter locally
        params = {
            "q": query,
            "page": page,
            "limit": 20,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(SEARCH_URL, params=params, headers=self._headers)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    def _parse_job(self, raw: dict) -> JobListing | None:
        try:
            url = raw.get("applicationLink") or raw.get("url") or raw.get("link", "")
            if not url:
                return None

            # Parse posted_at — Himalayas returns ISO or RFC822 strings
            posted_at: datetime | None = None
            for key in ("pubDate", "createdAt", "updatedAt"):
                val = raw.get(key)
                if val:
                    try:
                        # Try ISO 8601 first
                        posted_at = datetime.fromisoformat(
                            val.replace("Z", "+00:00")
                        )
                    except ValueError:
                        try:
                            posted_at = parsedate_to_datetime(val)
                        except Exception:  # noqa: BLE001
                            pass
                if posted_at:
                    break

            if posted_at and posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)

            # Location restrictions — empty means worldwide (India OK)
            location_restrictions: list[str] = raw.get("locationRestrictions", [])
            if location_restrictions:
                location = ", ".join(location_restrictions)
                # Accept if India is listed OR no restriction (worldwide)
                remote = True
            else:
                location = "Remote (Worldwide)"
                remote = True

            salary: str | None = None
            if raw.get("minSalary") and raw.get("maxSalary"):
                currency = raw.get("salaryCurrency", "USD")
                salary = f"{currency} {raw['minSalary']:,} – {raw['maxSalary']:,}"

            return JobListing(
                title=raw.get("title", "").strip(),
                company=raw.get("companyName", "").strip(),
                source=self.source_name,
                url=url,
                posted_at=posted_at,
                location=location,
                remote=remote,
                salary=salary,
                description=(raw.get("description") or raw.get("content", ""))[:2000],
                experience_level=raw.get("seniority"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to parse Himalayas job: %s — %s", raw.get("title"), exc)
            return None

    # ------------------------------------------------------------------
    def collect(self) -> list[JobListing]:
        jobs: list[JobListing] = []
        seen_urls: set[str] = set()

        for query in ROLE_QUERIES:
            try:
                data = self._fetch_search(query, page=1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Himalayas search failed for '%s': %s", query, exc)
                continue

            raw_jobs = data.get("jobs", [])
            if not isinstance(raw_jobs, list):
                logger.warning("Unexpected Himalayas response shape for query '%s'", query)
                continue

            for raw in raw_jobs:
                job = self._parse_job(raw)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

            logger.info(
                "Himalayas '%s': fetched %d jobs (total so far: %d)",
                query,
                len(raw_jobs),
                len(jobs),
            )

        logger.info("Himalayas total collected: %d", len(jobs))
        return jobs
