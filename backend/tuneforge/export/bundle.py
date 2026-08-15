from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datasets import Dataset

from tuneforge.export.splitting import split_train_eval
from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.records import (
    ChatMessage,
    CPTRecord,
    DPORecord,
    RecordMetadata,
    SFTConversationRecord,
    SFTPromptCompletionRecord,
)
from tuneforge.validation.pipeline import ValidationReport

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


def _write_split(records: list, output_dir: Path, name: str) -> None:
    if not records:
        return
    rows = [_parquet_safe_row(json.loads(r.model_dump_json())) for r in records]
    dataset = Dataset.from_list(rows)
    dataset.to_parquet(str(output_dir / f"{name}.parquet"))
    dataset.to_json(str(output_dir / f"{name}.jsonl"))
    # Verify by reloading — PLAN.md requires this, not just writing the files.
    reloaded = Dataset.from_parquet(str(output_dir / f"{name}.parquet"))
    if reloaded.to_list() != rows:
        raise RuntimeError(f"{name}.parquet did not reload to the same records it was written from")


def export_bundle(
    *,
    train: list,
    eval_records: list,
    output_dir: Path,
    model_profile: ModelProfile,
    plan: TrainingPlan,
    validation_report: ValidationReport,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_split(train, output_dir, "train")
    _write_split(eval_records, output_dir, "eval")

    (output_dir / "model-profile.json").write_text(model_profile.model_dump_json(indent=2))
    (output_dir / "training-plan.json").write_text(plan.model_dump_json(indent=2))
    (output_dir / "validation-report.json").write_text(
        json.dumps({"rejection_counts": validation_report.rejection_counts, "assurance_level": validation_report.assurance_level}, indent=2)
    )

    with (output_dir / "provenance.jsonl").open("w", encoding="utf-8") as provenance_file:
        for record in train + eval_records:
            provenance_file.write(json.dumps(json.loads(record.metadata.model_dump_json())))
            provenance_file.write("\n")

    manifest = {
        "objective": plan.objective,
        "canonical_schema": plan.canonical_schema,
        "model_id": model_profile.model_id,
        "plan_hash": plan.plan_hash,
        "train_row_count": len(train),
        "eval_row_count": len(eval_records),
        "leakage_warning": len(eval_records) == 0 and len(train) > 0,
        "rejection_counts": validation_report.rejection_counts,
        "assurance_level": validation_report.assurance_level,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return output_dir
