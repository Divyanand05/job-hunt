"""
conftest.py — pytest shared fixtures.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Make the project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject stub env vars so config.py doesn't raise on import during tests."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GMAIL_USER", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-app-password")
    monkeypatch.setenv("DRY_RUN", "true")


@pytest.fixture()
def sample_job():
    from job_hunter.collectors.base import JobListing
    return JobListing(
        title="Data Analyst",
        company="Acme Corp",
        source="himalayas",
        url="https://himalayas.app/jobs/acme/data-analyst",
        posted_at=datetime.now(timezone.utc),
        location="Remote (India)",
        remote=True,
        salary="USD 40,000 – 60,000",
        description="Fresher data analyst role. Python and SQL required.",
    )


@pytest.fixture()
def sample_jobs(sample_job):
    from job_hunter.collectors.base import JobListing
    from datetime import timedelta
    jobs = [sample_job]
    for i in range(1, 5):
        jobs.append(JobListing(
            title=f"Backend Engineer #{i}",
            company=f"Company {i}",
            source="weworkremotely",
            url=f"https://weworkremotely.com/jobs/backend-{i}",
            posted_at=datetime.now(timezone.utc) - timedelta(hours=i),
            location="Worldwide",
            remote=True,
            description=f"Entry level Python backend role #{i}.",
        ))
    return jobs


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR
