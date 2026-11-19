"""
weworkremotely.py — Collector for We Work Remotely.

Uses the official public RSS feeds (no authentication, no API key):
  https://weworkremotely.com/remote-jobs.rss          (all jobs)
  https://weworkremotely.com/categories/remote-programming-jobs.rss
  https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss
  https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss
  https://weworkremotely.com/categories/remote-all-other-remote-jobs.rss

Source: https://weworkremotely.com/remote-job-rss-feed
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from job_hunter.collectors.base import BaseCollector, JobListing

logger = logging.getLogger(__name__)

RSS_FEEDS = {
    "programming": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "back-end": "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "devops": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "other": "https://weworkremotely.com/categories/all-other-remote-jobs.rss",
}


class WeWorkRemotelyCollector(BaseCollector):
    source_name = "weworkremotely"
    unofficial = False

    # ------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=False,
    )
    def _fetch_feed(self, url: str) -> bytes:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.content

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_location(entry: Any) -> tuple[str, bool]:
        """Extract location and remote flag from WWR entry summary."""
        summary = getattr(entry, "summary", "") or ""
        # WWR encodes location in region tags like: <span class="region">Worldwide</span>
        region_match = re.search(r'class="region"[^>]*>([^<]+)<', summary)
        if region_match:
            region = region_match.group(1).strip()
            remote = True  # all WWR jobs are remote
            return region, remote
        return "Remote", True

    # ------------------------------------------------------------------
    def _parse_entry(self, entry: Any, category: str) -> JobListing | None:
        try:
            url = entry.get("link", "")
            if not url:
                return None

            title = entry.get("title", "").strip()
            # WWR title format: "Company: Job Title"
            if ": " in title:
                company, job_title = title.split(": ", 1)
            else:
                company = ""
                job_title = title

            # Parse posting date
            posted_at: datetime | None = None
            published = entry.get("published") or entry.get("updated")
            if published:
                try:
                    posted_at = parsedate_to_datetime(published)
                except Exception:  # noqa: BLE001
                    try:
                        posted_at = datetime.fromisoformat(
                            published.replace("Z", "+00:00")
                        )
                    except Exception:  # noqa: BLE001
                        pass

            if posted_at and posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)

            location, remote = self._parse_location(entry)

            # Extract plain-text description from summary HTML
            summary = getattr(entry, "summary", "") or ""
            description = re.sub(r"<[^>]+>", " ", summary).strip()[:2000]

            return JobListing(
                title=job_title.strip(),
                company=company.strip(),
                source=self.source_name,
                url=url,
                posted_at=posted_at,
                location=location,
                remote=remote,
                description=description,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to parse WWR entry: %s", exc)
            return None

    # ------------------------------------------------------------------
    def collect(self) -> list[JobListing]:
        jobs: list[JobListing] = []
        seen_urls: set[str] = set()

        for category, feed_url in RSS_FEEDS.items():
            try:
                raw_bytes = self._fetch_feed(feed_url)
                feed = feedparser.parse(raw_bytes)
            except Exception as exc:  # noqa: BLE001
                logger.warning("WWR feed '%s' failed: %s", category, exc)
                continue

            entries = feed.get("entries", [])
            for entry in entries:
                job = self._parse_entry(entry, category)
                if job and job.url not in seen_urls:
                    seen_urls.add(job.url)
                    jobs.append(job)

            logger.info(
                "WWR '%s': fetched %d entries (total so far: %d)",
                category,
                len(entries),
                len(jobs),
            )

        logger.info("WeWorkRemotely total collected: %d", len(jobs))
        return jobs
