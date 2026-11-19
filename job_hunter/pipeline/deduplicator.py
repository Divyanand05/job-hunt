"""
deduplicator.py — SQLite-backed cross-run duplicate tracking.

Each seen job is stored as a (fingerprint, url, title, company, source,
seen_at) row.  On each run we filter out any job whose fingerprint was
already stored, then write newly selected jobs back.

The fingerprint is a SHA-256 hash of (url, normalised_title, normalised_company)
computed on the JobListing.fingerprint() method.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from job_hunter.collectors.base import JobListing

logger = logging.getLogger(__name__)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS seen_jobs (
    fingerprint TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    source      TEXT NOT NULL,
    seen_at     TEXT NOT NULL
);
"""

INSERT_JOB = """
INSERT OR IGNORE INTO seen_jobs
    (fingerprint, url, title, company, source, seen_at)
VALUES
    (?, ?, ?, ?, ?, ?);
"""


class Deduplicator:
    def __init__(self, db_path: Path, dry_run: bool = False) -> None:
        self.db_path = db_path
        self.dry_run = dry_run
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(CREATE_TABLE)
        self._conn.commit()
        logger.info("Deduplicator: opened %s", db_path)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Deduplicator":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _known_fingerprints(self) -> set[str]:
        rows = self._conn.execute("SELECT fingerprint FROM seen_jobs").fetchall()
        return {r[0] for r in rows}

    # ------------------------------------------------------------------
    def filter_new(self, jobs: list[JobListing]) -> list[JobListing]:
        """Return only jobs NOT previously seen.  Does not write to DB."""
        known = self._known_fingerprints()
        new_jobs = [j for j in jobs if j.fingerprint() not in known]
        logger.info(
            "Deduplicator: %d total, %d already seen, %d new",
            len(jobs),
            len(jobs) - len(new_jobs),
            len(new_jobs),
        )
        return new_jobs

    # ------------------------------------------------------------------
    def mark_seen(self, jobs: list[JobListing]) -> None:
        """Persist jobs to DB so they're skipped on future runs."""
        if self.dry_run:
            logger.info("Deduplicator (dry-run): would mark %d jobs as seen", len(jobs))
            return
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (j.fingerprint(), j.url, j.title, j.company, j.source, now)
            for j in jobs
        ]
        self._conn.executemany(INSERT_JOB, rows)
        self._conn.commit()
        logger.info("Deduplicator: marked %d jobs as seen", len(rows))

    # ------------------------------------------------------------------
    def total_seen(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
