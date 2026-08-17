from __future__ import annotations

import hashlib
from pathlib import Path

import docling
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.settings import settings as docling_settings
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.exceptions import ConversionError, SecurityError
from docling_core.types.doc.document import DoclingDocument

# Docling's PDF layout model defaults to torch.compile()-ing itself for
# speed — that needs an MSVC C++ compiler (cl.exe), which a stock Windows
# install has no reason to have (this app's own tooling is uv/Python only).
# Without it, conversion crashes with InvalidCxxCompiler instead of just
# falling back to eager execution. Eager inference is correct either way,
# just not JIT-optimized — worth it to make PDFs work out of the box.
docling_settings.inference.compile_torch_models = False

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".md", ".txt"}
# Shared with tuneforge.api.projects.upload_source, which enforces this same
# ceiling at upload time (cheaper, via UploadFile.size) — this check here is a
# second line of defense for anything that reaches disk another way.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


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
    if size > MAX_UPLOAD_BYTES:
        raise OversizedDocumentError(f"{path.name}: {size} bytes exceeds the {MAX_UPLOAD_BYTES} byte limit")


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
