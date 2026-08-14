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
