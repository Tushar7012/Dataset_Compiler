from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column()
    storage_path: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("project_id", "source_hash", name="uq_sources_project_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column()
    source_hash: Mapped[str] = mapped_column(index=True)
    relative_path: Mapped[str] = mapped_column()
    size_bytes: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class ModelProfileRecord(Base):
    __tablename__ = "model_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    model_id: Mapped[str] = mapped_column()
    source: Mapped[str] = mapped_column()
    profile_json: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class TrainingPlanRecord(Base):
    __tablename__ = "training_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    objective: Mapped[str] = mapped_column()
    plan_json: Mapped[dict] = mapped_column(JSON)
    plan_hash: Mapped[str] = mapped_column(index=True)
    approved_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class ProviderProfileRecord(Base):
    __tablename__ = "provider_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column()
    base_url: Mapped[str] = mapped_column()
    model: Mapped[str] = mapped_column()
    endpoint_scope: Mapped[str] = mapped_column()
    credential_reference: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("training_plans.id"))
    generator_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_profiles.id"))
    judge_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_profiles.id"), default=None)
    is_preview: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(default="pending")
    total_rows: Mapped[int] = mapped_column(default=0)
    completed_rows: Mapped[int] = mapped_column(default=0)
    assurance_level: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow)


class CheckpointRecord(Base):
    __tablename__ = "checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"))
    sequence: Mapped[int] = mapped_column()
    completed_rows: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class EvidenceRecord(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject_type: Mapped[str] = mapped_column()
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    field: Mapped[str] = mapped_column()
    value_json: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class ExportRecord(Base):
    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"))
    format: Mapped[str] = mapped_column()
    file_path: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
