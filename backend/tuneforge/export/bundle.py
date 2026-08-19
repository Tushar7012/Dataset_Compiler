from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datasets import Dataset

from tuneforge.records import CPTRecord, DPORecord, SFTConversationRecord, SFTPromptCompletionRecord

_RECORD_TYPES = {
    "CPTRecord": CPTRecord,
    "SFTPromptCompletionRecord": SFTPromptCompletionRecord,
    "SFTConversationRecord": SFTConversationRecord,
    "DPORecord": DPORecord,
}


def load_records_from_jsonl(path: Path, canonical_schema: str) -> list:
    record_cls = _RECORD_TYPES[canonical_schema]
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(record_cls.model_validate_json(line))
    return records


def _parquet_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    """PyArrow cannot write empty struct fields to Parquet (e.g. metadata.extra={}).

    Omit empty dict values so Dataset.to_parquet succeeds; reload then matches
    these sanitized rows.
    """
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, dict):
            if value == {}:
                continue
            result[key] = _parquet_safe_row(value)
        else:
            result[key] = value
    return result


def export_bundle(*, records: list, output_dir: Path) -> Path:
    """Writes train.jsonl and train.parquet only — see CLAUDE.md's "Export
    bundle is train.jsonl/train.parquet only" deviation entry for why this
    doesn't also split off an eval set or write manifest/provenance/etc.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if not records:
        return output_dir

    rows = [_parquet_safe_row(json.loads(r.model_dump_json())) for r in records]
    dataset = Dataset.from_list(rows)
    dataset.to_parquet(str(output_dir / "train.parquet"))
    dataset.to_json(str(output_dir / "train.jsonl"))
    # Verify by reloading — PLAN.md requires this, not just writing the files.
    reloaded = Dataset.from_parquet(str(output_dir / "train.parquet"))
    if reloaded.to_list() != rows:
        raise RuntimeError("train.parquet did not reload to the same records it was written from")

    return output_dir
