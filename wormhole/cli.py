"""Command line interface for the Wormhole translator."""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
from typing import Iterable, Optional

from dotenv import load_dotenv

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
        help="Path to the .docx or .pptx file to translate.",
    )
    parser.add_argument(
        "-t",
        "--target-language",
        required=True,
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


def _env_flag(*names: str) -> bool:
    """Interpret boolean-like environment variables."""

    truthy = {"1", "true", "yes", "on"}
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip().lower() in truthy:
            return True
    return False


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
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    input_path = pathlib.Path(args.input_file).expanduser().resolve()
    output_path = (
        pathlib.Path(args.output).expanduser().resolve()
        if args.output
        else derive_output_path(input_path, args.target_language)
    )
    provider_debug = bool(
        args.debug_provider
        or _env_flag("WORMHOLE_PROVIDER_DEBUG", "WORMHOLE_DEBUG_PROVIDER")
    )

    try:
        validate_paths(input_path, output_path, force_overwrite=args.force)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    except OverwriteRefusedError as exc:
        print(str(exc))
        return 1
    except WormholeError as exc:
        print(str(exc))
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)

    runner = TranslationRunner(
        input_path=input_path,
        output_path=output_path,
        target_language=args.target_language,
        source_language=args.source_language,
        provider_name=args.provider,
        model=args.model,
        batch_budget=args.batch_guidance,
        interactive=not args.non_interactive,
        verbose=args.verbose,
        provider_debug=provider_debug,
    )

    try:
        summary = runner.run()
    except UnsupportedFileTypeError as exc:
        print(str(exc))
        return 1
    except TranslationProviderConfigurationError as exc:
        print(str(exc))
        return 1
    except NonInteractiveAbort as exc:
        print(str(exc))
        return 2
    except AbortRequested:
        print("Translation aborted at your request.")
        return 2
    except WormholeError as exc:
        print(str(exc))
        return 1
    except KeyboardInterrupt:
        print("Translation interrupted by user.")
        return 2
    except Exception as exc:  # pragma: no cover - defensive catch
        print(exc)
        print(
            "An unexpected error occurred. Please rerun with --verbose for more details."
        )
        return 1

    print_summary(summary)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
