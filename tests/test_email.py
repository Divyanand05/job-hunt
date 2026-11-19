"""
test_email.py — Unit tests for the email builder.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from job_hunter.collectors.base import JobListing
from job_hunter.pipeline.ranker import RankedJob


def _make_ranked_job(rank: int = 1) -> RankedJob:
    job = JobListing(
        title=f"Data Analyst #{rank}",
        company=f"Company {rank}",
        source="himalayas",
        url=f"https://himalayas.app/jobs/{rank}",
        posted_at=datetime.now(timezone.utc),
        location="Remote (India)",
        remote=True,
        salary="USD 40,000 – 60,000",
        description="Entry level fresher role.",
    )
    return RankedJob(
        job=job,
        score=90 - rank * 5,
        match_reasons=["Strong Python skills", "SQL experience"],
        missing_skills=["Spark"],
        cover_note="Dear Hiring Team, I am excited to apply..." if rank == 1 else None,
    )


class TestEmailBuilder:
    def test_dry_run_does_not_call_smtp(self, tmp_path, monkeypatch):
        """Dry-run should write an HTML preview and not connect to SMTP."""
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setattr("config.DRY_RUN", True)

        # Patch data dir to temp path
        import config
        monkeypatch.setattr(config, "DATA_DIR", tmp_path)

        from job_hunter.email_sender.gmail import send_email

        ranked = [_make_ranked_job(1), _make_ranked_job(2)]
        health = [{"source": "himalayas", "status": "ok", "jobs_fetched": 10, "unofficial": False}]

        with patch("smtplib.SMTP_SSL") as mock_smtp:
            send_email(ranked, health, dry_run=True)
            mock_smtp.assert_not_called()

    def test_empty_jobs_does_not_send(self):
        from job_hunter.email_sender.gmail import send_email
        with patch("smtplib.SMTP_SSL") as mock_smtp:
            send_email([], [], dry_run=False)
            mock_smtp.assert_not_called()

    def test_html_contains_job_title(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, "DATA_DIR", tmp_path)
        from job_hunter.email_sender.gmail import _build_html

        ranked = [_make_ranked_job(1)]
        health = []
        html = _build_html(ranked, health)

        assert "Data Analyst #1" in html
        assert "Company 1" in html
        assert "himalayas" in html

    def test_html_contains_cover_note(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, "DATA_DIR", tmp_path)
        from job_hunter.email_sender.gmail import _build_html

        ranked = [_make_ranked_job(1)]
        html = _build_html(ranked, [])

        assert "Dear Hiring Team" in html

    def test_html_contains_apply_link(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, "DATA_DIR", tmp_path)
        from job_hunter.email_sender.gmail import _build_html

        ranked = [_make_ranked_job(1)]
        html = _build_html(ranked, [])

        assert "https://himalayas.app/jobs/1" in html

    def test_html_contains_health_report(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, "DATA_DIR", tmp_path)
        from job_hunter.email_sender.gmail import _build_html

        ranked = [_make_ranked_job(1)]
        health = [
            {"source": "himalayas", "status": "ok", "jobs_fetched": 5, "unofficial": False},
            {"source": "linkedin", "status": "unsupported", "error": "No public API", "unofficial": False},
        ]
        html = _build_html(ranked, health)

        assert "himalayas" in html
        assert "linkedin" in html
