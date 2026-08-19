import uuid
from pathlib import Path

import pytest

from tuneforge.jobs.checkpoints import get_latest_checkpoint, record_checkpoint
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ProviderProfileRecord, RunRecord, TrainingPlanRecord
from tuneforge.storage.repositories import ProjectRepository


@pytest.fixture
def session(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    factory = create_session_factory(engine)
    with factory() as db_session:
        yield db_session


@pytest.fixture
def run(session, tmp_path: Path):
    artifact_store = ArtifactStore(tmp_path / "data")
    project = ProjectRepository(session, artifact_store).create("proj")

    plan = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project.id, objective="cpt", plan_json={}, plan_hash="hash1"
    )
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project.id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model",
    )
    session.add_all([plan, provider])
    session.commit()

    run_record = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id
    )
    session.add(run_record)
    session.commit()
    return run_record


def test_record_checkpoint_updates_run_progress(session, run):
    record_checkpoint(session, run.id, chunks_processed=5, completed_rows=4)

    session.refresh(run)
    assert run.completed_rows == 4


def test_get_latest_checkpoint_returns_the_highest_sequence(session, run):
    record_checkpoint(session, run.id, chunks_processed=5, completed_rows=4)
    record_checkpoint(session, run.id, chunks_processed=12, completed_rows=10)

    latest = get_latest_checkpoint(session, run.id)

    assert latest.sequence == 12
    assert latest.completed_rows == 10


def test_get_latest_checkpoint_returns_none_when_no_checkpoints_exist(session, run):
    assert get_latest_checkpoint(session, run.id) is None
