# SPEC-2026-03-05-01 — Custom Translation Instructions

**Date:** 2026-03-05
**Status:** Implemented
**Scope:** CLI, GUI, `TranslationRunner`, `TranslationProvider` interface

---

## 1. Motivation

Wormhole's built-in system prompt covers general-purpose translation requirements (JSON structure, run-tag preservation, formatting). Some use cases require domain-specific guidance that goes beyond this baseline — for example, enforcing terminology conventions, adjusting tone, or handling specialised vocabulary. This spec describes the addition of a user-supplied instruction string that is appended to the system prompt on every translation batch.

---

## 2. Design Decisions

### 2.1 Append, do not replace

Custom instructions are appended to the existing system prompt rather than replacing it. The built-in prompt encodes structural requirements (JSON output format, run-tag handling) that must remain in force regardless of user input. Replacing the prompt would risk breaking the provider contract.

### 2.2 Per-batch injection

Instructions are injected into every batch call individually. Wormhole translates documents in independent batches of approximately 2,000 characters; there is no shared state between batches. Instructions must therefore be stateless and self-contained — they cannot reference content from other parts of the document.

### 2.3 Optional with `None` default

The parameter is optional everywhere in the call chain. When absent or empty it has no effect, preserving full backward compatibility with existing integrations and test fixtures.

---

## 3. Prompt Change

### Before

```
You are a professional translator. Return only JSON.
Translate the provided text segments into the requested language.
Preserve formatting, placeholders, numbers, and markup.
Respond strictly with an object shaped as {"translations": [{"id": "...", "translated": "..."}]}.
Input may include tags such as <run id="…">…</run>; keep tags and their attributes exactly as
provided, translate only the inner text, and you may redistribute translated words across
sequential runs as needed while preserving tag order.
Do not add commentary. Do not wrap the JSON in markdown code fences.
```

### After (when `--instructions` is provided)

```
You are a professional translator. Return only JSON.
Translate the provided text segments into the requested language.
Preserve formatting, placeholders, numbers, and markup.
Respond strictly with an object shaped as {"translations": [{"id": "...", "translated": "..."}]}.
Input may include tags such as <run id="…">…</run>; keep tags and their attributes exactly as
provided, translate only the inner text, and you may redistribute translated words across
sequential runs as needed while preserving tag order.
Do not add commentary. Do not wrap the JSON in markdown code fences.

Additional instructions:
<user-supplied text>
```

The separator (`\n\nAdditional instructions:\n`) clearly delineates the structural requirements from the user's domain guidance.

---

## 4. Interface Changes

### 4.1 `TranslationProvider.translate()` (abstract base)

```python
# wormhole/providers.py

def translate(
    self,
    segments: Sequence[TextSegment],
    *,
    source_language: str | None,
    target_language: str,
    model: str | None = None,
    custom_instructions: str | None = None,   # NEW
) -> Dict[str, str]: ...
```

Affects all concrete implementations: `OpenAITranslationProvider`, `LegacyOpenAITranslationProvider`, `EchoTranslationProvider`.

### 4.2 `TranslationRunner.__init__()`

```python
# wormhole/translator.py

def __init__(
    self,
    *,
    ...
    custom_instructions: str | None = None,   # NEW
) -> None: ...
```

Stored as `self.custom_instructions` and forwarded to `provider.translate()` on every batch call in `_process_batch()`.

### 4.3 `execute_translation()` (CLI entry point)

```python
# wormhole/cli.py

def execute_translation(
    *,
    ...
    custom_instructions: str | None = None,   # NEW
    io: TranslationIO | None = None,
) -> tuple[int, TranslationSummary | None, str | None]: ...
```

### 4.4 `TranslationExecutor` Protocol (GUI)

```python
# wormhole/gui.py

class TranslationExecutor(Protocol):
    def __call__(
        self,
        *,
        ...
        custom_instructions: Optional[str] = None,   # NEW
        io: TranslationIO | None = None,
    ) -> tuple[int, Optional[TranslationSummary], Optional[str]]: ...
```

---

## 5. CLI Addition

```
-i, --instructions TEXT
    Custom instructions appended to the translation prompt.
    Free-form text added to the LLM system prompt for every batch.
```

Example:

```bash
wormhole contract.docx -t es \
  --instructions "Preserve all defined terms in their original English form enclosed in quotation marks."
```

---

## 6. GUI Addition

A labelled multi-line text field **"Custom instructions (optional)"** is added to the main form between the Batch guidance field and the checkboxes. Its content is read with `Text.get("1.0", tk.END)` and passed as `custom_instructions` in the translation configuration dictionary. An empty or whitespace-only value is normalised to `None`.

Window height is increased from 580 px to 720 px to accommodate the new field.

---

## 7. Limitations

- Instructions are applied per-batch. The LLM has no visibility into other batches, so guidance that depends on document-level context (cross-references, document-wide glossaries) will not be consistently applied.
- For PowerPoint (`.pptx`) documents, instructions that cause significant text expansion (e.g. adding bracket notes) may overflow fixed-size text boxes, undermining Wormhole's layout-preservation guarantee.
- The user is responsible for ensuring instructions do not conflict with the structural requirements of the built-in prompt (e.g. instructions that ask the model to return plain text instead of JSON will break reinsertion).

---

## 8. Files Changed

| File | Change |
|---|---|
| `wormhole/providers.py` | Added `custom_instructions` to abstract method and all implementations; appended to system prompt when non-empty. |
| `wormhole/translator.py` | Added `custom_instructions` parameter to `TranslationRunner.__init__()`; forwarded to `provider.translate()`. |
| `wormhole/cli.py` | Added `-i`/`--instructions` argument; threaded through `execute_translation()` → `TranslationRunner`. |
| `wormhole/gui.py` | Updated `TranslationExecutor` Protocol; added `Text` widget for instructions; increased window height to 720 px. |
| `README.md` | Added `-i`/`--instructions` row to the command-line reference table; added **Custom Instructions** section. |
