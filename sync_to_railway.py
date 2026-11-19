"""
sync_to_railway.py — Push local apply_agent.db records to Railway backend.

Usage:
  python sync_to_railway.py

Set RAILWAY_API_URL in .env or pass as env var.
Optional: set ADMIN_SECRET in Railway Variables for protection.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv(override=True)

import config
from apply_agent.store import ApplicationStore, _dt_to_str

RAILWAY_URL = os.getenv(
    "RAILWAY_API_URL",
    "https://job-hunt-production-812a0bc4.up.railway.app"
)
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")


def main():
    db = config.DATA_DIR / "apply_agent.db"
    if not db.exists():
        print("No apply_agent.db found. Run apply_main.py first.")
        sys.exit(1)

    with ApplicationStore(db) as store:
        records = store.list_all(limit=1000)

    if not records:
        print("No records in local DB.")
        sys.exit(0)

    print(f"Syncing {len(records)} records to {RAILWAY_URL}...")

    payload = []
    for r in records:
        payload.append({
            "id": r.id,
            "fingerprint": r.fingerprint,
            "job_title": r.job_title,
            "company": r.company,
            "source": r.source,
            "apply_url": r.apply_url,
            "score": r.score,
            "resume_used": r.resume_used,
            "status": r.status.value,
            "cover_note": r.cover_note,
            "answers": [a.to_dict() for a in r.answers],
            "adapter": r.adapter,
            "flags": r.flags,
            "notified": r.notified,
            "job_location": r.job_location,
            "job_salary": r.job_salary,
            "posted_at": _dt_to_str(r.posted_at),
            "match_reasons": r.match_reasons,
            "missing_skills": r.missing_skills,
        })

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{RAILWAY_URL}/api/admin/sync"
    headers = {"Content-Type": "application/json"}
    if ADMIN_SECRET:
        headers["X-Admin-Secret"] = ADMIN_SECRET

    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            print(f"Done! Synced {result['synced']} / {result['total']} records.")
            print(f"Open your dashboard: https://job-hunt-72l6.vercel.app")
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
