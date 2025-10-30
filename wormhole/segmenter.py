"""Text segmentation and batching utilities."""

from __future__ import annotations

import re
from typing import List, Sequence

from .structures import Batch, TextSegment, TextUnit

SENTENCE_PATTERN = re.compile(
    r".+?(?:[\.!?…‽。！？；؛](?:\s+|$)|$)", re.DOTALL
)
CLAUSE_PATTERN = re.compile(
    r".+?(?:[,;:،，；：](?:\s+|$)|$)", re.DOTALL
)


def contains_cjk(text: str) -> bool:
    """Detect whether the text contains CJK characters."""

    for char in text:
        code = ord(char)
        if (
            0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
            or 0x3400 <= code <= 0x4DBF  # Extension A
            or 0x3040 <= code <= 0x30FF  # Hiragana/Katakana
            or 0xAC00 <= code <= 0xD7AF  # Hangul syllables
        ):
            return True
    return False


def _consume_pattern(pattern: re.Pattern[str], text: str) -> List[str]:
    """Split text by greedily consuming matches from the start of a string."""

    if not text:
        return []

    segments: List[str] = []
    index = 0
    length = len(text)
    while index < length:
        match = pattern.match(text, index)
        if not match:
            # If no match is found, consume the rest of the text.
            segments.append(text[index:])
            break
        end = match.end()
        if end == index:
            # Avoid zero-length loops by consuming at least one character.
            end += 1
        segments.append(text[index:end])
        index = end
    return segments


def _tokenise_preserving_whitespace(text: str) -> List[str]:
    """Tokenise text into word+space tokens without losing whitespace."""

    tokens: List[str] = []
    idx = 0
    length = len(text)
    while idx < length:
        if text[idx].isspace():
            start = idx
            while idx < length and text[idx].isspace():
                idx += 1
            tokens.append(text[start:idx])
        else:
            start = idx
            while idx < length and not text[idx].isspace():
                idx += 1
            end = idx
            while idx < length and text[idx].isspace():
                idx += 1
            tokens.append(text[start:idx])
    return tokens


def _split_cjk(text: str, budget: int) -> List[str]:
    """Split text that lacks whitespace (e.g., CJK scripts) into safe chunks."""

    if budget <= 0:
        return [text]
    segments: List[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + budget, length)
        segments.append(text[start:end])
        start = end
    return segments


def _split_words(text: str, budget: int) -> List[str]:
    """Split text on whitespace boundaries while preserving formatting."""

    tokens = _tokenise_preserving_whitespace(text)
    if not tokens:
        return []

    segments: List[str] = []
    current = ""

    for token in tokens:
        if len(token) > budget:
            # Fallback to CJK-aware splitting when a token still exceeds budget.
            if current:
                segments.append(current)
                current = ""
            if contains_cjk(token):
                segments.extend(_split_cjk(token, budget))
            else:
                segments.extend(_split_cjk(token, budget))
            continue

        if len(current) + len(token) > budget and current:
            segments.append(current)
            current = token
        else:
            current += token

    if current:
        segments.append(current)

    return segments


def _pack_segments(chunks: Sequence[str], budget: int) -> List[str]:
    """Greedily pack smaller chunks into budget-sized segments."""

    packed: List[str] = []
    current = ""
    for chunk in chunks:
        if not chunk:
            continue
        if len(chunk) > budget:
            if current:
                packed.append(current)
                current = ""
            if contains_cjk(chunk.strip()) or not chunk.strip():
                packed.extend(_split_cjk(chunk, budget))
            else:
                packed.extend(_split_words(chunk, budget))
            continue
        if len(current) + len(chunk) > budget and current:
            packed.append(current)
            current = chunk
        else:
            current += chunk
    if current:
        packed.append(current)
    return packed


def segment_text(text: str, budget: int) -> List[str]:
    """Segment text into sentence-aligned chunks respecting the budget."""

    if not text:
        return []

    sentences = _consume_pattern(SENTENCE_PATTERN, text)
    segments: List[str] = []
    for sentence in sentences:
        if len(sentence) <= budget:
            segments.append(sentence)
            continue
        clauses = _consume_pattern(CLAUSE_PATTERN, sentence)
        if clauses and max(len(clause) for clause in clauses) <= budget:
            segments.extend(_pack_segments(clauses, budget))
            continue
        word_segments = _split_words(sentence, budget)
        if word_segments:
            segments.extend(word_segments)
        else:
            segments.append(sentence)
    return segments


class Segmenter:
    """Turns text units into sized translation segments."""

    def __init__(self, budget: int) -> None:
        self.budget = max(1, budget)

    def segment_units(self, units: Sequence[TextUnit]) -> List[TextSegment]:
        segments: List[TextSegment] = []
        for unit in units:
            if unit.atomic:
                raw_segments = (
                    [unit.original_text] if unit.original_text else []
                )
            else:
                raw_segments = segment_text(unit.original_text, self.budget)
            if not raw_segments:
                continue
            unit.segments = []
            for idx, content in enumerate(raw_segments):
                segment = TextSegment(
                    segment_id=f"{unit.unit_id}#seg{idx}",
                    unit_id=unit.unit_id,
                    text=content,
                    order=idx,
                )
                segments.append(segment)
                unit.segments.append(segment)
        return segments


class BatchBuilder:
    """Aggregates segments into batches within a character budget."""

    def __init__(self, budget: int) -> None:
        self.budget = max(1, budget)

    def build(self, segments: Sequence[TextSegment]) -> List[Batch]:
        batches: List[Batch] = []
        batch_segments: List[TextSegment] = []
        running_total = 0
        batch_id = 1

        for segment in segments:
            size = len(segment.text)
            if size > self.budget:
                if batch_segments:
                    batches.append(Batch(batch_id=batch_id, segments=batch_segments))
                    batch_id += 1
                    batch_segments = []
                    running_total = 0
                batches.append(Batch(batch_id=batch_id, segments=[segment]))
                batch_id += 1
                continue

            if running_total + size > self.budget and batch_segments:
                batches.append(Batch(batch_id=batch_id, segments=batch_segments))
                batch_id += 1
                batch_segments = []
                running_total = 0

            batch_segments.append(segment)
            running_total += size

        if batch_segments:
            batches.append(Batch(batch_id=batch_id, segments=batch_segments))

        return batches
