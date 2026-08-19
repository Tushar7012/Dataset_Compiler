# TuneForge Implementation Plan — Part 11 (React UI: structured column mapping)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec. Tasks 1–12, Part 7 (API composition), and `plan_8.md`/`plan_9.md`/`plan_10.md` (the full generate → preview → run → export lifecycle) are already implemented, committed, and pushed to `main`.
>
> **This is the last screen from `PLAN.md`'s Task 13 checklist.** After this part, everything remaining for Task 13 is a dedicated visual-design/WCAG-AA pass across every screen built across `plan_8.md` through this document — none of them have any styling yet, deliberately. That pass needs its own scope (a style/vibe decision, a design pass, not TDD feature-building) and is not part of this document.
>
> **This part deliberately does not wire its new screen into the main wizard in `App.tsx`, and that's not an oversight — read this before assuming it's incomplete.** Every other part so far built one more step in a strictly linear wizard (project → model → goal → plan → provider → preview → progress → export). Structured column mapping doesn't fit that line: it only applies when an uploaded source is a CSV/JSON/JSONL file, not the PDF/DOCX/HTML/MD/TXT documents the rest of the wizard assumes, and `ProjectSetupStep` doesn't currently tell the wizard which kind of file the user just uploaded. Deciding *when* this screen should appear, and what happens to its confirmed mapping afterward, runs straight into the exact gap Part 7 already flagged and deliberately left open: **a run only ever pulls in document-shaped sources — normalized structured records still don't merge into a run's generated output.** Wiring this screen into the wizard without answering that first would just be guessing at product behavior, not implementing a spec. This document builds and fully verifies the screen itself, standalone, against the real backend — the wizard-integration decision is left for Tushar, same as Part 7 left the run-merging question rather than rushing an answer.

**Goal (this part):** Expose Task 8's already-tested structured-data normalization logic (`detect_schema`, `apply_column_mapping`, `preview_normalization`) over HTTP for the first time, and build a screen that shows a source's detected training format, lets the user manually map columns when detection is inconclusive, and previews the normalized rows before anything is used for real.

**Architecture:** Two new endpoints on the existing `projects.py` router, alongside the existing `/projects/{id}/sources` upload endpoint they operate on — no new resource, no new router file, matching the "one thin translation layer per resource" principle from Part 7. `GET /projects/{id}/sources/{sid}/schema` reads the source file already on disk (uploaded exactly like any other source; the stored copy keeps its original extension, confirmed by reading `ArtifactStore.import_source_file`, so `load_structured_rows`'s suffix-based dispatch already works with zero changes there) and runs `detect_schema` over it. `POST /projects/{id}/sources/{sid}/normalize-preview` optionally accepts a manual `{actual_column: canonical_field}` mapping, applies it if given, re-detects, and returns up to 20 normalized preview records plus the real total row count — the same "preview before committing" shape every other screen in this app already uses (`PreviewStep`'s 20-row cap, `ModelSelectionStep`'s evidence display).

**Deliberately out of scope (this part):** wiring `ColumnMappingStep` into `App.tsx`'s wizard (see above), merging normalized structured records into a run's generated output (Part 7's still-open gap, unchanged), and any visual styling.

## Global Constraints

Repeated from Parts 1–10, still binding:

- Windows-first, Python 3.12/`uv` on the backend, `pnpm` (via `corepack pnpm` in this environment) on the frontend.
- Bind only to `127.0.0.1`. Bearer session token, memory-only.
- Existing structured data (CSV/JSON/JSONL matching a known training shape) normalizes without any LLM call — this part doesn't add one; it exposes the existing no-LLM normalization path over HTTP.

## Development Environment

```powershell
cd backend
uv sync
uv run pytest -q
```

```powershell
cd frontend
corepack pnpm install
corepack pnpm test
corepack pnpm exec tsc -b --noEmit
```

## Repository State

Same repo, branch `main`, up to date with `origin/main`. Commit locally as instructed at the end. **Do not run `git push`.**

## File Structure (this part)

```
backend/
  tuneforge/
    api/
      projects.py                              (modified — adds GET .../schema and POST .../normalize-preview)
  tests/
    api/
      test_projects.py                         (modified — 7 new tests)

frontend/
  src/
    api/
      types.ts                                  (modified — SchemaDetection, NormalizePreviewResponse)
      structured.ts                             (new — typed wrappers for the two new endpoints)
    features/
      column-mapping/
        ColumnMappingStep.tsx                    (new)
        ColumnMappingStep.test.tsx               (new)
```

---

### Step 1: Column-mapping backend endpoints — write the failing tests (RED)

Add to `backend/tests/api/test_projects.py`. Append these directly after the existing `test_upload_source_rejects_path_traversal_in_filename`:

```python
def _upload_csv(client, project_id, content: str, filename: str = "data.csv"):
    return client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": (filename, content.encode(), "text/csv")},
    )


def test_get_schema_detects_prompt_completion_csv(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "prompt,completion\nHi,Hello there\nBye,Goodbye\n").json()["id"]

    response = client.get(f"/api/projects/{project_id}/sources/{source_id}/schema")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_name"] == "prompt_completion"
    assert body["confidence"] == 1.0
    assert set(body["columns"]) == {"prompt", "completion"}


def test_get_schema_returns_null_when_inconclusive(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "col_a,col_b\nfoo,bar\n").json()["id"]

    response = client.get(f"/api/projects/{project_id}/sources/{source_id}/schema")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_name"] is None
    assert set(body["columns"]) == {"col_a", "col_b"}


def test_get_schema_for_unknown_source_returns_404(client):
    import uuid

    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    response = client.get(f"/api/projects/{project_id}/sources/{uuid.uuid4()}/schema")
    assert response.status_code == 404


def test_normalize_preview_with_detected_schema(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "prompt,completion\nHi,Hello there\nBye,Goodbye\n").json()["id"]

    response = client.post(f"/api/projects/{project_id}/sources/{source_id}/normalize-preview", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["schema_name"] == "prompt_completion"
    assert body["total_rows"] == 2
    assert len(body["preview"]) == 2
    assert body["preview"][0]["prompt"] == "Hi"
    assert body["preview"][0]["completion"] == "Hello there"


def test_normalize_preview_with_manual_column_mapping(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "question,answer\nHi,Hello there\n").json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/sources/{source_id}/normalize-preview",
        json={"mapping": {"question": "prompt", "answer": "completion"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_name"] == "prompt_completion"
    assert body["preview"][0]["prompt"] == "Hi"


def test_normalize_preview_without_mapping_when_inconclusive_returns_422(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "col_a,col_b\nfoo,bar\n").json()["id"]

    response = client.post(f"/api/projects/{project_id}/sources/{source_id}/normalize-preview", json={})

    assert response.status_code == 422


def test_normalize_preview_caps_at_20_rows_but_reports_the_real_total(client):
    lines = ["prompt,completion"] + [f"p{i},c{i}" for i in range(30)]
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "\n".join(lines) + "\n").json()["id"]

    response = client.post(f"/api/projects/{project_id}/sources/{source_id}/normalize-preview", json={})

    assert response.status_code == 200
    body = response.json()
    assert len(body["preview"]) == 20
    assert body["total_rows"] == 30
```

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/api/test_projects.py -k "schema or normalize_preview" -q
```

Expected: fails — the two new routes don't exist yet (`404`/wrong status on every one of them).

### Step 2: Column-mapping backend endpoints — implement (GREEN)

Edit `backend/tuneforge/api/projects.py`. Update the imports:

```python
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_artifact_store, get_session
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
```

Add these at the end of the file, after the existing `upload_source`:

```python
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
```

Run the tests again:

```powershell
uv run pytest tests/api/test_projects.py -q
```

Expected: all 13 pass (6 existing + 7 new).

### Step 3: Full backend suite

```powershell
cd backend
uv run pytest -q
```

Expected: 240 passed (233 already on `main` plus 7 new).

### Step 4: Frontend types + typed API wrappers

Edit `frontend/src/api/types.ts`, appending at the end:

```typescript
export interface SchemaDetection {
  schema_name: string | null
  confidence: number
  matched_keys: string[]
  columns: string[]
}

export interface NormalizePreviewResponse {
  schema_name: string
  preview: Record<string, unknown>[]
  total_rows: number
}
```

Create `frontend/src/api/structured.ts`:

```typescript
import { apiFetch } from './client'
import type { NormalizePreviewResponse, SchemaDetection } from './types'

export function getSourceSchema(projectId: string, sourceId: string): Promise<SchemaDetection> {
  return apiFetch<SchemaDetection>(`/api/projects/${projectId}/sources/${sourceId}/schema`)
}

export function normalizePreview(
  projectId: string,
  sourceId: string,
  mapping?: Record<string, string>,
): Promise<NormalizePreviewResponse> {
  return apiFetch<NormalizePreviewResponse>(`/api/projects/${projectId}/sources/${sourceId}/normalize-preview`, {
    method: 'POST',
    json: { mapping },
  })
}
```

### Step 5: `ColumnMappingStep` — write the failing tests (RED)

Create `frontend/src/features/column-mapping/ColumnMappingStep.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ColumnMappingStep } from './ColumnMappingStep'

vi.mock('../../api/structured', () => ({
  getSourceSchema: vi.fn(),
  normalizePreview: vi.fn(),
}))

import { getSourceSchema, normalizePreview } from '../../api/structured'

const mockGetSourceSchema = vi.mocked(getSourceSchema)
const mockNormalizePreview = vi.mocked(normalizePreview)

describe('ColumnMappingStep', () => {
  it('shows the detected schema and a Preview button when detection succeeds', async () => {
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion',
      confidence: 1.0,
      matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )

    expect(await screen.findByText(/prompt_completion/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /preview normalized rows/i })).toBeInTheDocument()
    expect(screen.queryByLabelText('prompt')).not.toBeInTheDocument()
  })

  it('shows a mapping input per column when detection is inconclusive', async () => {
    mockGetSourceSchema.mockResolvedValue({
      schema_name: null,
      confidence: 0,
      matched_keys: [],
      columns: ['question', 'answer'],
    })

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )

    expect(await screen.findByLabelText('question')).toBeInTheDocument()
    expect(screen.getByLabelText('answer')).toBeInTheDocument()
  })

  it('previews normalized rows for an auto-detected schema with no mapping', async () => {
    const user = userEvent.setup()
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion',
      confidence: 1.0,
      matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })
    mockNormalizePreview.mockResolvedValue({
      schema_name: 'prompt_completion',
      preview: [{ prompt: 'Hi', completion: 'Hello there' }],
      total_rows: 1,
    })

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )
    await user.click(await screen.findByRole('button', { name: /preview normalized rows/i }))

    expect(await screen.findByText(/1 row\(s\) found/i)).toBeInTheDocument()
    expect(mockNormalizePreview).toHaveBeenCalledWith('proj-1', 'src-1', undefined)
  })

  it('previews with the manual mapping when detection is inconclusive', async () => {
    const user = userEvent.setup()
    mockGetSourceSchema.mockResolvedValue({
      schema_name: null,
      confidence: 0,
      matched_keys: [],
      columns: ['question', 'answer'],
    })
    mockNormalizePreview.mockResolvedValue({
      schema_name: 'prompt_completion',
      preview: [{ prompt: 'Hi', completion: 'Hello there' }],
      total_rows: 1,
    })

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )
    await user.type(await screen.findByLabelText('question'), 'prompt')
    await user.type(screen.getByLabelText('answer'), 'completion')
    await user.click(screen.getByRole('button', { name: /preview normalized rows/i }))

    expect(await screen.findByText(/1 row\(s\) found/i)).toBeInTheDocument()
    expect(mockNormalizePreview).toHaveBeenCalledWith('proj-1', 'src-1', { question: 'prompt', answer: 'completion' })
  })

  it('calls onSchemaConfirmed with the schema name when Confirm is clicked', async () => {
    const user = userEvent.setup()
    mockGetSourceSchema.mockResolvedValue({
      schema_name: 'prompt_completion',
      confidence: 1.0,
      matched_keys: ['prompt', 'completion'],
      columns: ['prompt', 'completion'],
    })
    mockNormalizePreview.mockResolvedValue({
      schema_name: 'prompt_completion',
      preview: [{ prompt: 'Hi', completion: 'Hello there' }],
      total_rows: 1,
    })
    const onSchemaConfirmed = vi.fn()

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={onSchemaConfirmed} />,
    )
    await user.click(await screen.findByRole('button', { name: /preview normalized rows/i }))
    await user.click(await screen.findByRole('button', { name: /confirm/i }))

    expect(onSchemaConfirmed).toHaveBeenCalledWith('prompt_completion')
  })

  it('shows an error message when detection fails', async () => {
    mockGetSourceSchema.mockRejectedValue(new ApiError(422, "unsupported structured format '.txt'"))

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )

    expect(await screen.findByText("unsupported structured format '.txt'")).toBeInTheDocument()
  })

  it('shows an error message when the preview request fails', async () => {
    const user = userEvent.setup()
    mockGetSourceSchema.mockResolvedValue({
      schema_name: null,
      confidence: 0,
      matched_keys: [],
      columns: ['a', 'b'],
    })
    mockNormalizePreview.mockRejectedValue(
      new ApiError(422, 'could not determine the training format for this file — provide a column mapping'),
    )

    renderWithProviders(
      <ColumnMappingStep projectId="proj-1" sourceId="src-1" onSchemaConfirmed={vi.fn()} />,
    )
    await user.click(await screen.findByRole('button', { name: /preview normalized rows/i }))

    expect(
      await screen.findByText('could not determine the training format for this file — provide a column mapping'),
    ).toBeInTheDocument()
  })
})
```

Run it and confirm it fails:

```powershell
cd frontend
corepack pnpm test -- src/features/column-mapping
```

Expected: fails to resolve `./ColumnMappingStep`.

### Step 6: `ColumnMappingStep` — implement (GREEN)

Create `frontend/src/features/column-mapping/ColumnMappingStep.tsx`:

```typescript
import { useEffect, useState } from 'react'
import { getSourceSchema, normalizePreview } from '../../api/structured'
import { ApiError } from '../../api/client'
import type { NormalizePreviewResponse, SchemaDetection } from '../../api/types'

interface ColumnMappingStepProps {
  projectId: string
  sourceId: string
  onSchemaConfirmed: (schemaName: string) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ColumnMappingStep({ projectId, sourceId, onSchemaConfirmed }: ColumnMappingStepProps) {
  const [detected, setDetected] = useState<SchemaDetection | null>(null)
  const [detectError, setDetectError] = useState<string | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<NormalizePreviewResponse | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [isLoadingPreview, setIsLoadingPreview] = useState(false)

  useEffect(() => {
    getSourceSchema(projectId, sourceId)
      .then(setDetected)
      .catch((error: unknown) => setDetectError(errorMessage(error)))
  }, [projectId, sourceId])

  const loadPreview = () => {
    setPreviewError(null)
    setIsLoadingPreview(true)
    const mappingToSend = detected?.schema_name ? undefined : mapping
    normalizePreview(projectId, sourceId, mappingToSend)
      .then(setPreview)
      .catch((error: unknown) => setPreviewError(errorMessage(error)))
      .finally(() => setIsLoadingPreview(false))
  }

  if (!detected) {
    return <p role="alert">{detectError ?? 'Detecting format…'}</p>
  }

  return (
    <section>
      <p>
        Detected format: <strong>{detected.schema_name ?? 'unrecognized'}</strong>
      </p>

      {detected.schema_name === null && (
        <div>
          <p>Map each column to a training field:</p>
          {detected.columns.map((column) => (
            <div key={column}>
              <label htmlFor={`map-${column}`}>{column}</label>
              <input
                id={`map-${column}`}
                value={mapping[column] ?? ''}
                onChange={(event) => setMapping((previous) => ({ ...previous, [column]: event.target.value }))}
              />
            </div>
          ))}
        </div>
      )}

      <button type="button" disabled={isLoadingPreview} onClick={loadPreview}>
        Preview normalized rows
      </button>
      {previewError && <p role="alert">{previewError}</p>}

      {preview && (
        <>
          <p>
            {preview.total_rows} row(s) found, format: {preview.schema_name}
          </p>
          <ol>
            {preview.preview.map((record, index) => (
              <li key={index}>
                <pre>{JSON.stringify(record, null, 2)}</pre>
              </li>
            ))}
          </ol>
          <button type="button" onClick={() => onSchemaConfirmed(preview.schema_name)}>
            Confirm
          </button>
        </>
      )}
    </section>
  )
}
```

The manual-mapping inputs are deliberately plain free-text fields, not a schema-aware constrained dropdown — the backend is already the single source of truth for whether a mapping resolves to a valid canonical shape (`detect_schema` re-runs after `apply_column_mapping`, and a bad mapping just comes back as a 422 the UI already displays). Duplicating that validation client-side would be guessing at rules that already live correctly in one place.

Run the tests again:

```powershell
corepack pnpm test -- src/features/column-mapping
```

Expected: all 7 pass.

### Step 7: Full frontend suite and type-check

```powershell
cd frontend
corepack pnpm test
corepack pnpm exec tsc -b --noEmit
```

Expected: all tests pass (28 existing on `main` plus 7 new = 35); `tsc` prints nothing.

### Step 8: Live-verify the two new endpoints against a real backend

This part's screen isn't wired into the browser wizard (see the note at the top), so verify the backend piece directly with real file uploads rather than through a UI click-through:

```powershell
# terminal 1
$env:TUNEFORGE_DATA_DIR = "C:\tmp\tf-scratch"
cd backend
uv run python -m tuneforge.main
```

```powershell
# terminal 2 — create a project, upload a CSV with unrecognizable headers, confirm detection returns null
$token = (Invoke-RestMethod http://127.0.0.1:8420/api/session).token
$headers = @{ Authorization = "Bearer $token"; Origin = "http://127.0.0.1:8420" }
$project = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8420/api/projects -Headers $headers -ContentType "application/json" -Body '{"name":"col-map-check"}'

"question,answer`nWhat is PTO?,Paid time off.`nHow many days?,20 days." | Out-File -Encoding utf8 inconclusive.csv
$source = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8420/api/projects/$($project.id)/sources" -Headers $headers -Form @{ file = Get-Item inconclusive.csv }

Invoke-RestMethod -Uri "http://127.0.0.1:8420/api/projects/$($project.id)/sources/$($source.id)/schema" -Headers $headers
# expect schema_name: null, columns: question, answer

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8420/api/projects/$($project.id)/sources/$($source.id)/normalize-preview" -Headers $headers -ContentType "application/json" -Body (@{ mapping = @{ question = "prompt"; answer = "completion" } } | ConvertTo-Json)
# expect schema_name: prompt_completion, preview rows with prompt/completion fields
```

Both outcomes were confirmed exactly as designed during this document's own verification, using both an inconclusive CSV (requiring a manual mapping) and a plainly-named `prompt,completion` CSV (auto-detected with no mapping needed). Delete the scratch data directory afterward.

### Step 9: Commit

```powershell
cd backend
uv run pytest -q
```

```powershell
cd frontend
corepack pnpm test
corepack pnpm exec tsc -b --noEmit
```

```powershell
git add backend/tuneforge/api/projects.py backend/tests/api/test_projects.py
git add frontend/src/api/types.ts frontend/src/api/structured.ts
git add frontend/src/features/column-mapping
git commit -m "feat: expose structured column mapping over HTTP"
```

---

## When you're done

Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` from `backend/` (expect 240) and `corepack pnpm test` + `corepack pnpm exec tsc -b --noEmit` from `frontend/` (expect 35).
2. Output of `git log --oneline` — should show one new commit.
3. Confirmation that Step 8's live check actually happened, and what came back for both the inconclusive-CSV and auto-detected-CSV cases.
4. Your own opinion on the two open questions this document deliberately left for Tushar rather than guessing: (a) how should the wizard decide when to show this screen (file extension check in `ProjectSetupStep`? a format check against the upload response? something else?), and (b) should normalized structured records finally merge into a run's generated output, and if so, how does a run's `total_rows`/`plan.objective` reconcile two different record-production paths (generated-from-documents vs. normalized-from-structured-data)?
5. Anything else you had to deviate from in this document, and why.
6. If you find a correctness issue anywhere in the code exactly as given here — not a style preference, an actual bug — stop and describe it rather than silently changing behavior.
