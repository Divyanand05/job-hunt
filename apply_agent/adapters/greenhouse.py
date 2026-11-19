"""
adapters/greenhouse.py — GreenhouseAdapter.

Greenhouse has a public Job Board API for READING jobs (no key needed).
The APPLICATION SUBMISSION endpoint requires a Job Board API Key that
belongs to the EMPLOYER — applicants cannot obtain one.

Therefore:
  can_discover = True  (we can read job listings)
  can_prepare  = True  (we can prepare cover notes and answers)
  can_submit   = False (DENY — we do not have the employer's API key)

If Greenhouse ever provides an applicant-side submission token, that would
need to be validated here before setting can_submit=True.

Docs: https://docs.greenhouse.io/job-board
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from apply_agent.adapters.base import BaseAdapter, SubmissionDeniedError
from apply_agent.models import ApplicationRecord, ApplicationStatus, AuditEvent
from job_hunter.collectors.base import JobListing

logger = logging.getLogger(__name__)

GREENHOUSE_BOARD_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseAdapter(BaseAdapter):
    """Read-only Greenhouse adapter. Submit is always DENY."""

    name = "greenhouse"
    can_discover = True
    can_prepare = True
    can_submit = False          # Requires employer Job Board API key — not available to applicants

    def __init__(self, board_token: str, timeout: int = 30) -> None:
        self.board_token = board_token
        self.timeout = timeout

    # ------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=False,
    )
    def fetch_jobs(self) -> list[dict]:
        """Fetch all open jobs from a Greenhouse board (public, no key)."""
        url = GREENHOUSE_BOARD_API.format(token=self.board_token)
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params={"content": "true"})
            resp.raise_for_status()
            return resp.json().get("jobs", [])

    # ------------------------------------------------------------------
    @staticmethod
    def parse_job(raw: dict, board_token: str) -> Optional[JobListing]:
        """Parse a Greenhouse job dict into a JobListing."""
        from datetime import datetime, timezone

        job_id = raw.get("id")
        title = (raw.get("title") or "").strip()
        if not title or not job_id:
            return None

        url = raw.get("absolute_url") or f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}"

        # Greenhouse returns updated_at as ISO string
        posted_at: Optional[datetime] = None
        for key in ("updated_at", "created_at"):
            val = raw.get(key)
            if val:
                try:
                    posted_at = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    break
                except ValueError:
                    pass

        location = ""
        if raw.get("location"):
            location = raw["location"].get("name", "") or ""
        if not location:
            offices = raw.get("offices", [])
            if offices:
                location = offices[0].get("name", "Remote") or "Remote"
        location = location or "Remote"

        # Extract plain-text from content HTML
        content = raw.get("content", "") or ""
        import re
        description = re.sub(r"<[^>]+>", " ", content).strip()[:2000]

        return JobListing(
            title=title,
            company=board_token,         # caller should override with real company name
            source="greenhouse",
            url=url,
            posted_at=posted_at,
            location=location,
            remote="remote" in location.lower(),
            description=description,
        )

    # ------------------------------------------------------------------
    def prepare(
        self, record: ApplicationRecord
    ) -> tuple[ApplicationRecord, list[AuditEvent]]:
        """Mark as PREPARED and route to manual review."""
        events: list[AuditEvent] = []
        if record.status in (ApplicationStatus.DISCOVERED, ApplicationStatus.SHORTLISTED):
            events.append(record.transition(ApplicationStatus.PREPARED, actor="greenhouse_adapter"))
            events.append(record.transition(ApplicationStatus.PENDING_REVIEW, actor="greenhouse_adapter"))
            events.append(AuditEvent(
                application_id=record.id,
                actor="greenhouse_adapter",
                event="queued_for_review",
                detail=(
                    "Greenhouse application routed to manual queue. "
                    "The Job Board submit API requires the employer's API key — not available to applicants."
                ),
            ))
        return record, events

    # ------------------------------------------------------------------
    def submit(
        self, record: ApplicationRecord
    ) -> tuple[ApplicationRecord, list[AuditEvent]]:
        """Always denies — Greenhouse submission requires the employer's key."""
        reason = (
            "Greenhouse Job Board submission API (POST /boards/{token}/jobs/{id}) "
            "requires the employer's Job Board API Key. "
            "Applicants cannot obtain this key. Routing to manual review."
        )
        logger.warning("Greenhouse adapter: cannot submit — %s", reason)
        ev = record.transition(ApplicationStatus.PENDING_REVIEW, actor="greenhouse_adapter")
        deny_ev = self._deny_event(record, reason)
        return record, [ev, deny_ev]
