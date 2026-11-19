"""
config.py — All configuration loaded exclusively from environment variables.
Never hard-code secrets. Set these in a .env file locally or GitHub Secrets in CI.

Required variables raise EnvironmentError when accessed, not on import,
so pytest fixtures can inject stub values before the first access.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)  # always override existing env vars with .env values


def _require(key: str) -> str:
    """Return env var value; raise EnvironmentError if missing."""
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "See README.md for setup instructions."
        )
    return val


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "seen_jobs.db"
RESUME_PATH = DATA_DIR / "resume.txt"

# ---------------------------------------------------------------------------
# API keys — read from env at access time (not at import time) so that
# pytest monkeypatching works correctly.
# ---------------------------------------------------------------------------
def get_gemini_api_key() -> str:
    return _require("GEMINI_API_KEY")

def get_gmail_user() -> str:
    return _require("GMAIL_USER")

def get_gmail_app_password() -> str:
    return _require("GMAIL_APP_PASSWORD")

# Module-level values: empty string when unset (OK for type annotations).
# Real code should call the get_*() functions to get validated values.
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
HIMALAYAS_API_KEY: str = os.getenv("HIMALAYAS_API_KEY", "")
GMAIL_USER: str = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD: str = os.getenv("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL: str = os.getenv("RECIPIENT_EMAIL", os.getenv("GMAIL_USER", ""))

# ---------------------------------------------------------------------------
# Job search parameters
# ---------------------------------------------------------------------------
TARGET_ROLES: list = [
    "data analyst",
    "data engineer",
    "ai engineer",
    "ml engineer",
    "machine learning engineer",
    "python developer",
    "backend developer",
    "backend engineer",
]

TARGET_LOCATIONS: list = [
    "remote",
    "chennai",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "india",
    "worldwide",
]

EXPERIENCE_KEYWORDS: list = [
    "fresher",
    "internship",
    "intern",
    "entry level",
    "entry-level",
    "0-1 year",
    "0 to 1 year",
    "junior",
    "associate",
    "graduate",
    "2027",
    "new grad",
]

# Jobs older than this many hours are rejected
MAX_JOB_AGE_HOURS: int = int(os.getenv("MAX_JOB_AGE_HOURS", "24"))

# Maximum jobs to include in one email
MAX_JOBS_PER_EMAIL: int = int(os.getenv("MAX_JOBS_PER_EMAIL", "5"))

# ---------------------------------------------------------------------------
# Gemini model
# ---------------------------------------------------------------------------
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

# ---------------------------------------------------------------------------
# Apply Agent configuration
# ---------------------------------------------------------------------------
APPLY_DB_PATH = DATA_DIR / "apply_agent.db"

# Minimum Gemini score to shortlist a job (0–100)
MIN_SCORE: int = int(os.getenv("MIN_SCORE", "80"))

# ---------------------------------------------------------------------------
# Dry-run mode — collect & rank but do not send email or write to DB
# ---------------------------------------------------------------------------
DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() == "true"
