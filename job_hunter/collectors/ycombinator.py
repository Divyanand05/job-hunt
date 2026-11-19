"""
ycombinator.py — Collector for Y Combinator / Hacker News "Who is Hiring".

Uses the official HN Firebase API (no authentication, no API key):
  https://hacker-news.firebaseio.com/v0/

The monthly "Ask HN: Who is Hiring?" thread is posted by the account
`whoishiring`.  Each top-level comment is one company's job post.

Limitation: the thread is monthly, so within any given day most posts
will be older than 24 h.  We surface the thread's posts from the CURRENT
month only, and each job's `posted_at` is the comment's creation time
(a real UNIX timestamp from Firebase), so the 24-h filter will naturally
keep only comments posted that day.

Docs: https://github.com/HackerNews/API
"""
from __future__ import annotations

import logging
import re
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

HN_BASE = "https://hacker-news.firebaseio.com/v0"
WHOISHIRING_USER = "whoishiring"

# Max top-level comments to parse per thread (rate-limit friendly)
MAX_COMMENTS = 100
# Delay between individual item fetches to stay polite
ITEM_FETCH_DELAY = 0.05  # seconds


class YCombinatorCollector(BaseCollector):
    source_name = "ycombinator"
    unofficial = False

    # ------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=False,
    )
    def _get(self, url: str) -> Any:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    def _latest_hiring_thread_id(self) -> int | None:
        """Return the item ID of the most recent 'Who is Hiring' story."""
        try:
            submitted = self._get(f"{HN_BASE}/user/{WHOISHIRING_USER}.json")
            if not submitted or "submitted" not in submitted:
                return None
            # Items are in reverse-chronological order; grab the most recent
            for item_id in submitted["submitted"][:5]:
                item = self._get(f"{HN_BASE}/item/{item_id}.json")
                if item and "who is hiring" in (item.get("title") or "").lower():
                    return item_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to find HN hiring thread: %s", exc)
        return None

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_comment(text: str) -> dict[str, Any]:
        """
        Parse the first line of a typical HN hiring comment:
          Company | Role | Location | REMOTE | Salary | URL
        Returns a dict of extracted fields (all may be empty).
        """
        result: dict[str, Any] = {
            "company": "",
            "title": "",
            "location": "",
            "remote": False,
            "salary": "",
            "url": "",
        }
        if not text:
            return result

        # Strip HTML tags (HN returns HTML-escaped text)
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = clean.replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
        clean = clean.replace("&#x2F;", "/").replace("&#x27;", "'")

        first_line = clean.split("\n")[0].strip()
        parts = [p.strip() for p in first_line.split("|")]

        if len(parts) >= 1:
            result["company"] = parts[0]
        if len(parts) >= 2:
            result["title"] = parts[1]
        if len(parts) >= 3:
            result["location"] = parts[2]

        full_text = clean.lower()
        result["remote"] = any(
            kw in full_text for kw in ("remote", "wfh", "work from home")
        )

        # Extract first URL
        url_match = re.search(r"https?://\S+", clean)
        if url_match:
            result["url"] = url_match.group(0).rstrip(".,)")

        return result

    # ------------------------------------------------------------------
    def _is_relevant(self, parsed: dict[str, Any], text: str) -> bool:
        """Filter to data/ML/Python/backend roles open to India / remote."""
        combined = (
            (parsed.get("title") or "") + " " + (parsed.get("location") or "") + " " + text
        ).lower()

        relevant_roles = [
            "data analyst", "data engineer", "machine learning", "ml engineer",
            "ai engineer", "python", "backend", "back end", "back-end",
            "django", "fastapi", "flask",
        ]
        india_ok = any(
            kw in combined
            for kw in ["remote", "india", "worldwide", "anywhere", "chennai", "bangalore", "bengaluru", "hyderabad"]
        )
        role_match = any(role in combined for role in relevant_roles)

        return role_match and india_ok

    # ------------------------------------------------------------------
    def collect(self) -> list[JobListing]:
        jobs: list[JobListing] = []

        thread_id = self._latest_hiring_thread_id()
        if not thread_id:
            logger.warning("YC: could not locate current 'Who is Hiring' thread")
            return jobs

        logger.info("YC: using thread %d", thread_id)

        try:
            thread = self._get(f"{HN_BASE}/item/{thread_id}.json")
        except Exception as exc:  # noqa: BLE001
            logger.warning("YC: failed to fetch thread %d: %s", thread_id, exc)
            return jobs

        kids = (thread.get("kids") or [])[:MAX_COMMENTS]
        logger.info("YC: parsing %d top-level comments", len(kids))

        for kid_id in kids:
            try:
                time.sleep(ITEM_FETCH_DELAY)
                item = self._get(f"{HN_BASE}/item/{kid_id}.json")
                if not item or item.get("deleted") or item.get("dead"):
                    continue

                text = item.get("text") or ""
                parsed = self._parse_comment(text)

                if not self._is_relevant(parsed, text):
                    continue

                posted_at = None
                if item.get("time"):
                    posted_at = datetime.fromtimestamp(item["time"], tz=timezone.utc)

                url = parsed["url"] or f"https://news.ycombinator.com/item?id={kid_id}"
                company = parsed["company"] or "Unknown"
                title = parsed["title"] or "Job Posting"

                jobs.append(
                    JobListing(
                        title=title,
                        company=company,
                        source=self.source_name,
                        url=url,
                        posted_at=posted_at,
                        location=parsed.get("location") or "Remote",
                        remote=parsed.get("remote", True),
                        salary=parsed.get("salary") or None,
                        description=re.sub(r"<[^>]+>", " ", text)[:2000],
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("YC: skipped comment %d: %s", kid_id, exc)

        logger.info("YCombinator total collected: %d", len(jobs))
        return jobs
