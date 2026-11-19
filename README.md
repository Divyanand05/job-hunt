# AI Auto-Apply Agent

Automatically discovers fresh jobs, matches them against your four tailored resumes using Google Gemini, prepares truthful applications with cover notes and screening answers, and routes everything to a Streamlit review queue — 3× daily.

---

## Architecture

```
c:\src\job hunt\
├── job_hunter/               Existing pipeline (collectors, ranker, email)
│   ├── collectors/           Himalayas, WeWorkRemotely, YCombinator, HiringCafe
│   └── pipeline/             normalize, dedup, filter, rank, resume_selector
├── apply_agent/              NEW — Application tracking engine
│   ├── models.py             ApplicationRecord, Answer, AuditEvent, CANDIDATE_PROFILE
│   ├── store.py              SQLite store (apply_agent.db)
│   ├── screener.py           Gemini screening answer generator
│   ├── engine.py             Orchestrator: discover → score → prepare → route
│   └── adapters/
│       ├── base.py           BaseAdapter ABC + SubmissionDeniedError
│       ├── manual.py         ManualQueueAdapter (all sources → review queue)
│       └── greenhouse.py     GreenhouseAdapter (discover only, submit=DENY)
├── dashboard/
│   └── app.py                Streamlit dashboard
├── data/
│   ├── resume_aiml.txt       AI/ML Engineer resume
│   ├── resume_data.txt       Data Analyst/Engineer resume
│   ├── resume_backend.txt    Backend Developer resume
│   ├── resume_main.txt       General/fallback resume
│   ├── seen_jobs.db          SQLite — seen jobs dedup (auto-created)
│   └── apply_agent.db        SQLite — application tracking (auto-created)
├── docs/
│   ├── requirements.md
│   ├── design.md
│   └── tasks.md
├── .github/workflows/
│   ├── job_hunter.yml        Original notifier — 3× daily
│   └── apply_agent.yml       Auto-apply agent — 3× daily (discover + prepare)
├── main.py                   Original entry point (notify only)
├── apply_main.py             Extended entry point (discover + prepare + notify)
├── config.py                 All configuration
├── requirements.txt
└── tests/                    116 tests (all passing)
```

---

## Source Compatibility Matrix

| Source | Discover | Prepare | Auto-Submit | Method | Cost |
|---|---|---|---|---|---|
| **Himalayas** | ✅ | ✅ | ❌ DENY | Official JSON API (free, optional key) | Free |
| **We Work Remotely** | ✅ | ✅ | ❌ DENY | Official RSS feeds | Free |
| **Y Combinator / HN** | ✅ | ✅ | ❌ DENY | Official HN Firebase API | Free |
| **HiringCafe** | ⚠️ | ✅ | ❌ DENY | Unofficial endpoint (best-effort) | Free |
| **LinkedIn** | ❌ | — | ❌ | No public job search API | — |
| **Indeed** | ❌ | — | ❌ | Publisher-only APIs (no read) | — |
| **ZipRecruiter** | ❌ | — | ❌ | ZipSearch shut down March 2025 | — |
| **Wellfound** | ❌ | — | ❌ | No public API or RSS | — |
| **Welcome to the Jungle** | ❌ | — | ❌ | No public API or RSS | — |

> **No adapter has `can_submit=True`.** Submission is always DENY. Every application goes to the manual review queue in the dashboard.

---

## Free Tier Cost Breakdown

| Service | Free limit | Usage per run | Notes |
|---|---|---|---|
| **Gemini Flash Lite** | ~500 RPD | ~10–20 calls | Scoring + cover notes + screening |
| **Himalayas API** | 10,000/day (with free key) | ~5 req | Optional key at himalayas.app/signup/developer |
| **WWR RSS** | Unlimited | 4 feeds | Official public |
| **HN Firebase API** | Unlimited | ~100 req | Official public |
| **Gmail SMTP** | 500/day | 1 email | App password required |
| **GitHub Actions** | 2,000 min/month | ~3 min × 3 × 30 = 270 min | Well within free tier |
| **Streamlit** | Free local | — | Run locally on your machine |

**Total: $0.00/month**

---

## Windows Setup

### 1. Prerequisites

```powershell
python --version   # needs 3.9+; 3.11 recommended
```

### 2. Install dependencies

```powershell
cd "c:\src\job hunt"
pip install -r requirements.txt
```

### 3. Configure credentials

```powershell
copy .env.example .env
# Edit .env with your values
```

Required values in `.env`:

| Variable | Where to get it |
|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| `GMAIL_USER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) — enable 2FA first |
| `HIMALAYAS_API_KEY` | Optional — [himalayas.app/signup/developer](https://himalayas.app/signup/developer) |

### 4. Verify resumes

Confirm the four resume files exist and contain your real details:
```
data/resume_aiml.txt
data/resume_data.txt
data/resume_backend.txt
data/resume_main.txt
```

### 5. Test dry-run

```powershell
$env:DRY_RUN="true"
python apply_main.py
```

This collects, scores, and prepares applications without writing to the database or sending email. Output is logged to the console.

### 6. Normal run

```powershell
$env:DRY_RUN="false"
python apply_main.py
```

### 7. Launch the dashboard

```powershell
streamlit run dashboard/app.py
```

Opens at [http://localhost:8501](http://localhost:8501).

---

## GitHub Actions Deployment

### 1. Push to GitHub

```powershell
cd "c:\src\job hunt"
git init
git add .
git commit -m "AI Auto-Apply Agent"
git remote add origin https://github.com/Divyanand05/ai-job-hunter.git
git push -u origin main
```

### 2. Add GitHub Secrets

Go to: **Repository → Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|---|---|
| `GEMINI_API_KEY` | Your Gemini key |
| `GMAIL_USER` | `divyanand.aitech@gmail.com` |
| `GMAIL_APP_PASSWORD` | Your App Password |
| `RECIPIENT_EMAIL` | `divyanand.aitech@gmail.com` |
| `HIMALAYAS_API_KEY` | Your Himalayas key (optional) |

### 3. Schedule

Both workflows run automatically at **6:00 AM, 1:00 PM, 7:00 PM IST**.

You can also trigger manually: **Actions → workflow name → Run workflow**.

---

## Running Tests

```powershell
# All 116 tests
pytest tests/ -v

# Specific test file
pytest tests/test_apply_engine.py -v

# With coverage
pip install pytest-cov
pytest tests/ --cov=job_hunter --cov=apply_agent --cov-report=term-missing
```

---

## Dashboard Usage

1. Run `streamlit run dashboard/app.py`
2. The left panel shows all applications grouped by status
3. Click any job to see the full detail panel
4. Review the match score, cover note, and screening answers
5. Use **Approve**, **Skip**, or **Withdraw** buttons
6. For approved jobs: click **Open Application →** to go to the actual form, fill it in manually, then click **Mark as Submitted** in the dashboard

---

## Submission Policy

> **Auto-submit is off by default and cannot be enabled through the dashboard.**

The design is "DENY unless explicitly authorized." To enable auto-submit for a future adapter:

1. The adapter must set `can_submit = True`
2. You must set `AUTO_SUBMIT_{ADAPTERNAME}=true` in your environment
3. The application must have zero `NEEDS_MANUAL_REVIEW` answers

Currently no adapter satisfies condition 1 — all submissions go to the manual queue.

---

## Remaining Manual Steps

After deployment, the following require manual action:

1. **Fill in `.env`** — add `GEMINI_API_KEY`, `GMAIL_APP_PASSWORD`, `GMAIL_USER`
2. **Add GitHub Secrets** — same five values as above
3. **Review resume files** — confirm `data/resume_*.txt` contain accurate information
4. **First run** — trigger manually from GitHub Actions with `dry_run=true` to verify everything works
5. **Enable scheduled workflow** — GitHub Actions are paused after 60 days of inactivity; re-enable if needed
6. **Dashboard access** — run locally with `streamlit run dashboard/app.py`; for remote access, deploy to Streamlit Community Cloud (free) or run behind a tunnel

---

## Application Flow Diagram

```
GitHub Actions (3×/day)
        │
        ▼
  apply_main.py
        │
        ├─ run_discovery()          ← Himalayas + WWR + YC + HiringCafe
        ├─ normalize()              ← reject undated jobs
        ├─ Deduplicator             ← skip already-seen jobs
        ├─ filter_jobs()            ← 24h + role + India
        ├─ rank_jobs()              ← Gemini score 0–100
        ├─ shortlist (score ≥ 80)
        ├─ generate_answers()       ← truthful screening answers
        ├─ ManualQueueAdapter       ← PENDING_REVIEW (always)
        ├─ ApplicationStore.upsert()← persist to apply_agent.db
        └─ send_email()             ← top 5 matches + queue count

User opens dashboard (streamlit)
        │
        ├─ Reviews queue
        ├─ Reads match score, cover note, answers
        ├─ Clicks Approve / Skip / Withdraw
        ├─ Opens Apply link → fills form manually → submits
        └─ Clicks "Mark as Submitted" in dashboard
```
