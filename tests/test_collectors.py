"""
test_collectors.py — Unit tests for job collectors with mocked HTTP.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_hunter.collectors.base import JobListing
from job_hunter.collectors.himalayas import HimalayasCollector
from job_hunter.collectors.weworkremotely import WeWorkRemotelyCollector

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Himalayas
# ---------------------------------------------------------------------------
class TestHimalayasCollector:
    def test_parses_valid_response(self):
        raw = json.loads((FIXTURES / "himalayas_response.json").read_text())
        collector = HimalayasCollector()

        with patch.object(collector, "_fetch_search", return_value=raw):
            jobs = collector.collect()

        assert len(jobs) >= 1
        job = jobs[0]
        assert isinstance(job, JobListing)
        assert job.title == "Data Analyst"
        assert job.company == "Acme Corp"
        assert job.source == "himalayas"
        assert job.posted_at is not None
        assert job.posted_at.tzinfo is not None  # UTC-aware

    def test_skips_job_without_url(self):
        raw = {
            "jobs": [
                {
                    "title": "No URL Job",
                    "companyName": "Ghost Corp",
                    "applicationLink": "",
                    "pubDate": "2026-11-19T06:00:00Z",
                }
            ]
        }
        collector = HimalayasCollector()
        with patch.object(collector, "_fetch_search", return_value=raw):
            jobs = collector.collect()
        assert all(j.url for j in jobs)

    def test_handles_network_error_gracefully(self):
        import httpx
        collector = HimalayasCollector()
        with patch.object(collector, "_fetch_search", side_effect=httpx.TransportError("timeout")):
            jobs = collector.collect()
        assert jobs == []

    def test_parses_salary(self):
        raw = {
            "jobs": [{
                "title": "ML Engineer",
                "companyName": "AI Co",
                "applicationLink": "https://example.com/apply",
                "pubDate": "2026-11-19T08:00:00Z",
                "minSalary": 50000,
                "maxSalary": 80000,
                "salaryCurrency": "USD",
                "locationRestrictions": ["IN"],
            }]
        }
        collector = HimalayasCollector()
        with patch.object(collector, "_fetch_search", return_value=raw):
            jobs = collector.collect()
        assert len(jobs) == 1
        assert "50,000" in jobs[0].salary
        assert "USD" in jobs[0].salary


# ---------------------------------------------------------------------------
# We Work Remotely
# ---------------------------------------------------------------------------
class TestWeWorkRemotelyCollector:
    def test_parses_rss_feed(self, fixtures_dir):
        feed_xml = (fixtures_dir / "wwr_feed.xml").read_bytes()
        collector = WeWorkRemotelyCollector()

        with patch.object(collector, "_fetch_feed", return_value=feed_xml):
            jobs = collector.collect()

        assert len(jobs) >= 1
        titles = [j.title for j in jobs]
        assert any("Python" in t or "Data" in t for t in titles)

    def test_all_jobs_have_source(self, fixtures_dir):
        feed_xml = (fixtures_dir / "wwr_feed.xml").read_bytes()
        collector = WeWorkRemotelyCollector()
        with patch.object(collector, "_fetch_feed", return_value=feed_xml):
            jobs = collector.collect()
        assert all(j.source == "weworkremotely" for j in jobs)

    def test_handles_feed_error(self):
        collector = WeWorkRemotelyCollector()
        with patch.object(collector, "_fetch_feed", side_effect=Exception("network error")):
            jobs = collector.collect()
        assert jobs == []

    def test_no_duplicate_urls(self, fixtures_dir):
        feed_xml = (fixtures_dir / "wwr_feed.xml").read_bytes()
        collector = WeWorkRemotelyCollector()
        with patch.object(collector, "_fetch_feed", return_value=feed_xml):
            jobs = collector.collect()
        urls = [j.url for j in jobs]
        assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# Base JobListing
# ---------------------------------------------------------------------------
class TestJobListing:
    def test_fingerprint_is_stable(self, sample_job):
        fp1 = sample_job.fingerprint()
        fp2 = sample_job.fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex

    def test_fingerprint_differs_for_different_jobs(self, sample_job):
        from job_hunter.collectors.base import JobListing
        other = JobListing(
            title="Other Job",
            company="Other Corp",
            source="himalayas",
            url="https://example.com/other",
            posted_at=datetime.now(timezone.utc),
        )
        assert sample_job.fingerprint() != other.fingerprint()

    def test_is_recent_true_within_window(self, sample_job):
        assert sample_job.is_recent(24)

    def test_is_recent_false_without_date(self, sample_job):
        sample_job.posted_at = None
        assert not sample_job.is_recent(24)

    def test_is_recent_false_old_job(self):
        from datetime import timedelta
        from job_hunter.collectors.base import JobListing
        old_job = JobListing(
            title="Old Job",
            company="Old Corp",
            source="test",
            url="https://example.com/old",
            posted_at=datetime.now(timezone.utc) - timedelta(hours=30),
        )
        assert not old_job.is_recent(24)
