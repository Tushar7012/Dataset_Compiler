# TuneForge Implementation Plan — Part 4 (Tasks 7 & 8)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec. Tasks 1–6 are already implemented and committed: the FastAPI shell, SQLite persistence, provider client, credential storage, model analyzer, training planner, and research fallback. This part builds document ingestion (turning PDFs/DOCX/etc. into token-chunked source text) and structured-dataset normalization (turning existing training-shaped files directly into canonical records, skipping generation entirely). Do not implement anything beyond Task 7 and Task 8 — `plan_5.md` covers what's next.
>
> This is the largest part so far and pulls in a genuinely heavy dependency. Read the note right after Global Constraints below before you assume anything about what Docling needs — `torch`/`torchvision` are unavoidable pip installs the moment `docling` is a dependency at all (verified against Docling's actual package metadata, not assumed), but OCR is deliberately turned off in this part, so the OCR model itself never downloads. Every code block has already been run against the real installed libraries (79 tests, all green, including real document parsing and real tokenizer-based chunking) — copy it as-is. Only write your own code where a step explicitly says so.
>
> When both tasks are done, stop and produce the completion report at the bottom. Do not push to GitHub.

**Goal (this part):** Turn any of PDF/DOCX/HTML/Markdown/TXT/CSV/JSON/JSONL into either (a) provenance-tagged source text chunks ready for synthetic generation, or (b) canonical training records directly, when the file already looks like training data.

**Architecture:** Two independent modules. `tuneforge.ingestion` wraps Docling (document parsing + OCR + tokenizer-aware chunking) and a separate stdlib-only path for CSV/JSON/JSONL (structured data is read as structured data, never flattened to prose first). `tuneforge.normalization` takes what `ingestion.structured` loaded and, if it already matches one of six known training-data shapes, converts it straight into canonical records — no LLM involved, ever, for this path. This part also introduces `tuneforge.records`, the canonical Pydantic contracts from `PLAN.md` that neither ingestion nor normalization can work without and that nothing before this part needed.

**Tech Stack (new in this part):** `docling` (document parsing and tokenizer-aware chunking — pulls in `torch`/`torchvision` as its own unavoidable dependencies; OCR is disabled, see the note below), `transformers` (used directly for `AutoTokenizer`).

## Global Constraints

Repeated from Parts 1–3, still binding:

- Windows-first, Python 3.12, uv-managed, no conda.
- Input formats: PDF, DOCX, TXT, Markdown, HTML, CSV, JSON, JSONL — nothing else.
- Existing compatible structured data is normalized **without LLM rewriting**.
- API keys/tokens through Windows Credential Manager only (unaffected here — no new credentials needed).

## Note on Docling's dependencies — read before Step 1

This was checked against Docling's actual published package metadata, not assumed. Plain `pip install docling` (what `uv sync` will do here) is really `docling-slim[standard]` under the hood, and the `standard` extra unconditionally includes `torch`, `torchvision`, and `rapidocr` (an OCR engine) — there is no lighter Docling install that still supports PDF at all; without any extras, `docling-slim` has zero format backends, not even for PDF. Docling's whole approach to PDF is ML-based layout understanding (reading order, tables, headings), and that's what actually needs `torch`. If `docling` is a dependency, `torch`/`torchvision` are installed — that's not optional at the pip level.

What **is** avoidable, and deliberately avoided in this part: the OCR model itself. `PdfPipelineOptions()` defaults to `do_ocr=True` even if you never touch that setting — Step 6 below explicitly sets `do_ocr=False`. That means scanned/image-only PDFs won't extract any text (a real feature cut from `PLAN.md`'s Task 7 checklist, not a workaround), but the OCR model never gets downloaded, and normal text-layer PDFs, DOCX, HTML, Markdown, and TXT are completely unaffected by this flag. The layout model itself (`docling-ibm-models`, a few hundred MB) still downloads once, the first time you actually convert a real PDF — DOCX/HTML/MD/TXT parsing never touches it.

## Development Environment

Same as before — **uv**, no conda, no direct `pip`.

```powershell
cd backend
uv sync
uv run pytest -q
```

`uv sync` pulls in `torch`/`torchvision` and the rest of Docling's `standard` dependency set — a multi-minute, multi-GB install, not a quick one, for the reason explained above. The tests in this part use a real (tiny) tokenizer (`gpt2`) and real document parsing — the first test run downloads the `gpt2` tokenizer files (a few MB) from Hugging Face, then caches them locally. No OCR model download happens at any point in this part.

## Repository State

Same repo, branch `main`, `origin` already set. Commit locally as instructed. **Do not run `git push`.**

## File Structure (this part)

```
backend/
  pyproject.toml            (modified — add docling, transformers)
  tuneforge/
    records.py               (new — canonical contracts every later task also uses)
    ingestion/
      __init__.py
      documents.py
      chunking.py
      structured.py
    normalization/
      __init__.py
      detector.py
      mappers.py
      preview.py
  tests/
    ingestion/
      __init__.py
      test_documents.py
      test_chunking.py
      test_structured.py
    normalization/
      __init__.py
      test_detector.py
      test_mappers.py
      test_preview.py
```

---

### Task 7: Document ingestion and chunking

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/tuneforge/records.py`
- Create: `backend/tuneforge/ingestion/__init__.py`
- Create: `backend/tuneforge/ingestion/documents.py`
- Create: `backend/tuneforge/ingestion/chunking.py`
- Create: `backend/tuneforge/ingestion/structured.py`
- Create: `backend/tests/ingestion/__init__.py`
- Create: `backend/tests/ingestion/test_documents.py`
- Create: `backend/tests/ingestion/test_chunking.py`
- Create: `backend/tests/ingestion/test_structured.py`

**On the extra file (`records.py`) not in `PLAN.md`'s Task 7 file list:** `PLAN.md`'s "Canonical Data Contracts" section (`SourceRecord`, `CPTRecord`, `SFTPromptCompletionRecord`, `ChatMessage`, `SFTConversationRecord`, `DPORecord`) hasn't been created by any task so far, and both this task and Task 8 need it. It's created once, here, since ingestion is the first consumer.

**On `chunking.py` vs. hand-rolled chunking logic:** `PLAN.md` says "apply tokenizer-aware hybrid chunking" — that phrase isn't a description to reimplement, it's the name of a real Docling feature: `docling.chunking.HybridChunker`. This part uses it directly rather than writing a custom chunking algorithm.

**On OCR:** deliberately disabled (see the note above Development Environment). `PLAN.md`'s Task 7 checklist item "Enable local OCR for scanned PDFs" is explicitly **not** implemented in this part — scanned/image-only PDFs will parse without error but produce no extracted text. Every other checklist item (PDF/DOCX/HTML/MD/TXT parsing, CSV/JSON/JSONL without flattening, provenance preservation, tokenizer-aware chunking, error classification, caching) is implemented as specified.

**Interfaces produced (Task 8 and later parts rely on these exact names):**
- `tuneforge.records.SourceRecord`, `.RecordMetadata`, `.CPTRecord`, `.SFTPromptCompletionRecord`, `.ChatMessage`, `.SFTConversationRecord`, `.DPORecord` — match `PLAN.md`'s canonical contracts exactly
- `tuneforge.ingestion.documents.convert_document(path, *, converter=None) -> DoclingDocument`, `.convert_document_cached(path, *, cache_dir, converter=None) -> tuple[DoclingDocument, source_hash]`, `.build_converter() -> DocumentConverter`, `.hash_file(path) -> str`
- `tuneforge.ingestion.documents.UnsupportedDocumentError`, `.EmptyDocumentError`, `.OversizedDocumentError`, `.EncryptedDocumentError`, `.CorruptDocumentError`
- `tuneforge.ingestion.chunking.build_tokenizer(model_id, *, max_tokens=512) -> HuggingFaceTokenizer`, `.chunk_into_source_records(document, *, document_id, source_name, source_hash, tokenizer) -> list[SourceRecord]`
- `tuneforge.ingestion.structured.StructuredRow`, `.load_structured_rows(path) -> list[StructuredRow]`, `.UnsupportedStructuredFormatError`, `.EmptyStructuredFileError`

#### Step 1: Add dependencies

Edit `backend/pyproject.toml`:

```toml
[project]
name = "tuneforge"
version = "0.1.0"
description = "TuneForge backend"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "sqlalchemy>=2.0.35",
    "httpx>=0.27",
    "keyring>=25.0",
    "huggingface-hub>=1.0",
    "docling>=2.120.1",
    "transformers>=5.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["tuneforge*"]
```

```powershell
cd backend
uv sync
```

This will take a while and download several GB of dependencies (torch, torchvision, transformers) — that's expected, see the note above Development Environment for why. OCR is disabled in this part's code (Step 6), so no OCR model ever downloads; Docling's PDF layout model still downloads once, lazily, the first time a real PDF is converted.

#### Step 2: Canonical records — no test needed

`backend/tuneforge/records.py` is a pure data-contract file (Pydantic models, no logic) copied verbatim from `PLAN.md`'s own spec — it gets exercised by every test in this part that imports it, so a dedicated test file would just be testing the language, not any logic of ours.

Create `backend/tuneforge/records.py`:

```python
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, JsonValue


class SourceRecord(BaseModel):
    document_id: uuid.UUID
    chunk_id: str
    text: str
    source_name: str
    source_hash: str
    page: int | None
    heading: str | None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RecordMetadata(BaseModel):
    document_id: uuid.UUID
    source_name: str
    source_hash: str
    chunk_id: str | None = None
    row_id: str | None = None
    extra: dict[str, JsonValue] = Field(default_factory=dict)


class CPTRecord(BaseModel):
    text: str
    metadata: RecordMetadata


class SFTPromptCompletionRecord(BaseModel):
    prompt: str
    completion: str
    metadata: RecordMetadata


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class SFTConversationRecord(BaseModel):
    messages: list[ChatMessage]
    metadata: RecordMetadata


class DPORecord(BaseModel):
    prompt: list[ChatMessage]
    chosen: list[ChatMessage]
    rejected: list[ChatMessage]
    metadata: RecordMetadata
```

#### Step 3: Structured file loading — write the failing tests (RED)

Create `backend/tuneforge/ingestion/__init__.py` (empty), `backend/tests/ingestion/__init__.py` (empty).

Create `backend/tests/ingestion/test_structured.py`:

```python
import json

import pytest

from tuneforge.ingestion.structured import (
    EmptyStructuredFileError,
    UnsupportedStructuredFormatError,
    load_structured_rows,
)


def test_loads_csv_rows_preserving_row_index(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("prompt,completion\nhi,hello\nbye,goodbye\n")

    rows = load_structured_rows(path)

    assert [r.row_id for r in rows] == ["0", "1"]
    assert rows[0].data == {"prompt": "hi", "completion": "hello"}
    assert rows[0].source_name == "data.csv"


def test_loads_json_array_rows(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps([{"text": "a"}, {"text": "b"}]))

    rows = load_structured_rows(path)

    assert len(rows) == 2
    assert rows[1].data == {"text": "b"}


def test_loads_jsonl_rows_skipping_blank_lines(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text('{"text": "a"}\n\n{"text": "b"}\n')

    rows = load_structured_rows(path)

    assert len(rows) == 2
    assert rows[0].row_id == "0"
    assert rows[1].row_id == "2"


def test_empty_csv_raises_clear_error(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("prompt,completion\n")

    with pytest.raises(EmptyStructuredFileError):
        load_structured_rows(path)


def test_unsupported_extension_raises_clear_error(tmp_path):
    path = tmp_path / "data.xml"
    path.write_text("<root></root>")

    with pytest.raises(UnsupportedStructuredFormatError):
        load_structured_rows(path)


def test_identical_content_produces_identical_source_hash(tmp_path):
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    path_a.write_text(json.dumps([{"text": "same"}]))
    path_b.write_text(json.dumps([{"text": "same"}]))

    rows_a = load_structured_rows(path_a)
    rows_b = load_structured_rows(path_b)

    assert rows_a[0].source_hash == rows_b[0].source_hash
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/ingestion/test_structured.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.ingestion.structured'`.

#### Step 4: Structured file loading — implement (GREEN)

Create `backend/tuneforge/ingestion/structured.py`:

```python
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class UnsupportedStructuredFormatError(RuntimeError):
    pass


class EmptyStructuredFileError(RuntimeError):
    pass


@dataclass(frozen=True)
class StructuredRow:
    row_id: str
    data: dict[str, Any]
    source_name: str
    source_hash: str


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_csv_rows(path: Path) -> list[StructuredRow]:
    source_hash = _hash_file(path)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            StructuredRow(row_id=str(i), data=dict(row), source_name=path.name, source_hash=source_hash)
            for i, row in enumerate(reader)
        ]
    if not rows:
        raise EmptyStructuredFileError(f"{path.name}: no data rows")
    return rows


def load_json_rows(path: Path) -> list[StructuredRow]:
    source_hash = _hash_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise EmptyStructuredFileError(f"{path.name}: expected a non-empty JSON array or object")
    return [
        StructuredRow(row_id=str(i), data=row, source_name=path.name, source_hash=source_hash)
        for i, row in enumerate(data)
    ]


def load_jsonl_rows(path: Path) -> list[StructuredRow]:
    source_hash = _hash_file(path)
    rows = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            rows.append(
                StructuredRow(row_id=str(i), data=json.loads(line), source_name=path.name, source_hash=source_hash)
            )
    if not rows:
        raise EmptyStructuredFileError(f"{path.name}: no data rows")
    return rows


LOADERS = {
    ".csv": load_csv_rows,
    ".json": load_json_rows,
    ".jsonl": load_jsonl_rows,
}


def load_structured_rows(path: Path) -> list[StructuredRow]:
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        raise UnsupportedStructuredFormatError(f"{path.name}: unsupported structured format {path.suffix!r}")
    return loader(path)
```

Run the tests again:

```powershell
uv run pytest tests/ingestion/test_structured.py -q
```

Expected: all pass.

#### Step 5: Document parsing — write the failing tests (RED)

Create `backend/tests/ingestion/test_documents.py`:

```python
import pytest
from docling.exceptions import ConversionError, SecurityError

from tuneforge.ingestion.documents import (
    CorruptDocumentError,
    EmptyDocumentError,
    EncryptedDocumentError,
    OversizedDocumentError,
    UnsupportedDocumentError,
    convert_document,
    convert_document_cached,
)


class _FakeConverter:
    def __init__(self, *, raises: Exception | None = None, document=None):
        self._raises = raises
        self._document = document
        self.calls = 0

    def convert(self, path):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return type("Result", (), {"document": self._document})()


def test_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "data.xyz"
    path.write_text("hello")
    with pytest.raises(UnsupportedDocumentError):
        convert_document(path)


def test_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("")
    with pytest.raises(EmptyDocumentError):
        convert_document(path)


def test_rejects_oversized_file(tmp_path, monkeypatch):
    import tuneforge.ingestion.documents as documents_module

    monkeypatch.setattr(documents_module, "MAX_DOCUMENT_BYTES", 10)
    path = tmp_path / "big.txt"
    path.write_text("this text is definitely more than ten bytes long")
    with pytest.raises(OversizedDocumentError):
        convert_document(path)


def test_translates_security_error_to_encrypted_document_error(tmp_path):
    path = tmp_path / "locked.pdf"
    path.write_bytes(b"%PDF-1.4 fake but non-empty")
    fake_converter = _FakeConverter(raises=SecurityError("locked"))
    with pytest.raises(EncryptedDocumentError):
        convert_document(path, converter=fake_converter)


def test_translates_conversion_error_to_corrupt_document_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 not actually valid")
    fake_converter = _FakeConverter(raises=ConversionError("broken"))
    with pytest.raises(CorruptDocumentError):
        convert_document(path, converter=fake_converter)


def test_real_markdown_file_converts_successfully(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("# Title\n\nSome real content here.\n")

    document = convert_document(path)

    assert "Some real content here." in document.export_to_markdown()


def test_cached_conversion_skips_reparsing_on_second_call(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("# Title\n\nCached content.\n")
    cache_dir = tmp_path / "cache"

    document_a, hash_a = convert_document_cached(path, cache_dir=cache_dir)
    document_b, hash_b = convert_document_cached(path, cache_dir=cache_dir)

    assert hash_a == hash_b
    assert document_a.export_to_markdown() == document_b.export_to_markdown()
    assert len(list(cache_dir.iterdir())) == 1


def test_cache_hit_never_calls_the_converter(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("# Title\n\nCached content.\n")
    cache_dir = tmp_path / "cache"

    convert_document_cached(path, cache_dir=cache_dir)

    fake_converter = _FakeConverter(raises=AssertionError("should not be called on a cache hit"))
    convert_document_cached(path, cache_dir=cache_dir, converter=fake_converter)

    assert fake_converter.calls == 0
```

`test_real_markdown_file_converts_successfully` and the two caching tests use the **real** Docling converter (no mocking) — Markdown needs no OCR/ML models, so this stays fast. The encrypted/corrupt tests use a fake converter that raises Docling's real exception types (`SecurityError`, `ConversionError`) — that's how Docling actually signals those two conditions; producing an actual encrypted or corrupted PDF just to test error translation would be more effort for the same coverage.

Run it and confirm it fails on the missing module:

```powershell
uv run pytest tests/ingestion/test_documents.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.ingestion.documents'`.

#### Step 6: Document parsing — implement (GREEN)

Create `backend/tuneforge/ingestion/documents.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path

import docling
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.exceptions import ConversionError, SecurityError
from docling_core.types.doc.document import DoclingDocument

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".md", ".txt"}
# ponytail: fixed 200MB ceiling; make configurable if a real document exceeds it.
MAX_DOCUMENT_BYTES = 200 * 1024 * 1024


class UnsupportedDocumentError(RuntimeError):
    pass


class EmptyDocumentError(RuntimeError):
    pass


class OversizedDocumentError(RuntimeError):
    pass


class EncryptedDocumentError(RuntimeError):
    pass


class CorruptDocumentError(RuntimeError):
    pass


def build_converter() -> DocumentConverter:
    # OCR deliberately off: a bare DocumentConverter() actually defaults
    # do_ocr=True, so this has to be explicit. Scanned/image-only PDFs
    # won't extract any text as a result — accepted trade-off to avoid
    # ever pulling down an OCR model. Normal (text-layer) PDFs, DOCX,
    # HTML, Markdown, and TXT are unaffected by this flag either way.
    pdf_options = PdfPipelineOptions(do_ocr=False)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)})


def _validate_before_parsing(path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedDocumentError(f"{path.name}: unsupported file type {path.suffix!r}")
    size = path.stat().st_size
    if size == 0:
        raise EmptyDocumentError(f"{path.name}: file is empty")
    if size > MAX_DOCUMENT_BYTES:
        raise OversizedDocumentError(f"{path.name}: {size} bytes exceeds the {MAX_DOCUMENT_BYTES} byte limit")


def convert_document(path: Path, *, converter: DocumentConverter | None = None) -> DoclingDocument:
    """Parse one document into a DoclingDocument.

    Always raises one of the ...Error classes above with an actionable
    message — docling's own exception types never leak out of this
    function, so callers only need to know this module's vocabulary.
    """
    _validate_before_parsing(path)
    converter = converter or build_converter()
    try:
        result = converter.convert(path)
    except SecurityError as exc:
        raise EncryptedDocumentError(f"{path.name}: is password-protected or encrypted") from exc
    except ConversionError as exc:
        raise CorruptDocumentError(f"{path.name}: could not be parsed — {exc}") from exc
    return result.document


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def convert_document_cached(
    path: Path,
    *,
    cache_dir: Path,
    converter: DocumentConverter | None = None,
) -> tuple[DoclingDocument, str]:
    """Same as convert_document, but skips re-parsing (the expensive part,
    especially with OCR) if this exact file was already parsed by this
    exact docling version. Returns (document, source_hash) since callers
    need the hash anyway for the resulting SourceRecords.
    """
    source_hash = hash_file(path)
    cache_path = cache_dir / f"{source_hash}-{docling.__version__}.json"
    if cache_path.exists():
        return DoclingDocument.load_from_json(cache_path), source_hash

    document = convert_document(path, converter=converter)
    cache_dir.mkdir(parents=True, exist_ok=True)
    document.save_as_json(cache_path)
    return document, source_hash
```

Run the tests again:

```powershell
uv run pytest tests/ingestion/test_documents.py -q
```

Expected: all pass. The first run downloads Docling's layout-model weights on first real conversion — subsequent runs are fast.

#### Step 7: Tokenizer-aware chunking — write the failing tests (RED)

Create `backend/tests/ingestion/test_chunking.py`:

```python
import uuid

from tuneforge.ingestion.chunking import build_tokenizer, chunk_into_source_records
from tuneforge.ingestion.documents import convert_document


def test_chunks_carry_heading_and_are_grounded_in_source_text(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text(
        "# Company Policy\n\n"
        "## Vacation Policy\n\n"
        "Employees get 20 days of paid vacation per year.\n\n"
        "## Sick Leave\n\n"
        "Employees get 10 days of paid sick leave per year.\n"
    )
    document = convert_document(path)
    tokenizer = build_tokenizer("gpt2", max_tokens=64)
    document_id = uuid.uuid4()

    records = chunk_into_source_records(
        document,
        document_id=document_id,
        source_name=path.name,
        source_hash="deadbeef",
        tokenizer=tokenizer,
    )

    assert len(records) == 2
    assert records[0].heading == "Vacation Policy"
    assert "20 days" in records[0].text
    assert records[1].heading == "Sick Leave"
    assert "10 days" in records[1].text
    for record in records:
        assert record.document_id == document_id
        assert record.source_hash == "deadbeef"
        assert record.source_name == "policy.md"


def test_chunk_ids_are_unique_and_stable_within_a_document(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("# Title\n\nFirst paragraph.\n\nSecond paragraph.\n")
    document = convert_document(path)
    tokenizer = build_tokenizer("gpt2", max_tokens=64)
    document_id = uuid.uuid4()

    records = chunk_into_source_records(
        document, document_id=document_id, source_name="policy.md", source_hash="abc123", tokenizer=tokenizer
    )

    chunk_ids = [r.chunk_id for r in records]
    assert len(chunk_ids) == len(set(chunk_ids))
```

These tests use `gpt2` as the "target model" tokenizer — it's small, universally available, and downloads in seconds on first use. In production, `build_tokenizer` gets called with whatever model the user actually picked (via Task 4's analyzer), not a hardcoded value; `gpt2` here is just a fast, real stand-in for testing.

Run it and confirm it fails on the missing module:

```powershell
uv run pytest tests/ingestion/test_chunking.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.ingestion.chunking'`.

#### Step 8: Tokenizer-aware chunking — implement (GREEN)

Create `backend/tuneforge/ingestion/chunking.py`:

```python
from __future__ import annotations

import uuid

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc.document import DoclingDocument
from transformers import AutoTokenizer

from tuneforge.records import SourceRecord

DEFAULT_MAX_TOKENS_PER_CHUNK = 512


def build_tokenizer(model_id: str, *, max_tokens: int = DEFAULT_MAX_TOKENS_PER_CHUNK) -> HuggingFaceTokenizer:
    """Wraps the *target model's own* tokenizer for HybridChunker, so chunk
    boundaries are measured in the tokens that model will actually see —
    not some fixed character count that has nothing to do with its context
    window.
    """
    hf_tokenizer = AutoTokenizer.from_pretrained(model_id)
    return HuggingFaceTokenizer(tokenizer=hf_tokenizer, max_tokens=max_tokens)


def chunk_into_source_records(
    document: DoclingDocument,
    *,
    document_id: uuid.UUID,
    source_name: str,
    source_hash: str,
    tokenizer: HuggingFaceTokenizer,
) -> list[SourceRecord]:
    chunker = HybridChunker(tokenizer=tokenizer)
    records = []
    for index, chunk in enumerate(chunker.chunk(dl_doc=document)):
        page = None
        for doc_item in chunk.meta.doc_items:
            if doc_item.prov:
                page = doc_item.prov[0].page_no
                break
        heading = chunk.meta.headings[-1] if chunk.meta.headings else None
        records.append(
            SourceRecord(
                document_id=document_id,
                chunk_id=f"{document_id}-{index}",
                text=chunk.text,
                source_name=source_name,
                source_hash=source_hash,
                page=page,
                heading=heading,
                metadata={"headings": list(chunk.meta.headings)},
            )
        )
    return records
```

Run the tests again:

```powershell
uv run pytest tests/ingestion/test_chunking.py -q
```

Expected: all pass.

#### Step 9: Run the full backend suite and commit

```powershell
uv run pytest -q
```

Expected: every test from Parts 1–3 and this task passes.

```powershell
git add backend
git commit -m "feat: add provenance-aware document ingestion"
```

---

### Task 8: Existing structured-dataset normalization

**Files:**
- Create: `backend/tuneforge/normalization/__init__.py`
- Create: `backend/tuneforge/normalization/detector.py`
- Create: `backend/tuneforge/normalization/mappers.py`
- Create: `backend/tuneforge/normalization/preview.py`
- Create: `backend/tests/normalization/__init__.py`
- Create: `backend/tests/normalization/test_detector.py`
- Create: `backend/tests/normalization/test_mappers.py`
- Create: `backend/tests/normalization/test_preview.py`

**Interfaces consumed:** `tuneforge.ingestion.structured.StructuredRow` (this part's Task 7), `tuneforge.records.*` (this part's Task 7).

**Interfaces produced:**
- `tuneforge.normalization.detector.DetectedSchema` (enum), `.SchemaDetectionResult`, `.detect_schema(rows) -> SchemaDetectionResult`
- `tuneforge.normalization.mappers.normalize_rows(rows, schema, *, document_id) -> list`, `.InvalidRecordError`
- `tuneforge.normalization.preview.apply_column_mapping(rows, mapping) -> list[StructuredRow]`, `.preview_normalization(rows, schema, *, document_id, limit=20) -> list`, `.ColumnMappingError`

**On detection being exact-match only, not fuzzy:** `detect_schema` recognizes six specific key shapes and returns `None` for anything else — no partial credit, no "looks kind of like it." `PLAN.md`'s own instruction is "never call an LLM merely to rename or map obvious fields," and a fuzzy/scored detector would just be inventing false confidence about columns it doesn't actually recognize. Anything that doesn't match exactly is meant to go through `apply_column_mapping` — a human saying what a column means, not a model guessing.

**On the `prompt`/`chosen`/`rejected` DPO shape assumption:** this recognizes the common flat-string form (`{"prompt": "...", "chosen": "...", "rejected": "..."}`), each wrapped into a single-message `ChatMessage` list to fit the canonical `DPORecord` contract. A dataset that already stores `chosen`/`rejected` as multi-turn message lists isn't handled — out of scope for this task, not silently mishandled (it simply won't match this detector's key shape and will fall through to manual mapping instead).

#### Step 1: Schema detection — write the failing tests (RED)

Create `backend/tuneforge/normalization/__init__.py` (empty), `backend/tests/normalization/__init__.py` (empty).

Create `backend/tests/normalization/test_detector.py`:

```python
from tuneforge.normalization.detector import DetectedSchema, detect_schema


def test_detects_text_schema():
    result = detect_schema([{"text": "hello world"}])
    assert result.schema_name == DetectedSchema.TEXT


def test_detects_prompt_completion_schema():
    result = detect_schema([{"prompt": "hi", "completion": "hello"}])
    assert result.schema_name == DetectedSchema.PROMPT_COMPLETION


def test_detects_instruction_input_output_schema():
    result = detect_schema([{"instruction": "summarize", "input": "text", "output": "summary"}])
    assert result.schema_name == DetectedSchema.INSTRUCTION_INPUT_OUTPUT


def test_detects_messages_schema():
    result = detect_schema([{"messages": [{"role": "user", "content": "hi"}]}])
    assert result.schema_name == DetectedSchema.MESSAGES


def test_detects_conversations_schema():
    result = detect_schema([{"conversations": [{"from": "human", "value": "hi"}]}])
    assert result.schema_name == DetectedSchema.CONVERSATIONS


def test_detects_prompt_chosen_rejected_schema():
    result = detect_schema([{"prompt": "q", "chosen": "good", "rejected": "bad"}])
    assert result.schema_name == DetectedSchema.PROMPT_CHOSEN_REJECTED


def test_prompt_chosen_rejected_takes_priority_over_prompt_completion():
    # A row with all five keys is unambiguously DPO-shaped, not SFT-shaped.
    result = detect_schema([{"prompt": "q", "completion": "x", "chosen": "good", "rejected": "bad"}])
    assert result.schema_name == DetectedSchema.PROMPT_CHOSEN_REJECTED


def test_unrecognized_columns_return_none_not_a_guess():
    result = detect_schema([{"question": "hi", "answer": "hello"}])
    assert result.schema_name is None
    assert result.confidence == 0.0


def test_empty_rows_return_none():
    result = detect_schema([])
    assert result.schema_name is None
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/normalization/test_detector.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.normalization.detector'`.

#### Step 2: Schema detection — implement (GREEN)

Create `backend/tuneforge/normalization/detector.py`:

```python
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class DetectedSchema(StrEnum):
    TEXT = "text"
    PROMPT_COMPLETION = "prompt_completion"
    INSTRUCTION_INPUT_OUTPUT = "instruction_input_output"
    MESSAGES = "messages"
    CONVERSATIONS = "conversations"
    PROMPT_CHOSEN_REJECTED = "prompt_chosen_rejected"


class SchemaDetectionResult(BaseModel):
    schema_name: DetectedSchema | None
    confidence: float
    matched_keys: list[str]


def detect_schema(rows: list[dict]) -> SchemaDetectionResult:
    """Exact-key matching only — deliberately not fuzzy. This is meant to
    recognize obvious, common shapes without guessing; anything that
    doesn't match exactly falls back to manual column mapping rather than
    a low-confidence guess that might be wrong.
    """
    if not rows:
        return SchemaDetectionResult(schema_name=None, confidence=0.0, matched_keys=[])

    keys = set(rows[0].keys())

    if {"prompt", "chosen", "rejected"} <= keys:
        return SchemaDetectionResult(
            schema_name=DetectedSchema.PROMPT_CHOSEN_REJECTED, confidence=1.0, matched_keys=["prompt", "chosen", "rejected"]
        )
    if "messages" in keys and isinstance(rows[0].get("messages"), list):
        return SchemaDetectionResult(schema_name=DetectedSchema.MESSAGES, confidence=1.0, matched_keys=["messages"])
    if "conversations" in keys and isinstance(rows[0].get("conversations"), list):
        return SchemaDetectionResult(
            schema_name=DetectedSchema.CONVERSATIONS, confidence=1.0, matched_keys=["conversations"]
        )
    if {"prompt", "completion"} <= keys:
        return SchemaDetectionResult(
            schema_name=DetectedSchema.PROMPT_COMPLETION, confidence=1.0, matched_keys=["prompt", "completion"]
        )
    if {"instruction", "output"} <= keys:
        return SchemaDetectionResult(
            schema_name=DetectedSchema.INSTRUCTION_INPUT_OUTPUT, confidence=1.0, matched_keys=["instruction", "output"]
        )
    if "text" in keys and isinstance(rows[0].get("text"), str):
        return SchemaDetectionResult(schema_name=DetectedSchema.TEXT, confidence=1.0, matched_keys=["text"])

    return SchemaDetectionResult(schema_name=None, confidence=0.0, matched_keys=[])
```

Run the tests again:

```powershell
uv run pytest tests/normalization/test_detector.py -q
```

Expected: all pass.

#### Step 3: Mapping into canonical records — write the failing tests (RED)

Create `backend/tests/normalization/test_mappers.py`:

```python
import uuid

import pytest

from tuneforge.ingestion.structured import StructuredRow
from tuneforge.normalization.detector import DetectedSchema
from tuneforge.normalization.mappers import InvalidRecordError, normalize_rows


def _row(data: dict, row_id: str = "0") -> StructuredRow:
    return StructuredRow(row_id=row_id, data=data, source_name="data.jsonl", source_hash="deadbeef")


def test_normalizes_text_row_to_cpt_record():
    [record] = normalize_rows([_row({"text": "hello"})], DetectedSchema.TEXT, document_id=uuid.uuid4())
    assert record.text == "hello"
    assert record.metadata.row_id == "0"
    assert record.metadata.source_hash == "deadbeef"


def test_normalizes_prompt_completion_row():
    [record] = normalize_rows(
        [_row({"prompt": "hi", "completion": "hello"})], DetectedSchema.PROMPT_COMPLETION, document_id=uuid.uuid4()
    )
    assert record.prompt == "hi"
    assert record.completion == "hello"


def test_normalizes_instruction_row_combining_instruction_and_input():
    [record] = normalize_rows(
        [_row({"instruction": "Summarize:", "input": "long text", "output": "short"})],
        DetectedSchema.INSTRUCTION_INPUT_OUTPUT,
        document_id=uuid.uuid4(),
    )
    assert record.prompt == "Summarize:\n\nlong text"
    assert record.completion == "short"


def test_normalizes_instruction_row_without_input():
    [record] = normalize_rows(
        [_row({"instruction": "Say hi", "output": "hi"})],
        DetectedSchema.INSTRUCTION_INPUT_OUTPUT,
        document_id=uuid.uuid4(),
    )
    assert record.prompt == "Say hi"


def test_normalizes_messages_row():
    [record] = normalize_rows(
        [_row({"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]})],
        DetectedSchema.MESSAGES,
        document_id=uuid.uuid4(),
    )
    assert [m.role for m in record.messages] == ["user", "assistant"]


def test_messages_row_rejects_consecutive_same_role():
    rows = [_row({"messages": [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]})]
    with pytest.raises(InvalidRecordError):
        normalize_rows(rows, DetectedSchema.MESSAGES, document_id=uuid.uuid4())


def test_messages_row_rejects_starting_with_assistant():
    rows = [_row({"messages": [{"role": "assistant", "content": "a"}]})]
    with pytest.raises(InvalidRecordError):
        normalize_rows(rows, DetectedSchema.MESSAGES, document_id=uuid.uuid4())


def test_messages_row_allows_leading_system_message():
    [record] = normalize_rows(
        [
            _row(
                {
                    "messages": [
                        {"role": "system", "content": "be nice"},
                        {"role": "user", "content": "hi"},
                        {"role": "assistant", "content": "hello"},
                    ]
                }
            )
        ],
        DetectedSchema.MESSAGES,
        document_id=uuid.uuid4(),
    )
    assert [m.role for m in record.messages] == ["system", "user", "assistant"]


def test_normalizes_conversations_row_remapping_roles():
    [record] = normalize_rows(
        [_row({"conversations": [{"from": "human", "value": "hi"}, {"from": "gpt", "value": "hello"}]})],
        DetectedSchema.CONVERSATIONS,
        document_id=uuid.uuid4(),
    )
    assert [m.role for m in record.messages] == ["user", "assistant"]
    assert record.messages[1].content == "hello"


def test_conversations_row_rejects_unknown_sender():
    rows = [_row({"conversations": [{"from": "alien", "value": "hi"}]})]
    with pytest.raises(InvalidRecordError):
        normalize_rows(rows, DetectedSchema.CONVERSATIONS, document_id=uuid.uuid4())


def test_normalizes_dpo_row():
    [record] = normalize_rows(
        [_row({"prompt": "q", "chosen": "good answer", "rejected": "bad answer"})],
        DetectedSchema.PROMPT_CHOSEN_REJECTED,
        document_id=uuid.uuid4(),
    )
    assert record.prompt[0].content == "q"
    assert record.chosen[0].content == "good answer"
    assert record.rejected[0].content == "bad answer"


def test_missing_required_field_raises_invalid_record_error():
    rows = [_row({"prompt": "hi"})]
    with pytest.raises(InvalidRecordError):
        normalize_rows(rows, DetectedSchema.PROMPT_COMPLETION, document_id=uuid.uuid4())


def test_preserves_original_row_id_and_source_metadata():
    [record] = normalize_rows(
        [_row({"text": "hello"}, row_id="42")], DetectedSchema.TEXT, document_id=uuid.uuid4()
    )
    assert record.metadata.row_id == "42"
    assert record.metadata.source_name == "data.jsonl"
```

Run it and confirm it fails on the missing module:

```powershell
uv run pytest tests/normalization/test_mappers.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.normalization.mappers'`.

#### Step 4: Mapping into canonical records — implement (GREEN)

Create `backend/tuneforge/normalization/mappers.py`:

```python
from __future__ import annotations

import uuid

from tuneforge.ingestion.structured import StructuredRow
from tuneforge.normalization.detector import DetectedSchema
from tuneforge.records import (
    ChatMessage,
    CPTRecord,
    DPORecord,
    RecordMetadata,
    SFTConversationRecord,
    SFTPromptCompletionRecord,
)


class InvalidRecordError(RuntimeError):
    pass


def _metadata(row: StructuredRow, document_id: uuid.UUID) -> RecordMetadata:
    return RecordMetadata(
        document_id=document_id,
        source_name=row.source_name,
        source_hash=row.source_hash,
        row_id=row.row_id,
    )


def _require_nonempty_str(row: StructuredRow, field: str) -> str:
    value = row.data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRecordError(f"row {row.row_id}: {field!r} must be a non-empty string")
    return value


def _validate_role_alternation(messages: list[ChatMessage]) -> None:
    if not messages:
        raise InvalidRecordError("conversation has no messages")
    non_system = [m for m in messages if m.role != "system"]
    if not non_system:
        raise InvalidRecordError("conversation has only a system message")
    if non_system[0].role != "user":
        raise InvalidRecordError("conversation must start with a user message (after any system message)")
    for previous, current in zip(non_system, non_system[1:]):
        if previous.role == current.role:
            raise InvalidRecordError(f"consecutive {current.role!r} messages — roles must alternate")


def normalize_text_row(row: StructuredRow, *, document_id: uuid.UUID) -> CPTRecord:
    return CPTRecord(text=_require_nonempty_str(row, "text"), metadata=_metadata(row, document_id))


def normalize_prompt_completion_row(row: StructuredRow, *, document_id: uuid.UUID) -> SFTPromptCompletionRecord:
    return SFTPromptCompletionRecord(
        prompt=_require_nonempty_str(row, "prompt"),
        completion=_require_nonempty_str(row, "completion"),
        metadata=_metadata(row, document_id),
    )


def normalize_instruction_row(row: StructuredRow, *, document_id: uuid.UUID) -> SFTPromptCompletionRecord:
    instruction = _require_nonempty_str(row, "instruction")
    output = _require_nonempty_str(row, "output")
    input_text = row.data.get("input") or ""
    prompt = f"{instruction}\n\n{input_text}".strip() if input_text else instruction
    return SFTPromptCompletionRecord(prompt=prompt, completion=output, metadata=_metadata(row, document_id))


def normalize_messages_row(row: StructuredRow, *, document_id: uuid.UUID) -> SFTConversationRecord:
    raw_messages = row.data.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise InvalidRecordError(f"row {row.row_id}: 'messages' must be a non-empty list")
    try:
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in raw_messages]
    except (KeyError, TypeError) as exc:
        raise InvalidRecordError(f"row {row.row_id}: each message needs 'role' and 'content'") from exc
    _validate_role_alternation(messages)
    return SFTConversationRecord(messages=messages, metadata=_metadata(row, document_id))


_CONVERSATIONS_ROLE_MAP = {"human": "user", "gpt": "assistant", "system": "system"}


def normalize_conversations_row(row: StructuredRow, *, document_id: uuid.UUID) -> SFTConversationRecord:
    raw_turns = row.data.get("conversations")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise InvalidRecordError(f"row {row.row_id}: 'conversations' must be a non-empty list")
    messages = []
    for turn in raw_turns:
        sender = turn.get("from")
        role = _CONVERSATIONS_ROLE_MAP.get(sender)
        if role is None:
            raise InvalidRecordError(f"row {row.row_id}: unknown conversation sender {sender!r}")
        messages.append(ChatMessage(role=role, content=turn["value"]))
    _validate_role_alternation(messages)
    return SFTConversationRecord(messages=messages, metadata=_metadata(row, document_id))


def normalize_dpo_row(row: StructuredRow, *, document_id: uuid.UUID) -> DPORecord:
    prompt = _require_nonempty_str(row, "prompt")
    chosen = _require_nonempty_str(row, "chosen")
    rejected = _require_nonempty_str(row, "rejected")
    return DPORecord(
        prompt=[ChatMessage(role="user", content=prompt)],
        chosen=[ChatMessage(role="assistant", content=chosen)],
        rejected=[ChatMessage(role="assistant", content=rejected)],
        metadata=_metadata(row, document_id),
    )


NORMALIZERS = {
    DetectedSchema.TEXT: normalize_text_row,
    DetectedSchema.PROMPT_COMPLETION: normalize_prompt_completion_row,
    DetectedSchema.INSTRUCTION_INPUT_OUTPUT: normalize_instruction_row,
    DetectedSchema.MESSAGES: normalize_messages_row,
    DetectedSchema.CONVERSATIONS: normalize_conversations_row,
    DetectedSchema.PROMPT_CHOSEN_REJECTED: normalize_dpo_row,
}


def normalize_rows(rows: list[StructuredRow], schema: DetectedSchema, *, document_id: uuid.UUID) -> list:
    normalizer = NORMALIZERS[schema]
    return [normalizer(row, document_id=document_id) for row in rows]
```

Run the tests again:

```powershell
uv run pytest tests/normalization/test_mappers.py -q
```

Expected: all pass.

#### Step 5: Manual column mapping and preview — write the failing tests (RED)

Create `backend/tests/normalization/test_preview.py`:

```python
import uuid

import pytest

from tuneforge.ingestion.structured import StructuredRow
from tuneforge.normalization.detector import DetectedSchema
from tuneforge.normalization.preview import ColumnMappingError, apply_column_mapping, preview_normalization


def _row(data: dict, row_id: str = "0") -> StructuredRow:
    return StructuredRow(row_id=row_id, data=data, source_name="data.jsonl", source_hash="deadbeef")


def test_apply_column_mapping_renames_columns():
    rows = [_row({"question": "hi", "answer": "hello"})]
    remapped = apply_column_mapping(rows, {"question": "prompt", "answer": "completion"})
    assert remapped[0].data == {"prompt": "hi", "completion": "hello"}


def test_apply_column_mapping_raises_on_missing_column():
    rows = [_row({"question": "hi"})]
    with pytest.raises(ColumnMappingError):
        apply_column_mapping(rows, {"answer": "completion"})


def test_column_mapping_then_normalization_round_trip():
    rows = [_row({"question": "hi", "answer": "hello"})]
    remapped = apply_column_mapping(rows, {"question": "prompt", "answer": "completion"})
    [record] = preview_normalization(remapped, DetectedSchema.PROMPT_COMPLETION, document_id=uuid.uuid4())
    assert record.prompt == "hi"
    assert record.completion == "hello"


def test_preview_normalization_limits_to_requested_count():
    rows = [_row({"text": f"row {i}"}, row_id=str(i)) for i in range(50)]
    preview = preview_normalization(rows, DetectedSchema.TEXT, document_id=uuid.uuid4(), limit=20)
    assert len(preview) == 20
```

Run it and confirm it fails on the missing module:

```powershell
uv run pytest tests/normalization/test_preview.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.normalization.preview'`.

#### Step 6: Manual column mapping and preview — implement (GREEN)

Create `backend/tuneforge/normalization/preview.py`:

```python
from __future__ import annotations

import uuid

from tuneforge.ingestion.structured import StructuredRow
from tuneforge.normalization.detector import DetectedSchema
from tuneforge.normalization.mappers import normalize_rows


class ColumnMappingError(RuntimeError):
    pass


def apply_column_mapping(rows: list[StructuredRow], mapping: dict[str, str]) -> list[StructuredRow]:
    """`mapping` is {actual_column_name: canonical_field_name} — for when
    `detect_schema` came back inconclusive and a human says "column X is
    really the prompt" instead of a model guessing it.
    """
    remapped = []
    for row in rows:
        missing = [actual for actual in mapping if actual not in row.data]
        if missing:
            raise ColumnMappingError(f"row {row.row_id}: missing expected column(s) {missing}")
        new_data = dict(row.data)
        for actual, canonical in mapping.items():
            new_data[canonical] = new_data.pop(actual)
        remapped.append(
            StructuredRow(row_id=row.row_id, data=new_data, source_name=row.source_name, source_hash=row.source_hash)
        )
    return remapped


def preview_normalization(
    rows: list[StructuredRow],
    schema: DetectedSchema,
    *,
    document_id: uuid.UUID,
    limit: int = 20,
) -> list:
    return normalize_rows(rows[:limit], schema, document_id=document_id)
```

Run the tests again:

```powershell
uv run pytest tests/normalization/test_preview.py -q
```

Expected: all pass.

#### Step 7: Run the full backend suite and commit

```powershell
uv run pytest -q
```

Expected: every test from Parts 1–3 and this part's Tasks 7–8 passes.

```powershell
git add backend
git commit -m "feat: normalize existing training datasets"
```

---

## When you're done

Do not start Task 9. Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` (full pass/fail summary) from `backend/`. Note how long the suite takes now — Docling's real parsing tests make this part noticeably slower than earlier parts, and that's expected, not a problem to fix.
2. Output of `git log --oneline` — should show two new commits: `feat: add provenance-aware document ingestion` and `feat: normalize existing training datasets`.
3. Confirm `uv sync` completed and `backend/uv.lock` now includes `docling` and `transformers` (and their dependency trees), committed.
4. Anything you had to deviate from in this document, and why.
5. If you find a correctness issue in the code exactly as given here — not a style preference, an actual bug — stop and describe it rather than silently changing behavior.
