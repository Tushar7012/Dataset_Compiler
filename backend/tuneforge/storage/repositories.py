from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.models import Project, Source


class ProjectRepository:
    def __init__(self, session: Session, artifact_store: ArtifactStore):
        self.session = session
        self.artifact_store = artifact_store

    def create(self, name: str) -> Project:
        project = Project(id=uuid.uuid4(), name=name, storage_path="")
        project.storage_path = str(self.artifact_store.project_dir(project.id))
        self.artifact_store.project_dir(project.id).mkdir(parents=True, exist_ok=True)
        self.session.add(project)
        self.session.commit()
        return project

    def get(self, project_id: uuid.UUID) -> Project | None:
        return (
            self.session.query(Project)
            .filter(Project.id == project_id, Project.deleted_at.is_(None))
            .one_or_none()
        )

    def list_active(self) -> list[Project]:
        return (
            self.session.query(Project)
            .filter(Project.deleted_at.is_(None))
            .order_by(Project.created_at)
            .all()
        )

    def delete(self, project_id: uuid.UUID) -> None:
        project = self.get(project_id)
        if project is None:
            raise ValueError(f"unknown project: {project_id}")
        self.artifact_store.delete_project(project_id)
        project.deleted_at = datetime.now(timezone.utc)
        self.session.commit()


class SourceRepository:
    def __init__(self, session: Session, artifact_store: ArtifactStore):
        self.session = session
        self.artifact_store = artifact_store

    def add_source(self, project_id: uuid.UUID, src_path: Path) -> Source:
        existing = self.session.query(Source).filter(Source.project_id == project_id).all()
        imported = self.artifact_store.import_source_file(project_id, src_path)
        for source in existing:
            if source.source_hash == imported.sha256:
                return source

        source = Source(
            id=uuid.uuid4(),
            project_id=project_id,
            filename=src_path.name,
            source_hash=imported.sha256,
            relative_path=imported.relative_path,
            size_bytes=imported.size_bytes,
        )
        self.session.add(source)
        self.session.commit()
        return source

    def get_source_path(self, source: Source) -> Path:
        return self.artifact_store.resolve(source.relative_path)
