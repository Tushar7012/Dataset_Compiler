import json
import uuid
from pathlib import Path

from datasets import Dataset

from tuneforge.export.bundle import _parquet_safe_row, export_bundle
from tuneforge.records import CPTRecord, RecordMetadata


def _record(text: str) -> CPTRecord:
    return CPTRecord(
        text=text, metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef")
    )


def test_export_bundle_writes_only_train_parquet_and_jsonl(tmp_path: Path):
    records = [_record("example one"), _record("example two")]

    output_dir = tmp_path / "bundle"
    export_bundle(records=records, output_dir=output_dir)

    assert (output_dir / "train.parquet").exists()
    assert (output_dir / "train.jsonl").exists()
    assert sorted(p.name for p in output_dir.iterdir()) == ["train.jsonl", "train.parquet"]


def test_exported_parquet_reloads_through_hugging_face_datasets(tmp_path: Path):
    records = [_record("alpha"), _record("beta")]

    output_dir = tmp_path / "bundle"
    export_bundle(records=records, output_dir=output_dir)

    reloaded = Dataset.from_parquet(str(output_dir / "train.parquet"))
    # Empty metadata.extra must be omitted for Parquet; compare sanitized form.
    assert reloaded.to_list() == [_parquet_safe_row(json.loads(r.model_dump_json())) for r in records]


def test_no_files_written_when_there_are_no_records(tmp_path: Path):
    output_dir = tmp_path / "bundle"
    export_bundle(records=[], output_dir=output_dir)

    assert list(output_dir.iterdir()) == []
