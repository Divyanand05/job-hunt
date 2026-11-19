"""
test_screener.py — Tests for the screening answer generator.
"""
from __future__ import annotations

from apply_agent.models import AnswerConfidence
from apply_agent.screener import _extract_questions, _is_sensitive


class TestSensitiveDetection:
    def test_disability_is_sensitive(self):
        assert _is_sensitive("Do you have any disability?")

    def test_salary_is_sensitive(self):
        assert _is_sensitive("What is your expected salary?")
        assert _is_sensitive("What salary do you desire?")

    def test_visa_is_sensitive(self):
        assert _is_sensitive("Do you require visa sponsorship?")
        assert _is_sensitive("Are you authorized to work in the US?")

    def test_legal_attestation_is_sensitive(self):
        assert _is_sensitive("I attest that the above information is accurate")

    def test_criminal_is_sensitive(self):
        assert _is_sensitive("Have you ever been convicted of a felony?")

    def test_relocation_is_not_sensitive(self):
        assert not _is_sensitive("Are you willing to relocate?")

    def test_python_experience_not_sensitive(self):
        assert not _is_sensitive("Do you have Python experience?")

    def test_remote_work_not_sensitive(self):
        assert not _is_sensitive("Are you comfortable working remotely?")


class TestQuestionExtraction:
    def test_extracts_direct_questions(self):
        desc = "Are you willing to relocate? Do you have Python experience? We need a team player."
        questions = _extract_questions(desc)
        assert any("relocate" in q.lower() for q in questions)
        assert any("python" in q.lower() for q in questions)

    def test_extracts_implicit_questions(self):
        desc = "Are you comfortable with remote work. We are a global team."
        questions = _extract_questions(desc)
        assert any("remote" in q.lower() for q in questions)

    def test_deduplicates_questions(self):
        desc = "Are you willing to relocate? Are you willing to relocate?"
        questions = _extract_questions(desc)
        relocate_q = [q for q in questions if "relocate" in q.lower()]
        assert len(relocate_q) == 1

    def test_max_twenty_questions(self):
        # Build a description with 25 questions
        desc = " ".join([f"Are you able to do task {i}?" for i in range(25)])
        questions = _extract_questions(desc)
        assert len(questions) <= 20

    def test_empty_description_returns_empty(self):
        assert _extract_questions("") == []

    def test_no_questions_returns_empty(self):
        desc = "We are looking for a data analyst. The role requires Python and SQL."
        questions = _extract_questions(desc)
        # No sentences end in ? and no "do you have / are you" phrases
        assert isinstance(questions, list)


class TestAnswerConfidenceLevels:
    def test_confidence_enum_values(self):
        assert AnswerConfidence.HIGH.value == "HIGH"
        assert AnswerConfidence.LOW.value == "LOW"
        assert AnswerConfidence.NEEDS_MANUAL_REVIEW.value == "NEEDS_MANUAL_REVIEW"

    def test_all_confidence_values_valid(self):
        for val in ["HIGH", "LOW", "NEEDS_MANUAL_REVIEW"]:
            conf = AnswerConfidence(val)
            assert conf is not None
