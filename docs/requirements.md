# Requirements — AI Auto-Apply Agent

## Existing functionality preserved
- All four collectors (Himalayas, WeWorkRemotely, YCombinator, HiringCafe)
- Normalizer, deduplicator, filter, ranker, resume_selector pipeline
- Gmail email notifications
- GitHub Actions 3× daily schedule
- 51 existing passing tests

## New functional requirements

### R1 — Application tracking store
- Persistent SQLite database (`data/apply_agent.db`) separate from `seen_jobs.db`
- Track each job through statuses: discovered → shortlisted → prepared → pending_review → submitted → failed / skipped / withdrawn
- Idempotency key per job (fingerprint from existing `JobListing.fingerprint()`)
- Timestamps for each status transition
- Full audit log of every state change with actor and reason

### R2 — Extended job schema
- Add `ats_type` field to JobListing (greenhouse/lever/ashby/workday/unknown)
- Add `apply_url` field (direct form URL, may differ from listing URL)
- Add `questions` list (screening questions extracted from JD)

### R3 — Adapter interface
- `BaseAdapter` with capability flags: `can_discover`, `can_prepare`, `can_submit`
- `submit_permission = DENY` by default on every adapter
- Submission only proceeds when: adapter explicitly sets `can_submit=True`, user has set `AUTO_SUBMIT_{ADAPTER}=true` env var, AND no unresolved questions exist
- `prepare()` → generates cover note, screening answers, resume selection, marks unknowns
- `submit()` → raises `SubmissionDeniedError` unless all three gates pass

### R4 — Application engine
- Orchestrates: discover → score (≥80) → prepare → route (auto-submit or manual queue)
- Never bypass CAPTCHA, MFA, anti-bot measures or ToS
- Never auto-answer: demographic, disability, criminal, salary commitment, legal attestation, work-auth questions
- These are always flagged `NEEDS_MANUAL_REVIEW`
- Mark answer confidence: HIGH / LOW / NEEDS_MANUAL_REVIEW

### R5 — Streamlit dashboard
- Application queue with status filters
- Job detail panel: description, match score, resume preview, generated answers
- Approve / Reject / Skip controls per application
- Submission history with timestamps
- Source health panel
- Export queue to CSV

### R6 — Updated GitHub Actions
- Scheduled runs: discover + prepare only
- Submission only via manual approval in dashboard
- Persist `apply_agent.db` between runs (GitHub Actions cache or artifact)
- Timeout extended to 20 minutes

### R7 — Notifications
- Email includes "Review Queue" link count (N applications need your review)
- Submission receipt per confirmed submission
- Source failure alerts
- No duplicate notifications (tracked in DB)

### R8 — Tests
- Duplicate prevention (fingerprint collision)
- Freshness enforcement (>24h rejected)
- Resume selection for all three real resumes
- Eligibility check (graduation year, 0-exp, India)
- False success prevention (no confirmation → not marked submitted)
- Approval gate (submission blocked without approval)
- Source failure handling (adapter returns error → goes to manual queue)

## Non-requirements (explicitly out of scope)
- LinkedIn, Indeed, ZipRecruiter, Wellfound, Welcome to the Jungle auto-apply (no permitted API)
- CAPTCHA solving
- Browser session token storage
- Paid Apify actors
- Any demographic/disability/criminal question auto-answering

## Source permission matrix

| Source | Discover | Prepare | Auto-Submit | Notes |
|---|---|---|---|---|
| Himalayas | ✅ | ✅ | ❌ DENY | No apply API |
| WeWorkRemotely | ✅ | ✅ | ❌ DENY | No apply API |
| YCombinator/HN | ✅ | ✅ | ❌ DENY | Redirects to company ATS |
| HiringCafe | ✅ | ✅ | ❌ DENY | Unofficial, no submit API |
| Greenhouse (via job) | ✅ | ✅ | ❌ DENY | Needs employer key |
| All others | ✅ | ✅ | ❌ DENY | Manual queue |

> **No adapter currently has `can_submit=True`.**
> This is intentional. The architecture is ready for future authorized integrations.
