"""High-level orchestration for document translation."""

from __future__ import annotations

import pathlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .documents import detect_handler
from .errors import (
    ErrorCategory,
    OverwriteRefusedError,
    TranslationProviderError,
    WormholeError,
)
from .policy import ErrorPolicy
from .providers import TranslationProvider, build_provider
from .segmenter import BatchBuilder, Segmenter
from .structures import Batch, TextSegment


@dataclass
class TranslationSummary:
    """Report returned after processing a document."""

    input_path: pathlib.Path
    output_path: pathlib.Path
    document_type: str
    total_units: int
    translated_units: int
    skipped_units: int
    total_segments: int
    total_batches: int
    total_errors: int
    provider_name: str
    model: str | None
    target_language: str
    source_language: str | None
    elapsed_seconds: float
    error_messages: List[str] = field(default_factory=list)


class TranslationRunner:
    """Coordinates extraction, translation, and reinsertion."""

    def __init__(
        self,
        *,
        input_path: pathlib.Path,
        output_path: pathlib.Path,
        target_language: str,
        source_language: str | None,
        provider_name: str | None,
        model: str | None,
        batch_budget: int,
        interactive: bool,
        verbose: bool,
        provider_debug: bool,
    ) -> None:
        self.input_path = input_path
        self.output_path = output_path
        self.target_language = target_language
        self.source_language = source_language
        self.provider_name = provider_name
        self.model = model
        self.batch_budget = batch_budget
        self.interactive = interactive
        self.verbose = verbose
        self.provider_debug = provider_debug

        self.error_policy = ErrorPolicy(interactive=interactive)
        self.max_retries = 3
        self.retry_backoff = [1, 4, 9]

    def run(self) -> TranslationSummary:
        start_time = time.time()

        document_type, handler = detect_handler(self.input_path)
        units = handler.extract_text_units()

        segmenter = Segmenter(self.batch_budget)
        segments = segmenter.segment_units(units)

        batch_builder = BatchBuilder(self.batch_budget)
        batches = batch_builder.build(segments)
        if self.verbose:
            print(
                f"Prepared {len(units)} text units, "
                f"{len(segments)} segments, {len(batches)} batches."
            )

        provider = build_provider(self.provider_name, debug=self.provider_debug)

        buffers: Dict[str, List[str | None]] = {
            unit.unit_id: [None] * len(unit.segments) for unit in units
        }

        total_segments = len(segments)
        translated_units = 0
        skipped_units = 0

        for batch in batches:
            self._process_batch(
                provider=provider,
                batch=batch,
                buffers=buffers,
            )

        for unit in units:
            seg_buffer = buffers.get(unit.unit_id, [])
            if not seg_buffer:
                continue
            if any(value is None for value in seg_buffer):
                skipped_units += 1
                continue
            translated_text = "".join(seg_buffer)  # type: ignore[arg-type]
            try:
                unit.setter(translated_text)
                translated_units += 1
                self.error_policy.record_success()
            except Exception as exc:
                message = (
                    f"Could not reinsert translated text at {unit.location}. "
                    "Skipping this element."
                )
                action = self.error_policy.handle_error(
                    ErrorCategory.REINSERTION,
                    f"{message} ({exc})",
                )
                if action == "retry":
                    # Attempt once more immediately.
                    try:
                        unit.setter(translated_text)
                        translated_units += 1
                        self.error_policy.record_success()
                        continue
                    except Exception as retry_exc:
                        self.error_policy.handle_error(
                            ErrorCategory.REINSERTION,
                            f"Reinsertion retry failed at {unit.location}. "
                            f"Skipping this element. ({retry_exc})",
                        )
                skipped_units += 1

        handler.save(self.output_path)

        elapsed = time.time() - start_time
        summary = TranslationSummary(
            input_path=self.input_path,
            output_path=self.output_path,
            document_type=document_type,
            total_units=len(units),
            translated_units=translated_units,
            skipped_units=skipped_units,
            total_segments=total_segments,
            total_batches=len(batches),
            total_errors=len(self.error_policy.records),
            provider_name=self.provider_name or "openai",
            model=self.model,
            target_language=self.target_language,
            source_language=self.source_language,
            elapsed_seconds=elapsed,
            error_messages=[record.message for record in self.error_policy.records],
        )

        return summary

    def _process_batch(
        self,
        *,
        provider: TranslationProvider,
        batch: Batch,
        buffers: Dict[str, List[str | None]],
    ) -> None:
        attempt = 0
        while True:
            try:
                mapping = provider.translate(
                    batch.segments,
                    source_language=self.source_language,
                    target_language=self.target_language,
                    model=self.model,
                )
                self._map_translations(batch.segments, mapping, buffers)
                if self.verbose:
                    total_chars = sum(len(segment.text) for segment in batch.segments)
                    print(
                        f"Processed batch {batch.batch_id} "
                        f"({len(batch.segments)} segments, {total_chars} chars)."
                    )
                self.error_policy.record_success()
                return
            except TranslationProviderError as exc:
                attempt += 1
                if attempt <= self.max_retries:
                    wait_time = self.retry_backoff[min(attempt - 1, len(self.retry_backoff) - 1)]
                    print(
                        "Could not translate one batch "
                        f"(attempt {attempt} of {self.max_retries} — {exc}). "
                        "Retrying automatically..."
                    )
                    time.sleep(wait_time)
                    continue

                action = self.error_policy.handle_error(
                    ErrorCategory.TRANSLATION,
                    f"Batch {batch.batch_id} failed after multiple attempts. {exc}",
                )
                if action == "retry":
                    attempt = 0
                    continue

                # Skip this batch gracefully.
                if self.verbose:
                    print(
                        f"Skipping batch {batch.batch_id} after repeated failures."
                    )
                for segment in batch.segments:
                    buffer = buffers.get(segment.unit_id)
                    if buffer and segment.order < len(buffer):
                        buffer[segment.order] = None
                return

    def _map_translations(
        self,
        segments: Sequence[TextSegment],
        mapping: Dict[str, str],
        buffers: Dict[str, List[str | None]],
    ) -> None:
        for segment in segments:
            translated = mapping.get(segment.segment_id)
            if translated is None:
                message = (
                    f"Translation missing for segment {segment.segment_id}. "
                    "Skipping this element."
                )
                self.error_policy.handle_error(
                    ErrorCategory.TRANSLATION,
                    message,
                )
                continue
            buffer = buffers.get(segment.unit_id)
            if buffer is None or segment.order >= len(buffer):
                # Should not occur but handle gracefully.
                self.error_policy.handle_error(
                    ErrorCategory.REINSERTION,
                    f"Unexpected segment reference {segment.segment_id}.",
                )
                continue
            buffer[segment.order] = translated


def validate_paths(
    input_path: pathlib.Path,
    output_path: pathlib.Path,
    force_overwrite: bool,
) -> None:
    """Validate input/output path combinations and overwrite policy."""

    if not input_path.exists():
        raise FileNotFoundError(
            "Input file not found. Please provide a readable .docx or .pptx file."
        )
    if not input_path.is_file():
        raise WormholeError("Input path must be a file.")

    if input_path.resolve() == output_path.resolve():
        raise OverwriteRefusedError(
            "The output path matches the input document. Refusing to overwrite the source file."
        )

    if output_path.exists() and not force_overwrite:
        raise OverwriteRefusedError(
            "The output file already exists — rename or use the overwrite flag."
        )
