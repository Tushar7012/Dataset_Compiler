from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_artifact_store, get_session
from tuneforge.ingestion.documents import MAX_UPLOAD_BYTES
from tuneforge.ingestion.structured import (
    EmptyStructuredFileError,
    UnsupportedStructuredFormatError,
    load_structured_rows,
)
from tuneforge.normalization.detector import detect_schema
from tuneforge.normalization.mappers import InvalidRecordError
from tuneforge.normalization.preview import ColumnMappingError, apply_column_mapping, preview_normalization
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.models import Source
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
    # Cheapest possible check first, before any DB query or persisting into
    # project storage. UploadFile.size is already populated by Starlette's
    # multipart parser by the time this function body runs — no extra read
    # needed. Note this doesn't prevent the oversized body from being
    # received/spooled over the network in the first place (that's ASGI/
    # web-server territory, not this handler's) — it only stops it from
    # being written into a project permanently.
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{file.filename}: {file.size} bytes exceeds the {MAX_UPLOAD_BYTES} byte upload limit",
        )

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
    upload_path = upload_dir / Path(file.filename or "upload").name
    upload_path.write_bytes(await file.read())
    try:
        source = SourceRepository(session, artifact_store).add_source(project_id, upload_path)
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)

    return {"id": str(source.id), "filename": source.filename, "source_hash": source.source_hash}


def _get_source_or_404(session: Session, project_id: uuid.UUID, source_id: uuid.UUID) -> Source:
    source = (
        session.query(Source).filter(Source.id == source_id, Source.project_id == project_id).one_or_none()
    )
    if source is None:
        raise HTTPException(status_code=404, detail=f"source not found: {source_id}")
    return source


def _load_rows_or_422(artifact_store: ArtifactStore, source: Source) -> list:
    path = artifact_store.resolve(source.relative_path)
    try:
        return load_structured_rows(path)
    except (UnsupportedStructuredFormatError, EmptyStructuredFileError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/projects/{project_id}/sources/{source_id}/schema")
async def get_source_schema(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    source = _get_source_or_404(session, project_id, source_id)
    rows = _load_rows_or_422(artifact_store, source)

    detection = detect_schema([row.data for row in rows])
    columns = list(rows[0].data.keys()) if rows else []
    return {
        "schema_name": detection.schema_name,
        "confidence": detection.confidence,
        "matched_keys": detection.matched_keys,
        "columns": columns,
    }


@router.post("/projects/{project_id}/sources/{source_id}/normalize-preview")
async def normalize_source_preview(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    payload: dict,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    source = _get_source_or_404(session, project_id, source_id)
    rows = _load_rows_or_422(artifact_store, source)

    mapping = payload.get("mapping")
    if mapping:
        try:
            rows = apply_column_mapping(rows, mapping)
        except ColumnMappingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    detection = detect_schema([row.data for row in rows])
    if detection.schema_name is None:
        raise HTTPException(
            status_code=422,
            detail="could not determine the training format for this file — provide a column mapping",
        )

    try:
        preview_records = preview_normalization(rows, detection.schema_name, document_id=uuid.uuid4())
    except InvalidRecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "schema_name": detection.schema_name,
        "preview": [json.loads(record.model_dump_json()) for record in preview_records],
        "total_rows": len(rows),
    }


@router.post("/projects/{project_id}/sources/{source_id}/confirm-mapping")
async def confirm_source_mapping(
    project_id: uuid.UUID,
    source_id: uuid.UUID,
    payload: dict,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    source = _get_source_or_404(session, project_id, source_id)
    rows = _load_rows_or_422(artifact_store, source)

    mapping = payload.get("mapping")
    if mapping:
        try:
            rows = apply_column_mapping(rows, mapping)
        except ColumnMappingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    detection = detect_schema([row.data for row in rows])
    if detection.schema_name is None:
        raise HTTPException(
            status_code=422,
            detail="could not determine the training format for this file — provide a column mapping",
        )

    source.confirmed_schema = detection.schema_name.value
    source.column_mapping = json.dumps(mapping) if mapping else None
    session.commit()

    return {"schema_name": detection.schema_name, "total_rows": len(rows)}
