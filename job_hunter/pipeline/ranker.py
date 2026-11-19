"""
ranker.py — Structured 5-dimension AI scoring using Gemini.

Scoring dimensions (100 points total):
  Required technical skills   35 pts
  Experience & graduation     25 pts
  Relevant projects/evidence  20 pts
  Role & location alignment   15 pts
  Preferred skills             5 pts

Gemini returns structured JSON with:
  score_breakdown, evidence, missing_mandatory, uncertainty, recommendation

Rules:
  - Mandatory failures cap total score (never overridden by bonuses)
  - uncertainty=high → flagged for manual review regardless of score
  - Only facts from resume are cited
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
class ScoreBreakdown:
    skills: int = 0           # /35
    experience: int = 0       # /25
    projects: int = 0         # /20
    role_location: int = 0    # /15
    preferred: int = 0        # /5
    total: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "ScoreBreakdown":
        return cls(
            skills=int(d.get("skills", 0)),
            experience=int(d.get("experience", 0)),
            projects=int(d.get("projects", 0)),
            role_location=int(d.get("role_location", 0)),
            preferred=int(d.get("preferred", 0)),
            total=int(d.get("total", 0)),
        )


@dataclass
class RankedJob:
    job: JobListing
    score: int                              # 0–100 total
    score_breakdown: Optional[ScoreBreakdown] = None
    match_reasons: list = field(default_factory=list)
    missing_skills: list = field(default_factory=list)
    missing_mandatory: list = field(default_factory=list)
    uncertainty: str = "low"               # low | medium | high
    recommendation: str = "apply"          # apply | review | skip
    cover_note: Optional[str] = None
    resume_used: str = "main"


def _build_scoring_prompt(resume: str, jobs: list, job_indices: list) -> str:
    job_blocks = []
    for local_i, (abs_idx, job) in enumerate(zip(job_indices, jobs), start=1):
        desc = (job.description or "")[:1000]
        job_blocks.append(
            "JOB {li} (index {ai}):\n"
            "  Title: {title}\n  Company: {company}\n"
            "  Location: {loc}\n  Source: {src}\n"
            "  Description: {desc}\n".format(
                li=local_i, ai=abs_idx,
                title=job.title, company=job.company,
                loc=job.location, src=job.source,
                desc=desc,
            )
        )
    jobs_text = "\n".join(job_blocks)

    return textwrap.dedent("""
    You are evaluating job-candidate fit for a FRESHER (2027 B.Tech graduate).

    CANDIDATE RESUME:
    {resume}

    CANDIDATE FACTS (do not invent beyond these):
    - B.Tech AI & Data Science, Sri Manakula Vinayagar Engineering College, 2027
    - CGPA: 7.95 | Graduating: 2027 | 0 years full-time experience
    - Internship: CloudCouch Tech Oct 2025–Apr 2026 (REST APIs, PostgreSQL, Flask, Razorpay, Maps API)
    - Projects: Docvault (RAG/FAISS/AWS Lambda/Groq), AuraVision Guard (YOLOv8/OpenCV/MiDaS),
      Smart Campus AI (Flask/TF-IDF/MCP/Supabase), AI CRM (Node.js/PostgreSQL/MongoDB/OpenAI),
      DecisionTrace AI (Python/PostgreSQL/Pandas/Power BI),
      Claims Data Quality Monitor (FastAPI/scikit-learn)
    - Skills: Python, SQL, Pandas, Flask, FastAPI, PostgreSQL, MongoDB, MySQL, Supabase,
      AWS Lambda, S3, DynamoDB, FAISS, TF-IDF, OpenCV, YOLOv8, MiDaS, Git, GitHub,
      Power BI, Excel, React.js, Node.js, Express.js, Flutter, Groq API
    - Certifications: AWS Cloud Foundations, AWS ML Foundations, AWS GenAI Foundations,
      IBM Computer Vision, NPTEL Python for Data Science
    - Publication: Docvault — IMJRSET Mar 2026
    - Hackathons: Special Mention CloudCouch, Top 10 Tech-a-thon

    JOBS TO SCORE:
    {jobs_text}

    TASK:
    For each job, return a JSON array. Each element must have EXACTLY this structure:
    {{
      "job_index": <abs_idx integer>,
      "score_breakdown": {{
        "skills": <0-35, required technical skills match>,
        "experience": <0-25, experience/graduation eligibility>,
        "projects": <0-20, relevant project evidence>,
        "role_location": <0-15, role type + India/remote alignment>,
        "preferred": <0-5, preferred/nice-to-have skills>
      }},
      "total_score": <sum of above, 0-100>,
      "match_reasons": [<up to 3 specific evidence strings from resume>],
      "missing_mandatory": [<required skills/quals not in resume, max 3>],
      "missing_preferred": [<preferred skills not in resume, max 2>],
      "uncertainty": "<low|medium|high>",
      "recommendation": "<apply|review|skip>"
    }}

    SCORING RULES:

    skills (0-35):
      35 = all required technical skills present in resume
      25 = 75%+ required skills present
      15 = 50%+ required skills present
      5  = less than 50% required skills

    experience (0-25):
      25 = job is fresher/intern/0-1yr AND candidate is 2027 graduate
      20 = job says entry-level or no experience requirement stated
      10 = job requires 1 year (candidate has 6-month internship — partial)
      0  = job requires 2+ years → MANDATORY FAILURE, cap total at 20

    projects (0-20):
      20 = candidate has a directly relevant project using required stack
      15 = candidate has a partially relevant project
      5  = candidate has tangential projects only
      0  = no relevant project evidence

    role_location (0-15):
      15 = exact role match + India/remote eligible
      10 = role match + location unspecified (possible India)
      5  = adjacent role + India eligible
      0  = location blocks India applicants → MANDATORY FAILURE, cap total at 10

    preferred (0-5):
      5 = has 2+ preferred/nice-to-have skills
      3 = has 1 preferred skill
      0 = none

    MANDATORY FAILURE RULE:
    - If experience score = 0 (requires 2+ years): total_score = min(total, 20)
    - If location blocks India: total_score = min(total, 10)
    - Bonuses from projects/preferred CANNOT override mandatory failures

    uncertainty:
      "low"    = clear requirements, clear evidence
      "medium" = some requirements ambiguous or unspecified
      "high"   = cannot determine eligibility from description alone

    recommendation:
      "apply"  = total_score >= 75 AND uncertainty != "high"
      "review" = total_score 50-74 OR uncertainty = "high"
      "skip"   = total_score < 50

    STRICT RULES:
    - Only cite facts present in the CANDIDATE RESUME/FACTS above
    - Do NOT invent qualifications, metrics, years of experience, or achievements
    - Return ONLY valid JSON array, no markdown fences, no explanation text
    """).strip().format(resume=resume, jobs_text=jobs_text)


def _build_cover_prompt(resume: str, job: JobListing, match_reasons: list) -> str:
    desc = (job.description or "")[:1000]
    reasons = "\n".join(f"- {r}" for r in match_reasons)
    return textwrap.dedent("""
    Write a concise cover note (3-4 sentences, max 100 words) for this fresher application.
    Use ONLY facts from the resume below. Do NOT invent achievements, metrics or skills.
    Address it to "Hiring Team".

    JOB: {title} at {company}
    Description: {desc}

    RESUME:
    {resume}

    EVIDENCE OF FIT:
    {reasons}

    Return ONLY the cover note text — no preamble, no sign-off.
    """).strip().format(
        title=job.title, company=job.company,
        desc=desc, resume=resume, reasons=reasons,
    )


def _create_client():
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
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                    return data["candidates"][0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as exc:
                body_err = exc.read().decode("utf-8", errors="replace")[:300]
                raise Exception(f"Gemini HTTP {exc.code}: {body_err}") from exc

    return _Client()


def _generate(client, model: str, prompt: str) -> str:
    return client.generate(model, prompt)


def _parse_gemini_json(raw_text: str) -> list:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text.strip())


def rank_jobs(jobs: list, top_n: int = 5) -> list:
    if not jobs:
        logger.info("Ranker: no jobs to rank")
        return []

    client = _create_client()
    model = config.GEMINI_MODEL

    # Assign resume to each job (evidence-based)
    job_resumes: list[tuple[int, JobListing, str, str]] = []
    for idx, job in enumerate(jobs, start=1):
        resume_text, resume_key = select_resume(job.title, job.description or "")
        job_resumes.append((idx, job, resume_text, resume_key))
        logger.debug("Job %d '%s' → resume '%s'", idx, job.title, resume_key)

    # Group by resume_key, batch 10
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for item in job_resumes:
        groups[item[3]].append(item)

    all_scores: dict[int, dict] = {}
    BATCH_SIZE = 10

    for resume_key, group_items in groups.items():
        resume_text = group_items[0][2]
        logger.info("Ranker: scoring %d jobs with resume '%s'", len(group_items), resume_key)

        for batch_start in range(0, len(group_items), BATCH_SIZE):
            batch = group_items[batch_start: batch_start + BATCH_SIZE]
            abs_indices = [item[0] for item in batch]
            batch_jobs = [item[1] for item in batch]
            prompt = _build_scoring_prompt(resume_text, batch_jobs, abs_indices)

            try:
                raw_text = _generate(client, model, prompt)
                parsed = _parse_gemini_json(raw_text)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Ranker: JSON parse failed for '%s': %s", resume_key, exc)
                for abs_idx in abs_indices:
                    all_scores[abs_idx] = {"total_score": 0, "match_reasons": ["AI scoring unavailable"],
                                           "missing_mandatory": [], "missing_preferred": [],
                                           "uncertainty": "high", "recommendation": "review",
                                           "score_breakdown": {}}
                continue
            except Exception as exc:  # noqa: BLE001
                logger.error("Ranker: Gemini error: %s", exc)
                continue

            # Build a lookup from abs_idx → job object for this batch
            idx_to_job = {item[0]: item[1] for item in batch}

            for item in parsed:
                abs_idx = int(item.get("job_index", 0))
                if abs_idx in idx_to_job:
                    bd = item.get("score_breakdown", {})
                    total = int(item.get("total_score", sum(int(v) for v in bd.values()) if bd else 0))
                    exp_score = int(bd.get("experience", 25))
                    loc_score = int(bd.get("role_location", 15))
                    if exp_score == 0 and total > 20:
                        job_obj = idx_to_job[abs_idx]
                        desc_lower = (job_obj.description or "").lower()
                        has_explicit_exp = any(p in desc_lower for p in [
                            "2 year", "3 year", "4 year", "5 year",
                            "2+ year", "3+ year", "minimum 2", "at least 2"
                        ])
                        if has_explicit_exp:
                            total = min(total, 20)
                    if loc_score == 0:
                        total = min(total, 10)
                    item["total_score"] = total
                    all_scores[abs_idx] = item

    # Build RankedJob list
    ranked: list[RankedJob] = []
    for idx, job, resume_text, resume_key in job_resumes:
        s = all_scores.get(idx, {})
        bd_dict = s.get("score_breakdown", {})
        total = int(s.get("total_score", 0))

        ranked.append(RankedJob(
            job=job,
            score=total,
            score_breakdown=ScoreBreakdown.from_dict(bd_dict) if bd_dict else None,
            match_reasons=s.get("match_reasons", []),
            missing_skills=s.get("missing_preferred", []),
            missing_mandatory=s.get("missing_mandatory", []),
            uncertainty=s.get("uncertainty", "low"),
            recommendation=s.get("recommendation", "review"),
            resume_used=resume_key,
        ))

    ranked.sort(key=lambda r: r.score, reverse=True)
    top = ranked[:top_n]

    # Cover note for #1 job
    if top:
        best = top[0]
        best_resume_text, _ = select_resume(best.job.title, best.job.description or "")
        try:
            best.cover_note = _generate(
                client, model,
                _build_cover_prompt(best_resume_text, best.job, best.match_reasons),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ranker: cover note failed: %s", exc)

    logger.info("Ranker: scored %d jobs; top %d (scores: %s)",
                len(jobs), len(top), [r.score for r in top])
    return top
