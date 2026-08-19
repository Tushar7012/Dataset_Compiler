# TuneForge Implementation Plan — Part 10 (React UI: preview → run progress → export)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec. Tasks 1–12, Part 7 (API composition), `plan_8.md` (setup → plan confirmation), and `plan_9.md` (provider config + remote-consent threading) are already implemented, committed, and pushed to `main`.
>
> **This part found and fixed a critical, previously-invisible bug in already-merged code — not new-to-this-part work, so it's already committed on `main` as of this document, not included as a step below.** `jobs/runner.py`'s `run_generation_worker` read the target model's ID via `plan_record.plan_json.get("model_id", "")` — but `TrainingPlan` has no `model_id` field at all (confirm this yourself: it isn't in the schema block in `PLAN.md`, nor in `backend/tuneforge/planning/schemas.py`). That lookup always returned `""`, so **every real generation run this project has ever attempted would have failed immediately** with `HFValidationError: Repo id must use alphanumeric chars...`. Nothing caught this before now because every existing test mocked `analyze_model` directly, never exercising the broken lookup itself — this is the first time in the project's history a real generation run was driven end-to-end through a live backend rather than through mocks or a stubbed `start_run`. The fix (commit `20358e5` on `main`, already merged): look up the project's most recently analyzed `ModelProfileRecord` — the exact same query `api/exports.py` already uses — instead of a plan field that was never populated. If you're implementing this document, you already have the fix; you don't need to do anything about it, but it explains why the run lifecycle actually completes now when it wouldn't have a session ago.
>
> Also already fixed and merged, unrelated to Task 13 but discovered while verifying this part: `backend/tests/test_runtime_security.py`'s `make_client()` built its app from a bare `Settings()`, whose `data_dir` default falls back to the real `%LOCALAPPDATA%\TuneForge` — every `pytest` run was silently writing a real database into the directory the shipped app will use. Fixed in commit `759dc87` (already on `main`) by passing an explicit `tmp_path`-backed `data_dir`, matching `test_app_wiring.py`'s existing isolation. If you run this project's tests on Windows and want to confirm your own machine's `%LOCALAPPDATA%\TuneForge` stays clean, that's the mechanism that keeps it that way now.
>
> **Do not implement structured column mapping or any visual styling as part of this** — those are `plan_11.md`. Do not touch `PLAN.md`.
>
> Every code block below was actually written, run, and verified — including a live run through the full lifecycle (create preview → watch it complete for real → view its accepted rows → approve it into a full run → watch that complete → export → download and unzip a real bundle) against a real backend with a real (if slow-starting) spawned worker process. One genuinely useful operational finding from that live run, not a bug: a freshly spawned worker process took **20–40 seconds** before its first real progress update, because `multiprocessing.Process` with the `spawn` start method re-imports the whole `tuneforge` package cold in the new process — including `torch`/`transformers`/`docling` — even though the parent process already has them warm. This is not a hang; `PreviewStep`'s "pending" state is exactly the right thing to show during that window, and Step 12 below tells you to wait long enough before concluding otherwise.

**Goal (this part):** Add the remaining run-lifecycle screens — generate and inspect a 20-row preview, approve it into a full run and watch real-time progress with cancel/resume, then export and download the finished bundle with brief Unsloth import instructions.

**Architecture:** `GET /api/runs/{id}/records` is a new, minimal endpoint — it just reads up to `limit` lines back out of the same `records.jsonl` the generation worker already writes, no new storage. The existing SSE endpoint (`GET /api/runs/{id}/events`, built in Part 7) can't be reached with the browser's native `EventSource` — it doesn't support custom headers, and this app's whole auth model is a bearer header, not a cookie — so the frontend uses `fetch` plus a manual `ReadableStream` reader instead, parsing the same `data: {...}\n\n` frames by hand. Every run-lifecycle screen (`PreviewStep`, `RunProgressStep`) subscribes through that one shared client. `ExportStep`'s download can't be a plain `<a href>` either, for the same bearer-header reason — it fetches the zip as an authenticated `Blob` and triggers the save via a temporary object-URL anchor.

**Deliberately out of scope (this part):** structured column mapping (still needs its own new backend endpoint over Task 8's untouched `detect_schema`/`apply_column_mapping`/`preview_normalization` logic), and any visual styling/WCAG-AA pass — every screen built in `plan_8.md`, `plan_9.md`, and this part is still unstyled semantic HTML.

## Global Constraints

Repeated from Parts 1–9, still binding:

- Windows-first, Python 3.12/`uv` on the backend, `pnpm` (via `corepack pnpm` in this environment) on the frontend.
- Bind only to `127.0.0.1`. Bearer session token, memory-only.
- Max 100,000 accepted rows per run — already enforced by `MAX_ACCEPTED_ROWS` in `jobs/runner.py`, untouched here.

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

**A note on live-verifying this part yourself, from direct experience writing it:** if you drive a real generation run by hand, set your scratch data directory with `$env:TUNEFORGE_DATA_DIR = "..."` as its own statement *before* starting the backend — not inline-prefixed on a backgrounded command — and confirm which directory actually got used by checking where `tuneforge.db` shows up. This exact mistake silently wrote real test data into `%LOCALAPPDATA%\TuneForge` during this document's own verification (caught, inspected — only ever this session's own test projects — and deleted). It's now moot for `pytest` itself (see the runtime-security fix above), but still applies to manually running `uv run python -m tuneforge.main` yourself.

## Repository State

Same repo, branch `main`, up to date with `origin/main` (already includes the two fixes described above). Commit locally as instructed at the end. **Do not run `git push`.**

## File Structure (this part)

```
backend/
  tuneforge/
    api/
      runs.py                                (modified — adds GET /runs/{id}/records)
    jobs/
      runner.py                              (modified — marks a run "failed" on unhandled exception)
  tests/
    api/
      test_runs.py                           (modified — 3 new records-endpoint tests)
    jobs/
      test_runner.py                         (modified — 1 new failure-status test)

frontend/
  src/
    App.tsx                                  (modified — adds 'preview'/'progress'/'export' wizard steps)
    api/
      types.ts                               (modified — RunStatus/RunSummary/RunCreated/RunRecordsResponse)
      runs.ts                                (new — typed wrappers for the run-lifecycle endpoints)
      runEvents.ts                           (new — SSE-via-fetch client)
      runEvents.test.ts                      (new)
    features/
      preview/
        PreviewStep.tsx                       (new)
        PreviewStep.test.tsx                  (new)
      run-progress/
        RunProgressStep.tsx                   (new)
        RunProgressStep.test.tsx              (new)
      export/
        ExportStep.tsx                        (new)
        ExportStep.test.tsx                   (new)
```

---

### Step 1: Records-listing endpoint — write the failing tests (RED)

Add to `backend/tests/api/test_runs.py`. The import line needs `run_output_path`:

```python
from tuneforge.jobs.runner import run_output_path
```

Append these tests at the end of the file:

```python
def test_list_run_records_returns_up_to_limit_accepted_rows(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project.id, objective="cpt",
        plan_json={"objective": "cpt", "canonical_schema": "CPTRecord"}, plan_hash="hash1",
    )
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project.id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model", endpoint_scope="local",
    )
    session.add_all([plan, provider])
    session.commit()
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        status="completed", completed_rows=3, total_rows=3,
    )
    session = _session(client)
    session.add(run)
    session.commit()

    output_path = run_output_path(client.artifact_store.base_dir, project.id, run.id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for i in range(3):
            f.write(json.dumps({"text": f"row {i}", "metadata": {"chunk_id": f"c{i}"}}))
            f.write("\n")

    response = client.get(f"/api/runs/{run.id}/records?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert len(body["records"]) == 2
    assert body["records"][0]["text"] == "row 0"
    assert body["total_accepted"] == 3
    assert body["canonical_schema"] == "CPTRecord"


def test_list_run_records_returns_empty_list_before_any_rows_written(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
    )
    session = _session(client)
    session.add(run)
    session.commit()

    response = client.get(f"/api/runs/{run.id}/records")

    assert response.status_code == 200
    assert response.json()["records"] == []


def test_list_run_records_for_unknown_run_returns_404(client):
    response = client.get(f"/api/runs/{uuid.uuid4()}/records")
    assert response.status_code == 404
```

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/api/test_runs.py -k list_run_records -q
```

Expected: the first two fail with `404` (route doesn't exist yet); the unknown-run test already passes trivially (any unmatched path 404s).

### Step 2: Records-listing endpoint — implement (GREEN)

Edit `backend/tuneforge/api/runs.py`. Update the imports:

```python
from tuneforge.api.deps import get_artifact_store, get_session
from tuneforge.jobs.runner import is_run_process_alive, run_output_path, start_run
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.models import ProviderProfileRecord, RunRecord, TrainingPlanRecord
```

Add the endpoint at the end of the file, after `stream_events`:

```python
@router.get("/runs/{run_id}/records")
async def list_run_records(
    run_id: uuid.UUID,
    limit: int = 20,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    run = _get_run_or_404(session, run_id)
    plan = session.get(TrainingPlanRecord, run.plan_id)

    output_path = run_output_path(artifact_store.base_dir, run.project_id, run.id)
    records: list[dict] = []
    if output_path.exists():
        with output_path.open(encoding="utf-8") as f:
            for line in f:
                if len(records) >= limit:
                    break
                line = line.strip()
                if line:
                    records.append(json.loads(line))

    return {
        "canonical_schema": plan.plan_json.get("canonical_schema"),
        "records": records,
        "total_accepted": run.completed_rows,
    }
```

Run the tests again:

```powershell
uv run pytest tests/api/test_runs.py -q
```

Expected: all 18 pass.

### Step 3: Failure-status fix — write the failing test (RED)

`resume_run` already accepts `"failed"` as a resumable status, and the SSE stream already terminates on it — but nothing anywhere ever sets a run's status to `"failed"`. A crashed worker just leaves the run stuck at whatever status it had (usually `"running"`), forever, with no way to recover it. This closes that gap.

Add to `backend/tests/jobs/test_runner.py`, directly above `test_worker_process_can_be_spawned_and_joins_cleanly`:

```python
def test_worker_marks_run_failed_on_unhandled_exception(env, monkeypatch):
    session, artifact_store, project, run = env
    db_path = session.get_bind().url.database
    session.close()

    class _FakeTok:
        tokenizer = object()

    monkeypatch.setattr("tuneforge.ingestion.chunking.build_tokenizer", lambda model_id: _FakeTok())
    monkeypatch.setattr(
        "tuneforge.jobs.runner._load_project_sources", lambda session, artifact_store, project_id, tokenizer: []
    )
    monkeypatch.setattr("tuneforge.jobs.runner._load_provider", lambda session, profile_id: object())

    async def fake_run_generation_async(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("tuneforge.jobs.runner._run_generation_async", fake_run_generation_async)

    with pytest.raises(RuntimeError):
        run_generation_worker(db_path=db_path, base_data_dir=str(artifact_store.base_dir), run_id=str(run.id))

    check_session = create_session_factory(create_sqlite_engine(Path(db_path)))()
    stored = check_session.get(RunRecord, run.id)
    assert stored.status == "failed"
```

(`env`'s fixture already includes a real `ModelProfileRecord` as of the model_id fix on `main` — nothing to add there.)

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/jobs/test_runner.py -k marks_run_failed -q
```

Expected: fails — `RuntimeError` correctly propagates (the test's own `pytest.raises` catches that part), but `stored.status` is still `"pending"`, not `"failed"`.

### Step 4: Failure-status fix — implement (GREEN)

Edit `backend/tuneforge/jobs/runner.py`. Wrap the existing `asyncio.run(...)` call at the end of `run_generation_worker` in a `try`/`except`:

```python
    try:
        asyncio.run(
            _run_generation_async(
                session=session,
                run=run,
                plan=plan,
                sources=sources,
                generator=generator,
                judge=judge,
                spec=GenerationSpec(desired_behavior=plan.objective),
                tokenizer=tokenizer.tokenizer,
                max_tokens=model_profile.context_length or 2048,
                target_rows=target_rows,
                resume_from_chunk=resume_from_chunk,
                output_path=output_path,
                consent=consent,
            )
        )
    except Exception:
        logger.exception("run %s failed", run.id)
        run.status = "failed"
        session.commit()
        raise
```

Run the tests again:

```powershell
uv run pytest tests/jobs/test_runner.py -q
```

Expected: all 11 pass.

### Step 5: Full backend suite

```powershell
cd backend
uv run pytest -q
```

Expected: 237 passed (233 already on `main` plus 4 new: 3 records-endpoint tests, 1 failure-status test).

### Step 6: Frontend types + typed API wrappers for the run lifecycle

Edit `frontend/src/api/types.ts`, appending at the end:

```typescript
export type RunStatus = 'pending' | 'running' | 'cancel_requested' | 'cancelled' | 'completed' | 'failed'

export interface RunSummary {
  id: string
  status: RunStatus
  completed_rows: number
  total_rows: number
  is_preview: boolean
  assurance_level: string | null
}

export interface RunCreated {
  id: string
  status: RunStatus
  is_preview: boolean
}

export interface RunRecordsResponse {
  canonical_schema: string | null
  records: Record<string, unknown>[]
  total_accepted: number
}
```

Create `frontend/src/api/runs.ts`:

```typescript
import { apiFetch } from './client'
import { getSessionToken } from './session'
import type { RunCreated, RunRecordsResponse, RunSummary } from './types'

interface CreatePreviewInput {
  planId: string
  generatorProfileId: string
  judgeProfileId?: string
  remoteConsent?: boolean
}

export function createPreview(input: CreatePreviewInput): Promise<RunCreated> {
  return apiFetch<RunCreated>('/api/runs/preview', {
    method: 'POST',
    json: {
      plan_id: input.planId,
      generator_profile_id: input.generatorProfileId,
      judge_profile_id: input.judgeProfileId,
      remote_consent: input.remoteConsent,
    },
  })
}

export function approveFull(runId: string, remoteConsent?: boolean): Promise<RunCreated> {
  return apiFetch<RunCreated>(`/api/runs/${runId}/approve-full`, {
    method: 'POST',
    json: { remote_consent: remoteConsent },
  })
}

export function getRun(runId: string): Promise<RunSummary> {
  return apiFetch<RunSummary>(`/api/runs/${runId}`)
}

export function cancelRun(runId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/api/runs/${runId}/cancel`, { method: 'POST' })
}

export function resumeRun(runId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/api/runs/${runId}/resume`, { method: 'POST' })
}

export function listRunRecords(runId: string, limit = 20): Promise<RunRecordsResponse> {
  return apiFetch<RunRecordsResponse>(`/api/runs/${runId}/records?limit=${limit}`)
}

export function exportRun(runId: string): Promise<{ run_id: string; export_dir: string }> {
  return apiFetch(`/api/runs/${runId}/export`, { method: 'POST' })
}

// apiFetch always parses a JSON body — a zip download needs the raw Response
// so its bytes can be read as a Blob instead, hence a plain fetch here with
// the same manual bearer-header attachment apiFetch does internally.
export async function downloadExport(runId: string): Promise<Blob> {
  const token = await getSessionToken()
  const response = await fetch(`/api/exports/${runId}/download`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw new Error(`export download failed: ${response.status}`)
  }
  return response.blob()
}
```

### Step 7: SSE-via-fetch client — write the failing tests (RED)

Create `frontend/src/api/runEvents.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { subscribeToRunEvents } from './runEvents'
import { resetSessionTokenForTests } from './session'
import type { RunEvent } from './runEvents'

function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let index = 0
  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]))
        index += 1
      } else {
        controller.close()
      }
    },
  })
}

describe('subscribeToRunEvents', () => {
  beforeEach(() => {
    resetSessionTokenForTests()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('parses SSE events and stops at a terminal stage', async () => {
    const events = [
      'data: {"run_id":"r1","sequence":0,"stage":"running","completed_rows":1,"total_rows":3}\n\n',
      'data: {"run_id":"r1","sequence":1,"stage":"completed","completed_rows":3,"total_rows":3}\n\n',
    ]
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'abc' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(sseStream(events), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const received: RunEvent[] = []
    await subscribeToRunEvents('r1', (event) => received.push(event))

    expect(received).toHaveLength(2)
    expect(received[0].stage).toBe('running')
    expect(received[1].stage).toBe('completed')

    const [, eventsCall] = fetchMock.mock.calls
    const [url, requestInit] = eventsCall as [string, RequestInit]
    expect(url).toBe('/api/runs/r1/events')
    const headers = requestInit.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer abc')
  })

  it('handles a chunk boundary that splits a single SSE event', async () => {
    const events = [
      'data: {"run_id":"r1","sequence":0,"stage":"running","completed_rows":1,"total_rows":3}',
      '\n\ndata: {"run_id":"r1","sequence":1,"stage":"completed","completed_rows":3,"total_rows":3}\n\n',
    ]
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'abc' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(sseStream(events), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const received: RunEvent[] = []
    await subscribeToRunEvents('r1', (event) => received.push(event))

    expect(received).toHaveLength(2)
  })

  it('stops on a failed stage without throwing', async () => {
    const events = ['data: {"run_id":"r1","sequence":0,"stage":"failed","completed_rows":0,"total_rows":3}\n\n']
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'abc' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(sseStream(events), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const received: RunEvent[] = []
    await subscribeToRunEvents('r1', (event) => received.push(event))

    expect(received).toHaveLength(1)
    expect(received[0].stage).toBe('failed')
  })
})
```

Run it and confirm it fails:

```powershell
cd frontend
corepack pnpm test -- src/api/runEvents
```

Expected: fails to resolve `./runEvents`.

### Step 8: SSE-via-fetch client — implement (GREEN)

Create `frontend/src/api/runEvents.ts`:

```typescript
import { getSessionToken } from './session'

export interface RunEvent {
  run_id: string
  sequence: number
  stage: string
  completed_rows: number
  total_rows: number
}

// The backend's SSE endpoint requires a bearer Authorization header, which
// the native EventSource API cannot set — it only supports plain GET with no
// custom headers. fetch() plus a manual ReadableStream reader is the
// standard workaround: same auth path as every other request in this app,
// just parsed as "data: {...}\n\n" frames instead of a single JSON body.
const TERMINAL_STAGES = new Set(['completed', 'cancelled', 'failed'])

export async function subscribeToRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = await getSessionToken()
  const response = await fetch(`/api/runs/${runId}/events`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`failed to open run event stream: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const dataLine = rawEvent.split('\n').find((line) => line.startsWith('data: '))
      if (dataLine) {
        const event = JSON.parse(dataLine.slice('data: '.length)) as RunEvent
        onEvent(event)
        if (TERMINAL_STAGES.has(event.stage)) return
      }
      boundary = buffer.indexOf('\n\n')
    }
  }
}
```

Run the tests again:

```powershell
corepack pnpm test -- src/api/runEvents
```

Expected: all 3 pass.

### Step 9: `PreviewStep` — write the failing tests (RED)

Create `frontend/src/features/preview/PreviewStep.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { PreviewStep } from './PreviewStep'

vi.mock('../../api/runs', () => ({
  createPreview: vi.fn(),
  approveFull: vi.fn(),
  listRunRecords: vi.fn(),
}))
vi.mock('../../api/runEvents', () => ({
  subscribeToRunEvents: vi.fn(),
}))

import { approveFull, createPreview, listRunRecords } from '../../api/runs'
import { subscribeToRunEvents } from '../../api/runEvents'

const mockCreatePreview = vi.mocked(createPreview)
const mockApproveFull = vi.mocked(approveFull)
const mockListRunRecords = vi.mocked(listRunRecords)
const mockSubscribe = vi.mocked(subscribeToRunEvents)

describe('PreviewStep', () => {
  it('shows a Generate preview button initially', () => {
    renderWithProviders(
      <PreviewStep
        planId="plan-1"
        generatorProfileId="prov-1"
        remoteConsentGranted={false}
        onApprovedFull={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /generate preview/i })).toBeInTheDocument()
  })

  it('creates the preview, streams progress, and shows accepted rows on completion', async () => {
    const user = userEvent.setup()
    mockCreatePreview.mockResolvedValue({ id: 'run-1', status: 'pending', is_preview: true })
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 1, total_rows: 20 })
      onEvent({ run_id: runId, sequence: 1, stage: 'completed', completed_rows: 5, total_rows: 20 })
    })
    mockListRunRecords.mockResolvedValue({
      canonical_schema: 'CPTRecord',
      records: [{ text: 'row 1' }],
      total_accepted: 5,
    })

    renderWithProviders(
      <PreviewStep
        planId="plan-1"
        generatorProfileId="prov-1"
        remoteConsentGranted={false}
        onApprovedFull={vi.fn()}
      />,
    )
    await user.click(screen.getByRole('button', { name: /generate preview/i }))

    expect(await screen.findByText(/completed/i)).toBeInTheDocument()
    expect(await screen.findByText(/5 row\(s\) accepted/i)).toBeInTheDocument()
    expect(mockCreatePreview).toHaveBeenCalledWith({
      planId: 'plan-1',
      generatorProfileId: 'prov-1',
      judgeProfileId: undefined,
      remoteConsent: false,
    })
  })

  it('shows Approve full run once completed and calls onApprovedFull', async () => {
    const user = userEvent.setup()
    mockCreatePreview.mockResolvedValue({ id: 'run-1', status: 'pending', is_preview: true })
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'completed', completed_rows: 5, total_rows: 20 })
    })
    mockListRunRecords.mockResolvedValue({ canonical_schema: 'CPTRecord', records: [], total_accepted: 5 })
    const fullRun = { id: 'run-2', status: 'pending' as const, is_preview: false }
    mockApproveFull.mockResolvedValue(fullRun)
    const onApprovedFull = vi.fn()

    renderWithProviders(
      <PreviewStep
        planId="plan-1"
        generatorProfileId="prov-1"
        remoteConsentGranted={true}
        onApprovedFull={onApprovedFull}
      />,
    )
    await user.click(screen.getByRole('button', { name: /generate preview/i }))
    const approveButton = await screen.findByRole('button', { name: /approve full run/i })
    await user.click(approveButton)

    expect(mockApproveFull).toHaveBeenCalledWith('run-1', true)
    await waitFor(() => expect(onApprovedFull).toHaveBeenCalledWith(fullRun))
  })

  it('shows an error if preview creation fails', async () => {
    const user = userEvent.setup()
    mockCreatePreview.mockRejectedValue(new ApiError(404, 'plan not found'))

    renderWithProviders(
      <PreviewStep
        planId="plan-1"
        generatorProfileId="prov-1"
        remoteConsentGranted={false}
        onApprovedFull={vi.fn()}
      />,
    )
    await user.click(screen.getByRole('button', { name: /generate preview/i }))

    expect(await screen.findByText('plan not found')).toBeInTheDocument()
  })
})
```

Run it and confirm it fails:

```powershell
corepack pnpm test -- src/features/preview
```

Expected: fails to resolve `./PreviewStep`.

### Step 10: `PreviewStep` — implement (GREEN)

Create `frontend/src/features/preview/PreviewStep.tsx`:

```typescript
import { useEffect, useState } from 'react'
import { approveFull, createPreview, listRunRecords } from '../../api/runs'
import { subscribeToRunEvents } from '../../api/runEvents'
import { ApiError } from '../../api/client'
import type { RunCreated, RunRecordsResponse, RunStatus } from '../../api/types'

interface PreviewStepProps {
  planId: string
  generatorProfileId: string
  judgeProfileId?: string
  remoteConsentGranted: boolean
  onApprovedFull: (fullRun: RunCreated) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function PreviewStep({
  planId,
  generatorProfileId,
  judgeProfileId,
  remoteConsentGranted,
  onApprovedFull,
}: PreviewStepProps) {
  const [run, setRun] = useState<RunCreated | null>(null)
  const [stage, setStage] = useState<RunStatus | null>(null)
  const [progress, setProgress] = useState({ completed: 0, total: 0 })
  const [records, setRecords] = useState<RunRecordsResponse | null>(null)
  const [createError, setCreateError] = useState<string | null>(null)
  const [approveError, setApproveError] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [isApproving, setIsApproving] = useState(false)

  useEffect(() => {
    if (!run) return undefined
    const controller = new AbortController()
    subscribeToRunEvents(
      run.id,
      (event) => {
        setStage(event.stage as RunStatus)
        setProgress({ completed: event.completed_rows, total: event.total_rows })
      },
      controller.signal,
    ).catch(() => {})
    return () => controller.abort()
  }, [run])

  useEffect(() => {
    if (stage === 'completed' && run) {
      listRunRecords(run.id).then(setRecords).catch(() => {})
    }
  }, [stage, run])

  const startPreview = () => {
    setCreateError(null)
    setIsCreating(true)
    createPreview({ planId, generatorProfileId, judgeProfileId, remoteConsent: remoteConsentGranted })
      .then(setRun)
      .catch((error: unknown) => setCreateError(errorMessage(error)))
      .finally(() => setIsCreating(false))
  }

  const approve = () => {
    if (!run) return
    setApproveError(null)
    setIsApproving(true)
    approveFull(run.id, remoteConsentGranted)
      .then(onApprovedFull)
      .catch((error: unknown) => setApproveError(errorMessage(error)))
      .finally(() => setIsApproving(false))
  }

  if (!run) {
    return (
      <section>
        <button type="button" disabled={isCreating} onClick={startPreview}>
          Generate preview
        </button>
        {createError && <p role="alert">{createError}</p>}
      </section>
    )
  }

  return (
    <section>
      <p>
        Preview status: <strong>{stage ?? run.status}</strong> ({progress.completed}/{progress.total} rows)
      </p>

      {records && (
        <>
          <p>
            {records.total_accepted} row(s) accepted, schema: {records.canonical_schema}
          </p>
          <ol>
            {records.records.map((record, index) => (
              <li key={index}>
                <pre>{JSON.stringify(record, null, 2)}</pre>
              </li>
            ))}
          </ol>
        </>
      )}

      {stage === 'completed' && (
        <button type="button" disabled={isApproving} onClick={approve}>
          Approve full run
        </button>
      )}
      {approveError && <p role="alert">{approveError}</p>}
    </section>
  )
}
```

Run the tests again:

```powershell
corepack pnpm test -- src/features/preview
```

Expected: all 4 pass.

### Step 11: `RunProgressStep` — write the failing tests (RED)

Create `frontend/src/features/run-progress/RunProgressStep.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { RunProgressStep } from './RunProgressStep'

vi.mock('../../api/runs', () => ({
  cancelRun: vi.fn(),
  resumeRun: vi.fn(),
}))
vi.mock('../../api/runEvents', () => ({
  subscribeToRunEvents: vi.fn(),
}))

import { cancelRun, resumeRun } from '../../api/runs'
import { subscribeToRunEvents } from '../../api/runEvents'

const mockCancelRun = vi.mocked(cancelRun)
const mockResumeRun = vi.mocked(resumeRun)
const mockSubscribe = vi.mocked(subscribeToRunEvents)

describe('RunProgressStep', () => {
  it('shows status and progress from the event stream, with a Cancel button while running', async () => {
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 40, total_rows: 100 })
    })

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)

    expect(await screen.findByText(/running/i)).toBeInTheDocument()
    expect(screen.getByText(/40\/100/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /resume/i })).not.toBeInTheDocument()
  })

  it('cancels the run when Cancel is clicked', async () => {
    const user = userEvent.setup()
    mockCancelRun.mockResolvedValue({ status: 'cancel_requested' })
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 10, total_rows: 100 })
    })

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: /cancel/i }))

    expect(mockCancelRun).toHaveBeenCalledWith('run-1')
  })

  it('shows a Resume button once cancelled, and re-subscribes after resuming', async () => {
    const user = userEvent.setup()
    mockResumeRun.mockResolvedValue({ status: 'pending' })
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'cancelled', completed_rows: 10, total_rows: 100 })
    })

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)
    const resumeButton = await screen.findByRole('button', { name: /resume/i })
    expect(screen.queryByRole('button', { name: /cancel/i })).not.toBeInTheDocument()
    const subscribeCallsBeforeResume = mockSubscribe.mock.calls.length

    await user.click(resumeButton)

    expect(mockResumeRun).toHaveBeenCalledWith('run-1')
    await waitFor(() => expect(mockSubscribe.mock.calls.length).toBe(subscribeCallsBeforeResume + 1))
  })

  it('calls onCompleted when the stage becomes completed', async () => {
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'completed', completed_rows: 100, total_rows: 100 })
    })
    const onCompleted = vi.fn()

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={onCompleted} />)

    await waitFor(() => expect(onCompleted).toHaveBeenCalled())
  })

  it('shows an error message if cancelling fails', async () => {
    const user = userEvent.setup()
    mockCancelRun.mockRejectedValue(new ApiError(409, "run is 'completed', cannot cancel"))
    mockSubscribe.mockImplementation(async (runId, onEvent) => {
      onEvent({ run_id: runId, sequence: 0, stage: 'running', completed_rows: 10, total_rows: 100 })
    })

    renderWithProviders(<RunProgressStep runId="run-1" onCompleted={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: /cancel/i }))

    expect(await screen.findByText("run is 'completed', cannot cancel")).toBeInTheDocument()
  })
})
```

**Note on the second test's assertion style** — don't assert an absolute `toHaveBeenCalledTimes(N)` on `mockSubscribe` here. Vitest doesn't reset mock call counts between tests in this file by default, so an absolute count silently includes calls from earlier tests in the same run. Capture the count immediately before the action under test and assert the *increment*, exactly as shown — this was caught by actually running the test, not decided upfront.

Run it and confirm it fails:

```powershell
corepack pnpm test -- src/features/run-progress
```

Expected: fails to resolve `./RunProgressStep`.

### Step 12: `RunProgressStep` — implement (GREEN)

Create `frontend/src/features/run-progress/RunProgressStep.tsx`:

```typescript
import { useEffect, useState } from 'react'
import { cancelRun, resumeRun } from '../../api/runs'
import { subscribeToRunEvents } from '../../api/runEvents'
import { ApiError } from '../../api/client'
import type { RunStatus } from '../../api/types'

interface RunProgressStepProps {
  runId: string
  onCompleted: () => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function RunProgressStep({ runId, onCompleted }: RunProgressStepProps) {
  const [stage, setStage] = useState<RunStatus | null>(null)
  const [progress, setProgress] = useState({ completed: 0, total: 0 })
  const [actionError, setActionError] = useState<string | null>(null)
  const [isActing, setIsActing] = useState(false)
  const [subscriptionKey, setSubscriptionKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    subscribeToRunEvents(
      runId,
      (event) => {
        setStage(event.stage as RunStatus)
        setProgress({ completed: event.completed_rows, total: event.total_rows })
      },
      controller.signal,
    ).catch(() => {})
    return () => controller.abort()
    // subscriptionKey has no value of its own — it exists only to force a
    // fresh subscription after a resume, since the run's terminal SSE stream
    // from before the resume already ended.
  }, [runId, subscriptionKey])

  useEffect(() => {
    if (stage === 'completed') onCompleted()
  }, [stage, onCompleted])

  const cancel = () => {
    setActionError(null)
    setIsActing(true)
    cancelRun(runId)
      .catch((error: unknown) => setActionError(errorMessage(error)))
      .finally(() => setIsActing(false))
  }

  const resume = () => {
    setActionError(null)
    setIsActing(true)
    resumeRun(runId)
      .then(() => setSubscriptionKey((key) => key + 1))
      .catch((error: unknown) => setActionError(errorMessage(error)))
      .finally(() => setIsActing(false))
  }

  const canCancel = stage === 'pending' || stage === 'running'
  const canResume = stage === 'cancelled' || stage === 'failed'

  return (
    <section>
      <p>
        Run status: <strong>{stage ?? 'pending'}</strong> ({progress.completed}/{progress.total} rows)
      </p>

      {canCancel && (
        <button type="button" disabled={isActing} onClick={cancel}>
          Cancel
        </button>
      )}
      {canResume && (
        <button type="button" disabled={isActing} onClick={resume}>
          Resume
        </button>
      )}
      {actionError && <p role="alert">{actionError}</p>}
    </section>
  )
}
```

Run the tests again:

```powershell
corepack pnpm test -- src/features/run-progress
```

Expected: all 5 pass.

### Step 13: `ExportStep` — write the failing tests (RED)

Create `frontend/src/features/export/ExportStep.test.tsx`:

```typescript
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ExportStep } from './ExportStep'

vi.mock('../../api/runs', () => ({
  exportRun: vi.fn(),
  downloadExport: vi.fn(),
}))

import { downloadExport, exportRun } from '../../api/runs'

const mockExportRun = vi.mocked(exportRun)
const mockDownloadExport = vi.mocked(downloadExport)

describe('ExportStep', () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:mock-url')
    URL.revokeObjectURL = vi.fn()
  })

  it('renders a Download export button and Unsloth import instructions', () => {
    renderWithProviders(<ExportStep runId="run-1" />)

    expect(screen.getByRole('button', { name: /download export/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /unsloth/i })).toBeInTheDocument()
  })

  it('exports then downloads the bundle on click', async () => {
    const user = userEvent.setup()
    mockExportRun.mockResolvedValue({ run_id: 'run-1', export_dir: '/data/x' })
    const blob = new Blob(['zip-bytes'])
    mockDownloadExport.mockResolvedValue(blob)

    renderWithProviders(<ExportStep runId="run-1" />)
    await user.click(screen.getByRole('button', { name: /download export/i }))

    expect(await screen.findByText(/export downloaded/i)).toBeInTheDocument()
    expect(mockExportRun).toHaveBeenCalledWith('run-1')
    expect(mockDownloadExport).toHaveBeenCalledWith('run-1')
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
  })

  it('shows an error message if export creation fails', async () => {
    const user = userEvent.setup()
    mockExportRun.mockRejectedValue(new ApiError(409, "run is 'running', not ready to export"))

    renderWithProviders(<ExportStep runId="run-1" />)
    await user.click(screen.getByRole('button', { name: /download export/i }))

    expect(await screen.findByText("run is 'running', not ready to export")).toBeInTheDocument()
  })
})
```

Run it and confirm it fails:

```powershell
corepack pnpm test -- src/features/export
```

Expected: fails to resolve `./ExportStep`.

### Step 14: `ExportStep` — implement (GREEN)

Create `frontend/src/features/export/ExportStep.tsx`:

```typescript
import { useState } from 'react'
import { downloadExport, exportRun } from '../../api/runs'
import { ApiError } from '../../api/client'

interface ExportStepProps {
  runId: string
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ExportStep({ runId }: ExportStepProps) {
  const [isExporting, setIsExporting] = useState(false)
  const [downloaded, setDownloaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleExport = async () => {
    setError(null)
    setIsExporting(true)
    try {
      await exportRun(runId)
      const blob = await downloadExport(runId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `tuneforge-export-${runId}.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setDownloaded(true)
    } catch (caught: unknown) {
      setError(errorMessage(caught))
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <section>
      <h2>Export dataset</h2>
      <button type="button" disabled={isExporting} onClick={() => void handleExport()}>
        Download export
      </button>
      {downloaded && <p>Export downloaded.</p>}
      {error && <p role="alert">{error}</p>}

      <div>
        <h3>Using this in Unsloth</h3>
        <p>
          Load the exported Parquet/JSONL files with Hugging Face <code>datasets</code> (
          <code>load_dataset(&quot;parquet&quot;, data_files=...)</code> or{' '}
          <code>load_dataset(&quot;json&quot;, data_files=...)</code>) and pass the result straight into Unsloth's
          trainer for this plan's objective (<code>SFTTrainer</code> for prompt-completion/conversation,{' '}
          <code>DPOTrainer</code> for preference pairs) — the exported schema already matches what each expects.
        </p>
      </div>
    </section>
  )
}
```

Run the tests again:

```powershell
corepack pnpm test -- src/features/export
```

Expected: all 3 pass (jsdom prints a harmless `Not implemented: navigation to another Document` warning for the anchor click — that's expected, not a failure).

### Step 15: Wire the three new steps into `App.tsx`

Edit `frontend/src/App.tsx` — replace the whole file:

```typescript
import { useState } from 'react'
import { ProjectSetupStep } from './features/project-setup/ProjectSetupStep'
import { ModelSelectionStep } from './features/model-selection/ModelSelectionStep'
import { GoalWizardStep } from './features/goal-wizard/GoalWizardStep'
import { PlanConfirmationStep } from './features/plan-confirmation/PlanConfirmationStep'
import { ProviderConfigStep } from './features/provider-config/ProviderConfigStep'
import { PreviewStep } from './features/preview/PreviewStep'
import { RunProgressStep } from './features/run-progress/RunProgressStep'
import { ExportStep } from './features/export/ExportStep'
import type { ModelProfileResponse, Project, ProviderProfile, TrainingPlanResponse } from './api/types'

type WizardStep = 'project' | 'model' | 'goal' | 'plan' | 'provider' | 'preview' | 'progress' | 'export'

function App() {
  const [step, setStep] = useState<WizardStep>('project')
  const [project, setProject] = useState<Project | null>(null)
  const [modelProfile, setModelProfile] = useState<ModelProfileResponse | null>(null)
  const [plan, setPlan] = useState<TrainingPlanResponse | null>(null)
  const [provider, setProvider] = useState<ProviderProfile | null>(null)
  const [remoteConsentGranted, setRemoteConsentGranted] = useState(false)
  const [fullRunId, setFullRunId] = useState<string | null>(null)

  return (
    <main>
      <h1>TuneForge</h1>
      <p>Local dataset compiler for Unsloth fine-tuning.</p>

      {step === 'project' && (
        <ProjectSetupStep
          onProjectReady={(readyProject) => {
            setProject(readyProject)
            setStep('model')
          }}
        />
      )}

      {step === 'model' && project && (
        <ModelSelectionStep
          projectId={project.id}
          onProfileReady={(profile) => {
            setModelProfile(profile)
            setStep('goal')
          }}
        />
      )}

      {step === 'goal' && project && modelProfile && (
        <GoalWizardStep
          projectId={project.id}
          modelProfileId={modelProfile.id}
          onPlanRecommended={(recommendedPlan) => {
            setPlan(recommendedPlan)
            setStep('plan')
          }}
        />
      )}

      {step === 'plan' && plan && (
        <PlanConfirmationStep
          plan={plan}
          onApproved={() => {
            setStep('provider')
          }}
        />
      )}

      {step === 'provider' && project && (
        <ProviderConfigStep
          projectId={project.id}
          onProviderReady={(readyProvider, consentGranted) => {
            setProvider(readyProvider)
            setRemoteConsentGranted(consentGranted)
            setStep('preview')
          }}
        />
      )}

      {step === 'preview' && plan && provider && (
        <PreviewStep
          planId={plan.id}
          generatorProfileId={provider.id}
          remoteConsentGranted={remoteConsentGranted}
          onApprovedFull={(fullRun) => {
            setFullRunId(fullRun.id)
            setStep('progress')
          }}
        />
      )}

      {step === 'progress' && fullRunId && (
        <RunProgressStep
          runId={fullRunId}
          onCompleted={() => {
            setStep('export')
          }}
        />
      )}

      {step === 'export' && fullRunId && <ExportStep runId={fullRunId} />}
    </main>
  )
}

export default App
```

This is the point where `ProviderConfigStep`'s `onProviderReady` result finally gets used — `plan_9.md` deliberately left it as a no-op comment since nothing downstream consumed it yet.

### Step 16: Full frontend suite, type-check, and the live run-lifecycle verification

```powershell
cd frontend
corepack pnpm test
corepack pnpm exec tsc -b --noEmit
```

Expected: 43 tests pass across 11 files; `tsc` prints nothing.

Then drive the whole assembled lifecycle by hand against a real backend — this is what actually caught the `model_id` bug described at the top of this document, and it's the only way to catch the next one like it:

1. Start the backend with a scratch `TUNEFORGE_DATA_DIR` (see the note in Development Environment above) and the frontend dev server, same as previous parts.
2. Walk the wizard through to a **local**-scoped provider (simplest — CPT with a local provider never actually calls it, so any placeholder URL works) and click **Generate preview**.
3. **Wait at least 30–40 seconds** before concluding anything is stuck. The status will sit on `pending` while the freshly spawned worker process cold-imports `torch`/`transformers`/`docling` — this is real, expected latency in this app's process-per-run architecture, not a bug. If you want to confirm a run is genuinely progressing rather than hung, query `runs.status` directly in the scratch `tuneforge.db` rather than trusting only the UI on a first pass.
4. Once the preview reaches `completed`, confirm its accepted rows render, click **Approve full run**, and repeat the same wait for the full run.
5. Once the full run reaches `completed`, confirm the UI auto-advances to `ExportStep`, click **Download export**, and confirm the browser actually saves a `.zip` — then unzip it and confirm it contains `manifest.json`, `model-profile.json`, `provenance.jsonl`, `training-plan.json`, and `validation-report.json` (train/eval data files will only be present if any rows were actually accepted — a single tiny test document may legitimately accept zero rows, which is not itself a bug to chase).

### Step 17: Commit

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
git add backend/tuneforge/api/runs.py backend/tuneforge/jobs/runner.py
git add backend/tests/api/test_runs.py backend/tests/jobs/test_runner.py
git add frontend/src/App.tsx frontend/src/api/types.ts frontend/src/api/runs.ts
git add frontend/src/api/runEvents.ts frontend/src/api/runEvents.test.ts
git add frontend/src/features/preview frontend/src/features/run-progress frontend/src/features/export
git commit -m "feat: add preview, full-run progress, and export to the guided workflow"
```

---

## When you're done

Do not start anything from `plan_11.md`'s list (structured column mapping, visual styling). Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` from `backend/` (expect 237) and `corepack pnpm test` + `corepack pnpm exec tsc -b --noEmit` from `frontend/` (expect 43).
2. Output of `git log --oneline` — should show one new commit.
3. Confirmation that Step 16's live run-lifecycle walkthrough actually happened by hand — specifically, how long the preview run actually took to leave `pending` on your machine, and whether the exported zip's contents matched what's listed above.
4. Anything else you had to deviate from in this document, and why.
5. If you find a correctness issue anywhere in the code exactly as given here — not a style preference, an actual bug — stop and describe it rather than silently changing behavior.
