from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import httpx

from tuneforge.export.bundle import export_bundle
from tuneforge.export.splitting import split_train_eval
from tuneforge.generation.generator import generate_dpo_record
from tuneforge.generation.specs import GenerationSpec
from tuneforge.ingestion.chunking import build_tokenizer, chunk_into_source_records
from tuneforge.ingestion.documents import convert_document_cached
from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile, RunConsent
from tuneforge.records import DPORecord
from tuneforge.validation.pipeline import run_validation_pipeline


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "output" / "pdf" / "customer_service_test_fixture_40_pages.pdf"
OUTPUT_ROOT = ROOT / "backend" / "output" / "generated_datasets"
WORK_DIR = OUTPUT_ROOT / "dpo_customer_service_export_work"
ZIP_PATH = OUTPUT_ROOT / "dpo_customer_service_export.zip"
CACHE_DIR = ROOT / "backend" / "output" / "_docling_cache"
RAW_RECORDS = OUTPUT_ROOT / "dpo_customer_service_records.jsonl"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GENERATOR_MODEL = "gemini-2.5-flash"
JUDGE_MODEL = "gemini-2.5-flash-lite"


def load_model_profile() -> ModelProfile:
    source_zip = OUTPUT_ROOT / "cpt_customer_service_export.zip"
    with ZipFile(source_zip) as archive:
        return ModelProfile.model_validate(json.loads(archive.read("model-profile.json")))


def build_plan(target_rows: int) -> TrainingPlan:
    generator_id = uuid.UUID("f2b0d4c1-3bd0-4bfd-8e6e-89b6f2c2f3c1")
    judge_id = uuid.UUID("a1c2d3e4-5f60-4a70-8b90-1c2d3e4f5a60")
    hash_payload = {
        "objective": "dpo",
        "canonical_schema": "DPORecord",
        "target_rows": target_rows,
        "examples_per_chunk": 1,
        "generator_profile_id": str(generator_id),
        "judge_profile_id": str(judge_id),
        "generator_model": GENERATOR_MODEL,
        "judge_model": JUDGE_MODEL,
        "required_validators": ["structural", "deduplication", "source_grounding", "dpo_preference"],
    }
    plan_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True).encode()).hexdigest()
    return TrainingPlan(
        objective="dpo",
        canonical_schema="DPORecord",
        target_rows=target_rows,
        examples_per_chunk=1,
        generator_profile_id=generator_id,
        judge_profile_id=judge_id,
        required_validators=["structural", "deduplication", "source_grounding", "dpo_preference"],
        evidence=[],
        confidence=0.95,
        plan_hash=plan_hash,
    )


async def generate() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(f"source PDF not found: {SOURCE}")
    if ZIP_PATH.exists():
        raise FileExistsError(f"refusing to overwrite existing export: {ZIP_PATH}")

    model_profile = load_model_profile()
    tokenizer = build_tokenizer(model_profile.model_id, max_tokens=512)
    document, source_hash = convert_document_cached(SOURCE, cache_dir=CACHE_DIR)
    document_id = uuid.uuid4()
    sources = chunk_into_source_records(
        document,
        document_id=document_id,
        source_name=SOURCE.name,
        source_hash=source_hash,
        tokenizer=tokenizer,
    )
    if not sources:
        raise RuntimeError("PDF produced zero source chunks")

    plan = build_plan(len(sources))
    consent = RunConsent(run_id=uuid.uuid4(), granted_at=datetime.now(timezone.utc))
    generator_profile = ProviderProfile(
        name="gemini-dpo-generator",
        base_url=BASE_URL,
        model=GENERATOR_MODEL,
        endpoint_scope="remote",
        credential_reference="gemini",
    )
    judge_profile = ProviderProfile(
        name="gemini-dpo-judge",
        base_url=BASE_URL,
        model=JUDGE_MODEL,
        endpoint_scope="remote",
        credential_reference="gemini",
    )
    generator_client = httpx.AsyncClient(timeout=90)
    judge_client = httpx.AsyncClient(timeout=90)
    generator = OpenAICompatibleProvider(generator_profile, generator_client)
    judge = OpenAICompatibleProvider(judge_profile, judge_client)
    spec = GenerationSpec(desired_behavior="dpo", max_candidates=3, score_margin=0.0, max_retries=2)

    try:
        if RAW_RECORDS.exists():
            records = [DPORecord.model_validate_json(line) for line in RAW_RECORDS.read_text(encoding="utf-8").splitlines() if line]
            failures = []
            print(f"loaded cached DPO pairs: {len(records)}", flush=True)
        else:
            semaphore = asyncio.Semaphore(4)

            async def generate_one(index, source):
                async with semaphore:
                    record = await generate_dpo_record(generator, judge, source, spec, consent)
                    print(f"generated {index}/{len(sources)}", flush=True)
                    return index, source, record

            results = await asyncio.gather(*(generate_one(index, source) for index, source in enumerate(sources, start=1)))
            results.sort(key=lambda item: item[0])
            records = [record for _, _, record in results if record is not None]
            failures = [
                {"index": index, "page": source.page, "chunk_id": source.chunk_id}
                for index, source, record in results
                if record is None
            ]
            RAW_RECORDS.write_text("\n".join(record.model_dump_json() for record in records) + "\n", encoding="utf-8")

        if failures:
            raise RuntimeError(f"DPO generation failed for {len(failures)} chunks: {failures[:3]}")

        validation = await run_validation_pipeline(
            records,
            tokenizer=tokenizer.tokenizer,
            max_tokens=model_profile.context_length or 1024,
            judge=judge,
            consent=consent,
            dpo_judge_margin=0.0,
        )
        if not validation.accepted:
            raise RuntimeError(f"DPO validation rejected every row: {validation.rejection_counts}")

        split = split_train_eval(validation.accepted)
        if WORK_DIR.exists():
            shutil.rmtree(WORK_DIR)
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        export_bundle(
            train=split.train,
            eval_records=split.eval,
            output_dir=WORK_DIR,
            model_profile=model_profile,
            plan=plan,
            validation_report=validation,
        )
        shutil.make_archive(str(ZIP_PATH.with_suffix("")), "zip", root_dir=WORK_DIR)
        print(json.dumps({
            "source_pages": 40,
            "source_chunks": len(sources),
            "generated_rows": len(records),
            "accepted_rows": len(validation.accepted),
            "rejected_rows": len(records) - len(validation.accepted),
            "train_rows": len(split.train),
            "eval_rows": len(split.eval),
            "rejection_counts": validation.rejection_counts,
            "zip": str(ZIP_PATH),
        }, indent=2))
    finally:
        await generator.aclose()
        await judge.aclose()


if __name__ == "__main__":
    asyncio.run(generate())
