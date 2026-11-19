"""
base.py — Canonical JobListing dataclass and BaseCollector abstract class.

Every collector must return a list[JobListing].  Fields that cannot be
determined must remain None — never invent or guess values.
"""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class JobListing:
    """Normalised job listing.  All timestamps are UTC-aware datetimes."""

    # Required
    title: str
    company: str
    source: str                        # e.g. "himalayas", "weworkremotely"
    url: str                           # Direct application or listing URL

    # Strongly preferred — jobs with no posted_at are REJECTED downstream
    posted_at: Optional[datetime] = None

    # Location
    location: str = "Remote"
    remote: bool = True

    # Optional enrichment
    salary: Optional[str] = None
    description: Optional[str] = None
    experience_level: Optional[str] = None

    # Internal tracking
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Computed
    _fingerprint: Optional[str] = field(default=None, init=False, repr=False)

    # -----------------------------------------------------------------
    def fingerprint(self) -> str:
        """Stable dedup key: SHA-256 of (url, normalised title+company)."""
        if self._fingerprint is None:
            raw = f"{self.url}|{self.title.lower().strip()}|{self.company.lower().strip()}"
            self._fingerprint = hashlib.sha256(raw.encode()).hexdigest()
        return self._fingerprint

    def is_recent(self, max_age_hours: int) -> bool:
        """Return True only when posted_at is known and within max_age_hours."""
        if self.posted_at is None:
            return False
        now = datetime.now(timezone.utc)
        age = now - self.posted_at
        return age.total_seconds() / 3600 <= max_age_hours

    def age_hours(self) -> Optional[float]:
        if self.posted_at is None:
            return None
        return (datetime.now(timezone.utc) - self.posted_at).total_seconds() / 3600


class BaseCollector(ABC):
    """Abstract base for all job-source collectors."""

    source_name: str = "unknown"
    # Set to True for unofficial / reverse-engineered sources
    unofficial: bool = False

    def __init__(self, timeout: int = 30, max_retries: int = 3) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.logger = logging.getLogger(f"collector.{self.source_name}")

    @abstractmethod
    def collect(self) -> list[JobListing]:
        """Fetch, parse and return raw (unnormalised) job listings.

        Must NOT raise on network errors — catch, log, and return [].
        """

    def health_check(self) -> dict:
        """Return a brief status dict for the source-health report."""
        try:
            jobs = self.collect()
            return {
                "source": self.source_name,
                "status": "ok",
                "jobs_fetched": len(jobs),
                "unofficial": self.unofficial,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "source": self.source_name,
                "status": "error",
                "error": str(exc),
                "unofficial": self.unofficial,
            }
