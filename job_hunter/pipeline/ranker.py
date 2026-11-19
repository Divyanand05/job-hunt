"""
ranker.py — Rank jobs using Gemini API and return the top N with AI analysis.

Each job is matched against the MOST RELEVANT of the four tailored resumes
(selected by resume_selector.select_resume).  Jobs in the same batch that
share the same resume are grouped and sent in a single Gemini call to
minimise API usage.

For each job Gemini scores (0–100):
  - Resume match (skills overlap)
  - Experience level fit (fresher/entry-level priority)
  - India / remote eligibility

For the top-ranked job it also generates:
  - 3 bullet points: why I qualify
  - Missing skills (if any)
  - Tailored single-paragraph cover note

Important constraints (enforced in the prompt):
  - Never invent resume achievements, salary details or job requirements.
  - Only use facts present in the resume and job description.
"""
from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass, field
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config
from job_hunter.collectors.base import JobListing
from job_hunter.pipeline.resume_selector import select_resume

logger = logging.getLogger(__name__)


@dataclass
class RankedJob:
    job: JobListing
    score: int                          # 0–100
    match_reasons: list = field(default_factory=list)
    missing_skills: list = field(default_factory=list)
    cover_note: Optional[str] = None    # only for the #1 job
    resume_used: str = "main"           # which resume was selected


def _build_scoring_prompt(resume: str, jobs: list, job_indices: list) -> str:
    """Build a scoring prompt for a list of jobs (may be a subset)."""
    job_blocks = []
    for local_i, (abs_idx, job) in enumerate(zip(job_indices, jobs), start=1):
        desc = (job.description or "")[:800]
        job_blocks.append(
            "JOB {local_i} (index {abs_idx}):\n"
            "  Title: {title}\n"
            "  Company: {company}\n"
            "  Location: {location}\n"
            "  Salary: {salary}\n"
            "  Source: {source}\n"
            "  Description excerpt: {desc}\n".format(
                local_i=local_i,
                abs_idx=abs_idx,
                title=job.title,
                company=job.company,
                location=job.location,
                salary=job.salary or "not specified",
                source=job.source,
                desc=desc,
            )
        )
    jobs_text = "\n".join(job_blocks)

    return textwrap.dedent("""
    You are a career advisor helping a FRESHER candidate (2027 B.Tech graduate,
    6-month internship, 0 years full-time experience) match jobs to their resume.

    RESUME:
    {resume}

    JOBS TO EVALUATE:
    {jobs_text}

    TASK:
    For each job listed above, return a JSON array where each element has:
    {{
      "job_index": <the abs_idx value shown in parentheses above>,
      "score": <integer 0-100>,
      "match_reasons": [<up to 3 bullet strings explaining why candidate qualifies>],
      "missing_skills": [<skills mentioned in job but absent from resume, max 3>]
    }}

    SCORING RULES — apply in this exact order:

    STEP 1 — EXPERIENCE CHECK (most important):
    - If job requires 0 years / fresher / intern / entry-level / no experience → eligible, continue scoring.
    - If job has NO experience requirement mentioned → eligible, continue scoring.
    - If job requires 1 year → eligible but penalise 10 points.
    - If job requires 2+ years → score MAXIMUM 25. Stop here.
    - If job title has Senior / Lead / Staff / Principal → score MAXIMUM 20. Stop here.

    STEP 2 — SKILLS MATCH (if eligible from Step 1):
    - Count how many required skills appear in the resume.
    - 90–100: 80%+ skills match AND fresher/entry-level/intern role.
    - 70–89:  60–79% skills match, entry-level or unspecified experience.
    - 50–69:  40–59% skills match, candidate can grow into role.
    - 30–49:  Less than 40% skills match.
    - 0–29:   Very poor match or senior role.

    STEP 3 — BONUS POINTS (add to Step 2 score, max total 100):
    - +10 if job explicitly says fresher / fresh graduate / 2027 / campus hire.
    - +5  if role is internship.
    - +5  if location is India / Remote / Worldwide.
    - +5  if job mentions Python and candidate has Python.

    CANDIDATE PROFILE (never invent beyond this):
    - B.Tech AI & Data Science, 2027 graduate, CGPA 7.95
    - 6-month internship at CloudCouch Tech (Oct 2025 – Apr 2026): REST APIs, PostgreSQL, Flask
    - Projects: Docvault (RAG/FAISS/AWS Lambda), AuraVision Guard (YOLOv8/OpenCV), AI CRM (Node/PostgreSQL)
    - Skills: Python, SQL, Pandas, Flask, FastAPI, PostgreSQL, MongoDB, AWS Lambda, FAISS, TF-IDF, OpenCV, YOLOv8, Git
    - 0 years full-time experience. Fresher. Available immediately.

    STRICT RULES:
    - Only cite skills and facts from the resume above.
    - Do NOT invent qualifications, achievements or requirements.
    - Return ONLY valid JSON array (no markdown fences, no explanation).
    """).strip().format(resume=resume, jobs_text=jobs_text)


def _build_cover_prompt(resume: str, job: JobListing, match_reasons: list) -> str:
    desc = (job.description or "")[:1000]
    reasons = "\n".join("- {}".format(r) for r in match_reasons)
    return textwrap.dedent("""
    Write a concise, honest cover note (3-4 sentences, max 100 words) for this job
    application.  Use ONLY facts from the resume below.  Do NOT invent achievements,
    metrics or skills not in the resume.  Address it to "Hiring Team".

    JOB:
      Title: {title}
      Company: {company}
      Description excerpt: {desc}

    RESUME:
    {resume}

    WHY I QUALIFY (from previous analysis):
    {reasons}

    Return ONLY the cover note text -- no preamble, no sign-off.
    """).strip().format(
        title=job.title,
        company=job.company,
        desc=desc,
        resume=resume,
        reasons=reasons,
    )


def _create_client():
    """Create a simple HTTP-based Gemini client (avoids SDK timeout issues)."""
    import urllib.request
    import urllib.error

    api_key = config.GEMINI_API_KEY

    class _Client:
        def generate(self, model: str, prompt: str) -> str:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            body = json.dumps(
                {"contents": [{"parts": [{"text": prompt}]}]},
                ensure_ascii=False,
            ).encode("utf-8")
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                    return data["candidates"][0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as _he:
                err_body = _he.read().decode("utf-8", errors="replace")[:300]
                raise Exception(f"HTTP {_he.code} from Gemini: {err_body}") from _he

    return _Client()


def _generate(client, model: str, prompt: str) -> str:
    return client.generate(model, prompt)


def _parse_gemini_json(raw_text: str) -> list:
    """Strip markdown fences and parse JSON."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


def rank_jobs(jobs: list, top_n: int = 5) -> list:
    if not jobs:
        logger.info("Ranker: no jobs to rank")
        return []

    client = _create_client()
    model = config.GEMINI_MODEL

    # ------------------------------------------------------------------
    # Step 1: Assign each job its best-matching resume
    # ------------------------------------------------------------------
    job_resumes: list[tuple[int, JobListing, str, str]] = []  # (1-based idx, job, resume_text, resume_key)
    for idx, job in enumerate(jobs, start=1):
        resume_text, resume_key = select_resume(job.title, job.description or "")
        job_resumes.append((idx, job, resume_text, resume_key))
        logger.debug("Job %d '%s' → resume '%s'", idx, job.title, resume_key)

    # ------------------------------------------------------------------
    # Step 2: Group by resume_key and batch within each group
    # ------------------------------------------------------------------
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for item in job_resumes:
        groups[item[3]].append(item)  # group by resume_key

    all_scores: dict[int, dict] = {}  # abs_idx → score data

    BATCH_SIZE = 10

    for resume_key, group_items in groups.items():
        resume_text = group_items[0][2]  # all items in group share the same resume
        logger.info(
            "Ranker: scoring %d jobs with resume '%s'", len(group_items), resume_key
        )

        for batch_start in range(0, len(group_items), BATCH_SIZE):
            batch = group_items[batch_start: batch_start + BATCH_SIZE]
            abs_indices = [item[0] for item in batch]
            batch_jobs = [item[1] for item in batch]

            prompt = _build_scoring_prompt(resume_text, batch_jobs, abs_indices)

            try:
                raw_text = _generate(client, model, prompt)
                parsed = _parse_gemini_json(raw_text)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "Ranker: JSON parse failed for resume '%s' batch: %s", resume_key, exc
                )
                for abs_idx in abs_indices:
                    all_scores[abs_idx] = {
                        "score": 0,
                        "match_reasons": ["AI scoring unavailable"],
                        "missing_skills": [],
                    }
                continue
            except Exception as exc:  # noqa: BLE001
                logger.error("Ranker: Gemini API error: %s", exc)
                continue

            for item in parsed:
                abs_idx = int(item.get("job_index", 0))
                if abs_idx in {i[0] for i in batch}:
                    all_scores[abs_idx] = {
                        "score": int(item.get("score", 0)),
                        "match_reasons": item.get("match_reasons", []),
                        "missing_skills": item.get("missing_skills", []),
                    }

    # ------------------------------------------------------------------
    # Step 3: Build RankedJob list
    # ------------------------------------------------------------------
    ranked: list[RankedJob] = []
    for idx, job, resume_text, resume_key in job_resumes:
        score_data = all_scores.get(idx, {"score": 0, "match_reasons": [], "missing_skills": []})
        ranked.append(
            RankedJob(
                job=job,
                score=score_data["score"],
                match_reasons=score_data["match_reasons"],
                missing_skills=score_data["missing_skills"],
                resume_used=resume_key,
            )
        )

    ranked.sort(key=lambda r: r.score, reverse=True)
    top = ranked[:top_n]

    # ------------------------------------------------------------------
    # Step 4: Cover note for the #1 job using its selected resume
    # ------------------------------------------------------------------
    if top:
        best = top[0]
        best_resume_text, _ = select_resume(best.job.title, best.job.description or "")
        try:
            cover_prompt = _build_cover_prompt(
                best_resume_text, best.job, best.match_reasons
            )
            best.cover_note = _generate(client, model, cover_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ranker: failed to generate cover note: %s", exc)
            best.cover_note = None

    logger.info("Ranker: scored %d jobs; returning top %d", len(jobs), len(top))
    return top
