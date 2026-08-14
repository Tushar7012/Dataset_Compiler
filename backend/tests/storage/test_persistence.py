from pathlib import Path

import pytest

from tuneforge.storage.artifacts import ArtifactStore, MissingArtifactError
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import Source
from tuneforge.storage.repositories import ProjectRepository, SourceRepository


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "data")


@pytest.fixture
def session(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    factory = create_session_factory(engine)
    with factory() as db_session:
        yield db_session


def test_wal_and_foreign_keys_are_enabled(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data2" / "tuneforge.db")
    with engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
    assert mode.lower() == "wal"
    assert fk == 1


def test_create_project_creates_storage_directory(session, artifact_store):
    repo = ProjectRepository(session, artifact_store)
    project = repo.create("policy-assistant")
    assert Path(project.storage_path).exists()
    assert repo.get(project.id).name == "policy-assistant"


def test_add_source_copies_file_and_records_hash(session, artifact_store, tmp_path):
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("hello world")

    source_repo = SourceRepository(session, artifact_store)
    source = source_repo.add_source(project.id, src)

    assert source.size_bytes == len("hello world")
    assert source_repo.get_source_path(source).read_text() == "hello world"


def test_duplicate_import_reuses_existing_source(session, artifact_store, tmp_path):
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("same content")

    source_repo = SourceRepository(session, artifact_store)
    first = source_repo.add_source(project.id, src)
    second = source_repo.add_source(project.id, src)

    assert first.id == second.id


def test_interrupted_write_leaves_no_partial_source(session, artifact_store, tmp_path, monkeypatch):
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("data")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("tuneforge.storage.artifacts.shutil.copy2", boom)

    source_repo = SourceRepository(session, artifact_store)
    with pytest.raises(OSError):
        source_repo.add_source(project.id, src)

    assert session.query(Source).count() == 0


def test_missing_artifact_raises_clear_error(session, artifact_store, tmp_path):
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("data")
    source_repo = SourceRepository(session, artifact_store)
    source = source_repo.add_source(project.id, src)

    artifact_store.resolve(source.relative_path).unlink()

    with pytest.raises(MissingArtifactError):
        source_repo.get_source_path(source)


def test_deleted_project_is_recoverable_from_trash(session, artifact_store):
    repo = ProjectRepository(session, artifact_store)
    project = repo.create("to-delete")
    project_id = project.id
    original_dir = Path(project.storage_path)

    repo.delete(project_id)

    assert repo.get(project_id) is None
    assert not original_dir.exists()
    trashed = list(artifact_store.trash_dir.iterdir())
    assert len(trashed) == 1
    assert trashed[0].name.startswith(str(project_id))
