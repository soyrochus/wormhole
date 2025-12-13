"""Error handling policy implementation."""

from __future__ import annotations

from typing import List, Optional

from .errors import (
    AbortRequested,
    ErrorCategory,
    ErrorRecord,
    ErrorTracker,
    NonInteractiveAbort,
)
from .interaction import NullIO, TranslationIO


class ErrorPolicy:
    """Implements the resilient error policy described in the specification."""

    def __init__(self, *, interactive: bool, io: TranslationIO | None = None) -> None:
        self.interactive = interactive
        self.io = io or NullIO()
        self.records: List[ErrorRecord] = []
        self.tracker = ErrorTracker()

    def record_success(self) -> None:
        """Reset consecutive counters after successful work."""

        self.tracker.reset_consecutive()

    def handle_error(
        self,
        category: ErrorCategory,
        message: str,
        details: Optional[str] = None,
    ) -> str:
        """Handle an error and decide whether to continue, retry, or abort."""

        self.records.append(ErrorRecord(category=category, message=message, details=details))
        consecutive, total, threshold = self.tracker.register(category)

        self.io.error(message)

        if not threshold:
            return "continue"

        prompt = (
            "Repeated errors detected (3 times). Continue, retry, or abort?"
            if consecutive >= self.tracker.CONSECUTIVE_LIMIT
            else "More than 10 errors encountered. Continue, retry, or abort?"
        )

        if not self.interactive:
            raise NonInteractiveAbort(
                "Error threshold exceeded in non-interactive mode. Stopping safely."
            )

        choices = ["continue", "retry", "abort"]
        while True:
            response = self.io.prompt_choice(prompt, choices).strip().lower()
            if response in {"continue", "c"}:
                return "continue"
            if response in {"retry", "r"}:
                return "retry"
            if response in {"abort", "a"}:
                raise AbortRequested("Abort requested by user.")
            self.io.error("Please respond with Continue, Retry, or Abort (c/r/a).")
