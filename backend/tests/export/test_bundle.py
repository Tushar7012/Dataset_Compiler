import json
import uuid
from pathlib import Path

from datasets import Dataset

from tuneforge.export.bundle import _parquet_safe_row, export_bundle
from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.records import CPTRecord, RecordMetadata
from tuneforge.validation.pipeline import ValidationReport


def _record(text: str) -> CPTRecord:
    return CPTRecord(
        text=text, metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef")
    )


def _model_profile() -> ModelProfile:
    return ModelProfile(
        source="huggingface", model_id="sshleifer/tiny-gpt2", architecture="GPT2LMHeadModel", model_type="gpt2",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=1024,
        modalities=["text"], evidence=[], confidence=0.95,
    )


def _plan() -> TrainingPlan:
    return TrainingPlan(
        objective="cpt", canonical_schema="CPTRecord", target_rows=100, examples_per_chunk=1,
        generator_profile_id=None, judge_profile_id=None, required_validators=["structural"],
        evidence=[], confidence=0.9, plan_hash="hash1",
    )


def test_export_bundle_writes_parquet_jsonl_and_manifest_files(tmp_path: Path):
    train = [_record("train example one"), _record("train example two")]
    eval_records = [_record("eval example one")]
    report = ValidationReport(accepted=train + eval_records, rejection_counts={"structural": 2})

    output_dir = tmp_path / "bundle"
    export_bundle(
        train=train, eval_records=eval_records, output_dir=output_dir,
        model_profile=_model_profile(), plan=_plan(), validation_report=report,
    )

    assert (output_dir / "train.parquet").exists()
    assert (output_dir / "train.jsonl").exists()
    assert (output_dir / "eval.parquet").exists()
    assert (output_dir / "eval.jsonl").exists()
    assert (output_dir / "manifest.json").exists()
    assert (output_dir / "model-profile.json").exists()
    assert (output_dir / "training-plan.json").exists()
    assert (output_dir / "validation-report.json").exists()
    assert (output_dir / "provenance.jsonl").exists()


def test_exported_parquet_reloads_through_hugging_face_datasets(tmp_path: Path):
    train = [_record("alpha"), _record("beta")]
    report = ValidationReport(accepted=train, rejection_counts={})

    output_dir = tmp_path / "bundle"
    export_bundle(
        train=train, eval_records=[], output_dir=output_dir,
        model_profile=_model_profile(), plan=_plan(), validation_report=report,
    )

    reloaded = Dataset.from_parquet(str(output_dir / "train.parquet"))
    # Empty metadata.extra must be omitted for Parquet; compare sanitized form.
    assert reloaded.to_list() == [_parquet_safe_row(json.loads(r.model_dump_json())) for r in train]


def test_no_eval_files_written_when_eval_split_is_empty(tmp_path: Path):
    train = [_record("only train")]
    report = ValidationReport(accepted=train, rejection_counts={})

    output_dir = tmp_path / "bundle"
    export_bundle(
        train=train, eval_records=[], output_dir=output_dir,
        model_profile=_model_profile(), plan=_plan(), validation_report=report,
    )

    assert not (output_dir / "eval.parquet").exists()
    assert not (output_dir / "eval.jsonl").exists()
    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest["eval_row_count"] == 0
    assert manifest["leakage_warning"] is True


def test_manifest_records_row_counts_and_rejection_summary(tmp_path: Path):
    train = [_record("a"), _record("b")]
    eval_records = [_record("c")]
    report = ValidationReport(accepted=train + eval_records, rejection_counts={"structural": 4, "exact_duplicate": 1})

    output_dir = tmp_path / "bundle"
    export_bundle(
        train=train, eval_records=eval_records, output_dir=output_dir,
        model_profile=_model_profile(), plan=_plan(), validation_report=report,
    )

    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest["train_row_count"] == 2
    assert manifest["eval_row_count"] == 1
    assert manifest["rejection_counts"] == {"structural": 4, "exact_duplicate": 1}
    assert manifest["objective"] == "cpt"
    assert manifest["model_id"] == "sshleifer/tiny-gpt2"
