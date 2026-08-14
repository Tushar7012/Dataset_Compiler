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
    created: bool = False


class ArtifactStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.trash_dir = base_dir / "_trash"

    def project_dir(self, project_id: uuid.UUID) -> Path:
        return self.base_dir / "projects" / str(project_id)

    def import_source_file(self, project_id: uuid.UUID, src_path: Path) -> ImportedFile:
        sources_dir = self.project_dir(project_id) / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)

        tmp_path = sources_dir / f".{uuid.uuid4().hex}.part"
        try:
            shutil.copy2(src_path, tmp_path)
            digest = self._sha256(tmp_path)
            dest_path = self._existing_source_path(sources_dir, digest)
            if dest_path is None:
                dest_path = sources_dir / f"{digest}{src_path.suffix}"
                tmp_path.replace(dest_path)
                tmp_path = None
                created = True
            else:
                created = False
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

        size_bytes = dest_path.stat().st_size
        relative_path = str(dest_path.relative_to(self.base_dir))
        return ImportedFile(relative_path, digest, size_bytes, created)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _existing_source_path(sources_dir: Path, digest: str) -> Path | None:
        for path in sources_dir.iterdir():
            if path.is_file() and (
                path.name == digest or path.name.startswith(f"{digest}.")
            ):
                return path
        return None

    def discard_import(self, imported: ImportedFile) -> None:
        if not imported.created:
            return
        self._relative_path(imported.relative_path).unlink(missing_ok=True)

    def resolve(self, relative_path: str) -> Path:
        candidate = self._relative_path(relative_path)
        if not candidate.exists():
            raise MissingArtifactError(f"artifact missing: {relative_path}")
        return candidate

    def _relative_path(self, relative_path: str) -> Path:
        candidate = (self.base_dir / relative_path).resolve()
        base = self.base_dir.resolve()
        if candidate != base and base not in candidate.parents:
            raise MissingArtifactError(f"artifact path outside store: {relative_path}")
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

    def restore_project(self, project_id: uuid.UUID, trashed_path: Path) -> None:
        target = self.project_dir(project_id)
        trash = self.trash_dir.resolve()
        source = trashed_path.resolve()
        if source != trash and trash not in source.parents:
            raise MissingArtifactError(f"project trash path outside store: {trashed_path}")
        if not source.exists():
            raise MissingArtifactError(f"project trash missing: {trashed_path}")
        if target.exists():
            raise FileExistsError(f"project storage already exists: {project_id}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
