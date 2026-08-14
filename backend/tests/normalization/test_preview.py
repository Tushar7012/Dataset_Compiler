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
