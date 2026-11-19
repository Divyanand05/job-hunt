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
    # Data
    "data analyst", "junior data analyst", "bi analyst", "analytics intern",
    "data analytics", "business analyst", "analytics engineer",
    # Data Engineering
    "data engineer", "junior data engineer", "etl developer",
    "data engineering intern", "data pipeline",
    # AI / ML
    "ai engineer", "ml engineer", "machine learning engineer",
    "applied ai", "computer vision intern", "ml engineer intern",
    "applied machine learning", "ai intern",
    # Python / Backend
    "python developer", "python intern", "software engineer python",
    "backend developer", "backend engineer", "backend intern",
    "api developer", "associate software engineer",
    # General entry-level
    "graduate engineer trainee", "software developer intern",
    "software engineer intern", "junior software engineer",
    "junior developer", "junior engineer",
]

TARGET_LOCATIONS: list = [
    "remote",
    "chennai",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "india",
    "worldwide",
    "anywhere",
    "global",
    "work from home",
    "wfh",
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
    "2026",
    "new grad",
    "campus hire",
    "trainee",
    "apprentice",
    "no experience required",
    "no prior experience",
]

# Primary freshness window (hours) — strict 24h pool
MAX_JOB_AGE_HOURS: int = int(os.getenv("MAX_JOB_AGE_HOURS", "24"))

# Fallback pool: jobs 24–72h old, unseen, scored at higher bar
FALLBACK_AGE_HOURS: int = int(os.getenv("FALLBACK_AGE_HOURS", "72"))

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

# Score thresholds
MIN_SCORE: int = int(os.getenv("MIN_SCORE", "50"))        # absolute floor
SHORTLIST_SCORE: int = int(os.getenv("SHORTLIST_SCORE", "75"))    # primary pool threshold
PRIORITY_SCORE: int = int(os.getenv("PRIORITY_SCORE", "85"))     # priority flag
FALLBACK_MIN_SCORE: int = int(os.getenv("FALLBACK_MIN_SCORE", "82"))  # fallback pool (higher bar)

# ---------------------------------------------------------------------------
# Dry-run mode — collect & rank but do not send email or write to DB
# ---------------------------------------------------------------------------
DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() == "true"
