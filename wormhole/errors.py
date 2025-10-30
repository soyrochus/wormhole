"""Error definitions and policy helpers for the Wormhole translator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class ErrorCategory(Enum):
    """Categorises runtime errors to apply policy thresholds."""

    ARGUMENT = auto()
    FILE_IO = auto()
    FORMAT = auto()
    TRANSLATION = auto()
    REINSERTION = auto()
    NETWORK = auto()
    OTHER = auto()


class WormholeError(Exception):
    """Base exception for all custom errors."""


class AbortRequested(WormholeError):
    """Raised when the user elects to abort processing."""


class NonInteractiveAbort(WormholeError):
    """Raised when non-interactive policy dictates termination."""


class UnsupportedFileTypeError(WormholeError):
    """Raised when a given file extension is not supported."""


class OverwriteRefusedError(WormholeError):
    """Raised when attempting to overwrite an output without consent."""


class TranslationProviderConfigurationError(WormholeError):
    """Raised when the translation provider is misconfigured."""


class TranslationProviderError(WormholeError):
    """Raised when the translation provider fails permanently."""


@dataclass
class ErrorRecord:
    """Stores context for a handled error."""

    category: ErrorCategory
    message: str
    details: Optional[str] = None


class ErrorTracker:
    """Tracks consecutive and aggregate errors to satisfy policy rules."""

    CONSECUTIVE_LIMIT = 3
    TOTAL_LIMIT = 10

    def __init__(self) -> None:
        self.last_category: Optional[ErrorCategory] = None
        self.consecutive: int = 0
        self.total: int = 0

    def register(self, category: ErrorCategory) -> tuple[int, int, bool]:
        """Register a new error and return counters."""

        if self.last_category == category:
            self.consecutive += 1
        else:
            self.last_category = category
            self.consecutive = 1

        self.total += 1

        threshold_reached = (
            self.consecutive >= self.CONSECUTIVE_LIMIT
            or self.total >= self.TOTAL_LIMIT
        )

        return self.consecutive, self.total, threshold_reached

    def reset_consecutive(self) -> None:
        """Reset the consecutive counter after successful work."""

        self.consecutive = 0
        self.last_category = None
