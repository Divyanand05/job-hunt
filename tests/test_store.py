"""
test_store.py — Tests for ApplicationStore (apply_agent.db).
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apply_agent.models import (
    Answer,
    AnswerConfidence,
    ApplicationRecord,
    ApplicationStatus,
    AuditEvent,
)
from apply_agent.store import ApplicationStore


def _make_record(**kwargs) -> ApplicationRecord:
    defaults = dict(
        fingerprint="fp_test_001",
        job_title="Data Analyst",
        company="Acme",
        source="himalayas",
        apply_url="https://himalayas.app/jobs/acme-da",
        score=88,
        resume_used="data",
        status=ApplicationStatus.SHORTLISTED,
    )
    defaults.update(kwargs)
    return ApplicationRecord(**defaults)


class TestApplicationStore:
    def _store(self, dry_run: bool = False) -> ApplicationStore:
        self._tmpdir = tempfile.TemporaryDirectory()
        db = Path(self._tmpdir.name) / "test_apply.db"
        return ApplicationStore(db, dry_run=dry_run)

    # ------------------------------------------------------------------
    def test_upsert_and_get(self):
        with self._store() as store:
            rec = _make_record()
            store.upsert(rec)
            fetched = store.get(rec.id)
            assert fetched is not None
            assert fetched.job_title == "Data Analyst"
            assert fetched.score == 88
            assert fetched.status == ApplicationStatus.SHORTLISTED

    def test_get_by_fingerprint(self):
        with self._store() as store:
            rec = _make_record(fingerprint="unique_fp_xyz")
            store.upsert(rec)
            fetched = store.get_by_fingerprint("unique_fp_xyz")
            assert fetched is not None
            assert fetched.id == rec.id

    def test_exists(self):
        with self._store() as store:
            rec = _make_record(fingerprint="exists_fp")
            assert not store.exists("exists_fp")
            store.upsert(rec)
            assert store.exists("exists_fp")

    def test_idempotent_upsert(self):
        with self._store() as store:
            rec = _make_record(fingerprint="idempotent_fp")
            store.upsert(rec)
            rec.score = 95
            store.upsert(rec)  # update
            fetched = store.get(rec.id)
            assert fetched.score == 95

    def test_dry_run_no_write(self):
        with self._store(dry_run=True) as store:
            rec = _make_record(fingerprint="dry_fp")
            store.upsert(rec)
            assert not store.exists("dry_fp")

    def test_list_by_status(self):
        with self._store() as store:
            r1 = _make_record(fingerprint="fp1", status=ApplicationStatus.PENDING_REVIEW)
            r2 = _make_record(fingerprint="fp2", status=ApplicationStatus.APPROVED)
            r3 = _make_record(fingerprint="fp3", status=ApplicationStatus.PENDING_REVIEW)
            store.upsert(r1)
            store.upsert(r2)
            store.upsert(r3)
            pending = store.list_by_status(ApplicationStatus.PENDING_REVIEW)
            assert len(pending) == 2

    def test_counts_by_status(self):
        with self._store() as store:
            store.upsert(_make_record(fingerprint="c1", status=ApplicationStatus.PENDING_REVIEW))
            store.upsert(_make_record(fingerprint="c2", status=ApplicationStatus.PENDING_REVIEW))
            store.upsert(_make_record(fingerprint="c3", status=ApplicationStatus.SUBMITTED))
            counts = store.counts_by_status()
            assert counts["pending_review"] == 2
            assert counts["submitted"] == 1

    def test_audit_log_persisted(self):
        with self._store() as store:
            rec = _make_record(fingerprint="audit_fp")
            ev = AuditEvent(
                application_id=rec.id,
                actor="system",
                event="status_changed",
                old_value="shortlisted",
                new_value="prepared",
            )
            store.upsert(rec, [ev])
            log = store.audit_log(rec.id)
            assert len(log) == 1
            assert log[0].event == "status_changed"

    def test_answers_roundtrip(self):
        with self._store() as store:
            rec = _make_record(fingerprint="ans_fp")
            rec.answers = [
                Answer(
                    question="Are you willing to relocate?",
                    answer="Yes",
                    confidence=AnswerConfidence.HIGH,
                    source="profile",
                ),
                Answer(
                    question="Expected salary?",
                    answer=None,
                    confidence=AnswerConfidence.NEEDS_MANUAL_REVIEW,
                    is_sensitive=True,
                ),
            ]
            store.upsert(rec)
            fetched = store.get(rec.id)
            assert len(fetched.answers) == 2
            assert fetched.answers[0].answer == "Yes"
            assert fetched.answers[1].is_sensitive is True
            assert fetched.answers[1].confidence == AnswerConfidence.NEEDS_MANUAL_REVIEW

    def test_pending_notification(self):
        with self._store() as store:
            r1 = _make_record(fingerprint="notif1", status=ApplicationStatus.PENDING_REVIEW)
            r2 = _make_record(fingerprint="notif2", status=ApplicationStatus.PENDING_REVIEW)
            r2.notified = True
            store.upsert(r1)
            store.upsert(r2)
            store._conn.execute("UPDATE applications SET notified=1 WHERE fingerprint='notif2'")
            store._conn.commit()
            pending = store.pending_notification()
            fps = [p.fingerprint for p in pending]
            assert "notif1" in fps
            assert "notif2" not in fps

    def test_mark_notified(self):
        with self._store() as store:
            rec = _make_record(fingerprint="mark_fp", status=ApplicationStatus.PENDING_REVIEW)
            store.upsert(rec)
            store.mark_notified(rec.id)
            assert store.pending_notification() == []

    def test_to_csv_rows(self):
        with self._store() as store:
            store.upsert(_make_record(fingerprint="csv1"))
            rows = store.to_csv_rows()
            assert len(rows) == 1
            assert "job_title" in rows[0]
            assert rows[0]["status"] == "shortlisted"
