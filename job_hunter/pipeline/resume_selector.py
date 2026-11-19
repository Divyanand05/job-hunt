"""
resume_selector.py — Pick the most relevant resume for a given job.

Four tailored resumes are available:

  resume_data.txt    Data Analyst, Data Engineer, Business Analyst, Analytics
  resume_backend.txt Backend Developer, Python Developer, Software Engineer
  resume_aiml.txt    AI Engineer, ML Engineer, Computer Vision, GenAI
  resume_main.txt    General / fallback

Selection is a pure keyword match against the job title + description.
No external API call is made — this is fast and free.
"""
from __future__ import annotations

import re
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

# ---------------------------------------------------------------------------
# Resume definitions: each entry is (file_path, priority, keyword_patterns)
# Higher priority wins when multiple resumes match.
# ---------------------------------------------------------------------------
_RESUMES = [
    # --- AI / ML (highest specificity first) ---
    {
        "key": "aiml",
        "path": config.DATA_DIR / "resume_aiml.txt",
        "priority": 3,
        "patterns": re.compile(
            r"\b(ai engineer|machine learning|ml engineer|deep learning|"
            r"computer vision|nlp|generative ai|gen ai|llm|rag|"
            r"large language model|diffusion|transformer|yolo|"
            r"object detection|multimodal|reinforcement learning)\b",
            re.IGNORECASE,
        ),
    },
    # --- Data / Analytics ---
    {
        "key": "data",
        "path": config.DATA_DIR / "resume_data.txt",
        "priority": 3,
        "patterns": re.compile(
            r"\b(data analyst|data engineer|analytics engineer|"
            r"business analyst|bi developer|etl|data pipeline|"
            r"data quality|data warehouse|power bi|tableau|dbt|"
            r"spark|hadoop|airflow|looker|sql analyst)\b",
            re.IGNORECASE,
        ),
    },
    # --- Backend / Python ---
    {
        "key": "backend",
        "path": config.DATA_DIR / "resume_backend.txt",
        "priority": 2,
        "patterns": re.compile(
            r"\b(backend|back-end|back end|python developer|"
            r"software engineer|api developer|rest api|fastapi|"
            r"flask|django|node\.?js|express|microservice|"
            r"devops|cloud engineer|aws developer)\b",
            re.IGNORECASE,
        ),
    },
    # --- General fallback (always matches) ---
    {
        "key": "main",
        "path": config.DATA_DIR / "resume_main.txt",
        "priority": 1,
        "patterns": re.compile(r".*", re.IGNORECASE),  # match anything
    },
]

# Cache file contents so we don't re-read on every call
_cache: dict[str, str] = {}


def _read(path: Path) -> str:
    key = str(path)
    if key not in _cache:
        if not path.exists():
            raise FileNotFoundError(
                f"Resume file not found: {path}\n"
                "Make sure data/resume_*.txt files exist. See README.md."
            )
        _cache[key] = path.read_text(encoding="utf-8").strip()
    return _cache[key]


def select_resume(job_title: str, job_description: str = "") -> tuple[str, str]:
    """Return (resume_text, resume_key) for the best-matching resume.

    Args:
        job_title:       The normalised job title.
        job_description: The job description (used for tie-breaking).

    Returns:
        A tuple of (resume_text, resume_key) where resume_key is one of
        'aiml', 'data', 'backend', 'main'.
    """
    combined = f"{job_title} {job_description}".strip()

    best = None
    best_priority = -1

    for resume_def in _RESUMES:
        if resume_def["patterns"].search(combined):
            if resume_def["priority"] > best_priority:
                best = resume_def
                best_priority = resume_def["priority"]

    # 'main' always matches, so best is never None
    assert best is not None
    return _read(best["path"]), best["key"]


def all_resumes() -> dict[str, str]:
    """Return all four resume texts keyed by resume_key."""
    return {r["key"]: _read(r["path"]) for r in _RESUMES}
