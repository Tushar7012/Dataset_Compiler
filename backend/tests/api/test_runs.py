import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api import plans as plans_api
from tuneforge.api.runs import router
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ProviderProfileRecord, RunRecord, TrainingPlanRecord
from tuneforge.storage.repositories import ProjectRepository


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(tmp_path / "data")
    app.state.db_path = tmp_path / "data" / "tuneforge.db"
    app.include_router(router, prefix="/api")
    # approve-full still needs POST /api/plans/{id}/approve (moved to plans.py in this part)
    app.include_router(plans_api.router, prefix="/api")
    test_client = TestClient(app)
    test_client.session_factory = app.state.session_factory
    test_client.artifact_store = app.state.artifact_store
    return test_client


def _session(client):
    return client.session_factory()


def _make_plan_and_provider(client, project_id):
    session = _session(client)
    plan = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project_id, objective="cpt", plan_json={"objective": "cpt"}, plan_hash="hash1"
    )
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project_id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model", endpoint_scope="local",
    )
    session.add_all([plan, provider])
    session.commit()
    return plan, provider


def test_get_run_returns_current_status(client, monkeypatch):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
        completed_rows=7,
    )
    session = _session(client)
    session.add(run)
    session.commit()

    response = client.get(f"/api/runs/{run.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["completed_rows"] == 7


def test_get_unknown_run_returns_404(client):
    response = client.get(f"/api/runs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_cancel_sets_status_to_cancel_requested(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
    )
    session = _session(client)
    session.add(run)
    session.commit()

    response = client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 200
    session = _session(client)
    stored = session.get(RunRecord, run.id)
    assert stored.status == "cancel_requested"


def test_cancel_on_completed_run_is_a_no_op_error(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="completed",
    )
    session = _session(client)
    session.add(run)
    session.commit()

    response = client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 409


def test_approve_full_rejects_an_unapproved_plan(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        is_preview=True, status="completed",
    )
    session = _session(client)
    session.add(preview_run)
    session.commit()

    response = client.post(f"/api/runs/{preview_run.id}/approve-full")

    assert response.status_code == 409
    assert "plan_hash" in response.json()["detail"].lower()


def test_approve_plan_then_approve_full_succeeds(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        is_preview=True, status="completed",
    )
    session = _session(client)
    session.add(preview_run)
    session.commit()

    approve_response = client.post(f"/api/plans/{plan.id}/approve")
    assert approve_response.status_code == 200

    response = client.post(f"/api/runs/{preview_run.id}/approve-full")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_resume_moves_a_cancelled_run_back_to_pending(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        status="cancelled", completed_rows=42,
    )
    session = _session(client)
    session.add(run)
    session.commit()

    response = client.post(f"/api/runs/{run.id}/resume")

    assert response.status_code == 200
    session = _session(client)
    stored = session.get(RunRecord, run.id)
    assert stored.status == "pending"
    assert stored.completed_rows == 42  # resume doesn't reset progress


def test_resume_on_a_running_run_is_rejected(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
    )
    session = _session(client)
    session.add(run)
    session.commit()

    response = client.post(f"/api/runs/{run.id}/resume")

    assert response.status_code == 409


def test_events_stream_is_server_sent_events_format(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        status="completed", completed_rows=20, total_rows=20,
    )
    session = _session(client)
    session.add(run)
    session.commit()

    response = client.get(f"/api/runs/{run.id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.split("\n\n")
        if line.strip()
    ]
    assert events[-1]["stage"] == "completed"
    assert events[-1]["completed_rows"] == 20


def test_preview_creates_a_run_with_is_preview_true(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)

    response = client.post(
        "/api/runs/preview",
        json={"plan_id": str(plan.id), "generator_profile_id": str(provider.id)},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["is_preview"] is True

    session = _session(client)
    stored = session.get(RunRecord, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.is_preview is True


def _make_remote_provider(client, project_id):
    session = _session(client)
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project_id, name="openai", base_url="https://api.openai.com/v1",
        model="gpt-4", endpoint_scope="remote",
    )
    session.add(provider)
    session.commit()
    return provider


def test_preview_rejects_remote_generator_without_consent(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, _local_provider = _make_plan_and_provider(client, project.id)
    remote_provider = _make_remote_provider(client, project.id)

    response = client.post(
        "/api/runs/preview",
        json={"plan_id": str(plan.id), "generator_profile_id": str(remote_provider.id)},
    )

    assert response.status_code == 422
    assert "consent" in response.json()["detail"].lower()


def test_preview_accepts_remote_generator_with_consent_and_stores_the_timestamp(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, _local_provider = _make_plan_and_provider(client, project.id)
    remote_provider = _make_remote_provider(client, project.id)

    response = client.post(
        "/api/runs/preview",
        json={"plan_id": str(plan.id), "generator_profile_id": str(remote_provider.id), "remote_consent": True},
    )

    assert response.status_code == 201
    session = _session(client)
    stored = session.get(RunRecord, uuid.UUID(response.json()["id"]))
    assert stored.remote_consent_granted_at is not None


def test_preview_rejects_remote_judge_without_consent_even_when_generator_is_local(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, local_provider = _make_plan_and_provider(client, project.id)
    remote_judge = _make_remote_provider(client, project.id)

    response = client.post(
        "/api/runs/preview",
        json={
            "plan_id": str(plan.id),
            "generator_profile_id": str(local_provider.id),
            "judge_profile_id": str(remote_judge.id),
        },
    )

    assert response.status_code == 422
    assert "consent" in response.json()["detail"].lower()


def test_approve_full_rejects_remote_generator_without_consent(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, _local_provider = _make_plan_and_provider(client, project.id)
    remote_provider = _make_remote_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=remote_provider.id,
        is_preview=True, status="completed", remote_consent_granted_at=datetime.now(timezone.utc),
    )
    session = _session(client)
    session.add(preview_run)
    session.commit()
    client.post(f"/api/plans/{plan.id}/approve")

    response = client.post(f"/api/runs/{preview_run.id}/approve-full")

    assert response.status_code == 422
    assert "consent" in response.json()["detail"].lower()


def test_approve_full_accepts_remote_generator_with_consent_and_stores_the_timestamp(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, _local_provider = _make_plan_and_provider(client, project.id)
    remote_provider = _make_remote_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=remote_provider.id,
        is_preview=True, status="completed", remote_consent_granted_at=datetime.now(timezone.utc),
    )
    session = _session(client)
    session.add(preview_run)
    session.commit()
    client.post(f"/api/plans/{plan.id}/approve")

    response = client.post(f"/api/runs/{preview_run.id}/approve-full", json={"remote_consent": True})

    assert response.status_code == 200
    session = _session(client)
    full_run = session.get(RunRecord, uuid.UUID(response.json()["id"]))
    assert full_run.remote_consent_granted_at is not None
