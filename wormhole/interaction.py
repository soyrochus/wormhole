"""I/O abstractions for running translations in different environments."""

from __future__ import annotations

from typing import Protocol, Sequence


class TranslationIO(Protocol):
    """Minimal I/O surface needed by the translation runner."""

    def info(self, message: str) -> None:
        """Emit an informational or progress message."""

    def error(self, message: str) -> None:
        """Emit an error or warning message."""

    def prompt_choice(self, prompt: str, choices: Sequence[str]) -> str:
        """Request a choice from the user and return the selected value."""


class NullIO:
    """No-op implementation used when no I/O is desired."""

    def info(self, message: str) -> None:  # pragma: no cover - trivial
        return

    def error(self, message: str) -> None:  # pragma: no cover - trivial
        return

    def prompt_choice(self, prompt: str, choices: Sequence[str]) -> str:  # pragma: no cover
        # Default to the first option to keep caller logic moving.
        return choices[0]
