"""
screener.py — Gemini-powered screening answer generator.

Given a job description, resume text, and candidate profile constants,
generates truthful answers to screening questions found in the job description.

Rules:
  - Only use facts present in the resume and CANDIDATE_PROFILE.
  - Never invent qualifications, achievements, metrics or salary figures.
  - Classify each answer as HIGH / LOW / NEEDS_MANUAL_REVIEW confidence.
  - Any sensitive question (demographic, disability, criminal, salary, visa,
    legal attestation, work-authorization) is always NEEDS_MANUAL_REVIEW.
"""
from __future__ import annotations

import json
import logging
import re
import textwrap
import urllib.request
import urllib.error
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from apply_agent.models import (
    Answer,
    AnswerConfidence,
    CANDIDATE_PROFILE,
    SENSITIVE_QUESTION_PATTERNS,
)

logger = logging.getLogger(__name__)


def _is_sensitive(question: str) -> bool:
    q = question.lower()
    return any(pat in q for pat in SENSITIVE_QUESTION_PATTERNS)


def _gemini(prompt: str) -> str:
    """Raw HTTP call to Gemini — same approach as ranker.py."""
    key = config.GEMINI_API_KEY
    model = config.GEMINI_MODEL
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    body = json.dumps(
        {"contents": [{"parts": [{"text": prompt}]}]},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except urllib.error.HTTPError as exc:
        body_err = exc.read().decode("utf-8", errors="replace")[:200]
        raise Exception(f"Gemini HTTP {exc.code}: {body_err}") from exc


def _extract_questions(description: str) -> list[str]:
    """
    Extract screening questions from a job description.

    Looks for lines that:
    - End with "?" (direct questions)
    - Contain "required", "must have", "do you have" patterns
    Returns deduplicated list (max 20).
    """
    sentences = re.split(r"[.\n]", description)
    questions = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        lower = s.lower()
        if s.endswith("?"):
            questions.append(s)
        elif any(pat in lower for pat in [
            "do you have", "are you", "can you", "will you",
            "are you willing", "do you require", "do you need",
        ]):
            if "?" not in s:
                questions.append(s + "?")
            else:
                questions.append(s)
    # Deduplicate preserving order
    seen: set[str] = set()
    unique = []
    for q in questions:
        norm = q.lower().strip()
        if norm not in seen:
            seen.add(norm)
            unique.append(q)
    return unique[:20]


def _build_screening_prompt(
    resume: str,
    questions: list[str],
    job_title: str,
    company: str,
) -> str:
    profile_str = json.dumps(CANDIDATE_PROFILE, ensure_ascii=False, indent=2)
    q_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))

    return textwrap.dedent("""
    You are helping a job applicant answer screening questions honestly.
    Use ONLY the resume and profile below. Never invent facts.

    CANDIDATE PROFILE:
    {profile}

    RESUME:
    {resume}

    JOB: {title} at {company}

    SCREENING QUESTIONS:
    {questions}

    For each question return a JSON array:
    [
      {{
        "question_index": <1-based int>,
        "answer": <string answer or null if truly unknown>,
        "confidence": "HIGH" | "LOW" | "NEEDS_MANUAL_REVIEW",
        "reasoning": <one sentence why>
      }}
    ]

    RULES:
    - years_experience: always 0 (fresher, one 6-month internship)
    - graduation_year: 2027
    - work_authorization: "Indian citizen, eligible to work in India"
    - For remote roles: candidate is in India, no visa needed for India-based remote work
    - If truly unknown → answer: null, confidence: NEEDS_MANUAL_REVIEW
    - Salary questions → always NEEDS_MANUAL_REVIEW (never guess)
    - Return ONLY valid JSON array, no fences, no explanation.
    """).strip().format(
        profile=profile_str,
        resume=resume,
        title=job_title,
        company=company,
        questions=q_text,
    )


def generate_answers(
    job_title: str,
    company: str,
    description: str,
    resume_text: str,
) -> list[Answer]:
    """
    Extract questions from description and generate honest answers.

    Returns a list of Answer objects. Sensitive questions are always
    marked NEEDS_MANUAL_REVIEW regardless of Gemini output.
    """
    questions = _extract_questions(description)
    if not questions:
        logger.debug("Screener: no questions extracted from description")
        return []

    # Pre-mark sensitive questions before Gemini call
    sensitive_flags = {i: _is_sensitive(q) for i, q in enumerate(questions)}
    sensitive_indices = {i for i, flag in sensitive_flags.items() if flag}

    # Only send non-sensitive questions to Gemini
    non_sensitive = [(i, q) for i, q in enumerate(questions) if i not in sensitive_indices]

    answers: list[Answer] = []

    if non_sensitive:
        prompt = _build_screening_prompt(
            resume_text,
            [q for _, q in non_sensitive],
            job_title,
            company,
        )
        try:
            raw = _gemini(prompt)
            # Strip fences
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(raw.strip())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Screener: Gemini failed: %s", exc)
            parsed = []

        # Map back from local indices to original question list
        idx_map = {local + 1: orig_i for local, (orig_i, _) in enumerate(non_sensitive)}
        for item in parsed:
            local_idx = item.get("question_index", 0)
            orig_idx = idx_map.get(local_idx)
            if orig_idx is None:
                continue
            conf_str = item.get("confidence", "NEEDS_MANUAL_REVIEW")
            try:
                conf = AnswerConfidence(conf_str)
            except ValueError:
                conf = AnswerConfidence.NEEDS_MANUAL_REVIEW

            answers.append(Answer(
                question=questions[orig_idx],
                answer=item.get("answer"),
                confidence=conf,
                source="generated",
                is_sensitive=False,
            ))

    # Add sensitive questions as NEEDS_MANUAL_REVIEW
    answered_indices = {
        questions.index(a.question)
        for a in answers
        if a.question in questions
    }
    for orig_idx, q in enumerate(questions):
        if orig_idx in sensitive_indices or orig_idx not in answered_indices:
            answers.append(Answer(
                question=q,
                answer=None,
                confidence=AnswerConfidence.NEEDS_MANUAL_REVIEW,
                source="manual",
                is_sensitive=orig_idx in sensitive_indices,
            ))

    logger.info(
        "Screener: %d questions, %d answered, %d need manual review",
        len(questions),
        sum(1 for a in answers if a.confidence != AnswerConfidence.NEEDS_MANUAL_REVIEW),
        sum(1 for a in answers if a.confidence == AnswerConfidence.NEEDS_MANUAL_REVIEW),
    )
    return answers
