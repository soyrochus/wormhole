"""Core data structures for the Wormhole translator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List


TextSetter = Callable[[str], None]


@dataclass
class TextUnit:
    """Represents a single text element ready for translation."""

    unit_id: str
    original_text: str
    setter: TextSetter
    location: str
    segments: List["TextSegment"] = field(default_factory=list)
    atomic: bool = False


@dataclass
class TextSegment:
    """Represents a translation-ready segment derived from a TextUnit."""

    segment_id: str
    unit_id: str
    text: str
    order: int


@dataclass
class Batch:
    """A batch of segments constrained by a character budget."""

    batch_id: int
    segments: List[TextSegment]
