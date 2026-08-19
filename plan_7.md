# TuneForge Implementation Plan — Part 7 (API composition)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec. This part is **not one of `PLAN.md`'s numbered tasks** — it's inserted work, agreed directly with Tushar, between Task 12 and Task 13. Here's why: Task 13 is the React UI, and a UI needs a real HTTP API to call. Looking at what Tasks 1–12 actually built, only `/api/health`, `/api/version`, `/api/echo-session` were ever mounted onto the running app. Every other endpoint `PLAN.md`'s API surface calls for — projects, sources, model analysis, plan recommend/approve, providers, exports — exists as tested Python logic (Tasks 2–10) that nothing ever wired to HTTP. Task 11's `runs` router was built but explicitly never mounted either (that gap was called out at the time). Building a React app against endpoints that don't exist would just mean redoing this work later, so it happens now instead.
>
> Do not implement Task 13 (React UI) as part of this — that's the next part, once this one is done. Do not touch `PLAN.md`.
>
> The two genuinely new patterns here (file upload handling, per-request session dependency injection) were verified against real running FastAPI code before being written into this document. A real gap is deliberately **not** closed here and called out below — read it before assuming this part makes every documented endpoint fully functional.

**Goal:** Wire every remaining `PLAN.md` API endpoint to the actual business logic built in Tasks 2–10, mount everything (including Task 11's `runs` router) into the real running app with proper per-request database sessions, and close the "how does a run actually get its source chunks" gap left open in Task 11.

**Architecture:** One `APIRouter` per resource (`projects`, `models`, `plans`, `providers`, `runs`, `exports`), each a thin translation layer — parse the request, call the already-tested repository/service function, translate its result or exception into an HTTP response. No business logic lives in these files; if a router file needs new logic beyond "call an existing function and shape the response," that's a sign the logic belongs in an earlier task's module instead.

**Deliberately out of scope, called out again where it matters:** merging Task 8's structured-data (CSV/JSON/JSONL) path into a run. A run built by this part only pulls in document-shaped sources (PDF/DOCX/HTML/MD/TXT, chunked via Task 7 and generated via Task 9) — a project's CSV/JSONL sources are still normalized correctly (Task 8 already works standalone), but nothing in this part merges those normalized records into the same run's output alongside generated ones. Closing that requires deciding how a single run's `total_rows`/`plan.objective` reconciles two different record-production paths, which is a real design question, not a wiring gap — it needs its own decision, not a rushed answer bolted onto this already-large part.

## Global Constraints

Repeated from Parts 1–6, still binding — nothing here changes them, this part is pure wiring:

- Windows-first, Python 3.12, uv-managed, no conda.
- Bind only to `127.0.0.1`, bearer session auth on every mutating endpoint (Task 1's `require_session` — every router added here gets mounted behind it).
- API keys through Windows Credential Manager only, never SQLite/logs.
- Every remote generation call requires explicit consent (already enforced inside the Task 3 provider client — nothing new needed here).

## Development Environment

Same as before — **uv**, no conda, no direct `pip`.

```powershell
cd backend
uv sync
uv run pytest -q
```

`python-multipart` is a new dependency (Step 1) — FastAPI's file-upload handling silently requires it at import time and raises a clear `RuntimeError` if it's missing. Verified against a real upload test before being added here.

## Repository State

Same repo, branch `main`, `origin` already set. Commit locally as instructed. **Do not run `git push`.**

## File Structure (this part)

```
backend/
  pyproject.toml                  (modified — add python-multipart)
  tuneforge/
    storage/
      repositories.py             (modified — SourceRepository gains list_sources)
    export/
      bundle.py                   (modified — adds load_records_from_jsonl)
    jobs/
      runner.py                   (modified — closes the sources-loading gap)
    api/
      deps.py
      projects.py
      models.py
      plans.py
      providers.py
      runs.py                     (modified — per-request sessions, adds preview endpoint)
      exports.py
    main.py                       (modified — wires engine/session factory, mounts every router)
  tests/
    api/
      test_deps.py
      test_projects.py
      test_models.py
      test_plans.py
      test_providers.py
      test_runs.py                (modified — updated for the new session dependency)
      test_exports.py
      test_app_wiring.py
    jobs/
      test_runner.py              (modified — adds a real-sources integration test)
```

---

### Step 1: Add dependencies

Edit `backend/pyproject.toml` — add `python-multipart`:

```toml
[project]
name = "tuneforge"
version = "0.1.0"
description = "TuneForge backend"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "sqlalchemy>=2.0.35",
    "httpx>=0.27",
    "keyring>=25.0",
    "huggingface-hub>=1.0",
    "docling>=2.120.1",
    "transformers>=5.0",
    "datasketch>=2.0.0",
    "datasets>=5.0.0",
    "python-multipart>=0.0.20",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["tuneforge*"]
```

```powershell
cd backend
uv sync
```

### Step 2: Per-request session dependency — write the failing tests (RED)

Create `backend/tests/api/test_deps.py`:

```python
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.deps import get_session
from tuneforge.storage.db import create_session_factory, create_sqlite_engine


def _build_app(tmp_path: Path) -> FastAPI:
    engine = create_sqlite_engine(tmp_path / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)

    @app.get("/probe")
    def probe(session=Depends(get_session)):
        return {"is_active": session.is_active}

    return app


def test_get_session_provides_a_working_session(tmp_path):
    client = TestClient(_build_app(tmp_path))
    response = client.get("/probe")
    assert response.status_code == 200
    assert response.json()["is_active"] is True


def test_get_session_opens_a_fresh_session_per_request(tmp_path, monkeypatch):
    app = _build_app(tmp_path)
    seen_ids = []
    original_factory = app.state.session_factory

    def tracking_factory():
        session = original_factory()
        seen_ids.append(id(session))
        return session

    app.state.session_factory = tracking_factory
    client = TestClient(app)

    client.get("/probe")
    client.get("/probe")

    assert len(set(seen_ids)) == 2, "each request must get its own session, not a shared one"
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/api/test_deps.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.api.deps'`.

### Step 3: Per-request session dependency — implement (GREEN)

Create `backend/tuneforge/api/deps.py`:

```python
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from tuneforge.storage.artifacts import ArtifactStore


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_artifact_store(request: Request) -> ArtifactStore:
    return request.app.state.artifact_store
```

Run the tests again:

```powershell
uv run pytest tests/api/test_deps.py -q
```

Expected: all pass.

### Step 4: `SourceRepository.list_sources` — write the failing test (RED)

Add to `backend/tests/storage/test_persistence.py` (append, don't replace the file):

```python
def test_list_sources_returns_every_source_for_a_project_in_import_order(session, artifact_store, tmp_path):
    project = ProjectRepository(session, artifact_store).create("proj")
    source_repo = SourceRepository(session, artifact_store)

    first_path = tmp_path / "first.txt"
    first_path.write_text("first")
    second_path = tmp_path / "second.txt"
    second_path.write_text("second")

    first = source_repo.add_source(project.id, first_path)
    second = source_repo.add_source(project.id, second_path)

    sources = source_repo.list_sources(project.id)

    assert [s.id for s in sources] == [first.id, second.id]
```

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/storage/test_persistence.py::test_list_sources_returns_every_source_for_a_project_in_import_order -q
```

Expected: `AttributeError: 'SourceRepository' object has no attribute 'list_sources'`.

### Step 5: `SourceRepository.list_sources` — implement (GREEN)

Edit `backend/tuneforge/storage/repositories.py`. Add this method to the existing `SourceRepository` class (alongside `add_source` and `get_source_path`):

```python
    def list_sources(self, project_id: uuid.UUID) -> list[Source]:
        return (
            self.session.query(Source)
            .filter(Source.project_id == project_id)
            .order_by(Source.created_at)
            .all()
        )
```

Run the test again:

```powershell
uv run pytest tests/storage/test_persistence.py::test_list_sources_returns_every_source_for_a_project_in_import_order -q
```

Expected: passes.

### Step 6: Projects + sources API — write the failing tests (RED)

Create `backend/tests/api/test_projects.py`:

```python
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.projects import router
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(tmp_path / "data")
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_create_project_returns_the_new_project(client):
    response = client.post("/api/projects", json={"name": "HR Policy Bot"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "HR Policy Bot"
    assert "id" in body


def test_create_project_without_name_is_rejected(client):
    response = client.post("/api/projects", json={})
    assert response.status_code == 422


def test_delete_unknown_project_returns_404(client):
    import uuid

    response = client.delete(f"/api/projects/{uuid.uuid4()}")
    assert response.status_code == 404


def test_upload_source_stores_the_original_filename(client):
    create_response = client.post("/api/projects", json={"name": "proj"})
    project_id = create_response.json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": ("policy.md", b"# Policy\n\nContent here.", "text/markdown")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "policy.md"
    assert "source_hash" in body


def test_upload_source_to_unknown_project_returns_404(client):
    import uuid

    response = client.post(
        f"/api/projects/{uuid.uuid4()}/sources",
        files={"file": ("policy.md", b"content", "text/markdown")},
    )
    assert response.status_code == 404
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/api/test_projects.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.api.projects'`.

### Step 7: Projects + sources API — implement (GREEN)

Create `backend/tuneforge/api/projects.py`:

```python
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
```

Run the tests again:

```powershell
uv run pytest tests/api/test_projects.py -q
```

Expected: all pass.

### Step 8: Model analysis API — write the failing tests (RED)

Create `backend/tests/api/test_models.py`:

```python
import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.models import router
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ModelProfileRecord


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.include_router(router, prefix="/api")
    test_client = TestClient(app)
    test_client.session_factory = app.state.session_factory
    return test_client


def test_analyze_persists_a_model_profile_record(client, monkeypatch):
    from tuneforge.models.analyzer import ModelProfile

    fake_profile = ModelProfile(
        source="huggingface", model_id="sshleifer/tiny-gpt2", architecture="GPT2LMHeadModel", model_type="gpt2",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=1024,
        modalities=["text"], evidence=[], confidence=0.95,
    )
    monkeypatch.setattr("tuneforge.api.models.analyze_model", lambda model_id, *, source: fake_profile)

    response = client.post(
        "/api/models/analyze", json={"model_id": "sshleifer/tiny-gpt2", "project_id": str(uuid.uuid4())}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "sshleifer/tiny-gpt2"
    assert body["is_causal_lm"] is True

    session = client.session_factory()
    stored = session.query(ModelProfileRecord).one()
    assert stored.model_id == "sshleifer/tiny-gpt2"
    assert stored.confidence == 0.95


def test_analyze_translates_incompatible_model_error_to_422(client, monkeypatch):
    from tuneforge.models.compatibility import IncompatibleModelError

    def raise_incompatible(model_id, *, source):
        raise IncompatibleModelError("not a causal LM")

    monkeypatch.setattr("tuneforge.api.models.analyze_model", raise_incompatible)

    response = client.post(
        "/api/models/analyze", json={"model_id": "bert-base-uncased", "project_id": str(uuid.uuid4())}
    )

    assert response.status_code == 422


def test_analyze_requires_model_id_and_project_id(client):
    response = client.post("/api/models/analyze", json={})
    assert response.status_code == 422
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/api/test_models.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.api.models'`.

### Step 9: Model analysis API — implement (GREEN)

Create `backend/tuneforge/api/models.py`:

```python
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_session
from tuneforge.models.analyzer import GatedModelError, ModelNotAccessibleError, analyze_model
from tuneforge.models.compatibility import IncompatibleModelError
from tuneforge.storage.models import ModelProfileRecord

router = APIRouter()


@router.post("/models/analyze")
async def analyze(payload: dict, session: Session = Depends(get_session)):
    model_id = payload.get("model_id")
    project_id = payload.get("project_id")
    source = payload.get("source", "huggingface")
    if not model_id or not project_id:
        raise HTTPException(status_code=422, detail="'model_id' and 'project_id' are required")

    try:
        profile = analyze_model(model_id, source=source)
    except (GatedModelError, ModelNotAccessibleError, IncompatibleModelError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    profile_dict = json.loads(profile.model_dump_json())
    record = ModelProfileRecord(
        id=uuid.uuid4(),
        project_id=uuid.UUID(project_id),
        model_id=profile.model_id,
        source=profile.source,
        profile_json=profile_dict,
        confidence=profile.confidence,
    )
    session.add(record)
    session.commit()

    return {"id": str(record.id), **profile_dict}
```

Run the tests again:

```powershell
uv run pytest tests/api/test_models.py -q
```

Expected: all pass.

### Step 10: Providers API — write the failing tests (RED)

Create `backend/tests/api/test_providers.py`:

```python
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.providers import router
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ProviderProfileRecord


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.include_router(router, prefix="/api")
    test_client = TestClient(app)
    test_client.session_factory = app.state.session_factory
    return test_client


def test_create_local_provider_without_api_key_stores_no_credential_reference(client):
    response = client.post(
        "/api/providers",
        json={
            "project_id": str(uuid.uuid4()), "name": "ollama", "base_url": "http://127.0.0.1:11434",
            "model": "llama3", "endpoint_scope": "local",
        },
    )

    assert response.status_code == 201
    session = client.session_factory()
    stored = session.query(ProviderProfileRecord).one()
    assert stored.credential_reference is None


def test_create_remote_provider_with_api_key_stores_a_credential_reference_not_the_key(client, monkeypatch):
    stored_keys = {}
    monkeypatch.setattr(
        "tuneforge.api.providers.store_api_key", lambda ref, key: stored_keys.__setitem__(ref, key)
    )

    response = client.post(
        "/api/providers",
        json={
            "project_id": str(uuid.uuid4()), "name": "openai", "base_url": "https://api.openai.com/v1",
            "model": "gpt-4", "endpoint_scope": "remote", "api_key": "sk-super-secret",
        },
    )

    assert response.status_code == 201
    session = client.session_factory()
    stored = session.query(ProviderProfileRecord).one()
    assert stored.credential_reference is not None
    assert stored.credential_reference != "sk-super-secret"
    assert stored_keys[stored.credential_reference] == "sk-super-secret"


def test_invalid_endpoint_scope_is_rejected(client):
    response = client.post(
        "/api/providers",
        json={
            "project_id": str(uuid.uuid4()), "name": "x", "base_url": "http://x", "model": "x",
            "endpoint_scope": "not-a-real-scope",
        },
    )
    assert response.status_code == 422
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/api/test_providers.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.api.providers'`.

### Step 11: Providers API — implement (GREEN)

Create `backend/tuneforge/api/providers.py`:

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_session
from tuneforge.security.credentials import store_api_key
from tuneforge.storage.models import ProviderProfileRecord

router = APIRouter()

_VALID_SCOPES = {"local", "remote"}
_REQUIRED_FIELDS = ("project_id", "name", "base_url", "model", "endpoint_scope")


@router.post("/providers", status_code=201)
async def create_provider(payload: dict, session: Session = Depends(get_session)):
    missing = [field for field in _REQUIRED_FIELDS if not payload.get(field)]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing required field(s): {missing}")
    if payload["endpoint_scope"] not in _VALID_SCOPES:
        raise HTTPException(status_code=422, detail="endpoint_scope must be 'local' or 'remote'")

    credential_reference = None
    api_key = payload.get("api_key")
    if api_key:
        credential_reference = f"provider-{uuid.uuid4().hex}"
        store_api_key(credential_reference, api_key)

    record = ProviderProfileRecord(
        id=uuid.uuid4(),
        project_id=uuid.UUID(payload["project_id"]),
        name=payload["name"],
        base_url=payload["base_url"],
        model=payload["model"],
        endpoint_scope=payload["endpoint_scope"],
        credential_reference=credential_reference,
    )
    session.add(record)
    session.commit()
    return {"id": str(record.id), "name": record.name, "endpoint_scope": record.endpoint_scope}
```

Run the tests again:

```powershell
uv run pytest tests/api/test_providers.py -q
```

Expected: all pass.

### Step 12: Plans API — write the failing tests (RED)

Create `backend/tests/api/test_plans.py`:

```python
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.plans import router
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ModelProfileRecord, TrainingPlanRecord


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.include_router(router, prefix="/api")
    test_client = TestClient(app)
    test_client.session_factory = app.state.session_factory
    return test_client


def _stored_model_profile(client, project_id):
    from tuneforge.models.analyzer import ModelProfile

    profile = ModelProfile(
        source="huggingface", model_id="meta-llama/Llama-3-8B", architecture="LlamaForCausalLM", model_type="llama",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=4096,
        modalities=["text"], evidence=[], confidence=0.9,
    )
    session = client.session_factory()
    record = ModelProfileRecord(
        id=uuid.uuid4(), project_id=project_id, model_id=profile.model_id, source=profile.source,
        profile_json=__import__("json").loads(profile.model_dump_json()), confidence=profile.confidence,
    )
    session.add(record)
    session.commit()
    return record


def test_recommend_persists_a_training_plan(client):
    project_id = uuid.uuid4()
    model_profile_record = _stored_model_profile(client, project_id)

    response = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id),
            "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation",
            "desired_behavior": "understand HR policy",
            "language": "en",
            "target_rows": 500,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["objective"] == "cpt"

    session = client.session_factory()
    stored = session.query(TrainingPlanRecord).one()
    assert stored.objective == "cpt"


def test_recommend_returns_409_when_chat_template_required_but_missing(client):
    project_id = uuid.uuid4()
    model_profile_record = _stored_model_profile(client, project_id)  # chat_template_found=False

    response = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id),
            "model_profile_id": str(model_profile_record.id),
            "goal": "multi_turn_conversation",
            "desired_behavior": "chat",
            "language": "en",
            "target_rows": 500,
        },
    )

    assert response.status_code == 409


def test_approve_sets_approved_at(client):
    project_id = uuid.uuid4()
    model_profile_record = _stored_model_profile(client, project_id)
    recommend_response = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )
    plan_id = recommend_response.json()["id"]

    response = client.post(f"/api/plans/{plan_id}/approve")

    assert response.status_code == 200
    session = client.session_factory()
    stored = session.query(TrainingPlanRecord).one()
    assert stored.approved_at is not None
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/api/test_plans.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.api.plans'`.

### Step 13: Plans API — implement (GREEN)

Create `backend/tuneforge/api/plans.py`:

```python
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_session
from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.intents import TrainingIntent
from tuneforge.planning.planner import ChatTemplateRequiredError, DistinctJudgeRequiredError, recommend_plan
from tuneforge.storage.models import ModelProfileRecord, TrainingPlanRecord

router = APIRouter()


@router.post("/plans/recommend")
async def recommend(payload: dict, session: Session = Depends(get_session)):
    required = ("project_id", "model_profile_id", "goal", "desired_behavior", "language", "target_rows")
    missing = [field for field in required if payload.get(field) is None]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing required field(s): {missing}")

    model_profile_record = session.get(ModelProfileRecord, uuid.UUID(payload["model_profile_id"]))
    if model_profile_record is None:
        raise HTTPException(status_code=404, detail="model profile not found — analyze a model first")
    model_profile = ModelProfile.model_validate(model_profile_record.profile_json)

    intent = TrainingIntent(
        goal=payload["goal"], desired_behavior=payload["desired_behavior"], language=payload["language"]
    )

    try:
        plan = recommend_plan(
            intent,
            model_profile,
            target_rows=payload["target_rows"],
            objective_override=payload.get("objective_override"),
            generator_profile_id=uuid.UUID(payload["generator_profile_id"]) if payload.get("generator_profile_id") else None,
            judge_profile_id=uuid.UUID(payload["judge_profile_id"]) if payload.get("judge_profile_id") else None,
        )
    except (ChatTemplateRequiredError, DistinctJudgeRequiredError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    plan_dict = json.loads(plan.model_dump_json())
    record = TrainingPlanRecord(
        id=uuid.uuid4(),
        project_id=uuid.UUID(payload["project_id"]),
        objective=plan.objective,
        plan_json=plan_dict,
        plan_hash=plan.plan_hash,
    )
    session.add(record)
    session.commit()

    return {"id": str(record.id), **plan_dict}


@router.post("/plans/{plan_id}/approve")
async def approve_plan(plan_id: uuid.UUID, session: Session = Depends(get_session)):
    plan = session.get(TrainingPlanRecord, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")
    plan.approved_at = datetime.now(timezone.utc)
    session.commit()
    return {"id": str(plan.id), "approved_at": plan.approved_at.isoformat()}
```

> **`POST /api/plans/{id}/research` (Task 6) is not included here.** `resolve_rejected_recommendation` (Task 6) is `async` and needs an `httpx.AsyncClient` for the official-sources fetch — wiring it in needs the same shared-client-lifecycle question Task 3's provider client already has (who owns the client, when does it close), which none of the routers above needed to answer since they don't make outbound HTTP calls themselves. Rather than improvise an answer under this part's already-large scope, this endpoint is left out. Add it in a follow-up pass once that question has a real answer, not a guessed one.

Run the tests again:

```powershell
uv run pytest tests/api/test_plans.py -q
```

Expected: all pass.

### Step 14: Runs API — update for the new session pattern, add preview (RED then GREEN together)

Task 11's `runs.py` was written against `request.app.state.session` (a single shared session — the gap flagged at the time). Update it now to use the same per-request pattern as every other router in this part, and add the preview endpoint `PLAN.md` calls for.

First, update `backend/tests/api/test_runs.py`'s fixture to match the new pattern used by every other router test in this part:

```python
@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(tmp_path / "data")
    app.state.db_path = tmp_path / "data" / "tuneforge.db"
    app.include_router(router, prefix="/api")
    test_client = TestClient(app)
    test_client.session_factory = app.state.session_factory
    return test_client
```

Every place the old tests did `client.session.add(...)` / `client.session.commit()` / `client.session.refresh(...)` now opens its own session instead:

```python
def _session(client):
    return client.session_factory()
```

Replace every `client.session` reference in that file with a fresh `_session(client)` call at the point of use (each call opens a new session against the same SQLite file — since SQLite serializes writers, this is safe and matches how the real app will actually be hit, request by request).

**Write this test yourself rather than copying one from this document — here's the one deliberate exception to "every code block is final."** Every other test in this document is complete, runnable code; this one specific test is not written for you, because writing it correctly requires knowing the exact final shape of `_make_plan_and_provider` and the project-creation helper *after* you've converted the whole file to the new session pattern in this step — that shape depends on choices you make while doing that conversion, not on anything decidable ahead of time.

Add a real `test_preview_creates_a_run_with_is_preview_true` to `test_runs.py` that:

1. Mocks `tuneforge.api.runs.start_run` to a no-op (same reason as the other tests in this file that call it — no real process needed to test the endpoint's own logic).
2. Creates a project, a `TrainingPlanRecord`, and a `ProviderProfileRecord`, reusing this file's existing `_make_plan_and_provider`-style helper now updated to open sessions via `client.session_factory()`.
3. `POST`s to `/api/runs/preview` with `{"plan_id": ..., "generator_profile_id": ...}`.
4. Asserts the response has `is_preview: true`, and a fresh session confirms the created `RunRecord` has `is_preview=True`.

Now edit `backend/tuneforge/api/runs.py`. Replace every `request.app.state.session` with a session obtained via the shared dependency:

```python
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_session
from tuneforge.jobs.runner import is_run_process_alive, start_run
from tuneforge.storage.models import RunRecord, TrainingPlanRecord

router = APIRouter()

_CANCELLABLE_STATUSES = {"pending", "running"}


def _get_run_or_404(session: Session, run_id: uuid.UUID) -> RunRecord:
    run = session.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return run


@router.post("/runs/preview", status_code=201)
async def create_preview(payload: dict, request: Request, session: Session = Depends(get_session)):
    plan_id = payload.get("plan_id")
    generator_profile_id = payload.get("generator_profile_id")
    if not plan_id or not generator_profile_id:
        raise HTTPException(status_code=422, detail="'plan_id' and 'generator_profile_id' are required")

    plan = session.get(TrainingPlanRecord, uuid.UUID(plan_id))
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")

    run = RunRecord(
        id=uuid.uuid4(),
        project_id=plan.project_id,
        plan_id=plan.id,
        generator_profile_id=uuid.UUID(generator_profile_id),
        judge_profile_id=uuid.UUID(payload["judge_profile_id"]) if payload.get("judge_profile_id") else None,
        is_preview=True,
    )
    session.add(run)
    session.commit()
    start_run(db_path=request.app.state.db_path, base_data_dir=request.app.state.artifact_store.base_dir, run_id=run.id)
    return {"id": str(run.id), "status": run.status, "is_preview": run.is_preview}


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, session: Session = Depends(get_session)):
    run = _get_run_or_404(session, run_id)
    return {
        "id": str(run.id),
        "status": run.status,
        "completed_rows": run.completed_rows,
        "total_rows": run.total_rows,
        "is_preview": run.is_preview,
        "assurance_level": run.assurance_level,
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, session: Session = Depends(get_session)):
    run = _get_run_or_404(session, run_id)
    if run.status not in _CANCELLABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"run is {run.status!r}, cannot cancel")
    run.status = "cancel_requested"
    session.commit()
    return {"status": run.status}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: uuid.UUID, request: Request, session: Session = Depends(get_session)):
    run = _get_run_or_404(session, run_id)
    if run.status not in ("cancelled", "failed"):
        raise HTTPException(status_code=409, detail=f"run is {run.status!r}, nothing to resume")
    run.status = "pending"
    session.commit()
    start_run(db_path=request.app.state.db_path, base_data_dir=request.app.state.artifact_store.base_dir, run_id=run.id)
    return {"status": "pending"}


@router.post("/runs/{run_id}/approve-full")
async def approve_full(run_id: uuid.UUID, request: Request, session: Session = Depends(get_session)):
    preview_run = _get_run_or_404(session, run_id)
    if not preview_run.is_preview:
        raise HTTPException(status_code=409, detail="only a preview run can be approved into a full run")
    if preview_run.status != "completed":
        raise HTTPException(status_code=409, detail=f"preview is {preview_run.status!r}, not ready to approve")

    # See the comment in api/plans.py's approve_plan and this same block in
    # the original Task 11 document: this relies on TrainingPlanRecord rows
    # being immutable once created, which is true of everything built so
    # far — approved_at on this exact row already means "this exact
    # plan_hash was approved".
    plan = session.get(TrainingPlanRecord, preview_run.plan_id)
    if plan.approved_at is None:
        raise HTTPException(status_code=409, detail="plan_hash has not been approved (or was invalidated)")

    full_run = RunRecord(
        id=uuid.uuid4(),
        project_id=preview_run.project_id,
        plan_id=preview_run.plan_id,
        generator_profile_id=preview_run.generator_profile_id,
        judge_profile_id=preview_run.judge_profile_id,
        is_preview=False,
    )
    session.add(full_run)
    session.commit()
    start_run(db_path=request.app.state.db_path, base_data_dir=request.app.state.artifact_store.base_dir, run_id=full_run.id)
    return {"id": str(full_run.id), "status": full_run.status}


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: uuid.UUID, request: Request, session: Session = Depends(get_session)):
    run = _get_run_or_404(session, run_id)

    async def event_source():
        import asyncio

        sequence = 0
        while True:
            session.refresh(run)
            stage = run.status
            payload = {
                "run_id": str(run.id),
                "sequence": sequence,
                "stage": stage,
                "completed_rows": run.completed_rows,
                "total_rows": run.total_rows,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            sequence += 1
            if stage in ("completed", "cancelled", "failed"):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(event_source(), media_type="text/event-stream")
```

Note that `POST /api/plans/{plan_id}/approve` moved to `api/plans.py` in Step 13 — it's no longer in this file at all.

Run the tests again:

```powershell
uv run pytest tests/api/test_runs.py -q
```

Expected: all pass (once you've finished the one incomplete test noted above).

### Step 15: Close the sources-loading gap in the runner — write the failing test (RED)

This closes the gap Task 11 flagged: `run_generation_worker` had `sources: list[SourceRecord] = []` with no way to fill it in. It can be filled in now — Task 7's pieces (`convert_document_cached`, `chunk_into_source_records`) plus this part's new `SourceRepository.list_sources` are exactly what's needed. **Document-shaped sources only** (see this document's opening note on what's deliberately out of scope).

Add to `backend/tests/jobs/test_runner.py`:

```python
def test_load_project_sources_chunks_every_document_source_in_order(tmp_path):
    from tuneforge.ingestion.chunking import build_tokenizer
    from tuneforge.jobs.runner import _load_project_sources
    from tuneforge.storage.artifacts import ArtifactStore
    from tuneforge.storage.db import create_session_factory, create_sqlite_engine
    from tuneforge.storage.repositories import ProjectRepository, SourceRepository

    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    session = create_session_factory(engine)()
    artifact_store = ArtifactStore(tmp_path / "data")
    project = ProjectRepository(session, artifact_store).create("proj")

    doc_a = tmp_path / "a.md"
    doc_a.write_text("# Doc A\n\nFirst document content.\n")
    doc_b = tmp_path / "b.md"
    doc_b.write_text("# Doc B\n\nSecond document content.\n")
    source_repo = SourceRepository(session, artifact_store)
    source_repo.add_source(project.id, doc_a)
    source_repo.add_source(project.id, doc_b)

    tokenizer = build_tokenizer("gpt2", max_tokens=64)
    sources = _load_project_sources(session, artifact_store, project.id, tokenizer)

    assert len(sources) == 2
    texts = {s.text for s in sources}
    assert any("First document content" in t for t in texts)
    assert any("Second document content" in t for t in texts)
```

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/jobs/test_runner.py::test_load_project_sources_chunks_every_document_source_in_order -q
```

Expected: `ImportError: cannot import name '_load_project_sources' from 'tuneforge.jobs.runner'`.

### Step 16: Close the sources-loading gap in the runner — implement (GREEN)

Edit `backend/tuneforge/jobs/runner.py`. Add this function, and use it inside `run_generation_worker` in place of the placeholder line:

```python
def _load_project_sources(session, artifact_store, project_id: uuid.UUID, tokenizer) -> list[SourceRecord]:
    from tuneforge.ingestion.chunking import chunk_into_source_records
    from tuneforge.ingestion.documents import convert_document_cached
    from tuneforge.storage.repositories import SourceRepository

    source_repo = SourceRepository(session, artifact_store)
    cache_dir = artifact_store.base_dir / "_docling_cache"

    all_sources: list[SourceRecord] = []
    for source_row in source_repo.list_sources(project_id):
        file_path = source_repo.get_source_path(source_row)
        document, source_hash = convert_document_cached(file_path, cache_dir=cache_dir)
        document_id = uuid.uuid4()
        chunks = chunk_into_source_records(
            document,
            document_id=document_id,
            source_name=source_row.filename,
            source_hash=source_hash,
            tokenizer=tokenizer,
        )
        all_sources.extend(chunks)
    return all_sources
```

In `run_generation_worker`, replace:

```python
    source_repo = SourceRepository(session, artifact_store)
    sources: list[SourceRecord] = []  # populated by whatever wires ingestion+chunking to a run (out of scope here)

    model_profile = analyze_model(plan_record.plan_json.get("model_id", ""), source="huggingface")
    tokenizer = build_tokenizer(model_profile.model_id)
```

with:

```python
    model_profile = analyze_model(plan_record.plan_json.get("model_id", ""), source="huggingface")
    tokenizer = build_tokenizer(model_profile.model_id)
    sources = _load_project_sources(session, artifact_store, run.project_id, tokenizer)
```

(The `SourceRepository` import already present at the top of that function's body can stay or go — `_load_project_sources` imports its own copy, so it's fine either way; don't leave an unused import if you remove the inline usage.)

Run the test again:

```powershell
uv run pytest tests/jobs/test_runner.py::test_load_project_sources_chunks_every_document_source_in_order -q
```

Expected: passes. This test does real Docling parsing and downloads the real (tiny, cached-after-first-run) `gpt2` tokenizer — same pattern already proven in Task 7.

### Step 17: Export-on-demand API — write the failing tests (RED)

This wires Task 12's export bundle to an actual endpoint, since nothing did that either — `export_bundle` took an explicit `output_dir` and was never called from anywhere reachable over HTTP.

First, add a small reload helper to Task 12's own file. Add to `backend/tuneforge/export/bundle.py`:

```python
from tuneforge.records import ChatMessage, CPTRecord, DPORecord, RecordMetadata, SFTConversationRecord, SFTPromptCompletionRecord

_RECORD_TYPES = {
    "CPTRecord": CPTRecord,
    "SFTPromptCompletionRecord": SFTPromptCompletionRecord,
    "SFTConversationRecord": SFTConversationRecord,
    "DPORecord": DPORecord,
}


def load_records_from_jsonl(path: Path, canonical_schema: str) -> list:
    record_cls = _RECORD_TYPES[canonical_schema]
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(record_cls.model_validate_json(line))
    return records
```

Create `backend/tests/api/test_exports.py`:

```python
import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.exports import router
from tuneforge.jobs.runner import run_output_path
from tuneforge.records import CPTRecord, RecordMetadata
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ModelProfileRecord, RunRecord, TrainingPlanRecord
from tuneforge.storage.repositories import ProjectRepository


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(tmp_path / "data")
    app.include_router(router, prefix="/api")
    test_client = TestClient(app)
    test_client.session_factory = app.state.session_factory
    test_client.artifact_store = app.state.artifact_store
    return test_client


def _completed_run(client):
    session = client.session_factory()
    project = ProjectRepository(session, client.artifact_store).create("proj")

    from tuneforge.models.analyzer import ModelProfile

    profile = ModelProfile(
        source="huggingface", model_id="sshleifer/tiny-gpt2", architecture="GPT2LMHeadModel", model_type="gpt2",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=1024,
        modalities=["text"], evidence=[], confidence=0.95,
    )
    model_profile_record = ModelProfileRecord(
        id=uuid.uuid4(), project_id=project.id, model_id=profile.model_id, source=profile.source,
        profile_json=json.loads(profile.model_dump_json()), confidence=profile.confidence,
    )
    plan_record = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project.id, objective="cpt",
        plan_json={
            "objective": "cpt", "canonical_schema": "CPTRecord", "target_rows": 10, "examples_per_chunk": 1,
            "generator_profile_id": None, "judge_profile_id": None, "required_validators": [],
            "evidence": [], "confidence": 0.9, "plan_hash": "hash1",
        },
        plan_hash="hash1",
    )
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan_record.id,
        generator_profile_id=uuid.uuid4(), status="completed", completed_rows=2, total_rows=2,
    )
    session.add_all([model_profile_record, plan_record, run])
    session.commit()

    output_path = run_output_path(client.artifact_store.base_dir, project.id, run.id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for text in ("first accepted row", "second accepted row"):
            record = CPTRecord(
                text=text, metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="h")
            )
            f.write(record.model_dump_json())
            f.write("\n")

    return run


def test_export_then_download_returns_a_zip(client):
    run = _completed_run(client)

    export_response = client.post(f"/api/runs/{run.id}/export")
    assert export_response.status_code == 201

    download_response = client.get(f"/api/exports/{run.id}/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"


def test_download_before_export_returns_404(client):
    run = _completed_run(client)
    response = client.get(f"/api/exports/{run.id}/download")
    assert response.status_code == 404


def test_export_before_run_completes_is_rejected(client):
    session = client.session_factory()
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan_record = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project.id, objective="cpt", plan_json={"canonical_schema": "CPTRecord"}, plan_hash="h"
    )
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan_record.id, generator_profile_id=uuid.uuid4(), status="running"
    )
    session.add_all([plan_record, run])
    session.commit()

    response = client.post(f"/api/runs/{run.id}/export")
    assert response.status_code == 409
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/api/test_exports.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.api.exports'`.

### Step 18: Export-on-demand API — implement (GREEN)

Create `backend/tuneforge/api/exports.py`:

```python
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_artifact_store, get_session
from tuneforge.export.bundle import export_bundle, load_records_from_jsonl
from tuneforge.export.splitting import split_train_eval
from tuneforge.jobs.runner import run_output_path
from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.models import ModelProfileRecord, RunRecord, TrainingPlanRecord
from tuneforge.validation.pipeline import ValidationReport

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

    model_profile_record = (
        session.query(ModelProfileRecord)
        .filter(ModelProfileRecord.project_id == run.project_id)
        .order_by(ModelProfileRecord.created_at.desc())
        .first()
    )
    if model_profile_record is None:
        raise HTTPException(status_code=409, detail="no analyzed model found for this project")
    model_profile = ModelProfile.model_validate(model_profile_record.profile_json)

    output_path = run_output_path(artifact_store.base_dir, run.project_id, run.id)
    records = load_records_from_jsonl(output_path, plan.canonical_schema)
    split = split_train_eval(records)

    report = ValidationReport(accepted=records, rejection_counts={}, assurance_level=run.assurance_level or "lower_assurance")
    export_dir = _export_dir(artifact_store, run)
    export_bundle(
        train=split.train, eval_records=split.eval, output_dir=export_dir,
        model_profile=model_profile, plan=plan, validation_report=report,
    )

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
```

Run the tests again:

```powershell
uv run pytest tests/api/test_exports.py -q
```

Expected: all pass.

### Step 19: Mount everything into the real app — write the failing test (RED)

Create `backend/tests/api/test_app_wiring.py`:

```python
from tuneforge.main import create_app
from tuneforge.settings import Settings


def test_all_routers_are_mounted(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = create_app(Settings())

    paths = {route.path for route in app.routes}
    assert "/api/projects" in paths
    assert "/api/models/analyze" in paths
    assert "/api/plans/recommend" in paths
    assert "/api/providers" in paths
    assert "/api/runs/preview" in paths
    assert "/api/runs/{run_id}/export" in paths
    assert "/api/exports/{run_id}/download" in paths


def test_project_endpoints_require_bearer_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = create_app(Settings())
    client = TestClient(app)

    response = client.post("/api/projects", json={"name": "test"})

    assert response.status_code == 401
```

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/api/test_app_wiring.py -q
```

Expected: fails — the new routers aren't mounted yet, and `/api/projects` with no auth currently 404s rather than 401ing (nothing handles that path at all).

### Step 20: Mount everything into the real app — implement (GREEN)

Edit `backend/tuneforge/main.py`. Add the new imports and wire the engine/session factory/artifact store into `app.state`, then mount every router behind `require_session`:

```python
from tuneforge.api import exports, models, plans, projects, providers, runs
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
```

Inside `create_app`, after `app.state.session_token = generate_session_token()` and before the existing route definitions, add:

```python
    db_path = settings.data_dir / "tuneforge.db"
    engine = create_sqlite_engine(db_path)
    app.state.db_path = db_path
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(settings.data_dir)
```

After the existing `/api/echo-session` route (leave everything already there untouched), add:

```python
    protected = [Depends(require_session)]
    app.include_router(projects.router, prefix="/api", dependencies=protected)
    app.include_router(models.router, prefix="/api", dependencies=protected)
    app.include_router(plans.router, prefix="/api", dependencies=protected)
    app.include_router(providers.router, prefix="/api", dependencies=protected)
    app.include_router(runs.router, prefix="/api", dependencies=protected)
    app.include_router(exports.router, prefix="/api", dependencies=protected)
```

This must come **before** the `dist_dir` static-files mount at the bottom of `create_app` — `StaticFiles(..., html=True)` mounted at `/` will otherwise catch requests to unmatched paths as 404s from the SPA fallback instead of letting them reach these routers. Since these routers are all prefixed with `/api` and the static mount is `/`, order only matters if FastAPI/Starlette route matching is prefix-sensitive in a way that lets the broader mount shadow narrower ones — verify this by running Step 19's tests after making this change, in this order, rather than assuming.

Run the tests again:

```powershell
uv run pytest tests/api/test_app_wiring.py -q
```

Expected: all pass.

### Step 21: Run the full backend suite and commit

```powershell
cd backend
uv run pytest -q
```

Expected: every test from Parts 1–6 and this part passes.

```powershell
git add backend
git commit -m "feat: wire the REST API to the existing backend logic"
```

---

## When you're done

Do not start Task 13. Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` (full pass/fail summary) from `backend/`.
2. Output of `git log --oneline` — should show one new commit: `feat: wire the REST API to the existing backend logic`.
3. **How you finished the incomplete test in Step 14** (`test_preview_creates_a_run_with_is_preview_true`) — that one was deliberately left for you to complete, not a mistake.
4. **Whether `POST /api/plans/{id}/research` (Task 6) needs to be added now or can wait** — it was explicitly left out in Step 13 pending a decision about the shared `httpx.AsyncClient` lifecycle. If you have an opinion on the right answer, say so; if you added it anyway, describe exactly what lifecycle decision you made.
5. Confirm the router-ordering concern in Step 20 (API routes vs. the SPA static mount) actually behaves as expected — that one line asked you to verify rather than trust it.
6. Confirm `backend/uv.lock` picked up `python-multipart` and is committed.
7. Anything else you had to deviate from in this document, and why.
8. If you find a correctness issue anywhere in the code exactly as given here — not a style preference, an actual bug — stop and describe it rather than silently changing behavior.
