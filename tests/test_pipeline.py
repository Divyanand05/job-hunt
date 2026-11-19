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
        old = _make_job(posted_at=datetime.now(timezone.utc) - timedelta(hours=30))
        result = filter_jobs([old])
        assert result == []

    def test_no_role_match_rejected(self):
        # Completely unrelated role
        job = _make_job(
            title="Marketing Manager",
            description="Manage social media campaigns and brand strategy.",
        )
        result = filter_jobs([job])
        assert result == []

    def test_non_india_location_rejected(self):
        # Explicitly US-only
        job = _make_job(
            location="New York, USA only",
            remote=False,
            description="Must be located in the United States. Python developer.",
        )
        result = filter_jobs([job])
        # Should fail location check (no "india"/"remote"/"worldwide" in combined)
        assert result == []

    def test_worldwide_remote_passes(self):
        job = _make_job(location="Worldwide", remote=True, description="data analyst python entry level")
        result = filter_jobs([job])
        assert len(result) == 1

    def test_no_date_already_filtered_by_normalizer(self):
        # Jobs without posted_at fail is_recent() — same result
        job = _make_job(posted_at=None)
        result = filter_jobs([job])
        assert result == []
