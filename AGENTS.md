# Functional Specification — CLI Document Translator (DOCX & PPTX)

## 1) Purpose

Provide a command-line application that translates the text of Word (.docx) and PowerPoint (.pptx) files into a target language while preserving the original layout and formatting. The tool creates a new file with translated text in the exact original positions. The source file is never modified.

## 2) Primary Users

* Users who need accurate, layout-preserving translation of office documents.
* Teams that may later swap the LLM provider without changing the CLI contract.

## 3) Inputs and Parameters

* **Input file**: path to a `.docx` or `.pptx`.
* **Destination language (required)**: short or long form (e.g., `ES`, `Spanish`, `Español`).
* **Source language (optional)**: short or long form; acts as a hint for the LLM.
* **Output file (optional)**: if omitted, a new filename is derived by appending the destination language to the original.
* **Model/provider options (optional)**.
* **Batch guidance (optional)**: target character budget per batch (approximate).
* **Force overwrite (optional)**: allows replacing an existing *output* file — never the input.
* **Non-interactive mode (optional)**: disables prompts; suitable for automated use.

## 4) Core Behavior

1. Detect file type and reject unsupported extensions.
2. Extract all text-bearing elements:

   * **Word:** paragraphs, runs, tables, headers, footers.
   * **PowerPoint:** text boxes, tables, notes, all slides.
3. Assign stable, deterministic IDs to each text unit, uniquely identifying its position.
4. Build translation batches guided by a character budget while ensuring sentences are not split and words are never cut.
5. Translate batches through a provider adapter using a strict translation-only protocol.
6. Reinsert translations at the exact original locations, preserving formatting.
7. Save the translated version as a *new file* and generate a completion summary.

## 5) Output

* A `.docx` or `.pptx` file containing translated text with identical structure.
* A final report summarizing input, output, counts, batches, time, and model used.

## 6) Localization and Language Handling

* Destination language is **mandatory**.
* Source language is **optional**; if omitted, the LLM infers it.
* If the language name or code is unrecognized, the tool proposes close matches interactively.
* All language codes and names follow ISO-639 conventions where possible.

## 7) Safety and Preservation Rules

* The input document is **read-only** and never overwritten.
* If the output file already exists and overwrite is not requested, the tool stops with a clear, friendly message.
* If the output path equals the input path, the operation is refused.
* Corrupt or unreadable files trigger a safe abort with a human-readable explanation.

## 8) Resilient Error Policy and User Interaction

The application must **never terminate abruptly** due to recoverable errors.

* Each exception produces a clear, user-friendly message that identifies the problem and the affected element.
* The application then **skips the failed element** and proceeds automatically.

**Repeated error policy:**

* If **3 consecutive errors of the same type** occur, the tool pauses and offers:
  **Continue**, **Retry**, or **Abort**.
* If more than **10 total errors** occur in a single run, the tool automatically asks the same question even if they are of mixed types.
* In **non-interactive mode**, the tool auto-continues up to these thresholds; if exceeded, it stops safely and outputs a final summary with exit code >0.

**Error examples and guidance:**

* “Could not translate one paragraph (timeout). Retrying automatically...”
* “Repeated translation errors detected (3 times). Continue, retry, or abort?”

Irrecoverable errors (e.g., missing file) trigger immediate safe termination with clear instructions, but never abrupt termination or stack traces.

## 9) Performance and Reliability

* Sensible defaults: around 2000 characters per batch, balanced against sentence boundaries.
* Automatic retries (up to 3 attempts per batch) for transient network or provider errors.
* Deterministic traversal ensures identical results on reprocessing the same document.

## 10) Privacy and Security

* No data retained beyond the translation operation.
* Provider interaction controlled through environment variables or configuration.

## 11) Friendly Error Messages

The tool always communicates in plain, human-readable language, suggesting next steps rather than showing technical traces.
Examples include:

* “This file type isn’t supported — please use .docx or .pptx.”
* “The output file already exists — rename or use the overwrite flag.”
* “Translation service temporarily unavailable — retrying shortly.”

---

# Technical Addendum — Implementation Boundaries and Guarantees

## A) Supported Formats

* Supported inputs: `.docx`, `.pptx`.
* Unsupported inputs are politely rejected.

## B) Libraries and Runtime (non-binding)

* Implemented in Python 3.11+ with standard document libraries.
* Clean adapter layer for translation provider (OpenAI default).

## C) Stable ID Scheme

* Deterministic, human-readable IDs representing the document path:

  * Word: section → paragraph → run → optional table cell.
  * PowerPoint: slide → shape → paragraph → run.
* Stable across runs on unchanged files.

## D) Extraction Scope and Rules

* Word: body, tables, headers, footers; extract at run-level.
* PowerPoint: shapes with text frames, table cells, notes.
* Skip empty or whitespace-only text safely.

## E) Replacement Rules

* Replace text at the exact extraction level.
* Preserve formatting and style attributes whenever possible.
* Never alter paragraph or direction properties.
* Do not translate field codes or hidden content.

## F) Batching and Segmentation Guarantees

**Objective:** Maintain translation coherence by batching text in natural sentence groups while keeping requests below provider limits.

* Target budget: ~2000 characters per batch (configurable).
* Sentences are **never split**, and words are **never truncated**.
* Sentence segmentation policy:

  * If the **source language is known**, use a tokenizer appropriate to that language family (e.g., spaCy for Latin and Germanic, language-agnostic punctuation segmentation for others).
  * If **unknown**, apply multilingual heuristics based on punctuation (`.`, `!`, `?`, `;`) and capitalization patterns.
  * For East Asian or other non-space-delimited scripts, rely on script boundary detection rather than punctuation only.
  * If a single sentence exceeds the target budget, split on natural clause boundaries (commas, semicolons); as a last resort, split on whitespace while preserving whole words.
* Forced splits are tagged internally to allow rejoining translated fragments coherently.

Result: translations remain semantically coherent and grammatically correct, even for long sentences, with minimal token waste.

## G) Translation Adapter Abstraction

* Provider-agnostic adapter; default implementation for OpenAI models.
* Inputs: `{id, text}` pairs.
* Outputs: `{id, translated}` pairs with 1:1 mapping.
* Retries: up to 3 per batch with exponential backoff (1 s, 4 s, 9 s).
* Guardrails: translation only — no rewriting, summarization, or stylistic changes.

## H) Error Taxonomy and Control Flow

* Error categories: argument validation, file I/O, format parsing, translation, reinsertion, network.
* For each error:

  * Log and show a friendly message.
  * Continue processing subsequent items.
  * If 3 consecutive errors of the same class or 10 total errors are reached, request user confirmation or abort safely.
* In non-interactive mode, auto-continue within limits, then stop cleanly with an error summary.

## I) File I/O and Overwrite Policy

* Input opened read-only.
* Output always new and distinct.
* Output existing: ask before overwrite unless `--force`.
* Input = Output: always rejected.

## J) Logging and Reporting

* Default: INFO-level summary (files, languages, total items, batches, elapsed time).
* Verbose mode: details per batch, retries, segmentation stats, skipped items.
* All logs readable by non-technical users.

## K) Testing Expectations

* Word: multiple runs, tables, headers/footers, long paragraphs.
* PowerPoint: multi-slide, text boxes, tables, speaker notes.
* Verify stable IDs, sentence boundaries, and proper error recovery.
* Test both interactive and non-interactive modes for user-prompt logic.
* Test repeated errors to confirm Continue/Retry/Abort mechanism.

## L) Known Limits / Out of Scope

* No extraction from embedded spreadsheets, charts, or OLE objects.
* No translation of images or PDF files.
* No typographic or style translation.
* Complex field codes treated as visible text only.
