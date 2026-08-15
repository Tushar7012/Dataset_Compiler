import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.exports import router
from tuneforge.jobs.runner import run_output_path
from tuneforge.records import CPTRecord, RecordMetadata
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ModelProfileRecord, ProviderProfileRecord, RunRecord, TrainingPlanRecord
from tuneforge.storage.repositories import ProjectRepository


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(tmp_path / "data")
    app.include_router(router, prefix="/api")
    test_client = TestClient(app)
    test_client.session_factory = app.state.session_factory
    test_client.artifact_store = app.state.artifact_store
    return test_client


def _completed_run(client):
    session = client.session_factory()
    project = ProjectRepository(session, client.artifact_store).create("proj")

    from tuneforge.models.analyzer import ModelProfile

    profile = ModelProfile(
        source="huggingface", model_id="sshleifer/tiny-gpt2", architecture="GPT2LMHeadModel", model_type="gpt2",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=1024,
        modalities=["text"], evidence=[], confidence=0.95,
    )
    model_profile_record = ModelProfileRecord(
        id=uuid.uuid4(), project_id=project.id, model_id=profile.model_id, source=profile.source,
        profile_json=json.loads(profile.model_dump_json()), confidence=profile.confidence,
    )
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project.id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model", endpoint_scope="local",
    )
    plan_record = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project.id, objective="cpt",
        plan_json={
            "objective": "cpt", "canonical_schema": "CPTRecord", "target_rows": 10, "examples_per_chunk": 1,
            "generator_profile_id": None, "judge_profile_id": None, "required_validators": [],
            "evidence": [], "confidence": 0.9, "plan_hash": "hash1",
        },
        plan_hash="hash1",
    )
    # Commit parents before the run row — SQLite FK checks each INSERT immediately,
    # and a single add_all can emit runs before provider_profiles.
    session.add_all([model_profile_record, provider, plan_record])
    session.commit()
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan_record.id,
        generator_profile_id=provider.id, status="completed", completed_rows=2, total_rows=2,
    )
    session.add(run)
    session.commit()

    output_path = run_output_path(client.artifact_store.base_dir, project.id, run.id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for text in ("first accepted row", "second accepted row"):
            record = CPTRecord(
                text=text, metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="h")
            )
            f.write(record.model_dump_json())
            f.write("\n")

    return run


def test_export_then_download_returns_a_zip(client):
    run = _completed_run(client)

    export_response = client.post(f"/api/runs/{run.id}/export")
    assert export_response.status_code == 201

    download_response = client.get(f"/api/exports/{run.id}/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"


def test_download_before_export_returns_404(client):
    run = _completed_run(client)
    response = client.get(f"/api/exports/{run.id}/download")
    assert response.status_code == 404


def test_export_before_run_completes_is_rejected(client):
    session = client.session_factory()
    project = ProjectRepository(session, client.artifact_store).create("proj")
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project.id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model", endpoint_scope="local",
    )
    plan_record = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project.id, objective="cpt", plan_json={"canonical_schema": "CPTRecord"}, plan_hash="h"
    )
    session.add_all([provider, plan_record])
    session.commit()
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan_record.id, generator_profile_id=provider.id, status="running"
    )
    session.add(run)
    session.commit()

    response = client.post(f"/api/runs/{run.id}/export")
    assert response.status_code == 409
