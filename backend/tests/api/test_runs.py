import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.runs import router
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ProviderProfileRecord, RunRecord, TrainingPlanRecord
from tuneforge.storage.repositories import ProjectRepository


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    factory = create_session_factory(engine)
    session = factory()
    artifact_store = ArtifactStore(tmp_path / "data")

    app = FastAPI()
    app.state.session = session
    app.state.artifact_store = artifact_store
    app.state.db_path = tmp_path / "data" / "tuneforge.db"
    app.include_router(router, prefix="/api")

    test_client = TestClient(app)
    test_client.session = session
    test_client.artifact_store = artifact_store
    return test_client


def _make_plan_and_provider(client, project_id):
    plan = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project_id, objective="cpt", plan_json={"objective": "cpt"}, plan_hash="hash1"
    )
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project_id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model", endpoint_scope="local",
    )
    client.session.add_all([plan, provider])
    client.session.commit()
    return plan, provider


def test_get_run_returns_current_status(client, monkeypatch):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
        completed_rows=7,
    )
    client.session.add(run)
    client.session.commit()

    response = client.get(f"/api/runs/{run.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["completed_rows"] == 7


def test_get_unknown_run_returns_404(client):
    response = client.get(f"/api/runs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_cancel_sets_status_to_cancel_requested(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
    )
    client.session.add(run)
    client.session.commit()

    response = client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 200
    client.session.refresh(run)
    assert run.status == "cancel_requested"


def test_cancel_on_completed_run_is_a_no_op_error(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="completed",
    )
    client.session.add(run)
    client.session.commit()

    response = client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 409


def test_approve_full_rejects_an_unapproved_plan(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        is_preview=True, status="completed",
    )
    client.session.add(preview_run)
    client.session.commit()

    response = client.post(f"/api/runs/{preview_run.id}/approve-full")

    assert response.status_code == 409
    assert "plan_hash" in response.json()["detail"].lower()


def test_approve_plan_then_approve_full_succeeds(client, monkeypatch):
    # start_run spawns a real OS process (Step 5) — irrelevant to what this
    # test checks (the approval bookkeeping), and run_generation_worker
    # can't actually run yet given the sources-loading gap noted in Step 5.
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        is_preview=True, status="completed",
    )
    client.session.add(preview_run)
    client.session.commit()

    approve_response = client.post(f"/api/plans/{plan.id}/approve")
    assert approve_response.status_code == 200

    response = client.post(f"/api/runs/{preview_run.id}/approve-full")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_resume_moves_a_cancelled_run_back_to_pending(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        status="cancelled", completed_rows=42,
    )
    client.session.add(run)
    client.session.commit()

    response = client.post(f"/api/runs/{run.id}/resume")

    assert response.status_code == 200
    client.session.refresh(run)
    assert run.status == "pending"
    assert run.completed_rows == 42  # resume doesn't reset progress


def test_resume_on_a_running_run_is_rejected(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
    )
    client.session.add(run)
    client.session.commit()

    response = client.post(f"/api/runs/{run.id}/resume")

    assert response.status_code == 409


def test_events_stream_is_server_sent_events_format(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        status="completed", completed_rows=20, total_rows=20,
    )
    client.session.add(run)
    client.session.commit()

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
