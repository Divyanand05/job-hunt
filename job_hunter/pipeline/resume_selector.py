"""
resume_selector.py — Evidence-based resume selection.

Scores ALL three tailored resumes against every job by counting how many
skill/responsibility keywords from the job description appear in each resume.
The resume with the highest evidence count wins. Ties broken by specificity.

This replaces the previous keyword-priority approach (W5 fix).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

# ---------------------------------------------------------------------------
# Resume definitions
# ---------------------------------------------------------------------------
_RESUMES = [
    {
        "key": "aiml",
        "path": config.DATA_DIR / "resume_aiml.txt",
        "specificity": 3,   # tie-break: higher = preferred
        "domain_keywords": re.compile(
            r"\b(machine learning|deep learning|computer vision|nlp|"
            r"neural network|yolo|object detection|llm|rag|faiss|"
            r"transformers|pytorch|tensorflow|opencv|generative ai|"
            r"diffusion|multimodal|reinforcement|ai engineer|ml engineer|"
            r"model training|inference|embedding|vector|classification)\b",
            re.IGNORECASE,
        ),
    },
    {
        "key": "data",
        "path": config.DATA_DIR / "resume_data.txt",
        "specificity": 3,
        "domain_keywords": re.compile(
            r"\b(data analyst|data engineer|sql|etl|pipeline|power bi|"
            r"tableau|dbt|spark|hadoop|airflow|looker|data warehouse|"
            r"data quality|reconciliation|anomaly detection|pandas|"
            r"excel|bi developer|analytics engineer|business analyst|"
            r"reporting|dashboard|kpi|data validation|data modeling)\b",
            re.IGNORECASE,
        ),
    },
    {
        "key": "backend",
        "path": config.DATA_DIR / "resume_backend.txt",
        "specificity": 2,
        "domain_keywords": re.compile(
            r"\b(backend|rest api|fastapi|flask|django|node\.?js|express|"
            r"microservice|postgresql|mongodb|mysql|supabase|aws lambda|"
            r"s3|dynamodb|api development|server.?side|web service|"
            r"authentication|database schema|system design|mcp)\b",
            re.IGNORECASE,
        ),
    },
    {
        "key": "main",
        "path": config.DATA_DIR / "resume_main.txt",
        "specificity": 1,
        "domain_keywords": re.compile(r".", re.IGNORECASE),  # always matches
    },
]

_cache: dict[str, str] = {}


def _read(path: Path) -> str:
    key = str(path)
    if key not in _cache:
        if not path.exists():
            raise FileNotFoundError(
                f"Resume file not found: {path}. "
                "Make sure data/resume_*.txt files exist."
            )
        _cache[key] = path.read_text(encoding="utf-8").strip()
    return _cache[key]


def _count_evidence(job_text: str, resume_text: str) -> int:
    """
    Count how many unique words from the job text appear in the resume text.
    Uses token overlap: tokenize job text, count how many tokens exist in resume.
    """
    # Extract meaningful words (3+ chars) from job text
    job_words = set(re.findall(r"\b[a-zA-Z][a-zA-Z0-9+#.-]{2,}\b", job_text.lower()))
    resume_lower = resume_text.lower()
    # Count how many job words appear in resume
    return sum(1 for w in job_words if w in resume_lower)


def select_resume(job_title: str, job_description: str = "") -> tuple[str, str]:
    """
    Return (resume_text, resume_key) for the best-supported resume.

    Selection logic:
    1. For each non-main resume, check if its domain keywords appear in the job.
    2. Among matching resumes, count token overlap with the job text.
    3. Highest overlap wins. Ties broken by specificity.
    4. If no domain keywords match, fall back to main resume.
    """
    combined_job = f"{job_title} {job_description}".strip()

    candidates = []
    for r in _RESUMES:
        if r["key"] == "main":
            continue
        # Check domain match first (fast gate)
        if r["domain_keywords"].search(combined_job):
            evidence = _count_evidence(combined_job, _read(r["path"]))
            candidates.append((evidence, r["specificity"], r))

    if not candidates:
        # No domain match — use main resume
        main = next(r for r in _RESUMES if r["key"] == "main")
        return _read(main["path"]), "main"

    # Sort by evidence DESC, then specificity DESC
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = candidates[0][2]
    return _read(best["path"]), best["key"]


def select_best_resume_for_job(job_title: str, job_description: str = "") -> dict:
    """
    Extended version: returns scores for ALL resumes for transparency.

    Returns dict with keys: selected_key, scores (dict of key → score), resume_text
    """
    combined_job = f"{job_title} {job_description}".strip()
    scores = {}

    for r in _RESUMES:
        if r["key"] == "main":
            scores["main"] = 0
            continue
        if r["domain_keywords"].search(combined_job):
            scores[r["key"]] = _count_evidence(combined_job, _read(r["path"]))
        else:
            scores[r["key"]] = 0

    best_key = max(scores, key=lambda k: (scores[k], next(
        r["specificity"] for r in _RESUMES if r["key"] == k
    )))

    if scores[best_key] == 0:
        best_key = "main"

    return {
        "selected_key": best_key,
        "scores": scores,
        "resume_text": _read(next(r["path"] for r in _RESUMES if r["key"] == best_key)),
    }


def all_resumes() -> dict[str, str]:
    return {r["key"]: _read(r["path"]) for r in _RESUMES}
