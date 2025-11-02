"""Command line interface for the Wormhole translator."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Iterable, Optional

from .configuration import get_settings
from .errors import (
    AbortRequested,
    NonInteractiveAbort,
    OverwriteRefusedError,
    TranslationProviderConfigurationError,
    UnsupportedFileTypeError,
    WormholeError,
)
from .translator import TranslationRunner, TranslationSummary, validate_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wormhole",
        description=(
            "Translate Word (.docx) and PowerPoint (.pptx) documents while preserving layout."
        ),
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        help="Path to the .docx or .pptx file to translate.",
    )
    parser.add_argument(
        "-t",
        "--target-language",
        required=False,
        help="Destination language (name or ISO-639 code).",
    )
    parser.add_argument(
        "-s",
        "--source-language",
        help="Optional source language hint (name or ISO-639 code).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path. Defaults to appending the target language code.",
    )
    parser.add_argument(
        "-p",
        "--provider",
        help="Translation provider identifier (default: openai).",
    )
    parser.add_argument(
        "-m",
        "--model",
        help="Provider-specific model or engine identifier.",
    )
    parser.add_argument(
        "-b",
        "--batch-guidance",
        type=int,
        default=2000,
        help="Approximate maximum characters per translation batch (default: 2000).",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Allow overwriting the output file if it already exists.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable prompts and enforce automatic decisions (suitable for CI).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed progress information.",
    )
    parser.add_argument(
        "--debug-provider",
        action="store_true",
        help="Log complete provider requests and responses for troubleshooting.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the graphical interface for configuring and running translations.",
    )
    return parser


def sanitise_language_for_filename(language: str) -> str:
    """Generate a filesystem-friendly suffix from a language descriptor."""

    collapsed = re.sub(r"\s+", "-", language.strip())
    ascii_only = collapsed.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9\-]+", "", ascii_only)
    return cleaned or "translated"


def derive_output_path(input_path: pathlib.Path, language: str) -> pathlib.Path:
    suffix = input_path.suffix
    stem = input_path.stem
    addition = sanitise_language_for_filename(language)
    candidate = f"{stem}_{addition}{suffix}"
    return input_path.with_name(candidate)


def execute_translation(
    *,
    input_file: str,
    output_file: str | None,
    target_language: str,
    source_language: str | None,
    provider: str | None,
    model: str | None,
    batch_guidance: int,
    force_overwrite: bool,
    non_interactive: bool,
    verbose: bool,
    provider_debug: bool,
) -> tuple[int, TranslationSummary | None, str | None]:
    """Execute a translation run and return the exit code, summary, and message."""

    input_path = pathlib.Path(input_file).expanduser().resolve()
    output_path = (
        pathlib.Path(output_file).expanduser().resolve()
        if output_file
        else derive_output_path(input_path, target_language)
    )

    try:
        validate_paths(input_path, output_path, force_overwrite=force_overwrite)
    except FileNotFoundError as exc:
        return 1, None, str(exc)
    except OverwriteRefusedError as exc:
        return 1, None, str(exc)
    except WormholeError as exc:
        return 1, None, str(exc)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    runner = TranslationRunner(
        input_path=input_path,
        output_path=output_path,
        target_language=target_language,
        source_language=source_language,
        provider_name=provider,
        model=model,
        batch_budget=batch_guidance,
        interactive=not non_interactive,
        verbose=verbose,
        provider_debug=provider_debug,
    )

    try:
        summary = runner.run()
    except UnsupportedFileTypeError as exc:
        return 1, None, str(exc)
    except TranslationProviderConfigurationError as exc:
        return 1, None, str(exc)
    except NonInteractiveAbort as exc:
        return 2, None, str(exc)
    except AbortRequested:
        return 2, None, "Translation aborted at your request."
    except WormholeError as exc:
        return 1, None, str(exc)
    except KeyboardInterrupt:
        return 2, None, "Translation interrupted by user."
    except Exception as exc:  # pragma: no cover - defensive catch
        error_message = (
            f"{exc}\n"
            "An unexpected error occurred. Please rerun with --verbose for more details."
        )
        return 1, None, error_message

    return 0, summary, None


def print_summary(summary: TranslationSummary) -> None:
    """Output a friendly report once processing completes."""

    print("\nTranslation complete.")
    print(f"  Input file:      {summary.input_path}")
    print(f"  Output file:     {summary.output_path}")
    print(f"  Document type:   {summary.document_type}")
    print(
        "  Text units:      "
        f"{summary.translated_units} translated / {summary.total_units} total "
        f"({summary.skipped_units} skipped)"
    )
    print(
        f"  Segments:        {summary.total_segments} "
        f"in {summary.total_batches} batches"
    )
    print(
        f"  Provider:        {summary.provider_name}"
        + (f" ({summary.model})" if summary.model else "")
    )
    if summary.source_language:
        print(f"  Source language: {summary.source_language}")
    print(f"  Target language: {summary.target_language}")
    print(f"  Elapsed time:    {summary.elapsed_seconds:.2f} seconds")
    if summary.total_errors:
        print("  Notes:")
        for message in summary.error_messages:
            print(f"    - {message}")


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    provider_debug = bool(args.debug_provider)
    if not provider_debug:
        try:
            settings = get_settings()
        except TranslationProviderConfigurationError as exc:
            print(exc)
            return 1
        provider_debug = bool(
            settings.WORMHOLE_PROVIDER_DEBUG
            or settings.WORMHOLE_DEBUG_PROVIDER
        )

    if args.gui:
        from .gui import launch_gui

        return launch_gui(
            args=args,
            translation_executor=execute_translation,
            summary_printer=print_summary,
            provider_debug=provider_debug,
        )

    if args.input_file is None:
        parser.error("the following arguments are required: input_file")
    if not args.target_language:
        parser.error("the following arguments are required: -t/--target-language")

    exit_code, summary, message = execute_translation(
        input_file=args.input_file,
        output_file=args.output,
        target_language=args.target_language,
        source_language=args.source_language,
        provider=args.provider,
        model=args.model,
        batch_guidance=args.batch_guidance,
        force_overwrite=args.force,
        non_interactive=args.non_interactive,
        verbose=args.verbose,
        provider_debug=provider_debug,
    )

    if message:
        print(message)
    if summary:
        print_summary(summary)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
