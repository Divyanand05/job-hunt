"""
test_adapters.py — Tests for the adapter interface and permission gates.
"""
from __future__ import annotations

import pytest

from apply_agent.adapters.base import BaseAdapter, SubmissionDeniedError
from apply_agent.adapters.manual import ManualQueueAdapter
from apply_agent.adapters.greenhouse import GreenhouseAdapter
from apply_agent.models import (
    Answer,
    AnswerConfidence,
    ApplicationRecord,
    ApplicationStatus,
)


def _make_record(**kwargs) -> ApplicationRecord:
    defaults = dict(
        fingerprint="fp_adapter_test",
        job_title="ML Engineer",
        company="TestCo",
        source="himalayas",
        apply_url="https://example.com/apply",
        score=85,
        resume_used="aiml",
        status=ApplicationStatus.SHORTLISTED,
    )
    defaults.update(kwargs)
    return ApplicationRecord(**defaults)


class TestManualQueueAdapter:
    def test_can_submit_is_false(self):
        adapter = ManualQueueAdapter()
        assert adapter.can_submit is False

    def test_prepare_transitions_to_pending_review(self):
        adapter = ManualQueueAdapter()
        rec = _make_record()
        rec, events = adapter.prepare(rec)
        assert rec.status == ApplicationStatus.PENDING_REVIEW
        statuses = [e.new_value for e in events if e.event == "status_changed"]
        assert "pending_review" in statuses

    def test_prepare_emits_audit_events(self):
        adapter = ManualQueueAdapter()
        rec = _make_record()
        rec, events = adapter.prepare(rec)
        assert len(events) >= 2

    def test_submit_routes_to_pending_review(self):
        adapter = ManualQueueAdapter()
        rec = _make_record(status=ApplicationStatus.PREPARED)
        rec, events = adapter.submit(rec)
        assert rec.status == ApplicationStatus.PENDING_REVIEW
        deny_events = [e for e in events if e.event == "submission_denied"]
        assert len(deny_events) == 1

    def test_prepare_already_pending_is_idempotent(self):
        adapter = ManualQueueAdapter()
        rec = _make_record(status=ApplicationStatus.PENDING_REVIEW)
        rec, events = adapter.prepare(rec)
        assert rec.status == ApplicationStatus.PENDING_REVIEW
        # No new transitions should fire
        assert all(e.event != "status_changed" for e in events)


class TestGreenhouseAdapter:
    def test_can_submit_is_false(self):
        adapter = GreenhouseAdapter("some-company")
        assert adapter.can_submit is False

    def test_submit_always_denies(self):
        adapter = GreenhouseAdapter("some-company")
        rec = _make_record()
        rec, events = adapter.submit(rec)
        assert rec.status == ApplicationStatus.PENDING_REVIEW
        deny_events = [e for e in events if e.event == "submission_denied"]
        assert len(deny_events) == 1
        assert "employer" in deny_events[0].detail.lower() or "key" in deny_events[0].detail.lower()

    def test_prepare_routes_to_pending_review(self):
        adapter = GreenhouseAdapter("some-company")
        rec = _make_record()
        rec, events = adapter.prepare(rec)
        assert rec.status == ApplicationStatus.PENDING_REVIEW

    def test_parse_job_valid(self):
        raw = {
            "id": 12345,
            "title": "Data Engineer",
            "absolute_url": "https://boards.greenhouse.io/testco/jobs/12345",
            "updated_at": "2026-11-19T06:00:00Z",
            "location": {"name": "Remote"},
            "content": "<p>Python and SQL required.</p>",
        }
        job = GreenhouseAdapter.parse_job(raw, "testco")
        assert job is not None
        assert job.title == "Data Engineer"
        assert job.posted_at is not None
        assert "Python" in job.description

    def test_parse_job_missing_title_returns_none(self):
        raw = {"id": 999, "title": "", "absolute_url": "https://example.com"}
        job = GreenhouseAdapter.parse_job(raw, "testco")
        assert job is None


class TestBaseAdapterPermissionGates:
    """Test the three submission permission gates via a concrete subclass."""

    def test_gate1_can_submit_false_raises(self):
        """Gate 1: can_submit=False always blocks."""
        adapter = ManualQueueAdapter()  # can_submit=False
        rec = _make_record()
        with pytest.raises(SubmissionDeniedError, match="can_submit=False"):
            adapter._check_submission_gates(rec)

    def test_gate3_unresolved_answers_raises(self, monkeypatch):
        """Gate 3: unresolved questions block even if gates 1+2 pass."""

        class FakeAdapter(BaseAdapter):
            name = "fake"
            can_submit = True  # Gate 1 passes

            def prepare(self, record):
                return record, []

        monkeypatch.setenv("AUTO_SUBMIT_FAKE", "true")  # Gate 2 passes
        adapter = FakeAdapter()
        rec = _make_record()
        rec.answers = [
            Answer(
                question="Expected salary?",
                answer=None,
                confidence=AnswerConfidence.NEEDS_MANUAL_REVIEW,
                is_sensitive=True,
            )
        ]
        with pytest.raises(SubmissionDeniedError, match="unresolved"):
            adapter._check_submission_gates(rec)

    def test_gate2_missing_env_raises(self, monkeypatch):
        """Gate 2: missing AUTO_SUBMIT env var blocks submission."""

        class FakeAdapter2(BaseAdapter):
            name = "fake2"
            can_submit = True

            def prepare(self, record):
                return record, []

        monkeypatch.delenv("AUTO_SUBMIT_FAKE2", raising=False)
        adapter = FakeAdapter2()
        rec = _make_record()
        with pytest.raises(SubmissionDeniedError, match="AUTO_SUBMIT_FAKE2"):
            adapter._check_submission_gates(rec)
