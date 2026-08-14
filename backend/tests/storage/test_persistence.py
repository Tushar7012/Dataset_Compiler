import hashlib
import shutil
import uuid
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


def test_readding_source_recovers_missing_artifact(session, artifact_store, tmp_path):
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("same content")

    source_repo = SourceRepository(session, artifact_store)
    original = source_repo.add_source(project.id, src)
    artifact_store.resolve(original.relative_path).unlink()

    recovered = source_repo.add_source(project.id, src)

    assert recovered.id == original.id
    assert source_repo.get_source_path(recovered).read_text() == "same content"
    assert session.query(Source).filter(Source.id == original.id).one().relative_path == recovered.relative_path


def test_recovery_keeps_artifact_when_commit_would_fail(
    session, artifact_store, tmp_path, monkeypatch
):
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("same content")
    source_repo = SourceRepository(session, artifact_store)
    original = source_repo.add_source(project.id, src)
    artifact_store.resolve(original.relative_path).unlink()

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", fail_commit)

    recovered = source_repo.add_source(project.id, src)

    assert recovered.id == original.id
    assert source_repo.get_source_path(recovered).read_text() == "same content"


def test_duplicate_content_with_different_extension_reuses_existing_artifact(
    session, artifact_store, tmp_path
):
    project = ProjectRepository(session, artifact_store).create("proj")
    text_source = tmp_path / "policy.txt"
    csv_source = tmp_path / "policy.csv"
    text_source.write_text("same content")
    csv_source.write_text("same content")

    source_repo = SourceRepository(session, artifact_store)
    first = source_repo.add_source(project.id, text_source)
    second = source_repo.add_source(project.id, csv_source)

    assert second.id == first.id
    assert list((artifact_store.project_dir(project.id) / "sources").iterdir()) == [
        artifact_store.resolve(first.relative_path)
    ]


def test_add_source_rejects_inactive_project_before_creating_artifact(
    session, artifact_store, tmp_path
):
    project_repo = ProjectRepository(session, artifact_store)
    project = project_repo.create("deleted")
    project_repo.delete(project.id)
    src = tmp_path / "policy.txt"
    src.write_text("data")

    with pytest.raises(ValueError, match="unknown project"):
        SourceRepository(session, artifact_store).add_source(project.id, src)

    assert not artifact_store.project_dir(project.id).exists()
    assert session.query(Source).count() == 0


def test_add_source_rolls_back_and_removes_new_artifact_when_commit_fails(
    session, artifact_store, tmp_path, monkeypatch
):
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("data")

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        SourceRepository(session, artifact_store).add_source(project.id, src)

    assert list((artifact_store.project_dir(project.id) / "sources").iterdir()) == []
    assert session.query(Source).count() == 0


def test_add_source_commit_failure_keeps_preexisting_artifact(
    session, artifact_store, tmp_path, monkeypatch
):
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("data")
    imported = artifact_store.import_source_file(project.id, src)

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        SourceRepository(session, artifact_store).add_source(project.id, src)

    assert artifact_store.resolve(imported.relative_path).read_text() == "data"
    assert session.query(Source).count() == 0


def test_import_hash_matches_bytes_copied_when_source_changes_during_copy(
    session, artifact_store, tmp_path, monkeypatch
):
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("before")

    original_copy2 = shutil.copy2

    def mutate_then_copy(source, destination, *args, **kwargs):
        Path(source).write_text("after")
        return original_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr("tuneforge.storage.artifacts.shutil.copy2", mutate_then_copy)

    source = SourceRepository(session, artifact_store).add_source(project.id, src)

    assert source.source_hash == hashlib.sha256(b"after").hexdigest()
    assert artifact_store.resolve(source.relative_path).read_text() == "after"


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


def test_create_rolls_back_and_removes_new_storage_when_commit_fails(
    session, artifact_store, monkeypatch
):
    created_paths: list[Path] = []
    original_project_dir = artifact_store.project_dir

    def record_project_dir(project_id):
        path = original_project_dir(project_id)
        created_paths.append(path)
        return path

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(artifact_store, "project_dir", record_project_dir)
    monkeypatch.setattr(session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        ProjectRepository(session, artifact_store).create("proj")

    assert created_paths
    assert not created_paths[0].exists()
    assert ProjectRepository(session, artifact_store).list_active() == []


def test_delete_does_not_move_storage_when_commit_fails(
    session, artifact_store, monkeypatch
):
    repo = ProjectRepository(session, artifact_store)
    project = repo.create("proj")
    project_path = Path(project.storage_path)

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        repo.delete(project.id)

    # The soft-delete commit is attempted before the filesystem move, so a
    # failed commit means the move never happened at all — nothing to
    # restore, and the project is still active.
    assert project_path.exists()
    assert not artifact_store.trash_dir.exists()
    assert repo.get(project.id) is not None


def test_add_source_recovers_from_concurrent_unique_violation(
    session, artifact_store, tmp_path, monkeypatch
):
    # Real thread-timing races over SQLite are too fast and GIL-serialized
    # to reproduce reliably in-process, so this forces the exact TOCTOU
    # window instead: our own pre-check SELECT is made to miss a row that
    # a "concurrent" writer already committed, so add_source is driven
    # into the INSERT branch against an already-taken (project_id,
    # source_hash) pair — exactly what the unique constraint exists for.
    project = ProjectRepository(session, artifact_store).create("proj")
    src = tmp_path / "policy.txt"
    src.write_text("same content")
    imported = artifact_store.import_source_file(project.id, src)

    winner = Source(
        id=uuid.uuid4(),
        project_id=project.id,
        filename="policy.txt",
        source_hash=imported.sha256,
        relative_path=imported.relative_path,
        size_bytes=imported.size_bytes,
    )
    session.add(winner)
    session.commit()

    original_query = session.query

    def query_that_missed_the_race(model, *args, **kwargs):
        query = original_query(model, *args, **kwargs)
        if model is Source:
            monkeypatch.setattr(session, "query", original_query)
            return query.filter(Source.id == uuid.uuid4())  # force "not found"
        return query

    monkeypatch.setattr(session, "query", query_that_missed_the_race)

    result = SourceRepository(session, artifact_store).add_source(project.id, src)

    assert result.id == winner.id
    assert (
        session.query(Source)
        .filter_by(project_id=project.id, source_hash=imported.sha256)
        .count()
        == 1
    )
