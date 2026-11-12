# SPEC-2026-11-12-01 — Excel (.xlsx) Support

**Date:** 2026-11-12
**Status:** Proposed
**Scope:** `documents.py` (new handler), `translator.py`, CLI, GUI, dependencies, packaging, docs

---

## 1. Motivation

Wormhole translates `.docx` and `.pptx` files. An `.xlsx` file is rejected by `detect_handler()` with "This file type isn't supported". Users regularly have spreadsheet deliverables that belong to the same document set as the Word and PowerPoint files (for example a response matrix accompanying a proposal) and must translate them by other means.

This spec adds `.xlsx` as a third supported format. The translation pipeline after extraction (segmenting, batching, provider calls, reinsertion, error policy) is format-agnostic and is not changed.

---

## 2. Scope

### In scope (v1)

- `.xlsx` workbooks.
- Text in worksheet cells, on every worksheet, including hidden sheets.

### Out of scope (v1)

| Item | Reason |
|---|---|
| Sheet names | Formulas reference them by name; Excel caps them at 31 characters and forbids `: \ / ? * [ ]`. |
| Formula cells, including string literals inside formulas | Rewriting formulas risks breaking the workbook. |
| Cell comments / notes | Separate object model; can be added later. |
| Data-validation dropdown lists | Lookups and formulas may match on the values. |
| Headers / footers, defined names, chart titles, text boxes, shapes | Not cell content; see §6 for fidelity limits. |
| Mixed formatting inside a single cell | See §3.4. |
| `.xlsm`, `.xls`, `.xlsb`, `.csv` | Rejected as unsupported, as today. |

---

## 3. Design Decisions

### 3.1 Library: `openpyxl`

`openpyxl` is the Excel counterpart of `python-docx` / `python-pptx`: it loads a workbook, lets cell values be changed in place, and saves it with cell formatting, column widths, merged ranges and formulas intact. It keeps the handler small and consistent with the existing two.

Its limitation is that it does not round-trip every workbook feature (§6). Editing the XML parts inside the `.xlsx` package directly would avoid that, at the cost of considerably more code. That approach is deferred until a real workbook requires it.

### 3.2 What counts as translatable

A cell is translatable when all of the following hold:

1. `cell.data_type == "s"` (a string; this excludes formulas, numbers, dates, booleans and errors).
2. The value is non-empty after `strip()` (the same rule `_build_units_from_runs()` applies to runs).
3. The value contains at least one alphabetic character (`any(ch.isalpha() for ch in value)`). This skips codes such as `"2024-01"`, `"—"` or `"1.2.3"` that are stored as text.

### 3.3 One unit per distinct string

Spreadsheets repeat values heavily (category columns, status labels). The handler emits **one `TextUnit` per distinct cell string across the whole workbook**; its setter writes the translation to every cell that holds that string.

- Lower cost and faster runs.
- The same source text always gets the same translation, which matters for columns users filter or group on.

Strings are compared exactly (case- and whitespace-sensitive).

### 3.4 Plain-text cells only

The workbook is loaded without `rich_text=True`. A cell with mixed inline formatting (for example one bold word) is read as plain text, and after translation the whole cell carries the cell-level format. Cell-level formatting (font, fill, alignment, wrap, number format) is always preserved because only `cell.value` is assigned.

### 3.5 Merged cells

Only the top-left cell of a merged range holds a value; the others are `MergedCell` objects with `value is None` and fail rule 3.2(1). No dedupe logic is needed.

### 3.6 Formulas that depend on translated text

A formula such as `=IF(A1="Sí", …)` or a `VLOOKUP` keyed on a text label stops matching once the label is translated. Wormhole does not detect this. It is documented as a known limitation in the README.

---

## 4. Implementation

### 4.1 Dependency

```toml
# pyproject.toml
dependencies = [
    "python-docx>=0.8.11",
    "python-pptx>=0.6.21",
    "openpyxl>=3.1.0",        # NEW
    "openai>=1.0.0",
    "python-dotenv>=1.0.0",
]
```

Run `uv lock` to refresh `uv.lock`.

### 4.2 Import guard

```python
# wormhole/documents.py

def _import_openpyxl():
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise WormholeError(
            "openpyxl is required to process .xlsx files. "
            "Install the optional dependency with `pip install openpyxl`."
        ) from exc
    return load_workbook
```

### 4.3 `XlsxDocumentHandler`

```python
# wormhole/documents.py

class XlsxDocumentHandler(BaseDocumentHandler):
    """Extracts and reinserts text for Excel workbooks."""

    def __init__(self, source_path: pathlib.Path):
        super().__init__(source_path)
        load_workbook = _import_openpyxl()
        self.workbook = load_workbook(str(source_path))
        self.warnings = self._detect_unsupported_content(source_path)

    def extract_text_units(self) -> List[TextUnit]: ...
    def save(self, destination: pathlib.Path) -> None:
        self.workbook.save(str(destination))
```

Loading rules:

- Use the default `data_only=False`. With `data_only=True` formulas are replaced by their cached values and are **lost on save**.
- Do not use `read_only=True`; cells must be writable.

`extract_text_units()`:

1. Iterate `self.workbook.worksheets` in order, with index `s_idx`.
2. For each sheet iterate `sheet.iter_rows()` and each cell in the row.
3. Apply the rules of §3.2.
4. Group cells by their string value in a dict that preserves first-seen order.
5. Emit one unit per distinct string:

| Field | Value |
|---|---|
| `unit_id` | `sheet{s_idx}.{coordinate}` of the first occurrence, e.g. `sheet0.B5` |
| `original_text` | the cell string |
| `location` | `Sheet "<title>", cell B5`; append ` (and N more cells)` when the string occurs more than once |
| `atomic` | `False` (long cell texts may be split by the segmenter like any paragraph) |
| `setter` | assigns the translated text to `cell.value` for every cell in the group |

The setter must bind its cell list explicitly (default argument or a factory function), not via a loop-variable closure.

6. Return `self.register_units(units)`.

### 4.4 Handler warnings

`openpyxl` drops some content on save (§6). The user must be told before they rely on the output.

```python
# wormhole/documents.py — BaseDocumentHandler.__init__
self.warnings: List[str] = []      # NEW, empty for docx/pptx
```

`XlsxDocumentHandler._detect_unsupported_content()` opens the source file with `zipfile` and inspects the part names. It returns one message per category found:

| Part name prefix | Message |
|---|---|
| `xl/charts/` | "This workbook contains charts. They may be missing from the translated file." |
| `xl/drawings/` or `xl/media/` | "This workbook contains images, shapes or text boxes. They may be missing from the translated file." |
| `xl/pivotTables/` | "This workbook contains pivot tables. Check them in the translated file." |

In `TranslationRunner.run()`, directly after `detect_handler()`:

```python
for warning in handler.warnings:
    self.io.error(warning)
```

Warnings are shown regardless of `--verbose` and do not count as errors in the summary.

### 4.5 `detect_handler()`

```python
if suffix == ".xlsx":
    handler = XlsxDocumentHandler(path)
    return "xlsx", handler
raise UnsupportedFileTypeError(
    "This file type isn’t supported — please use .docx, .pptx or .xlsx."
)
```

### 4.6 User-facing text

| File | Change |
|---|---|
| `wormhole/cli.py` | Parser description and `input_file` help mention Excel / `.xlsx`. |
| `wormhole/translator.py` | "Input file not found" message in `validate_paths()` lists `.xlsx`. |
| `wormhole/gui.py` | Input label reads "(.docx, .pptx or .xlsx)"; both file dialogs gain `("Excel workbooks", "*.xlsx")`; the "please choose an input" message lists `.xlsx`. |
| `wormhole/gui.py` | `asksaveasfilename` currently hard-codes `defaultextension=".docx"`. Derive it from the selected input file's suffix, falling back to `.docx`. |

`derive_output_path()` already reuses the input suffix and needs no change.

### 4.7 Packaging and docs

- `wormhole.spec`: verify the PyInstaller build opens an `.xlsx`; add `collect_submodules('openpyxl')` to `hidden` if it does not.
- `README.md`: supported formats, an `.xlsx` example, and a "Known limitations for Excel" section covering §2 (out of scope), §3.6 and §6.
- `TECHSPEC.md`: supported formats, `document_type` values (`"xlsx"`), handler list.

---

## 5. Files Changed

| File | Change |
|---|---|
| `pyproject.toml`, `uv.lock` | Add `openpyxl` |
| `wormhole/documents.py` | `_import_openpyxl()`, `XlsxDocumentHandler`, `warnings` on the base handler, `.xlsx` branch in `detect_handler()` |
| `wormhole/translator.py` | Emit handler warnings; update "file not found" message |
| `wormhole/cli.py` | Help texts |
| `wormhole/gui.py` | Labels, file-dialog filters, default extension |
| `wormhole.spec` | Hidden imports, if needed |
| `README.md`, `TECHSPEC.md` | Documentation |

No changes to `segmenter.py`, `providers.py`, `structures.py`, `policy.py` or `interaction.py`.

---

## 6. Fidelity Limits of `openpyxl`

`openpyxl` rewrites the whole workbook on save and only writes back what it models. Content it does not model can be missing or altered in the output: charts, shapes and text boxes are the known cases; images, pivot tables and some conditional-formatting or extension features should be checked per workbook.

The exact behaviour of the pinned `openpyxl` version must be confirmed during implementation (§7, test 7) and the warning texts in §4.4 adjusted to match what is actually lost.

---

## 7. Acceptance Criteria

Verification uses the `echo` provider where no real translation is needed, and one real provider run.

1. `wormhole book.xlsx -t en` produces `book_en.xlsx`; the input file is unchanged.
2. Every text cell on every sheet is translated; numbers, dates, booleans and formulas are identical to the source, and formulas still calculate when opened in Excel.
3. Column widths, row heights, merged ranges, fills, fonts, number formats and frozen panes match the source.
4. A string that appears in 50 cells yields one unit (visible in the `-v` "Prepared N text units" line) and all 50 cells receive the same translation.
5. Text-typed cells without letters (e.g. `"2024-01"`) are left untouched.
6. Sheet names are unchanged.
7. A workbook containing a chart and an image triggers the corresponding warnings, with and without `-v`. The output is inspected to record what `openpyxl` actually preserved.
8. `.xlsm`, `.xls` and `.csv` inputs are rejected with the updated "unsupported file type" message.
9. The GUI lists Excel workbooks in both file dialogs and suggests an `.xlsx` output name for an `.xlsx` input.
10. `.docx` and `.pptx` translation behaves as before.

---

## 8. Possible Follow-ups

- Translate cell comments and headers / footers.
- Opt-in sheet-name translation with formula-reference rewriting and 31-character truncation.
- Preserve mixed in-cell formatting via `rich_text=True` and the existing `<run id="…">` tagging.
- `.xlsm` support via `keep_vba=True`.
- Direct package-XML editing (`xl/sharedStrings.xml` and inline strings) for full fidelity when a workbook contains charts or shapes.
