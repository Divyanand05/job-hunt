"""
dashboard/app.py — Streamlit dashboard for the AI Auto-Apply Agent.

Run:
  streamlit run dashboard/app.py

Shows:
  - Application queue with status filters
  - Job detail panel (description, score, resume, answers)
  - Approve / Reject / Skip controls
  - Submission history
  - Source health (from last run log)
  - CSV export
"""
from __future__ import annotations

import csv
import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make sure repo root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

import config
from apply_agent.models import ApplicationStatus, AnswerConfidence, AuditEvent
from apply_agent.store import ApplicationStore

APPLY_DB_PATH = config.DATA_DIR / "apply_agent.db"

st.set_page_config(
    page_title="AI Auto-Apply Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATUS_EMOJI = {
    "discovered":     "🔍",
    "shortlisted":    "⭐",
    "prepared":       "📝",
    "pending_review": "⏳",
    "approved":       "✅",
    "submitted":      "🚀",
    "failed":         "❌",
    "skipped":        "⏭",
    "withdrawn":      "🗑",
}

RESUME_LABELS = {
    "aiml":    "AI/ML Resume",
    "data":    "Data Resume",
    "backend": "Backend Resume",
    "main":    "General Resume",
}

CONF_COLOR = {
    "HIGH":               "green",
    "LOW":                "orange",
    "NEEDS_MANUAL_REVIEW": "red",
}


@st.cache_resource
def get_store() -> ApplicationStore:
    return ApplicationStore(APPLY_DB_PATH)


def reload_store() -> ApplicationStore:
    """Force a fresh connection (bypass cache)."""
    if "store" not in st.session_state:
        st.session_state["store"] = ApplicationStore(APPLY_DB_PATH)
    return st.session_state["store"]


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%d %b %Y %H:%M UTC")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("🤖 AI Auto-Apply Agent")
st.sidebar.caption("Divyanand M · 2027 Graduate")
st.sidebar.markdown("---")

STATUS_OPTIONS = [
    "all",
    "pending_review",
    "approved",
    "submitted",
    "failed",
    "shortlisted",
    "prepared",
    "skipped",
    "withdrawn",
]
selected_status = st.sidebar.selectbox(
    "Filter by status",
    STATUS_OPTIONS,
    format_func=lambda s: f"{STATUS_EMOJI.get(s, '')} {s.replace('_', ' ').title()}" if s != "all" else "All",
)

min_score = st.sidebar.slider("Minimum score", 0, 100, 0, step=5)
st.sidebar.markdown("---")

if st.sidebar.button("Refresh"):
    if "store" in st.session_state:
        st.session_state["store"].close()
        del st.session_state["store"]
    st.rerun()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

store = reload_store()
counts = store.counts_by_status()

if selected_status == "all":
    records = store.list_all(limit=200)
else:
    records = store.list_by_status(ApplicationStatus(selected_status))

records = [r for r in records if r.score >= min_score]

# ---------------------------------------------------------------------------
# Top metrics row
# ---------------------------------------------------------------------------

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Pending Review", counts.get("pending_review", 0))
col2.metric("Approved", counts.get("approved", 0))
col3.metric("Submitted", counts.get("submitted", 0))
col4.metric("Shortlisted", counts.get("shortlisted", 0) + counts.get("prepared", 0))
col5.metric("Total Tracked", sum(counts.values()))

st.markdown("---")

# ---------------------------------------------------------------------------
# Main layout: queue list + detail panel
# ---------------------------------------------------------------------------

left, right = st.columns([1, 2])

with left:
    st.subheader(f"Queue ({len(records)} jobs)")

    if not records:
        st.info("No applications match the current filter.")
        selected_id = None
    else:
        selected_id = st.session_state.get("selected_id", records[0].id if records else None)

        for rec in records:
            emoji = STATUS_EMOJI.get(rec.status.value, "•")
            unresolved = rec.has_unresolved()
            warn = " ⚠️" if unresolved else ""
            label = f"{emoji} {rec.job_title[:28]} | {rec.company[:18]} | {rec.score}/100{warn}"
            if st.button(label, key=f"btn_{rec.id}", use_container_width=True):
                st.session_state["selected_id"] = rec.id
                selected_id = rec.id

with right:
    if not selected_id:
        st.info("Select a job from the queue.")
    else:
        rec = store.get(selected_id)
        if rec is None:
            st.warning("Record not found — it may have been deleted.")
        else:
            # --- Header ---
            st.markdown(f"## {rec.job_title}")
            st.markdown(
                f"**{rec.company}** &nbsp;|&nbsp; {rec.job_location} &nbsp;|&nbsp; "
                f"Source: `{rec.source}` &nbsp;|&nbsp; "
                f"Status: **{STATUS_EMOJI.get(rec.status.value,'')} {rec.status.value}**"
            )
            if rec.job_salary:
                st.caption(f"Salary: {rec.job_salary}")
            st.caption(f"Posted: {fmt_dt(rec.posted_at)}  |  Tracked: {fmt_dt(rec.created_at)}")

            # --- Score bar ---
            st.markdown(f"**Match Score: {rec.score}/100**")
            st.progress(rec.score / 100)

            # --- Why qualify ---
            if rec.match_reasons:
                st.markdown("**Why You Qualify**")
                for r in rec.match_reasons:
                    st.markdown(f"- {r}")

            # --- Missing skills ---
            if rec.missing_skills:
                st.markdown("**Skills to Develop**")
                for s in rec.missing_skills:
                    st.markdown(f"- {s}")

            # --- Resume ---
            st.markdown(
                f"**Resume used:** {RESUME_LABELS.get(rec.resume_used, rec.resume_used)}"
            )

            # --- Cover note ---
            if rec.cover_note:
                with st.expander("Cover Note", expanded=True):
                    st.markdown(rec.cover_note)

            # --- Answers ---
            if rec.answers:
                st.markdown("**Screening Answers**")
                for ans in rec.answers:
                    conf_col = CONF_COLOR.get(ans.confidence.value, "gray")
                    sensitive_badge = " 🔒 SENSITIVE" if ans.is_sensitive else ""
                    st.markdown(
                        f"<small style='color:{conf_col}'>**{ans.confidence.value}**</small>"
                        f"{sensitive_badge} &nbsp; **Q:** {ans.question}",
                        unsafe_allow_html=True,
                    )
                    if ans.answer:
                        st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;**A:** {ans.answer}")
                    else:
                        st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;**A:** *(needs manual input)*")

            # --- Apply link ---
            st.markdown(f"[Open Application →]({rec.apply_url})", unsafe_allow_html=False)

            st.markdown("---")

            # --- Action buttons ---
            if rec.status in (
                ApplicationStatus.PENDING_REVIEW,
                ApplicationStatus.SHORTLISTED,
                ApplicationStatus.PREPARED,
            ):
                bcol1, bcol2, bcol3 = st.columns(3)

                if bcol1.button("Approve", key=f"approve_{rec.id}", type="primary"):
                    ev = rec.transition(ApplicationStatus.APPROVED, actor="user")
                    store.upsert(rec, [ev, AuditEvent(
                        application_id=rec.id,
                        actor="user",
                        event="approved_in_dashboard",
                    )])
                    st.success("Approved! Click the Apply link to submit manually.")
                    st.rerun()

                if bcol2.button("Skip", key=f"skip_{rec.id}"):
                    ev = rec.transition(ApplicationStatus.SKIPPED, actor="user")
                    store.upsert(rec, [ev])
                    st.info("Skipped.")
                    st.rerun()

                if bcol3.button("Withdraw", key=f"withdraw_{rec.id}"):
                    ev = rec.transition(ApplicationStatus.WITHDRAWN, actor="user")
                    store.upsert(rec, [ev])
                    st.warning("Withdrawn.")
                    st.rerun()

            elif rec.status == ApplicationStatus.APPROVED:
                st.success("Approved — apply manually using the link above.")
                if st.button("Mark as Submitted", key=f"submit_{rec.id}"):
                    rec.submitted_at = datetime.now(timezone.utc)
                    rec.confirmation_ref = "manual"
                    ev = rec.transition(ApplicationStatus.SUBMITTED, actor="user")
                    store.upsert(rec, [ev, AuditEvent(
                        application_id=rec.id,
                        actor="user",
                        event="marked_submitted_manually",
                        detail="User confirmed manual submission via dashboard.",
                    )])
                    st.success("Marked as submitted!")
                    st.rerun()

            elif rec.status == ApplicationStatus.SUBMITTED:
                st.success(f"Submitted on {fmt_dt(rec.submitted_at)}")
                if rec.confirmation_ref:
                    st.caption(f"Ref: {rec.confirmation_ref}")

            # --- Audit log ---
            with st.expander("Audit Log"):
                events = store.audit_log(rec.id)
                if events:
                    for ev in events:
                        st.markdown(
                            f"`{fmt_dt(ev.timestamp)}` **{ev.actor}** — {ev.event}"
                            + (f": {ev.old_value} → {ev.new_value}" if ev.old_value else "")
                            + (f" _{ev.detail}_" if ev.detail else "")
                        )
                else:
                    st.caption("No audit events yet.")

# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Export")

if st.button("Download CSV"):
    rows = store.to_csv_rows()
    if rows:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        st.download_button(
            "Save applications.csv",
            data=output.getvalue().encode("utf-8"),
            file_name=f"applications_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )
    else:
        st.info("No data to export yet.")
