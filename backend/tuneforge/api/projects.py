from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_artifact_store, get_session
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.repositories import ProjectRepository, SourceRepository

router = APIRouter()


@router.post("/projects", status_code=201)
async def create_project(
    payload: dict,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    name = payload.get("name")
    if not name:
        raise HTTPException(status_code=422, detail="'name' is required")
    project = ProjectRepository(session, artifact_store).create(name)
    return {"id": str(project.id), "name": project.name, "created_at": project.created_at.isoformat()}


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    try:
        ProjectRepository(session, artifact_store).delete(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/sources", status_code=201)
async def upload_source(
    project_id: uuid.UUID,
    file: UploadFile,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    project_repo = ProjectRepository(session, artifact_store)
    project = project_repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")

    # add_source needs a real file on disk to hash and copy — and needs the
    # *original* filename preserved, so this can't just be a random temp
    # name. A per-upload subdirectory avoids collisions between concurrent
    # uploads of files that share a name.
    upload_dir = Path(project.storage_path) / "_incoming" / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / (file.filename or "upload")
    upload_path.write_bytes(await file.read())
    try:
        source = SourceRepository(session, artifact_store).add_source(project_id, upload_path)
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)

    return {"id": str(source.id), "filename": source.filename, "source_hash": source.source_hash}
