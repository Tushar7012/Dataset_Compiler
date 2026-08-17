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


def test_disables_torch_compile_for_docling_pdf_layout_model():
    # Docling's PDF layout model defaults to torch.compile()-ing itself,
    # which needs an MSVC C++ compiler (cl.exe) — absent on a stock Windows
    # install with no Visual Studio Build Tools. Found via a real 40-page
    # PDF during a manual E2E pass: conversion crashed with
    # docling.exceptions.ConversionError wrapping
    # torch._inductor.exc.InductorError: InvalidCxxCompiler. Eager
    # (uncompiled) inference is correct either way, just not JIT-optimized.
    from docling.datamodel.settings import settings as docling_settings

    assert docling_settings.inference.compile_torch_models is False


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

    monkeypatch.setattr(documents_module, "MAX_UPLOAD_BYTES", 10)
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
