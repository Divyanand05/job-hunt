"""
adapters/manual.py — ManualQueueAdapter.

Used for all sources that have no permitted programmatic submission API.
prepare() attaches the cover note and generated answers.
submit() always routes to PENDING_REVIEW (manual queue).
"""
from __future__ import annotations

import logging

from apply_agent.adapters.base import BaseAdapter, SubmissionDeniedError
from apply_agent.models import ApplicationRecord, ApplicationStatus, AuditEvent

logger = logging.getLogger(__name__)


class ManualQueueAdapter(BaseAdapter):
    """Routes every application to the manual review queue."""

    name = "manual"
    can_discover = False
    can_prepare = True
    can_submit = False          # Always DENY — intentional

    def prepare(
        self, record: ApplicationRecord
    ) -> tuple[ApplicationRecord, list[AuditEvent]]:
        """
        Mark record as PREPARED and transition to PENDING_REVIEW.
        The screener has already attached cover_note and answers before this.
        """
        events: list[AuditEvent] = []

        if record.status in (
            ApplicationStatus.DISCOVERED,
            ApplicationStatus.SHORTLISTED,
        ):
            ev = record.transition(ApplicationStatus.PREPARED, actor="manual_adapter")
            events.append(ev)

            ev2 = record.transition(ApplicationStatus.PENDING_REVIEW, actor="manual_adapter")
            events.append(ev2)
            events.append(AuditEvent(
                application_id=record.id,
                actor="manual_adapter",
                event="queued_for_review",
                detail="Application placed in manual review queue — no auto-submit available for this source.",
            ))

        return record, events

    def submit(
        self, record: ApplicationRecord
    ) -> tuple[ApplicationRecord, list[AuditEvent]]:
        """Always denies — routes to manual review."""
        reason = (
            f"ManualQueueAdapter.submit() called for '{record.job_title}' at "
            f"'{record.company}'. This adapter never auto-submits. "
            "Transition to PENDING_REVIEW instead."
        )
        logger.info("Manual adapter: routing %s to pending review", record.id[:8])
        ev = record.transition(ApplicationStatus.PENDING_REVIEW, actor="manual_adapter")
        deny_ev = self._deny_event(record, reason)
        return record, [ev, deny_ev]
