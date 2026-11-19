"""
api/main.py — FastAPI backend for the AI Auto-Apply Agent dashboard.

Runs on Railway (free tier). Reads/writes apply_agent.db.
Serves JSON to the Next.js frontend on Vercel.

Start locally:
  uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import csv
import io
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from apply_agent.models import ApplicationStatus, AuditEvent
from apply_agent.store import ApplicationStore

app = FastAPI(title="AI Auto-Apply Agent API", version="1.0.0")

# CORS — allow Vercel frontend + localhost dev
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,https://*.vercel.app",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to ALLOWED_ORIGINS in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = config.DATA_DIR / "apply_agent.db"


def get_store() -> ApplicationStore:
    return ApplicationStore(DB_PATH)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class StatusUpdate(BaseModel):
    status: str
    actor: str = "user"
    detail: Optional[str] = None

class SubmitConfirm(BaseModel):
    confirmation_ref: str = "manual"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "db": str(DB_PATH)}


@app.get("/api/stats")
def stats():
    with get_store() as store:
        counts = store.counts_by_status()
        total = sum(counts.values())
        return {"counts": counts, "total": total}


@app.get("/api/applications")
def list_applications(
    status: Optional[str] = Query(None),
    min_score: int = Query(0),
    limit: int = Query(200),
):
    with get_store() as store:
        if status and status != "all":
            try:
                records = store.list_by_status(ApplicationStatus(status))
            except ValueError:
                raise HTTPException(400, f"Unknown status: {status}")
        else:
            records = store.list_all(limit=limit)

        records = [r for r in records if r.score >= min_score]

    return [_serialize(r) for r in records]


@app.get("/api/applications/{app_id}")
def get_application(app_id: str):
    with get_store() as store:
        rec = store.get(app_id)
        if not rec:
            raise HTTPException(404, "Application not found")
        log = store.audit_log(app_id)
    return {**_serialize(rec), "audit_log": [_serialize_event(e) for e in log]}


@app.patch("/api/applications/{app_id}/status")
def update_status(app_id: str, body: StatusUpdate):
    with get_store() as store:
        rec = store.get(app_id)
        if not rec:
            raise HTTPException(404, "Application not found")
        try:
            new_status = ApplicationStatus(body.status)
        except ValueError:
            raise HTTPException(400, f"Unknown status: {body.status}")

        ev = rec.transition(new_status, actor=body.actor)
        if body.detail:
            ev.detail = body.detail
        store.upsert(rec, [ev])
        return _serialize(rec)


@app.post("/api/applications/{app_id}/submit")
def mark_submitted(app_id: str, body: SubmitConfirm):
    """User manually confirms they submitted — sets status=SUBMITTED with confirmation_ref."""
    from datetime import datetime, timezone
    with get_store() as store:
        rec = store.get(app_id)
        if not rec:
            raise HTTPException(404, "Application not found")
        if rec.status != ApplicationStatus.APPROVED:
            raise HTTPException(400, "Application must be in APPROVED status before marking submitted")

        rec.submitted_at = datetime.now(timezone.utc)
        rec.confirmation_ref = body.confirmation_ref
        ev = rec.transition(ApplicationStatus.SUBMITTED, actor="user")
        store.upsert(rec, [ev, AuditEvent(
            application_id=rec.id,
            actor="user",
            event="marked_submitted_manually",
            detail=f"User confirmed manual submission. Ref: {body.confirmation_ref}",
        )])
        return _serialize(rec)


@app.get("/api/export/csv")
def export_csv():
    with get_store() as store:
        rows = store.to_csv_rows()
    if not rows:
        raise HTTPException(404, "No data to export")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _serialize(rec) -> dict:
    from apply_agent.store import _dt_to_str
    return {
        "id": rec.id,
        "fingerprint": rec.fingerprint,
        "job_title": rec.job_title,
        "company": rec.company,
        "source": rec.source,
        "apply_url": rec.apply_url,
        "score": rec.score,
        "resume_used": rec.resume_used,
        "status": rec.status.value,
        "cover_note": rec.cover_note,
        "answers": [a.to_dict() for a in rec.answers],
        "created_at": _dt_to_str(rec.created_at),
        "updated_at": _dt_to_str(rec.updated_at),
        "submitted_at": _dt_to_str(rec.submitted_at),
        "confirmation_ref": rec.confirmation_ref,
        "adapter": rec.adapter,
        "flags": rec.flags,
        "notified": rec.notified,
        "job_location": rec.job_location,
        "job_salary": rec.job_salary,
        "posted_at": _dt_to_str(rec.posted_at),
        "match_reasons": rec.match_reasons,
        "missing_skills": rec.missing_skills,
    }


def _serialize_event(ev) -> dict:
    from apply_agent.store import _dt_to_str
    return {
        "timestamp": _dt_to_str(ev.timestamp),
        "actor": ev.actor,
        "event": ev.event,
        "old_value": ev.old_value,
        "new_value": ev.new_value,
        "detail": ev.detail,
    }
