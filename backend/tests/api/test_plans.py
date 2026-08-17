import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.plans import router
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ModelProfileRecord, TrainingPlanRecord
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


def _stored_model_profile(client, project_id):
    from tuneforge.models.analyzer import ModelProfile

    profile = ModelProfile(
        source="huggingface", model_id="meta-llama/Llama-3-8B", architecture="LlamaForCausalLM", model_type="llama",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=4096,
        modalities=["text"], evidence=[], confidence=0.9,
    )
    session = client.session_factory()
    record = ModelProfileRecord(
        id=uuid.uuid4(), project_id=project_id, model_id=profile.model_id, source=profile.source,
        profile_json=__import__("json").loads(profile.model_dump_json()), confidence=profile.confidence,
    )
    session.add(record)
    session.commit()
    return record


def _project_id(client) -> uuid.UUID:
    session = client.session_factory()
    return ProjectRepository(session, client.artifact_store).create("proj").id


def test_recommend_persists_a_training_plan(client):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)

    response = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id),
            "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation",
            "desired_behavior": "understand HR policy",
            "language": "en",
            "target_rows": 500,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["objective"] == "cpt"

    session = client.session_factory()
    stored = session.query(TrainingPlanRecord).one()
    assert stored.objective == "cpt"


def test_recommend_returns_409_when_chat_template_required_but_missing(client):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)  # chat_template_found=False

    response = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id),
            "model_profile_id": str(model_profile_record.id),
            "goal": "multi_turn_conversation",
            "desired_behavior": "chat",
            "language": "en",
            "target_rows": 500,
        },
    )

    assert response.status_code == 409


def test_estimated_rows_counts_chunks_without_any_provider_configured(client, tmp_path):
    from tuneforge.models.analyzer import ModelProfile
    from tuneforge.storage.repositories import SourceRepository

    project_id = _project_id(client)
    session = client.session_factory()
    # gpt2, not the gated Llama fixture _stored_model_profile uses elsewhere in
    # this file — this test's endpoint really calls build_tokenizer(model_id),
    # so it needs a real, public, downloadable tokenizer.
    profile = ModelProfile(
        source="huggingface", model_id="gpt2", architecture="GPT2LMHeadModel", model_type="gpt2",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=1024,
        modalities=["text"], evidence=[], confidence=0.9,
    )
    model_profile_record = ModelProfileRecord(
        id=uuid.uuid4(), project_id=project_id, model_id=profile.model_id, source=profile.source,
        profile_json=json.loads(profile.model_dump_json()), confidence=profile.confidence,
    )
    session.add(model_profile_record)
    session.commit()

    doc_path = tmp_path / "a.md"
    doc_path.write_text("# Doc\n\nSome content here.\n")
    SourceRepository(session, client.artifact_store).add_source(project_id, doc_path)

    response = client.get(
        f"/api/plans/estimated-rows",
        params={"project_id": str(project_id), "model_profile_id": str(model_profile_record.id)},
    )

    assert response.status_code == 200
    assert response.json() == {"total_rows": 1, "truncated": False, "capped_at": 100_000}


def test_estimated_rows_for_unknown_model_profile_returns_404(client):
    project_id = _project_id(client)
    response = client.get(
        "/api/plans/estimated-rows",
        params={"project_id": str(project_id), "model_profile_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


def test_approve_sets_approved_at(client):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    recommend_response = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )
    plan_id = recommend_response.json()["id"]

    response = client.post(f"/api/plans/{plan_id}/approve")

    assert response.status_code == 200
    session = client.session_factory()
    stored = session.query(TrainingPlanRecord).one()
    assert stored.approved_at is not None
