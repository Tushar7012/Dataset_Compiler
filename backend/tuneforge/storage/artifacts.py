from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class MissingArtifactError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportedFile:
    relative_path: str
    sha256: str
    size_bytes: int


class ArtifactStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.trash_dir = base_dir / "_trash"

    def project_dir(self, project_id: uuid.UUID) -> Path:
        return self.base_dir / "projects" / str(project_id)

    def import_source_file(self, project_id: uuid.UUID, src_path: Path) -> ImportedFile:
        sources_dir = self.project_dir(project_id) / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256(src_path.read_bytes()).hexdigest()
        dest_path = sources_dir / f"{digest}{src_path.suffix}"

        if not dest_path.exists():
            tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
            try:
                shutil.copy2(src_path, tmp_path)
                tmp_path.replace(dest_path)
            finally:
                tmp_path.unlink(missing_ok=True)

        size_bytes = dest_path.stat().st_size
        relative_path = str(dest_path.relative_to(self.base_dir))
        return ImportedFile(relative_path=relative_path, sha256=digest, size_bytes=size_bytes)

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.base_dir / relative_path).resolve()
        base = self.base_dir.resolve()
        if candidate != base and base not in candidate.parents:
            raise MissingArtifactError(f"artifact path outside store: {relative_path}")
        if not candidate.exists():
            raise MissingArtifactError(f"artifact missing: {relative_path}")
        return candidate

    def delete_project(self, project_id: uuid.UUID) -> Path:
        project_dir = self.project_dir(project_id)
        if not project_dir.exists():
            raise MissingArtifactError(f"project storage missing: {project_id}")
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        trashed_path = self.trash_dir / f"{project_id}-{stamp}"
        shutil.move(str(project_dir), str(trashed_path))
        return trashed_path
