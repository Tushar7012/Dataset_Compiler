from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_artifact_store, get_session
from tuneforge.export.bundle import export_bundle, load_records_from_jsonl
from tuneforge.jobs.runner import run_output_path
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.models import RunRecord, TrainingPlanRecord

router = APIRouter()


def _export_dir(artifact_store: ArtifactStore, run: RunRecord) -> Path:
    return run_output_path(artifact_store.base_dir, run.project_id, run.id).parent / "export"


@router.post("/runs/{run_id}/export", status_code=201)
async def create_export(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    run = session.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    if run.status != "completed":
        raise HTTPException(status_code=409, detail=f"run is {run.status!r}, not ready to export")

    plan_record = session.get(TrainingPlanRecord, run.plan_id)
    plan = TrainingPlan.model_validate(plan_record.plan_json)

    output_path = run_output_path(artifact_store.base_dir, run.project_id, run.id)
    records = load_records_from_jsonl(output_path, plan.canonical_schema)

    export_dir = _export_dir(artifact_store, run)
    export_bundle(records=records, output_dir=export_dir)

    return {"run_id": str(run.id), "export_dir": str(export_dir)}


@router.get("/exports/{run_id}/download")
async def download_export(
    run_id: uuid.UUID,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    run = session.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")

    export_dir = _export_dir(artifact_store, run)
    if not export_dir.exists():
        raise HTTPException(status_code=404, detail="no export found for this run — POST /api/runs/{run_id}/export first")

    zip_base = export_dir.parent / f"{run.id}-bundle"
    zip_path = Path(shutil.make_archive(str(zip_base), "zip", export_dir))
    return FileResponse(zip_path, filename=f"tuneforge-export-{run.id}.zip", media_type="application/zip")
