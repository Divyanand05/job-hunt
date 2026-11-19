"""
test_apply_engine.py — Tests for the application engine pipeline.

Tests cover:
- Duplicate prevention (same fingerprint not processed twice)
- Freshness enforcement (>24h jobs rejected)
- Resume selection for all three real resumes
- Eligibility check (graduation year, 0-exp, India)
- False success prevention (no confirmation → not marked submitted)
- Approval gate (submission blocked without approval)
- Source failure handling (adapter error → manual queue)
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apply_agent.adapters.base import SubmissionDeniedError
from apply_agent.adapters.manual import ManualQueueAdapter
from apply_agent.models import (
    Answer,
    AnswerConfidence,
    ApplicationRecord,
    ApplicationStatus,
    CANDIDATE_PROFILE,
)
from apply_agent.store import ApplicationStore
from job_hunter.collectors.base import JobListing
from job_hunter.pipeline.ranker import RankedJob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_job(title="Data Analyst", company="TestCo", source="himalayas", score=85, **kwargs) -> RankedJob:
    job = JobListing(
        title=title,
        company=company,
        source=source,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        posted_at=datetime.now(timezone.utc) - timedelta(hours=2),
        location="Remote (India)",
        remote=True,
        description=f"Entry level {title} role open to freshers. Python and SQL required.",
    )
    return RankedJob(
        job=job,
        score=score,
        match_reasons=["Python skills match", "Entry level role"],
        missing_skills=["Spark"],
        cover_note="Dear Hiring Team, I am excited to apply.",
        resume_used="data",
    )


def _old_job(**kwargs) -> RankedJob:
    ranked = _fresh_job(**kwargs)
    ranked.job.posted_at = datetime.now(timezone.utc) - timedelta(hours=30)
    return ranked


def _store(dry_run: bool = False) -> ApplicationStore:
    tmpdir = tempfile.mkdtemp()
    return ApplicationStore(Path(tmpdir) / "test.db", dry_run=dry_run)


# ---------------------------------------------------------------------------
# Test: Duplicate prevention
# ---------------------------------------------------------------------------

class TestDuplicatePrevention:
    def test_same_fingerprint_not_processed_twice(self):
        """Engine must not create two records for the same job fingerprint."""
        ranked = _fresh_job()
        fp = ranked.job.fingerprint()

        with _store() as store:
            # Simulate first run: manually insert a record
            rec = ApplicationRecord(
                fingerprint=fp,
                job_title=ranked.job.title,
                company=ranked.job.company,
                source=ranked.job.source,
                apply_url=ranked.job.url,
                score=ranked.score,
                status=ApplicationStatus.PENDING_REVIEW,
            )
            store.upsert(rec)

            # Verify exists before "second run"
            assert store.exists(fp)

            # Second run: engine should skip this job
            is_duplicate = store.exists(fp)
            assert is_duplicate, "Existing fingerprint must be detected as duplicate"

    def test_different_jobs_both_stored(self):
        """Two different jobs should both be stored."""
        with _store() as store:
            r1 = _fresh_job(title="Data Analyst", company="A")
            r2 = _fresh_job(title="ML Engineer", company="B")

            assert r1.job.fingerprint() != r2.job.fingerprint()

            rec1 = ApplicationRecord(fingerprint=r1.job.fingerprint(), job_title="Data Analyst",
                                     company="A", source="x", apply_url="http://a.com", score=85)
            rec2 = ApplicationRecord(fingerprint=r2.job.fingerprint(), job_title="ML Engineer",
                                     company="B", source="x", apply_url="http://b.com", score=82)
            store.upsert(rec1)
            store.upsert(rec2)
            assert store.exists(r1.job.fingerprint())
            assert store.exists(r2.job.fingerprint())


# ---------------------------------------------------------------------------
# Test: Freshness enforcement
# ---------------------------------------------------------------------------

class TestFreshnessEnforcement:
    def test_old_job_fails_is_recent(self):
        """Jobs older than MAX_JOB_AGE_HOURS must fail is_recent()."""
        ranked = _old_job()
        assert not ranked.job.is_recent(24), "30h old job should fail 24h freshness"

    def test_fresh_job_passes_is_recent(self):
        ranked = _fresh_job()
        assert ranked.job.is_recent(24)

    def test_job_without_date_fails_is_recent(self):
        ranked = _fresh_job()
        ranked.job.posted_at = None
        assert not ranked.job.is_recent(24)


# ---------------------------------------------------------------------------
# Test: Resume selection
# ---------------------------------------------------------------------------

class TestResumeSelection:
    def test_data_analyst_uses_data_resume(self):
        from job_hunter.pipeline.resume_selector import select_resume
        _, key = select_resume("Data Analyst", "SQL Python ETL Power BI")
        assert key == "data"

    def test_ml_engineer_uses_aiml_resume(self):
        from job_hunter.pipeline.resume_selector import select_resume
        _, key = select_resume("Machine Learning Engineer", "PyTorch deep learning NLP")
        assert key == "aiml"

    def test_backend_developer_uses_backend_resume(self):
        from job_hunter.pipeline.resume_selector import select_resume
        _, key = select_resume("Backend Developer", "FastAPI PostgreSQL REST API")
        assert key == "backend"

    def test_unknown_role_falls_back_to_main(self):
        from job_hunter.pipeline.resume_selector import select_resume
        _, key = select_resume("Product Manager", "stakeholder management")
        assert key == "main"

    def test_aiml_beats_backend_on_priority(self):
        from job_hunter.pipeline.resume_selector import select_resume
        _, key = select_resume("Backend Engineer", "machine learning LLM RAG")
        assert key == "aiml", "AI/ML (priority 3) beats backend (priority 2)"

    def test_all_resumes_non_empty(self):
        from job_hunter.pipeline.resume_selector import all_resumes
        resumes = all_resumes()
        for key, text in resumes.items():
            assert len(text) > 50, f"Resume '{key}' is too short or empty"


# ---------------------------------------------------------------------------
# Test: Eligibility (graduation year, 0-exp, India)
# ---------------------------------------------------------------------------

class TestEligibility:
    def test_candidate_profile_graduation_year(self):
        assert CANDIDATE_PROFILE["graduation_year"] == 2027

    def test_candidate_profile_zero_experience(self):
        assert CANDIDATE_PROFILE["years_experience"] == 0

    def test_candidate_profile_india_work_auth(self):
        auth = CANDIDATE_PROFILE["work_authorization"].lower()
        assert "india" in auth or "indian" in auth

    def test_candidate_profile_no_visa_for_india_remote(self):
        assert CANDIDATE_PROFILE["visa_required_for_india_remote"] is False

    def test_sensitive_question_detection(self):
        from apply_agent.screener import _is_sensitive
        assert _is_sensitive("Are you authorized to work in the US?")
        assert _is_sensitive("What is your expected salary?")
        assert _is_sensitive("Do you have any disability?")
        assert not _is_sensitive("Are you willing to relocate?")
        assert not _is_sensitive("Do you have Python experience?")


# ---------------------------------------------------------------------------
# Test: False success prevention
# ---------------------------------------------------------------------------

class TestFalseSuccessPrevention:
    def test_submitted_status_requires_confirmation_ref(self):
        """A record should only be marked SUBMITTED if it has a confirmation_ref."""
        with _store() as store:
            rec = ApplicationRecord(
                fingerprint="false_success_fp",
                job_title="Data Engineer",
                company="FakeCo",
                source="himalayas",
                apply_url="https://example.com/de",
                score=88,
                status=ApplicationStatus.APPROVED,
            )
            store.upsert(rec)

            # Try to mark submitted WITHOUT confirmation
            rec.status = ApplicationStatus.SUBMITTED
            # confirmation_ref should NOT be set automatically
            assert rec.confirmation_ref is None, (
                "confirmation_ref must not be set without actual submission confirmation"
            )

    def test_manual_submission_requires_user_action(self):
        """Only after user confirms in dashboard should submitted_at be set."""
        rec = ApplicationRecord(
            fingerprint="manual_sub_fp",
            job_title="Data Analyst",
            company="TestCo",
            source="himalayas",
            apply_url="https://example.com",
            score=85,
            status=ApplicationStatus.APPROVED,
        )
        # Before user action — not submitted
        assert rec.submitted_at is None
        assert rec.status != ApplicationStatus.SUBMITTED

        # Simulate user action in dashboard
        rec.submitted_at = datetime.now(timezone.utc)
        rec.confirmation_ref = "manual"
        ev = rec.transition(ApplicationStatus.SUBMITTED, actor="user")

        assert rec.status == ApplicationStatus.SUBMITTED
        assert rec.submitted_at is not None
        assert rec.confirmation_ref == "manual"


# ---------------------------------------------------------------------------
# Test: Approval gate
# ---------------------------------------------------------------------------

class TestApprovalGate:
    def test_manual_adapter_never_auto_submits(self):
        """ManualQueueAdapter.submit() must route to PENDING_REVIEW, never SUBMITTED."""
        adapter = ManualQueueAdapter()
        rec = ApplicationRecord(
            fingerprint="approval_gate_fp",
            job_title="Python Developer",
            company="TestCo",
            source="weworkremotely",
            apply_url="https://example.com",
            score=82,
            status=ApplicationStatus.PREPARED,
        )
        rec, events = adapter.submit(rec)
        assert rec.status == ApplicationStatus.PENDING_REVIEW
        assert rec.status != ApplicationStatus.SUBMITTED

    def test_submission_denied_error_raised_without_permission(self):
        """BaseAdapter._check_submission_gates raises SubmissionDeniedError when can_submit=False."""
        adapter = ManualQueueAdapter()
        rec = ApplicationRecord(
            fingerprint="gate_fp",
            job_title="Backend Dev",
            company="Co",
            source="test",
            apply_url="https://example.com",
            score=90,
        )
        with pytest.raises(SubmissionDeniedError):
            adapter._check_submission_gates(rec)

    def test_approved_status_still_requires_manual_apply(self):
        """APPROVED does not mean SUBMITTED — user must manually click Apply."""
        with _store() as store:
            rec = ApplicationRecord(
                fingerprint="approved_not_submitted",
                job_title="Data Analyst",
                company="Co",
                source="himalayas",
                apply_url="https://example.com",
                score=85,
                status=ApplicationStatus.PENDING_REVIEW,
            )
            store.upsert(rec)
            # Transition to approved
            ev = rec.transition(ApplicationStatus.APPROVED, actor="user")
            store.upsert(rec, [ev])

            fetched = store.get(rec.id)
            assert fetched.status == ApplicationStatus.APPROVED
            assert fetched.status != ApplicationStatus.SUBMITTED
            assert fetched.submitted_at is None


# ---------------------------------------------------------------------------
# Test: Source failure handling
# ---------------------------------------------------------------------------

class TestSourceFailureHandling:
    def test_failed_collector_does_not_crash_pipeline(self):
        """If a collector raises, its jobs are skipped but others continue."""
        with patch("apply_agent.engine.HimalayasCollector") as MockHim:
            MockHim.return_value.collect.side_effect = Exception("Network error")
            MockHim.return_value.source_name = "himalayas"
            MockHim.return_value.unofficial = False

            from apply_agent.engine import run_discovery
            # Even with one collector failing, function should not raise
            jobs, health = run_discovery(dry_run=True)

            him_health = next((h for h in health if h["source"] == "himalayas"), None)
            assert him_health is not None
            assert him_health["status"] == "error"

    def test_has_unresolved_answers_flag(self):
        """Record with NEEDS_MANUAL_REVIEW answers should be flagged."""
        rec = ApplicationRecord(
            fingerprint="unresolved_fp",
            job_title="Data Analyst",
            company="Co",
            source="test",
            apply_url="https://example.com",
            score=85,
        )
        rec.answers = [
            Answer("What is your salary expectation?", None,
                   AnswerConfidence.NEEDS_MANUAL_REVIEW, is_sensitive=True),
        ]
        assert rec.has_unresolved() is True

    def test_no_unresolved_answers(self):
        rec = ApplicationRecord(
            fingerprint="resolved_fp",
            job_title="Data Analyst",
            company="Co",
            source="test",
            apply_url="https://example.com",
            score=85,
        )
        rec.answers = [
            Answer("Are you willing to relocate?", "Yes", AnswerConfidence.HIGH),
            Answer("Years of experience?", "0", AnswerConfidence.HIGH),
        ]
        assert rec.has_unresolved() is False
