"""
store.py — SQLite-backed persistent store for ApplicationRecord and AuditEvent.

Uses a single database file (data/apply_agent.db) separate from seen_jobs.db.
All writes are transactional. The schema auto-migrates on first open.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apply_agent.models import (
    Answer,
    ApplicationRecord,
    ApplicationStatus,
    AuditEvent,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id               TEXT PRIMARY KEY,
    fingerprint      TEXT NOT NULL UNIQUE,
    job_title        TEXT NOT NULL,
    company          TEXT NOT NULL,
    source           TEXT NOT NULL,
    apply_url        TEXT NOT NULL,
    score            INTEGER NOT NULL DEFAULT 0,
    resume_used      TEXT NOT NULL DEFAULT 'main',
    status           TEXT NOT NULL DEFAULT 'discovered',
    cover_note       TEXT,
    answers_json     TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    submitted_at     TEXT,
    confirmation_ref TEXT,
    adapter          TEXT NOT NULL DEFAULT 'manual',
    flags_json       TEXT NOT NULL DEFAULT '[]',
    notified         INTEGER NOT NULL DEFAULT 0,
    job_location     TEXT NOT NULL DEFAULT '',
    job_salary       TEXT,
    posted_at        TEXT,
    match_reasons_json TEXT NOT NULL DEFAULT '[]',
    missing_skills_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS audit_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id   TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    actor            TEXT NOT NULL,
    event            TEXT NOT NULL,
    old_value        TEXT,
    new_value        TEXT,
    detail           TEXT
);

CREATE INDEX IF NOT EXISTS idx_app_fingerprint ON applications(fingerprint);
CREATE INDEX IF NOT EXISTS idx_app_status      ON applications(status);
CREATE INDEX IF NOT EXISTS idx_audit_app_id    ON audit_log(application_id);
"""


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class ApplicationStore:
    """Thread-safe SQLite store for applications and audit events."""

    def __init__(self, db_path: Path, dry_run: bool = False) -> None:
        self.db_path = db_path
        self.dry_run = dry_run
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("ApplicationStore: opened %s (dry_run=%s)", db_path, dry_run)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ApplicationStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------
    def upsert(self, record: ApplicationRecord, events: list[AuditEvent] | None = None) -> None:
        """Insert or replace an application record and append audit events."""
        if self.dry_run:
            logger.debug("Store (dry-run): would upsert %s", record.id[:8])
            return

        row = (
            record.id,
            record.fingerprint,
            record.job_title,
            record.company,
            record.source,
            record.apply_url,
            record.score,
            record.resume_used,
            record.status.value,
            record.cover_note,
            json.dumps([a.to_dict() for a in record.answers], ensure_ascii=False),
            _dt_to_str(record.created_at),
            _dt_to_str(record.updated_at),
            _dt_to_str(record.submitted_at),
            record.confirmation_ref,
            record.adapter,
            json.dumps(record.flags, ensure_ascii=False),
            1 if record.notified else 0,
            record.job_location,
            record.job_salary,
            _dt_to_str(record.posted_at),
            json.dumps(record.match_reasons, ensure_ascii=False),
            json.dumps(record.missing_skills, ensure_ascii=False),
        )

        self._conn.execute("""
            INSERT OR REPLACE INTO applications
            (id, fingerprint, job_title, company, source, apply_url, score,
             resume_used, status, cover_note, answers_json, created_at, updated_at,
             submitted_at, confirmation_ref, adapter, flags_json, notified,
             job_location, job_salary, posted_at, match_reasons_json, missing_skills_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, row)

        if events:
            for ev in events:
                self._append_audit(ev)

        self._conn.commit()

    def _append_audit(self, ev: AuditEvent) -> None:
        self._conn.execute(
            """INSERT INTO audit_log
               (application_id, timestamp, actor, event, old_value, new_value, detail)
               VALUES (?,?,?,?,?,?,?)""",
            (
                ev.application_id,
                _dt_to_str(ev.timestamp),
                ev.actor,
                ev.event,
                ev.old_value,
                ev.new_value,
                ev.detail,
            ),
        )

    def mark_notified(self, application_id: str) -> None:
        if self.dry_run:
            return
        self._conn.execute(
            "UPDATE applications SET notified=1 WHERE id=?", (application_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------
    def _row_to_record(self, row: sqlite3.Row) -> ApplicationRecord:
        r = dict(row)
        return ApplicationRecord(
            id=r["id"],
            fingerprint=r["fingerprint"],
            job_title=r["job_title"],
            company=r["company"],
            source=r["source"],
            apply_url=r["apply_url"],
            score=r["score"],
            resume_used=r["resume_used"],
            status=ApplicationStatus(r["status"]),
            cover_note=r.get("cover_note"),
            answers=[Answer.from_dict(a) for a in json.loads(r.get("answers_json") or "[]")],
            created_at=_str_to_dt(r["created_at"]) or datetime.now(timezone.utc),
            updated_at=_str_to_dt(r["updated_at"]) or datetime.now(timezone.utc),
            submitted_at=_str_to_dt(r.get("submitted_at")),
            confirmation_ref=r.get("confirmation_ref"),
            adapter=r.get("adapter", "manual"),
            flags=json.loads(r.get("flags_json") or "[]"),
            notified=bool(r.get("notified", 0)),
            job_location=r.get("job_location", ""),
            job_salary=r.get("job_salary"),
            posted_at=_str_to_dt(r.get("posted_at")),
            match_reasons=json.loads(r.get("match_reasons_json") or "[]"),
            missing_skills=json.loads(r.get("missing_skills_json") or "[]"),
        )

    def get(self, application_id: str) -> Optional[ApplicationRecord]:
        row = self._conn.execute(
            "SELECT * FROM applications WHERE id=?", (application_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_fingerprint(self, fingerprint: str) -> Optional[ApplicationRecord]:
        row = self._conn.execute(
            "SELECT * FROM applications WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def exists(self, fingerprint: str) -> bool:
        row = self._conn.execute(
            "SELECT id FROM applications WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        return row is not None

    def list_by_status(self, *statuses: ApplicationStatus) -> list[ApplicationRecord]:
        placeholders = ",".join("?" * len(statuses))
        rows = self._conn.execute(
            f"SELECT * FROM applications WHERE status IN ({placeholders}) ORDER BY score DESC, updated_at DESC",
            [s.value for s in statuses],
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_all(self, limit: int = 500) -> list[ApplicationRecord]:
        rows = self._conn.execute(
            "SELECT * FROM applications ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def audit_log(self, application_id: str) -> list[AuditEvent]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE application_id=? ORDER BY id ASC",
            (application_id,),
        ).fetchall()
        events = []
        for row in rows:
            r = dict(row)
            events.append(AuditEvent(
                application_id=r["application_id"],
                actor=r["actor"],
                event=r["event"],
                old_value=r.get("old_value"),
                new_value=r.get("new_value"),
                detail=r.get("detail"),
                timestamp=_str_to_dt(r["timestamp"]) or datetime.now(timezone.utc),
            ))
        return events

    def counts_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as n FROM applications GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def pending_notification(self) -> list[ApplicationRecord]:
        """Applications that haven't been notified yet."""
        rows = self._conn.execute(
            "SELECT * FROM applications WHERE notified=0 AND status NOT IN ('discovered','skipped')"
            " ORDER BY score DESC"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def to_csv_rows(self) -> list[dict]:
        records = self.list_all()
        rows = []
        for r in records:
            rows.append({
                "id": r.id,
                "status": r.status.value,
                "job_title": r.job_title,
                "company": r.company,
                "source": r.source,
                "score": r.score,
                "resume_used": r.resume_used,
                "apply_url": r.apply_url,
                "location": r.job_location,
                "salary": r.job_salary or "",
                "posted_at": _dt_to_str(r.posted_at) or "",
                "created_at": _dt_to_str(r.created_at) or "",
                "submitted_at": _dt_to_str(r.submitted_at) or "",
                "confirmation_ref": r.confirmation_ref or "",
                "adapter": r.adapter,
                "flags": "|".join(r.flags),
            })
        return rows
