# Implementation Tasks

## Phase 1 — Foundation (DONE)
- [x] Repository audit
- [x] requirements.md, design.md, tasks.md
- [x] `apply_agent/models.py` — ApplicationRecord, Answer, AuditEvent, CANDIDATE_PROFILE
- [x] `apply_agent/store.py` — ApplicationStore (SQLite)
- [x] `apply_agent/adapters/base.py` — BaseAdapter + SubmissionDeniedError
- [x] `apply_agent/adapters/manual.py` — ManualQueueAdapter (always DENY)
- [x] `apply_agent/adapters/greenhouse.py` — GreenhouseAdapter (discover only)
- [x] `apply_agent/screener.py` — Gemini screening answer generator
- [x] `apply_agent/engine.py` — Full discovery → score → prepare → route pipeline
- [x] `apply_main.py` — New entry point extending main.py
- [x] `dashboard/app.py` — Streamlit dashboard
- [x] Updated `config.py` with APPLY_DB_PATH and MIN_SCORE
- [x] Updated `requirements.txt` with streamlit
- [x] `.github/workflows/apply_agent.yml` — New workflow
- [x] Updated `.github/workflows/job_hunter.yml` — Timeout 20min

## Phase 2 — Tests (DONE)
- [x] test_store.py (14 tests)
- [x] test_adapters.py (13 tests)
- [x] test_apply_engine.py (18 tests)
- [x] test_screener.py (15 tests)
- [x] All 116 tests pass

## Phase 3 — Manual Setup (REQUIRED)
See README.md → "Remaining Manual Steps"

## Phase 4 — Future (when explicitly authorized)
- [ ] Email-based apply (mailto: links — user clicks to send)
- [ ] Greenhouse applicant-side submit (requires official applicant API — not yet public)
- [ ] Lever submit adapter (same constraint)
- [ ] Ashby submit adapter (same constraint)
