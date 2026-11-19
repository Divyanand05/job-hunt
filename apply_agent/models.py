"""
models.py — Core data models for the auto-apply agent.

All dataclasses use slots=False for SQLite-compatibility (easy __dict__ access).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ApplicationStatus(str, Enum):
    DISCOVERED     = "discovered"
    SHORTLISTED    = "shortlisted"
    PREPARED       = "prepared"
    PENDING_REVIEW = "pending_review"
    APPROVED       = "approved"
    SUBMITTED      = "submitted"
    FAILED         = "failed"
    SKIPPED        = "skipped"
    WITHDRAWN      = "withdrawn"


class AnswerConfidence(str, Enum):
    HIGH               = "HIGH"
    LOW                = "LOW"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"


# Questions whose answers must NEVER be auto-generated.
SENSITIVE_QUESTION_PATTERNS = [
    "disability", "disabled", "accommodation",
    "race", "ethnicity", "gender", "sex", "veteran",
    "criminal", "felony", "conviction",
    "salary expectation", "expected salary", "desired salary",
    "salary do you", "what salary", "salary range", "compensation",
    "authorize", "authorized to work", "visa", "sponsorship",
    "legal right", "work permit",
    "discrimination", "equal opportunity",
    "attest", "certify", "i certify", "i attest", "declaration",
]


@dataclass
class Answer:
    question: str
    answer: Optional[str] = None
    confidence: AnswerConfidence = AnswerConfidence.NEEDS_MANUAL_REVIEW
    source: str = "generated"       # resume | profile | generated | manual
    is_sensitive: bool = False

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "confidence": self.confidence.value,
            "source": self.source,
            "is_sensitive": self.is_sensitive,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Answer":
        return cls(
            question=d["question"],
            answer=d.get("answer"),
            confidence=AnswerConfidence(d.get("confidence", "NEEDS_MANUAL_REVIEW")),
            source=d.get("source", "generated"),
            is_sensitive=d.get("is_sensitive", False),
        )


@dataclass
class ApplicationRecord:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    fingerprint: str = ""
    job_title: str = ""
    company: str = ""
    source: str = ""
    apply_url: str = ""
    score: int = 0
    resume_used: str = "main"
    status: ApplicationStatus = ApplicationStatus.DISCOVERED
    cover_note: Optional[str] = None
    answers: list[Answer] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_at: Optional[datetime] = None
    confirmation_ref: Optional[str] = None   # only set on verified submission
    adapter: str = "manual"
    flags: list[str] = field(default_factory=list)
    notified: bool = False

    # Extra display fields (not persisted separately)
    job_location: str = ""
    job_salary: Optional[str] = None
    posted_at: Optional[datetime] = None
    match_reasons: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)

    def has_unresolved(self) -> bool:
        """True if any answer still needs manual review."""
        return any(
            a.confidence == AnswerConfidence.NEEDS_MANUAL_REVIEW
            for a in self.answers
        )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def transition(self, new_status: ApplicationStatus, actor: str = "system") -> "AuditEvent":
        old = self.status
        self.status = new_status
        self.touch()
        return AuditEvent(
            application_id=self.id,
            actor=actor,
            event="status_changed",
            old_value=old.value,
            new_value=new_status.value,
        )


@dataclass
class AuditEvent:
    application_id: str
    actor: str                              # system | user | adapter
    event: str                              # status_changed | answer_updated | note_added
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    detail: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Candidate profile — factual constants, never invented
# ---------------------------------------------------------------------------
CANDIDATE_PROFILE: dict = {
    "name": "Divyanand M",
    "graduation_year": 2027,
    "degree": "B.Tech AI & Data Science",
    "college": "Sri Manakula Vinayagar Engineering College",
    "years_experience": 0,
    "internship_months": 6,
    "notice_period_days": 0,
    "willing_to_relocate": True,
    "current_location": "Pondicherry, India",
    "work_authorization": "Indian citizen — eligible to work in India",
    "visa_required_for_india_remote": False,
    "linkedin": "linkedin.com/in/divyanandm",
    "github": "github.com/Divyanand05",
    "phone": "+91 9150050261",
    "email": "divyanand.aitech@gmail.com",
}
