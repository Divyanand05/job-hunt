# Design — AI Auto-Apply Agent

## New directory layout (additions to existing repo)

```
c:\src\job hunt\
├── apply_agent/                  ← NEW top-level package
│   ├── __init__.py
│   ├── engine.py                 Orchestrator: discover → score → prepare → route
│   ├── models.py                 ApplicationRecord, Answer, AuditEvent dataclasses
│   ├── store.py                  SQLite store for applications + audit log
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py               BaseAdapter ABC + SubmissionDeniedError
│   │   ├── manual.py             ManualQueueAdapter (all unsupported sources)
│   │   └── greenhouse.py         GreenhouseAdapter (discover only, submit=DENY)
│   └── screener.py               Gemini-powered screening answer generator
├── dashboard/
│   └── app.py                    Streamlit dashboard
├── docs/
│   ├── requirements.md
│   ├── design.md
│   └── tasks.md
├── tests/
│   ├── test_apply_engine.py      NEW
│   ├── test_adapters.py          NEW
│   ├── test_store.py             NEW
│   ├── test_screener.py          NEW
│   └── ... existing tests ...
├── .github/workflows/
│   ├── job_hunter.yml            Updated (timeout, DB persistence)
│   └── dashboard.yml             Optional: Streamlit Cloud deploy
├── apply_main.py                 New entry point (extends main.py)
└── requirements.txt              Updated (streamlit added)
```

## Data model

### ApplicationRecord
```python
@dataclass
class ApplicationRecord:
    id: str                        # UUID
    fingerprint: str               # from JobListing.fingerprint()
    job_title: str
    company: str
    source: str
    apply_url: str
    score: int                     # Gemini score 0-100
    resume_used: str               # aiml|data|backend|main
    status: ApplicationStatus      # enum
    cover_note: Optional[str]
    answers: list[Answer]
    created_at: datetime
    updated_at: datetime
    submitted_at: Optional[datetime]
    confirmation_ref: Optional[str]  # only set on verified submission
    adapter: str                   # which adapter prepared/submitted
    flags: list[str]               # e.g. ["has_manual_review_items"]
```

### ApplicationStatus (enum)
```
DISCOVERED        — found by collector, not yet scored
SHORTLISTED       — score >= MIN_SCORE (default 80)
PREPARED          — answers + cover note generated
PENDING_REVIEW    — waiting for user approval in dashboard
APPROVED          — user approved in dashboard
SUBMITTED         — confirmed submitted (has confirmation_ref)
FAILED            — submission attempted but failed
SKIPPED           — score < MIN_SCORE or filtered
WITHDRAWN         — user withdrew from dashboard
```

### Answer
```python
@dataclass
class Answer:
    question: str
    answer: Optional[str]
    confidence: AnswerConfidence    # HIGH | LOW | NEEDS_MANUAL_REVIEW
    source: str                     # "resume"|"profile"|"generated"|"manual"
    is_sensitive: bool              # demographic, disability, etc.
```

### AuditEvent
```python
@dataclass
class AuditEvent:
    application_id: str
    timestamp: datetime
    actor: str                     # "system"|"user"|"adapter"
    event: str                     # "status_changed", "answer_added", etc.
    old_value: Optional[str]
    new_value: Optional[str]
    detail: Optional[str]
```

## SQLite schema (apply_agent.db)

```sql
CREATE TABLE applications (
    id              TEXT PRIMARY KEY,
    fingerprint     TEXT NOT NULL UNIQUE,
    job_title       TEXT NOT NULL,
    company         TEXT NOT NULL,
    source          TEXT NOT NULL,
    apply_url       TEXT NOT NULL,
    score           INTEGER NOT NULL DEFAULT 0,
    resume_used     TEXT NOT NULL DEFAULT 'main',
    status          TEXT NOT NULL DEFAULT 'discovered',
    cover_note      TEXT,
    answers_json    TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    submitted_at    TEXT,
    confirmation_ref TEXT,
    adapter         TEXT NOT NULL DEFAULT 'manual',
    flags_json      TEXT NOT NULL DEFAULT '[]',
    notified        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    actor           TEXT NOT NULL,
    event           TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    detail          TEXT
);

CREATE INDEX idx_applications_fingerprint ON applications(fingerprint);
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_audit_application_id ON audit_log(application_id);
```

## Adapter interface

```python
class BaseAdapter(ABC):
    name: str = "base"
    can_discover: bool = False
    can_prepare: bool = True
    can_submit: bool = False         # DENY by default — must be overridden

    @abstractmethod
    def prepare(self, job: JobListing, ranked: RankedJob) -> ApplicationRecord: ...

    def submit(self, record: ApplicationRecord) -> ApplicationRecord:
        # Default implementation — always denies
        raise SubmissionDeniedError(
            f"Adapter '{self.name}' has can_submit=False. "
            "Route to manual queue."
        )
```

## Permission gates for submission

All three must be True before `submit()` proceeds:
1. `adapter.can_submit == True`
2. `os.getenv(f"AUTO_SUBMIT_{adapter.name.upper()}") == "true"`
3. `not any(a.confidence == NEEDS_MANUAL_REVIEW for a in record.answers)`

If any gate fails → status = `PENDING_REVIEW`, goes to dashboard queue.

## Screener design

Gemini prompt asks:
- For each question in the job description: provide a truthful answer using only the resume
- Classify confidence: HIGH (direct resume evidence), LOW (inferred), NEEDS_MANUAL_REVIEW (unknown/sensitive)
- Mark `is_sensitive=True` for: demographic, disability, criminal, salary, legal attestation, visa/work-auth

Profile constants (never invent):
```python
PROFILE = {
    "name": "Divyanand M",
    "graduation_year": 2027,
    "degree": "B.Tech AI & Data Science",
    "college": "Sri Manakula Vinayagar Engineering College",
    "years_experience": 0,
    "internship_months": 6,
    "notice_period_days": 0,
    "willing_to_relocate": True,
    "work_authorization": "Indian citizen — eligible to work in India",
    "visa_required_for_remote": False,
}
```

## Dashboard layout

```
┌─────────────────────────────────────────────────┐
│  AI Auto-Apply Agent           [Refresh] [Export]│
├──────────────┬──────────────────────────────────┤
│ QUEUE        │ JOB DETAIL                       │
│              │  Title / Company / Score          │
│ [Pending: 3] │  ┌─ Description ──────────────┐ │
│ [Approved:1] │  └────────────────────────────┘ │
│ [Submitted:2]│  Resume: [AI/ML ▾]               │
│ [Failed: 0]  │  Cover note:  [text]             │
│              │  Screening answers:               │
│ ○ Job A  85  │    Q: Years experience? A: 0 ✓   │
│ ○ Job B  82  │    Q: Willing relocate? A: Yes ✓  │
│ ○ Job C  80  │    Q: Salary expect? ⚠ REVIEW    │
│              │                                   │
│              │  [APPROVE] [SKIP] [WITHDRAW]      │
├──────────────┴──────────────────────────────────┤
│ SOURCE HEALTH                                    │
│  ✅ himalayas 0 jobs  ✅ wwr 97 jobs  ❌ hiringcafe │
└─────────────────────────────────────────────────┘
```
