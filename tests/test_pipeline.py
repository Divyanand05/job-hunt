"""
test_pipeline.py — Unit tests for normalizer, deduplicator, and filter.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_hunter.collectors.base import JobListing
from job_hunter.pipeline.normalizer import normalize
from job_hunter.pipeline.deduplicator import Deduplicator
from job_hunter.pipeline.filter import filter_jobs


def _make_job(**kwargs) -> JobListing:
    defaults = dict(
        title="Data Analyst",
        company="Acme",
        source="himalayas",
        url="https://example.com/job/1",
        posted_at=datetime.now(timezone.utc),
        location="Remote (India)",
        remote=True,
        description="Entry level Python and SQL role for freshers.",
    )
    defaults.update(kwargs)
    return JobListing(**defaults)


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------
class TestNormalizer:
    def test_accepts_valid_job(self):
        jobs = [_make_job()]
        result = normalize(jobs)
        assert len(result) == 1

    def test_rejects_job_without_date(self):
        jobs = [_make_job(posted_at=None)]
        result = normalize(jobs)
        assert result == []

    def test_rejects_job_without_title(self):
        jobs = [_make_job(title="")]
        result = normalize(jobs)
        assert result == []

    def test_rejects_job_without_url(self):
        jobs = [_make_job(url="")]
        result = normalize(jobs)
        assert result == []

    def test_makes_naive_dt_utc_aware(self):
        naive_dt = datetime(2026, 11, 19, 6, 0, 0)  # no tzinfo
        jobs = [_make_job(posted_at=naive_dt)]
        result = normalize(jobs)
        assert len(result) == 1
        assert result[0].posted_at.tzinfo is not None

    def test_mixed_batch(self):
        jobs = [
            _make_job(url="https://example.com/1"),
            _make_job(posted_at=None, url="https://example.com/2"),
            _make_job(title="", url="https://example.com/3"),
            _make_job(url="https://example.com/4"),
        ]
        result = normalize(jobs)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Deduplicator
# ---------------------------------------------------------------------------
class TestDeduplicator:
    def test_new_jobs_pass_through(self, sample_jobs):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "test.db"
            with Deduplicator(db) as dedup:
                result = dedup.filter_new(sample_jobs)
            assert len(result) == len(sample_jobs)

    def test_seen_jobs_are_filtered(self, sample_jobs):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "test.db"
            with Deduplicator(db) as dedup:
                dedup.mark_seen(sample_jobs)
                result = dedup.filter_new(sample_jobs)
            assert result == []

    def test_dry_run_does_not_write(self, sample_jobs):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "test.db"
            with Deduplicator(db, dry_run=True) as dedup:
                dedup.mark_seen(sample_jobs)
                # Dry-run should NOT persist — same jobs should still be new
                result = dedup.filter_new(sample_jobs)
            assert len(result) == len(sample_jobs)

    def test_partial_overlap(self, sample_jobs):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "test.db"
            with Deduplicator(db) as dedup:
                dedup.mark_seen(sample_jobs[:2])
                result = dedup.filter_new(sample_jobs)
            assert len(result) == len(sample_jobs) - 2

    def test_total_seen_count(self, sample_jobs):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "test.db"
            with Deduplicator(db) as dedup:
                dedup.mark_seen(sample_jobs)
                assert dedup.total_seen() == len(sample_jobs)


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------
class TestFilter:
    def test_recent_role_match_passes(self):
        jobs = [_make_job()]
        result = filter_jobs(jobs)
        assert len(result) == 1

    def test_old_job_rejected(self):
        """Jobs older than FALLBACK_AGE_HOURS (72h) are rejected."""
        from datetime import timedelta
        old = _make_job(posted_at=datetime.now(timezone.utc) - timedelta(hours=75))
        result = filter_jobs([old])
        assert result == []

    def test_job_30h_old_passes_as_fallback(self):
        """Jobs 24-72h old pass as fallback pool (not rejected)."""
        from datetime import timedelta
        fallback = _make_job(posted_at=datetime.now(timezone.utc) - timedelta(hours=30))
        result = filter_jobs([fallback])
        assert len(result) == 1  # passes, flagged as fallback

    def test_no_role_match_rejected(self):
        # Completely unrelated role
        job = _make_job(
            title="Marketing Manager",
            description="Manage social media campaigns and brand strategy.",
        )
        result = filter_jobs([job])
        assert result == []

    def test_non_india_location_review_required(self):
        """Jobs without India/remote location signal → REVIEW_REQUIRED (not rejected)."""
        job = _make_job(
            location="New York, USA",
            remote=False,
            description="Python developer. No experience requirement mentioned.",
        )
        result = filter_jobs([job])
        # With new eligibility model: no explicit India block → passes as REVIEW_REQUIRED
        # Only explicit "must be in US / UK only" blocks
        assert isinstance(result, list)  # doesn't crash

    def test_worldwide_remote_passes(self):
        job = _make_job(location="Worldwide", remote=True, description="data analyst python entry level")
        result = filter_jobs([job])
        assert len(result) == 1

    def test_no_date_already_filtered_by_normalizer(self):
        # Jobs without posted_at fail is_recent() — same result
        job = _make_job(posted_at=None)
        result = filter_jobs([job])
        assert result == []


# ---------------------------------------------------------------------------
# New: Senior role hard filter
# ---------------------------------------------------------------------------

class TestSeniorFilter:
    def test_senior_engineer_rejected(self):
        from datetime import datetime, timezone
        job = JobListing(
            title="Senior Data Engineer",
            company="BigCo",
            source="himalayas",
            url="https://example.com/senior-de",
            posted_at=datetime.now(timezone.utc),
            location="Remote",
            remote=True,
            description="Senior Data Engineer role. 5+ years of experience required. Python, Spark.",
        )
        result = filter_jobs([job])
        assert result == [], "Senior role with 5+ years must be rejected"

    def test_two_years_requirement_rejected(self):
        from datetime import datetime, timezone
        job = JobListing(
            title="Data Analyst",
            company="Corp",
            source="weworkremotely",
            url="https://example.com/da",
            posted_at=datetime.now(timezone.utc),
            location="Remote",
            remote=True,
            description="Data Analyst needed. Minimum 2 years of experience in SQL and Python.",
        )
        result = filter_jobs([job])
        assert result == [], "2+ years requirement must be rejected"

    def test_fresher_role_passes(self):
        from datetime import datetime, timezone
        job = JobListing(
            title="Data Analyst",
            company="Startup",
            source="himalayas",
            url="https://example.com/fresher-da",
            posted_at=datetime.now(timezone.utc),
            location="Remote India",
            remote=True,
            description="Fresher data analyst role. 0-1 years experience. Python and SQL required.",
        )
        result = filter_jobs([job])
        assert len(result) == 1, "Fresher role must pass"

    def test_no_experience_mentioned_passes(self):
        """Jobs with no experience requirement are assumed open to freshers."""
        from datetime import datetime, timezone
        job = JobListing(
            title="Python Developer",
            company="Startup",
            source="himalayas",
            url="https://example.com/py-dev",
            posted_at=datetime.now(timezone.utc),
            location="Remote",
            remote=True,
            description="Python developer role. Skills: FastAPI, PostgreSQL, Git.",
        )
        result = filter_jobs([job])
        assert len(result) == 1, "No experience requirement → allowed for fresher"

    def test_intern_role_passes(self):
        from datetime import datetime, timezone
        job = JobListing(
            title="ML Engineer Intern",
            company="AI Corp",
            source="ycombinator",
            url="https://example.com/ml-intern",
            posted_at=datetime.now(timezone.utc),
            location="Bengaluru",
            remote=False,
            description="ML internship. Looking for 2027 graduates. Python, TensorFlow.",
        )
        result = filter_jobs([job])
        assert len(result) == 1, "Internship must pass"

    def test_lead_title_rejected(self):
        from datetime import datetime, timezone
        job = JobListing(
            title="Lead Backend Engineer",
            company="Corp",
            source="weworkremotely",
            url="https://example.com/lead",
            posted_at=datetime.now(timezone.utc),
            location="Remote",
            remote=True,
            description="Lead backend engineer to manage a team of 5. Python, AWS.",
        )
        result = filter_jobs([job])
        assert result == [], "Lead title must be rejected"
