"""
adapters/base.py — BaseAdapter interface and SubmissionDeniedError.

The default submit_permission is DENY.
Automatic submission only proceeds when ALL THREE gates pass:
  1. adapter.can_submit == True
  2. env var AUTO_SUBMIT_{ADAPTER_NAME.upper()} == "true"
  3. record has no NEEDS_MANUAL_REVIEW answers

No adapter currently has can_submit=True.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

from apply_agent.models import ApplicationRecord, ApplicationStatus, AuditEvent

logger = logging.getLogger(__name__)


class SubmissionDeniedError(Exception):
    """Raised when submission is blocked by the permission gates."""


class BaseAdapter(ABC):
    """Abstract base for all source/ATS adapters."""

    name: str = "base"
    can_discover: bool = False
    can_prepare: bool = True
    can_submit: bool = False       # DENY by default on every adapter

    # ------------------------------------------------------------------
    @abstractmethod
    def prepare(self, record: ApplicationRecord) -> tuple[ApplicationRecord, list[AuditEvent]]:
        """
        Prepare an application: attach cover note, screening answers, flags.

        Returns the updated record and a list of audit events.
        Must NOT submit — only prepare the data.
        """

    # ------------------------------------------------------------------
    def submit(self, record: ApplicationRecord) -> tuple[ApplicationRecord, list[AuditEvent]]:
        """
        Attempt to submit the application.

        Default implementation: always raises SubmissionDeniedError.
        Subclasses with can_submit=True must override this AND pass the
        three permission gates below before calling super().
        """
        self._check_submission_gates(record)
        raise SubmissionDeniedError(
            f"Adapter '{self.name}' does not implement submit()."
        )

    # ------------------------------------------------------------------
    def _check_submission_gates(self, record: ApplicationRecord) -> None:
        """Raise SubmissionDeniedError if any permission gate fails."""
        # Gate 1: adapter must declare can_submit
        if not self.can_submit:
            raise SubmissionDeniedError(
                f"Adapter '{self.name}' has can_submit=False. "
                "All applications are routed to manual review."
            )

        # Gate 2: user must explicitly opt in via env var
        env_key = f"AUTO_SUBMIT_{self.name.upper()}"
        if os.getenv(env_key, "false").lower() != "true":
            raise SubmissionDeniedError(
                f"Auto-submit disabled for adapter '{self.name}'. "
                f"Set {env_key}=true to enable."
            )

        # Gate 3: no unresolved questions
        if record.has_unresolved():
            unresolved = [
                a.question for a in record.answers
                if a.confidence.value == "NEEDS_MANUAL_REVIEW"
            ]
            raise SubmissionDeniedError(
                f"Application has {len(unresolved)} unresolved question(s): "
                + "; ".join(unresolved[:3])
            )

    # ------------------------------------------------------------------
    @staticmethod
    def _deny_event(record: ApplicationRecord, reason: str) -> AuditEvent:
        return AuditEvent(
            application_id=record.id,
            actor="system",
            event="submission_denied",
            detail=reason,
        )
