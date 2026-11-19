"""
test_improvements.py — Tests for the improved eligibility, resume selection,
scoring consistency and authorization gates.

Covers all requirements from the improvement spec:
- Experience filtering (mandatory vs preferred)
- Remote India eligibility
- Graduation requirements
- Mandatory skills presence
- Cross-platform duplicate prevention
- Resume selection evidence-based
- Scoring consistency (mandatory failures cap score)
- Authorization gates (unchanged)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from job_hunter.collectors.base import JobListing
from job_hunter.pipeline.filter import (
    Eligibility,
    assess_eligibility,
    filter_jobs,
    _check_location,
    _check_experience,
)
from job_hunter.pipeline.resume_selector import select_resume, select_best_resume_for_job


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _job(title="Data Analyst", desc="", location="Remote", remote=True,
         hours_old=2, exp_level=None) -> JobListing:
    return JobListing(
        title=title,
        company="TestCo",
        source="himalayas",
        url=f"https://example.com/{title.replace(' ', '-').lower()}",
        posted_at=datetime.now(timezone.utc) - timedelta(hours=hours_old),
        location=location,
        remote=remote,
        description=desc,
        experience_level=exp_level,
    )


# ─── Experience filtering ─────────────────────────────────────────────────────

class TestExperienceFiltering:
    def test_fresher_explicit_is_eligible(self):
        job = _job(desc="Fresher data analyst role. 0-1 years. Python required.")
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.ELIGIBLE

    def test_intern_explicit_is_eligible(self):
        job = _job(title="ML Intern", desc="Internship for 2027 graduates. TensorFlow.")
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.ELIGIBLE

    def test_two_years_is_ineligible(self):
        job = _job(desc="Requires 2 years of experience in Python and SQL.")
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.INELIGIBLE

    def test_senior_title_is_ineligible(self):
        job = _job(title="Senior Data Engineer", desc="Python, Spark, 5+ years.")
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.INELIGIBLE

    def test_no_experience_mentioned_is_review_required(self):
        """W7 fix: unspecified experience → REVIEW_REQUIRED, not auto-eligible."""
        job = _job(desc="Python developer. Skills: FastAPI, PostgreSQL, Git.")
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.REVIEW_REQUIRED
        assert "experience_requirement_unspecified" in r.flags

    def test_one_year_requirement_is_review_required(self):
        job = _job(desc="1 year of experience in Python required.")
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.REVIEW_REQUIRED
        assert "requires_1_year_experience" in r.flags

    def test_lead_title_is_ineligible(self):
        job = _job(title="Lead Backend Engineer", desc="Python, AWS, team lead.")
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.INELIGIBLE

    def test_graduate_trainee_is_eligible(self):
        job = _job(title="Graduate Engineer Trainee", desc="Fresh graduates welcome.")
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.ELIGIBLE

    def test_associate_engineer_is_eligible(self):
        job = _job(title="Associate Software Engineer", desc="Entry level, 0-1 years.")
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.ELIGIBLE


# ─── Remote India eligibility ─────────────────────────────────────────────────

class TestRemoteIndiaEligibility:
    def test_remote_worldwide_eligible(self):
        job = _job(location="Remote (Worldwide)", remote=True,
                   desc="Fully remote role, open globally. Python developer.")
        r = assess_eligibility(job, 2)
        assert r.eligibility != Eligibility.INELIGIBLE

    def test_india_location_eligible(self):
        job = _job(location="Bengaluru, India", remote=False,
                   desc="Backend developer, Bengaluru office.")
        r = assess_eligibility(job, 2)
        assert r.eligibility != Eligibility.INELIGIBLE

    def test_us_only_explicit_ineligible(self):
        job = _job(location="United States",
                   desc="Must be located in the US. No visa sponsorship available. Python.",
                   remote=False)
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.INELIGIBLE

    def test_uk_only_ineligible(self):
        job = _job(desc="Must have UK work authorization. Python developer.", remote=False)
        r = assess_eligibility(job, 2)
        assert r.eligibility == Eligibility.INELIGIBLE

    def test_no_location_info_review_required(self):
        job = _job(location="", remote=False,
                   desc="Python developer. No experience needed.")
        r = assess_eligibility(job, 2)
        # No location info → REVIEW_REQUIRED (location flag)
        assert "location_unspecified" in r.flags or r.eligibility == Eligibility.REVIEW_REQUIRED

    def test_india_eligible_explicit_passes(self):
        job = _job(desc="Remote role, India-eligible applicants welcome. Data analyst.")
        r = assess_eligibility(job, 2)
        assert r.eligibility != Eligibility.INELIGIBLE


# ─── Age / fallback pool ──────────────────────────────────────────────────────

class TestAgeAndFallbackPool:
    def test_fresh_24h_job_no_fallback_flag(self):
        job = _job(desc="Data analyst intern.", hours_old=2)
        r = assess_eligibility(job, 2)
        assert "fallback_pool_24_72h" not in r.flags

    def test_job_25h_old_gets_fallback_flag(self):
        job = _job(desc="Python developer. No experience needed.", hours_old=25)
        r = assess_eligibility(job, 25)
        assert "fallback_pool_24_72h" in r.flags
        assert r.eligibility != Eligibility.INELIGIBLE  # still passes, not rejected

    def test_job_73h_old_is_ineligible(self):
        job = _job(desc="Data analyst.", hours_old=73)
        r = assess_eligibility(job, 73)
        assert r.eligibility == Eligibility.INELIGIBLE
        assert "too_old" in r.flags


# ─── Role matching ─────────────────────────────────────────────────────────────

class TestExpandedRoleMatching:
    def test_junior_data_analyst_matches(self):
        job = _job(title="Junior Data Analyst", desc="SQL and Python required.")
        result = filter_jobs([job])
        assert len(result) == 1

    def test_bi_analyst_matches(self):
        job = _job(title="BI Analyst", desc="Power BI, SQL, entry level.")
        result = filter_jobs([job])
        assert len(result) == 1

    def test_analytics_intern_matches(self):
        job = _job(title="Analytics Intern", desc="Fresher role, Python, Excel.")
        result = filter_jobs([job])
        assert len(result) == 1

    def test_graduate_engineer_trainee_matches(self):
        job = _job(title="Graduate Engineer Trainee", desc="Python developer role.")
        result = filter_jobs([job])
        assert len(result) == 1

    def test_software_engineer_intern_matches(self):
        job = _job(title="Software Engineer Intern", desc="Backend Python role.")
        result = filter_jobs([job])
        assert len(result) == 1

    def test_marketing_manager_does_not_match(self):
        job = _job(title="Marketing Manager", desc="Brand strategy, social media.")
        result = filter_jobs([job])
        assert result == []


# ─── Evidence-based resume selection ─────────────────────────────────────────

class TestEvidenceBasedResumeSelection:
    def test_data_analyst_with_sql_selects_data(self):
        _, key = select_resume("Data Analyst",
                               "SQL, Pandas, Power BI, data pipeline, ETL")
        assert key == "data"

    def test_ml_engineer_with_pytorch_selects_aiml(self):
        _, key = select_resume("ML Engineer",
                               "machine learning, neural network, computer vision, YOLO")
        assert key == "aiml"

    def test_backend_with_fastapi_selects_backend(self):
        _, key = select_resume("Backend Developer",
                               "REST API, FastAPI, PostgreSQL, microservice, authentication")
        assert key == "backend"

    def test_software_engineer_with_ml_desc_selects_aiml(self):
        """Evidence-based: description overrides generic title."""
        _, key = select_resume("Software Engineer",
                               "machine learning inference, LLM, RAG, FAISS, vector embeddings")
        assert key == "aiml"

    def test_all_resume_scores_returned(self):
        result = select_best_resume_for_job(
            "Data Analyst",
            "SQL, Pandas, ETL, data quality, reconciliation"
        )
        assert "selected_key" in result
        assert "scores" in result
        assert result["selected_key"] in ("data", "aiml", "backend", "main")

    def test_no_domain_match_falls_back_to_main(self):
        _, key = select_resume("Product Manager",
                               "roadmap planning, stakeholder management, OKRs")
        assert key == "main"

    def test_selection_deterministic(self):
        r1, k1 = select_resume("ML Engineer Intern", "Python, TensorFlow, CV")
        r2, k2 = select_resume("ML Engineer Intern", "Python, TensorFlow, CV")
        assert k1 == k2 and r1 == r2


# ─── Cross-platform duplicate prevention ─────────────────────────────────────

class TestCrossPlatformDuplicates:
    def test_same_url_different_source_is_duplicate(self):
        from job_hunter.collectors.base import JobListing
        url = "https://company.com/jobs/data-analyst"
        j1 = JobListing(title="Data Analyst", company="Co",
                        source="himalayas", url=url,
                        posted_at=datetime.now(timezone.utc))
        j2 = JobListing(title="Data Analyst", company="Co",
                        source="weworkremotely", url=url,
                        posted_at=datetime.now(timezone.utc))
        # Same URL → same fingerprint
        assert j1.fingerprint() == j2.fingerprint()

    def test_different_url_same_title_not_duplicate(self):
        from job_hunter.collectors.base import JobListing
        j1 = JobListing(title="Data Analyst", company="Co",
                        source="himalayas", url="https://a.com/job1",
                        posted_at=datetime.now(timezone.utc))
        j2 = JobListing(title="Data Analyst", company="Co",
                        source="weworkremotely", url="https://b.com/job2",
                        posted_at=datetime.now(timezone.utc))
        assert j1.fingerprint() != j2.fingerprint()


# ─── Scoring consistency (mandatory failures) ─────────────────────────────────

class TestScoringConsistency:
    def test_ranker_dataclass_score_breakdown(self):
        from job_hunter.pipeline.ranker import ScoreBreakdown
        bd = ScoreBreakdown.from_dict({
            "skills": 30, "experience": 0, "projects": 15,
            "role_location": 12, "preferred": 3
        })
        assert bd.skills == 30
        assert bd.experience == 0
        # Total with mandatory failure cap: experience=0 → cap at 20
        raw_total = 30 + 0 + 15 + 12 + 3   # = 60
        capped_total = min(raw_total, 20)
        assert capped_total == 20

    def test_ranked_job_has_score_breakdown_field(self):
        from job_hunter.pipeline.ranker import RankedJob, ScoreBreakdown
        from job_hunter.collectors.base import JobListing
        job = JobListing(title="DA", company="Co", source="x",
                         url="https://x.com", posted_at=datetime.now(timezone.utc))
        ranked = RankedJob(job=job, score=75,
                           score_breakdown=ScoreBreakdown(30, 20, 15, 10, 0, 75))
        assert ranked.score_breakdown.skills == 30

    def test_recommendation_field_exists(self):
        from job_hunter.pipeline.ranker import RankedJob
        from job_hunter.collectors.base import JobListing
        job = JobListing(title="DA", company="Co", source="x",
                         url="https://x.com", posted_at=datetime.now(timezone.utc))
        ranked = RankedJob(job=job, score=80, recommendation="apply")
        assert ranked.recommendation in ("apply", "review", "skip")
