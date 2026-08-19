# TuneForge Implementation Plan — Part 8 (React UI: setup → plan confirmation)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec. Tasks 1–12 and the Part 7 API-composition pass are already implemented, committed, and pushed to `main`: every endpoint this part calls (`/api/session`, `/api/projects`, `/api/projects/{id}/sources`, `/api/models/analyze`, `/api/plans/recommend`, `/api/plans/{id}/approve`) is real, mounted, and bearer-auth-protected.
>
> **Task 13 (React UI) is bigger than any backend part so far — nine distinct screens plus accessibility work — so it's split across two documents.** This part covers the first half of the guided workflow: the API client foundation, project creation + source upload, model selection + evidence display, the training-goal wizard, and the plan-recommendation confirmation modal. `plan_9.md` covers what's left: provider configuration + remote-consent dialog, structured column mapping, the 20-row preview, full-run progress/cancel/resume, and export download. Do not implement anything from that list as part of this document.
>
> **Every piece of code below was actually written, run, and verified before being put in this document — including two real bugs this process found and fixed, described in Steps 1 and 2.** This is not a smaller-scope guarantee than earlier parts; it's the same rigor, just over a UI stack instead of a Python one: `vitest` unit/component tests for every screen, `tsc -b --noEmit` for the whole project, and a live click-through of the assembled flow in a real browser against a real running backend (not just mocked fetches) — because a mocked-fetch test cannot catch a browser-vs-proxy header mismatch, and one very nearly shipped silently in Step 2.
>
> **A real, load-bearing gap was found and closed before any screen could be built at all: there was no way for the browser to ever learn the bearer session token.** `require_session` checks a request's `Authorization` header against `app.state.session_token`, a value generated fresh in memory on every process start — and nothing in the whole codebase ever exposed that value to a client. Every screen in this part depends on Step 1 below. If you're auditing this document against the real repo and don't see a `GET /api/session` endpoint yet, that confirms the gap was real and still open.
>
> **No visual styling was written in this part.** Everything below is semantic, unstyled markup — real `<label htmlFor>`/`<input id>` pairing, `role="alert"` on error messages, native `<button>`/`<select>`/`<dl>` elements — which is a genuine (if partial) down payment on `PLAN.md`'s "keyboard navigation, focus management, error summaries, and WCAG AA contrast" requirement, but contrast, spacing, layout, and focus-ring styling are all still open. Do not treat this part as closing that checklist item.

**Goal (this part):** Give TuneForge's FastAPI backend a real browser front end for the first half of the guided workflow: bootstrap a session, create a project and upload a source document, analyze a target model and show its evidence, collect a training goal, get a recommended plan, and approve it.

**Architecture:** One `WizardStep` state machine in `App.tsx` (`'project' | 'model' | 'goal' | 'plan'`) drives which feature component renders; each step is a self-contained component under `frontend/src/features/<step>/` that receives only the IDs/values it needs as props and reports completion via an `onXReady`-style callback — no routing library, no global state manager. `frontend/src/api/` is a thin, fully-typed HTTP layer: `session.ts` bootstraps and caches the bearer token in memory (never `localStorage`, matching the project's "session token held in memory only" constraint), `client.ts` is a single `apiFetch` wrapper every request goes through, and one file per backend resource (`projects.ts`, `models.ts`, `plans.ts`) exposes typed functions matching the real JSON shapes read directly from the backend's Pydantic models — not from `PLAN.md`'s aspirational schema, which is occasionally stale relative to the actual code (this project's own `CLAUDE.md` says to trust the code over the docs here).

**Deliberately out of scope (this part):** provider configuration/remote-consent, structured column mapping, 20-row preview, full-run progress/cancel/resume, export download, and any visual styling. All of that is `plan_9.md` or later. One direct consequence worth calling out: picking "Preference alignment" in the goal wizard maps to the `dpo` objective, which the backend's `recommend_plan` rejects with a 409 (`DistinctJudgeRequiredError`) unless a `generator_profile_id` and a distinct `judge_profile_id` are supplied — and this part has no UI to create those yet. The wizard surfaces that 409 with an explicit "finish provider setup, then try again" hint rather than pretending the goal works end-to-end already.

## Global Constraints

Repeated from Parts 1–7, still binding:

- Windows-first, Python 3.12/`uv` on the backend, `pnpm` on the frontend — no npm/yarn.
- Bind only to `127.0.0.1`. Bearer session token, memory-only, never `localStorage`/cookies.
- Every mutating request goes through the existing `require_session` dependency chain — this part adds exactly one new *unauthenticated* endpoint (`GET /api/session`), and Step 1 explains in detail why that's safe rather than a hole in the auth model.
- No API keys or secrets touched in this part at all (that's provider configuration, `plan_9.md`).

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

If plain `pnpm` isn't on `PATH` in your shell but Node is, `corepack pnpm <args>` works identically — that's how every command in this document was actually run and verified.

## Repository State

Same repo, branch `main`, already up to date with `origin/main` (Part 7's API wiring plus a path-traversal fix are already pushed). Commit locally as instructed at the end. **Do not run `git push`.**

## File Structure (this part)

```
backend/
  tests/
    test_runtime_security.py    (modified — adds 3 tests for the new /api/session endpoint)
  tuneforge/
    main.py                     (modified — adds GET /api/session)

frontend/
  package.json                  (modified — adds @tanstack/react-query, @testing-library/user-event)
  vite.config.ts                (modified — adds the dev-server /api proxy, with an Origin-header fix)
  src/
    main.tsx                    (modified — wraps App in QueryClientProvider)
    App.tsx                     (modified — becomes the wizard-step container)
    App.test.tsx                (modified — renders through the new test helper)
    test-utils.tsx              (new — renderWithProviders test helper)
    api/
      types.ts                  (new)
      session.ts                (new)
      client.ts                 (new)
      client.test.ts            (new)
      projects.ts                (new)
      models.ts                  (new)
      plans.ts                   (new)
    features/
      project-setup/
        ProjectSetupStep.tsx        (new)
        ProjectSetupStep.test.tsx   (new)
      model-selection/
        ModelSelectionStep.tsx        (new)
        ModelSelectionStep.test.tsx   (new)
      goal-wizard/
        GoalWizardStep.tsx        (new)
        GoalWizardStep.test.tsx   (new)
      plan-confirmation/
        PlanConfirmationStep.tsx        (new)
        PlanConfirmationStep.test.tsx   (new)
```

---

### Step 1: Session bootstrap endpoint — write the failing tests (RED)

This is the piece nothing else in this part works without. Add to `backend/tests/test_runtime_security.py`, directly above `test_version_reports_configured_version`:

```python
def test_session_bootstrap_returns_token_without_auth_header():
    app, client = make_client()
    resp = client.get("/api/session")
    assert resp.status_code == 200
    assert resp.json() == {"token": app.state.session_token}


def test_session_bootstrap_rejects_mismatched_origin():
    _, client = make_client()
    resp = client.get("/api/session", headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 403


def test_session_bootstrap_allows_matching_origin():
    app, client = make_client()
    origin = f"http://127.0.0.1:{app.state.settings.port}"
    resp = client.get("/api/session", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.json() == {"token": app.state.session_token}
```

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/test_runtime_security.py -k session_bootstrap -q
```

Expected: 2 of the 3 fail with `404` (the origin-mismatch one already passes — `enforce_origin` runs before routing, so it 403s a nonexistent route too).

### Step 2: Session bootstrap endpoint — implement (GREEN)

Edit `backend/tuneforge/main.py`. Add this directly after the existing `/api/version` route, before `/api/echo-session`:

```python
    @app.get("/api/session")
    async def session_bootstrap():
        """Let the SPA learn the process-generated session token.

        Unauthenticated by design — there is no other way for the browser to
        ever obtain the token before making its first authenticated request.
        Safe because the enforce_origin middleware above already rejects any
        request whose Origin doesn't match this app's own origin, and the
        app only ever binds to 127.0.0.1: only this machine's browser, on
        this exact origin, can reach it.
        """
        return {"token": app.state.session_token}
```

Run the tests again:

```powershell
uv run pytest tests/test_runtime_security.py -q
```

Expected: all pass (13 tests in this file).

**Why this specific design, not a login form or a URL-embedded token:** this is a single-user local desktop app whose entire security perimeter is "bind to 127.0.0.1" — anything else already running on this machine is implicitly trusted (that's the whole reason it's local-only rather than networked). The remaining real threat is a malicious webpage open in another tab trying to fetch this token cross-origin — and `enforce_origin`, already sitting in front of every route including this new one, already defeats that: a request from `https://evil.example.com` carries `Origin: https://evil.example.com`, which doesn't match, so it 403s before it ever reaches the handler. This endpoint reuses an existing security control instead of inventing new infrastructure.

### Step 3: Dev-server proxy — configure it, then prove it actually works

The production app serves the built frontend from FastAPI's own static mount, so browser and backend share one origin and this step doesn't apply there. In development, `pnpm dev` runs Vite on its own port with hot-reload, so `/api/*` calls need to reach the real backend on `127.0.0.1:8420`.

Edit `frontend/vite.config.ts`:

```typescript
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// The backend's enforce_origin middleware rejects any request whose Origin
// header doesn't match its own http://127.0.0.1:<port> exactly. changeOrigin
// only rewrites the outgoing Host header, not Origin — the browser's real
// Origin (http://localhost:<vite-port>) still reaches the backend unchanged
// and gets 403'd on every state-changing request. Force it here instead.
const BACKEND_ORIGIN = 'http://127.0.0.1:8420'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('origin', BACKEND_ORIGIN)
          })
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
  },
})
```

**Do not skip the `configure`/`proxyReq` block or assume `changeOrigin: true` alone is enough — it isn't, and this is exactly the bug this step's own verification caught.** `changeOrigin` only rewrites the outgoing `Host` header; it does not touch `Origin`. A `curl` check with no `Origin` header set will falsely appear to work (curl doesn't send one by default), which is precisely how this almost slipped through here — the fix was only found by driving a real browser through the real dev server and watching `POST /api/projects` come back `403` while `GET /api/session` came back `200`, because modern browsers attach `Origin` to state-changing requests (POST/PUT/DELETE) but often not to plain GETs.

**Verify this for real, not just by reading it** — start both servers and drive a real POST through the proxy with a real `Origin` header:

```powershell
# terminal 1
cd backend
$env:TUNEFORGE_DATA_DIR = "$env:TEMP\tf-devcheck"
uv run python -m tuneforge.main

# terminal 2
cd frontend
corepack pnpm dev --port 5173
```

```powershell
# terminal 3 — before the fix this returns 403 ("origin not allowed"); after, 401 ("invalid session"),
# proving the Origin header now reaches the backend correctly rewritten (a missing/wrong bearer
# token is expected here — this check is only about the origin check passing)
curl.exe -s -X POST -H "Origin: http://localhost:5173" -H "Content-Type: application/json" `
  -d '{\"name\":\"curl-test\"}' http://localhost:5173/api/projects
```

Expected: `{"detail":"invalid session"}` with a `401`, not `{"detail":"origin not allowed"}` with a `403`.

### Step 4: Install frontend dependencies

```powershell
cd frontend
corepack pnpm add @tanstack/react-query
corepack pnpm add -D @testing-library/user-event
```

`@tanstack/react-query` is named explicitly in `PLAN.md`'s tech stack and wasn't installed yet. `@testing-library/user-event` is needed for realistic form-interaction tests in every step below — `fireEvent` alone doesn't fire the same event sequence a real user does for typing/selecting/uploading.

### Step 5: API types — matching the real backend, not `PLAN.md`'s draft

Create `frontend/src/api/types.ts`. Every field here was cross-checked directly against `backend/tuneforge/models/analyzer.py` (`ModelProfile`), `backend/tuneforge/models/evidence.py` (`Evidence`), `backend/tuneforge/planning/intents.py` (`TrainingIntent`), and `backend/tuneforge/planning/schemas.py` (`TrainingPlan`) — not against `PLAN.md`'s contract block, which is a draft and not always current:

```typescript
export interface Evidence {
  field: string
  value: string
  source: string
  detail: string
}

export type ModelSource = 'huggingface' | 'local'

export interface ModelProfile {
  source: ModelSource
  model_id: string
  architecture: string
  model_type: string
  is_causal_lm: boolean
  is_chat_model: boolean
  chat_template_found: boolean
  context_length: number
  modalities: string[]
  evidence: Evidence[]
  confidence: number
}

export interface ModelProfileResponse extends ModelProfile {
  id: string
}

export interface Project {
  id: string
  name: string
  created_at: string
}

export interface Source {
  id: string
  filename: string
  source_hash: string
}

export type TrainingGoal =
  | 'domain_adaptation'
  | 'single_turn_instruction'
  | 'multi_turn_conversation'
  | 'preference_alignment'

export interface TrainingIntentInput {
  goal: TrainingGoal
  desired_behavior: string
  language: string
  target_rows: number
  generator_profile_id?: string
  judge_profile_id?: string
  objective_override?: TrainingObjective
}

export type TrainingObjective = 'cpt' | 'sft_prompt_completion' | 'sft_conversation' | 'dpo'

export interface TrainingPlan {
  objective: TrainingObjective
  canonical_schema: string
  target_rows: number
  examples_per_chunk: number
  generator_profile_id: string | null
  judge_profile_id: string | null
  required_validators: string[]
  evidence: Evidence[]
  confidence: number
  plan_hash: string
}

export interface TrainingPlanResponse extends TrainingPlan {
  id: string
}

export interface PlanApproval {
  id: string
  approved_at: string
}
```

No runtime schema validation library (no Zod) — deliberate. The frontend and backend ship together from the same repo and the same commit; there is no untrusted third-party boundary between them the way there would be calling an external API. Add one if that stops being true (e.g. if the backend becomes independently versioned).

### Step 6: Session token bootstrap

Create `frontend/src/api/session.ts`:

```typescript
// Holds the process-generated bearer token in memory only — never localStorage,
// never a cookie. A page reload always re-fetches from the server, which is
// exactly the "held in memory only, never persisted" contract this app requires.
let cachedToken: Promise<string> | null = null

export function getSessionToken(): Promise<string> {
  if (!cachedToken) {
    cachedToken = fetch('/api/session')
      .then((response) => {
        if (!response.ok) {
          throw new Error(`session bootstrap failed: ${response.status}`)
        }
        return response.json() as Promise<{ token: string }>
      })
      .then(({ token }) => token)
      .catch((error: unknown) => {
        cachedToken = null
        throw error
      })
  }
  return cachedToken
}

export function resetSessionTokenForTests(): void {
  cachedToken = null
}
```

### Step 7: Typed fetch wrapper — write the tests (RED), then implement (GREEN)

Create `frontend/src/api/client.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch, ApiError } from './client'
import { resetSessionTokenForTests } from './session'

describe('apiFetch', () => {
  beforeEach(() => {
    resetSessionTokenForTests()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function mockFetchSequence(...responses: Response[]): ReturnType<typeof vi.fn> {
    const fetchMock = vi.fn()
    for (const response of responses) {
      fetchMock.mockResolvedValueOnce(response)
    }
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('fetches the session token once, then attaches it as a bearer header', async () => {
    const fetchMock = mockFetchSequence(
      new Response(JSON.stringify({ token: 'abc123' }), { status: 200 }),
      new Response(JSON.stringify({ id: '1', name: 'proj' }), { status: 201 }),
    )

    const result = await apiFetch<{ id: string; name: string }>('/api/projects', {
      method: 'POST',
      json: { name: 'proj' },
    })

    expect(result).toEqual({ id: '1', name: 'proj' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [, projectCall] = fetchMock.mock.calls
    const [, requestInit] = projectCall as [string, RequestInit]
    const headers = requestInit.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer abc123')
    expect(headers['Content-Type']).toBe('application/json')
  })

  it('reuses the cached session token across multiple calls', async () => {
    const fetchMock = mockFetchSequence(
      new Response(JSON.stringify({ token: 'abc123' }), { status: 200 }),
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )

    await apiFetch('/api/health')
    await apiFetch('/api/health')

    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('throws ApiError with the backend detail message on non-2xx responses', async () => {
    mockFetchSequence(
      new Response(JSON.stringify({ token: 'abc123' }), { status: 200 }),
      new Response(JSON.stringify({ detail: "'name' is required" }), { status: 422 }),
    )

    await expect(apiFetch('/api/projects', { method: 'POST', json: {} })).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      message: "'name' is required",
    })
  })

  it('is an instance of ApiError so callers can narrow with instanceof', async () => {
    mockFetchSequence(
      new Response(JSON.stringify({ token: 'abc123' }), { status: 200 }),
      new Response(JSON.stringify({ detail: 'not found' }), { status: 404 }),
    )

    try {
      await apiFetch('/api/projects/missing')
      expect.unreachable('expected apiFetch to throw')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
    }
  })
})
```

Run it and confirm it fails on the missing module:

```powershell
corepack pnpm test -- src/api/client.test.ts
```

Expected: fails to resolve `./client`.

Create `frontend/src/api/client.ts`:

```typescript
import { getSessionToken } from './session'

export class ApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE'
  json?: unknown
  formData?: FormData
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = await getSessionToken()
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  }

  let body: BodyInit | undefined
  if (options.formData) {
    body = options.formData
  } else if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.json)
  }

  const response = await fetch(path, { method: options.method ?? 'GET', headers, body })

  if (!response.ok) {
    throw new ApiError(response.status, await extractErrorDetail(response))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

async function extractErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail
    }
    return JSON.stringify(body)
  } catch {
    return response.statusText
  }
}
```

Run the tests again:

```powershell
corepack pnpm test -- src/api/client.test.ts
```

Expected: all 4 pass.

### Step 8: Thin per-resource API functions

These have no dedicated tests of their own — they're exercised through each feature's component tests in the steps below (mocking these modules directly), matching the same "thin translation layer" principle Part 7 used for the backend routers.

Create `frontend/src/api/projects.ts`:

```typescript
import { apiFetch } from './client'
import type { Project, Source } from './types'

export function createProject(name: string): Promise<Project> {
  return apiFetch<Project>('/api/projects', { method: 'POST', json: { name } })
}

export function uploadSource(projectId: string, file: File): Promise<Source> {
  const formData = new FormData()
  formData.append('file', file)
  return apiFetch<Source>(`/api/projects/${projectId}/sources`, { method: 'POST', formData })
}
```

Create `frontend/src/api/models.ts`:

```typescript
import { apiFetch } from './client'
import type { ModelProfileResponse, ModelSource } from './types'

export function analyzeModel(
  projectId: string,
  modelId: string,
  source: ModelSource = 'huggingface',
): Promise<ModelProfileResponse> {
  return apiFetch<ModelProfileResponse>('/api/models/analyze', {
    method: 'POST',
    json: { project_id: projectId, model_id: modelId, source },
  })
}
```

Create `frontend/src/api/plans.ts`:

```typescript
import { apiFetch } from './client'
import type { PlanApproval, TrainingIntentInput, TrainingPlanResponse } from './types'

export function recommendPlan(
  projectId: string,
  modelProfileId: string,
  intent: TrainingIntentInput,
): Promise<TrainingPlanResponse> {
  return apiFetch<TrainingPlanResponse>('/api/plans/recommend', {
    method: 'POST',
    json: {
      project_id: projectId,
      model_profile_id: modelProfileId,
      goal: intent.goal,
      desired_behavior: intent.desired_behavior,
      language: intent.language,
      target_rows: intent.target_rows,
      generator_profile_id: intent.generator_profile_id,
      judge_profile_id: intent.judge_profile_id,
      objective_override: intent.objective_override,
    },
  })
}

export function approvePlan(planId: string): Promise<PlanApproval> {
  return apiFetch<PlanApproval>(`/api/plans/${planId}/approve`, { method: 'POST' })
}
```

### Step 9: Query client wiring and the render test helper

Edit `frontend/src/main.tsx`:

```typescript
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'

const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
```

Create `frontend/src/test-utils.tsx` — every component test in this part renders through this, since every step's component uses `useMutation`:

```typescript
import type { ReactElement } from 'react'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

export function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}
```

### Step 10: Project setup + upload — write the failing tests (RED)

Create `frontend/src/features/project-setup/ProjectSetupStep.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ProjectSetupStep } from './ProjectSetupStep'

vi.mock('../../api/projects', () => ({
  createProject: vi.fn(),
  uploadSource: vi.fn(),
}))

import { createProject, uploadSource } from '../../api/projects'

const mockCreateProject = vi.mocked(createProject)
const mockUploadSource = vi.mocked(uploadSource)

describe('ProjectSetupStep', () => {
  it('shows only the project name form initially', () => {
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    expect(screen.getByLabelText(/project name/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/upload/i)).not.toBeInTheDocument()
  })

  it('creates the project and reveals the upload form', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/project name/i), 'HR Policy Bot')
    await user.click(screen.getByRole('button', { name: /create project/i }))

    expect(await screen.findByLabelText(/upload/i)).toBeInTheDocument()
    expect(mockCreateProject).toHaveBeenCalledWith('HR Policy Bot')
  })

  it('shows a validation error when project creation fails', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockRejectedValue(new ApiError(422, "'name' is required"))
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /create project/i }))

    expect(await screen.findByText("'name' is required")).toBeInTheDocument()
  })

  it('uploads a source and lists it, enabling Continue', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'policy.md', source_hash: 'abc' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/project name/i), 'HR Policy Bot')
    await user.click(screen.getByRole('button', { name: /create project/i }))
    const fileInput = await screen.findByLabelText(/upload/i)
    const file = new File(['# Policy'], 'policy.md', { type: 'text/markdown' })
    await user.upload(fileInput, file)

    expect(await screen.findByText('policy.md')).toBeInTheDocument()
    expect(mockUploadSource).toHaveBeenCalledWith('proj-1', file)
    expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled()
  })

  it('disables Continue until at least one source is uploaded', async () => {
    const user = userEvent.setup()
    mockCreateProject.mockResolvedValue({ id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' })
    renderWithProviders(<ProjectSetupStep onProjectReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/project name/i), 'HR Policy Bot')
    await user.click(screen.getByRole('button', { name: /create project/i }))

    expect(await screen.findByRole('button', { name: /continue/i })).toBeDisabled()
  })

  it('calls onProjectReady with the created project when Continue is clicked', async () => {
    const user = userEvent.setup()
    const project = { id: 'proj-1', name: 'HR Policy Bot', created_at: '2026-08-15T00:00:00Z' }
    mockCreateProject.mockResolvedValue(project)
    mockUploadSource.mockResolvedValue({ id: 'src-1', filename: 'policy.md', source_hash: 'abc' })
    const onProjectReady = vi.fn()
    renderWithProviders(<ProjectSetupStep onProjectReady={onProjectReady} />)

    await user.type(screen.getByLabelText(/project name/i), 'HR Policy Bot')
    await user.click(screen.getByRole('button', { name: /create project/i }))
    const fileInput = await screen.findByLabelText(/upload/i)
    await user.upload(fileInput, new File(['# Policy'], 'policy.md', { type: 'text/markdown' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: /continue/i }))

    expect(onProjectReady).toHaveBeenCalledWith(project)
  })
})
```

Run it and confirm it fails on the missing module:

```powershell
corepack pnpm test -- src/features/project-setup
```

Expected: fails to resolve `./ProjectSetupStep`.

### Step 11: Project setup + upload — implement (GREEN)

Create `frontend/src/features/project-setup/ProjectSetupStep.tsx`:

```typescript
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { createProject, uploadSource } from '../../api/projects'
import { ApiError } from '../../api/client'
import type { Project, Source } from '../../api/types'

interface ProjectSetupStepProps {
  onProjectReady: (project: Project) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ProjectSetupStep({ onProjectReady }: ProjectSetupStepProps) {
  const [name, setName] = useState('')
  const [project, setProject] = useState<Project | null>(null)
  const [sources, setSources] = useState<Source[]>([])

  const createProjectMutation = useMutation({
    mutationFn: () => createProject(name),
    onSuccess: setProject,
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadSource(project!.id, file),
    onSuccess: (source) => setSources((previous) => [...previous, source]),
  })

  if (!project) {
    return (
      <form
        onSubmit={(event) => {
          event.preventDefault()
          createProjectMutation.mutate()
        }}
      >
        <label htmlFor="project-name">Project name</label>
        <input id="project-name" value={name} onChange={(event) => setName(event.target.value)} />
        <button type="submit" disabled={createProjectMutation.isPending}>
          Create project
        </button>
        {createProjectMutation.isError && <p role="alert">{errorMessage(createProjectMutation.error)}</p>}
      </form>
    )
  }

  return (
    <section>
      <h2>{project.name}</h2>
      <label htmlFor="source-upload">Upload a source document</label>
      <input
        id="source-upload"
        type="file"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) uploadMutation.mutate(file)
        }}
      />
      {uploadMutation.isError && <p role="alert">{errorMessage(uploadMutation.error)}</p>}
      <ul>
        {sources.map((source) => (
          <li key={source.id}>{source.filename}</li>
        ))}
      </ul>
      <button type="button" disabled={sources.length === 0} onClick={() => onProjectReady(project)}>
        Continue
      </button>
    </section>
  )
}
```

Run the tests again:

```powershell
corepack pnpm test -- src/features/project-setup
```

Expected: all 6 pass.

### Step 12: Model selection + evidence — write the failing tests (RED)

Create `frontend/src/features/model-selection/ModelSelectionStep.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ModelSelectionStep } from './ModelSelectionStep'

vi.mock('../../api/models', () => ({
  analyzeModel: vi.fn(),
}))

import { analyzeModel } from '../../api/models'

const mockAnalyzeModel = vi.mocked(analyzeModel)

const profile = {
  id: 'profile-1',
  source: 'huggingface' as const,
  model_id: 'Qwen/Qwen2.5-1.5B-Instruct',
  architecture: 'Qwen2ForCausalLM',
  model_type: 'qwen2',
  is_causal_lm: true,
  is_chat_model: true,
  chat_template_found: true,
  context_length: 32768,
  modalities: ['text'],
  evidence: [
    { field: 'architecture', value: 'Qwen2ForCausalLM', source: 'config.json', detail: 'architectures[0]' },
  ],
  confidence: 0.95,
}

describe('ModelSelectionStep', () => {
  it('renders a model id field and an Analyze button, no evidence yet', () => {
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={vi.fn()} />)

    expect(screen.getByLabelText(/model/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /analyze/i })).toBeInTheDocument()
    expect(screen.queryByText(/architecture/i)).not.toBeInTheDocument()
  })

  it('analyzes the model and displays its evidence', async () => {
    const user = userEvent.setup()
    mockAnalyzeModel.mockResolvedValue(profile)
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/model/i), 'Qwen/Qwen2.5-1.5B-Instruct')
    await user.click(screen.getByRole('button', { name: /analyze/i }))

    expect(await screen.findByText('Qwen2ForCausalLM')).toBeInTheDocument()
    expect(screen.getByText(/chat template found/i)).toBeInTheDocument()
    expect(screen.getByText('config.json')).toBeInTheDocument()
    expect(mockAnalyzeModel).toHaveBeenCalledWith('proj-1', 'Qwen/Qwen2.5-1.5B-Instruct', 'huggingface')
  })

  it('shows the backend rejection message for an incompatible model', async () => {
    const user = userEvent.setup()
    mockAnalyzeModel.mockRejectedValue(new ApiError(422, 'not a text decoder-only causal language model'))
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/model/i), 'stabilityai/stable-diffusion-2')
    await user.click(screen.getByRole('button', { name: /analyze/i }))

    expect(await screen.findByText('not a text decoder-only causal language model')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /continue/i })).not.toBeInTheDocument()
  })

  it('calls onProfileReady with the analyzed profile when Continue is clicked', async () => {
    const user = userEvent.setup()
    mockAnalyzeModel.mockResolvedValue(profile)
    const onProfileReady = vi.fn()
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={onProfileReady} />)

    await user.type(screen.getByLabelText(/model/i), 'Qwen/Qwen2.5-1.5B-Instruct')
    await user.click(screen.getByRole('button', { name: /analyze/i }))
    await user.click(await screen.findByRole('button', { name: /continue/i }))

    expect(onProfileReady).toHaveBeenCalledWith(profile)
  })

  it('lets the user switch source to local before analyzing', async () => {
    const user = userEvent.setup()
    mockAnalyzeModel.mockResolvedValue({ ...profile, source: 'local' })
    renderWithProviders(<ModelSelectionStep projectId="proj-1" onProfileReady={vi.fn()} />)

    await user.selectOptions(screen.getByLabelText(/source/i), 'local')
    await user.type(screen.getByLabelText(/model/i), 'C:\\models\\my-model')
    await user.click(screen.getByRole('button', { name: /analyze/i }))

    expect(mockAnalyzeModel).toHaveBeenCalledWith('proj-1', 'C:\\models\\my-model', 'local')
  })
})
```

Run it and confirm it fails on the missing module:

```powershell
corepack pnpm test -- src/features/model-selection
```

Expected: fails to resolve `./ModelSelectionStep`.

### Step 13: Model selection + evidence — implement (GREEN)

Create `frontend/src/features/model-selection/ModelSelectionStep.tsx`:

```typescript
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { analyzeModel } from '../../api/models'
import { ApiError } from '../../api/client'
import type { ModelProfileResponse, ModelSource } from '../../api/types'

interface ModelSelectionStepProps {
  projectId: string
  onProfileReady: (profile: ModelProfileResponse) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ModelSelectionStep({ projectId, onProfileReady }: ModelSelectionStepProps) {
  const [modelId, setModelId] = useState('')
  const [source, setSource] = useState<ModelSource>('huggingface')

  const analyzeMutation = useMutation({
    mutationFn: () => analyzeModel(projectId, modelId, source),
  })

  const profile = analyzeMutation.data

  return (
    <section>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          analyzeMutation.mutate()
        }}
      >
        <label htmlFor="model-source">Source</label>
        <select
          id="model-source"
          value={source}
          onChange={(event) => setSource(event.target.value as ModelSource)}
        >
          <option value="huggingface">Hugging Face</option>
          <option value="local">Local directory</option>
        </select>

        <label htmlFor="model-id">Model</label>
        <input id="model-id" value={modelId} onChange={(event) => setModelId(event.target.value)} />

        <button type="submit" disabled={analyzeMutation.isPending}>
          Analyze
        </button>
      </form>

      {analyzeMutation.isError && <p role="alert">{errorMessage(analyzeMutation.error)}</p>}

      {profile && (
        <dl>
          <dt>Architecture</dt>
          <dd>{profile.architecture}</dd>
          <dt>Model type</dt>
          <dd>{profile.model_type}</dd>
          <dt>Causal LM</dt>
          <dd>{profile.is_causal_lm ? 'Yes' : 'No'}</dd>
          <dt>Chat model</dt>
          <dd>{profile.is_chat_model ? 'Yes' : 'No'}</dd>
          <dt>Chat template found</dt>
          <dd>{profile.chat_template_found ? 'Yes' : 'No'}</dd>
          <dt>Context length</dt>
          <dd>{profile.context_length}</dd>
          <dt>Confidence</dt>
          <dd>{Math.round(profile.confidence * 100)}%</dd>
          <dt>Evidence</dt>
          <dd>
            <ul>
              {profile.evidence.map((item) => (
                <li key={`${item.field}-${item.source}`}>
                  <strong>{item.field}</strong>: {item.value} (<code>{item.source}</code> — {item.detail})
                </li>
              ))}
            </ul>
          </dd>
        </dl>
      )}

      {profile && (
        <button type="button" onClick={() => onProfileReady(profile)}>
          Continue
        </button>
      )}
    </section>
  )
}
```

Note the `<code>{item.source}</code>` wrapper around the evidence source — without a real element boundary there, `screen.getByText('config.json')` in the test above can't match it, since Testing Library matches a text node against the nearest whole element's text content and `"config.json"` would otherwise just be one inline text fragment among several inside the `<li>`. This was caught by actually running the test, not decided upfront.

Run the tests again:

```powershell
corepack pnpm test -- src/features/model-selection
```

Expected: all 5 pass.

### Step 14: Training-goal wizard — write the failing tests (RED)

Create `frontend/src/features/goal-wizard/GoalWizardStep.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { GoalWizardStep } from './GoalWizardStep'

vi.mock('../../api/plans', () => ({
  recommendPlan: vi.fn(),
  approvePlan: vi.fn(),
}))

import { recommendPlan } from '../../api/plans'

const mockRecommendPlan = vi.mocked(recommendPlan)

const plan = {
  id: 'plan-1',
  objective: 'sft_conversation' as const,
  canonical_schema: 'SFTConversationRecord',
  target_rows: 500,
  examples_per_chunk: 2,
  generator_profile_id: null,
  judge_profile_id: null,
  required_validators: ['structural', 'dedup'],
  evidence: [],
  confidence: 0.9,
  plan_hash: 'hash123',
}

describe('GoalWizardStep', () => {
  it('renders the goal, desired behavior, language, and target rows fields', () => {
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    expect(screen.getByLabelText(/training goal/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/desired behavior/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/language/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/target rows/i)).toBeInTheDocument()
  })

  it('submits the form and reports the recommended plan', async () => {
    const user = userEvent.setup()
    mockRecommendPlan.mockResolvedValue(plan)
    const onPlanRecommended = vi.fn()
    renderWithProviders(
      <GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={onPlanRecommended} />,
    )

    await user.selectOptions(screen.getByLabelText(/training goal/i), 'multi_turn_conversation')
    await user.type(screen.getByLabelText(/desired behavior/i), 'Answer HR policy questions')
    await user.clear(screen.getByLabelText(/target rows/i))
    await user.type(screen.getByLabelText(/target rows/i), '500')
    await user.click(screen.getByRole('button', { name: /get recommendation/i }))

    expect(mockRecommendPlan).toHaveBeenCalledWith('proj-1', 'profile-1', {
      goal: 'multi_turn_conversation',
      desired_behavior: 'Answer HR policy questions',
      language: 'en',
      target_rows: 500,
    })
    expect(onPlanRecommended).toHaveBeenCalledWith(plan)
  })

  it('surfaces the chat-template-required rejection distinctly', async () => {
    const user = userEvent.setup()
    mockRecommendPlan.mockRejectedValue(
      new ApiError(409, "org/base-model has no chat template, which 'multi_turn_conversation' requires"),
    )
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    await user.type(screen.getByLabelText(/desired behavior/i), 'x')
    await user.click(screen.getByRole('button', { name: /get recommendation/i }))

    expect(await screen.findByText(/has no chat template/i)).toBeInTheDocument()
  })

  it('surfaces the distinct-judge-required rejection for preference alignment', async () => {
    const user = userEvent.setup()
    mockRecommendPlan.mockRejectedValue(new ApiError(409, 'dpo requires a generator_profile_id'))
    renderWithProviders(<GoalWizardStep projectId="proj-1" modelProfileId="profile-1" onPlanRecommended={vi.fn()} />)

    await user.selectOptions(screen.getByLabelText(/training goal/i), 'preference_alignment')
    await user.type(screen.getByLabelText(/desired behavior/i), 'x')
    await user.click(screen.getByRole('button', { name: /get recommendation/i }))

    expect(await screen.findByText(/requires a generator_profile_id/i)).toBeInTheDocument()
    expect(screen.getByText(/provider setup/i)).toBeInTheDocument()
  })
})
```

Run it and confirm it fails on the missing module:

```powershell
corepack pnpm test -- src/features/goal-wizard
```

Expected: fails to resolve `./GoalWizardStep`.

### Step 15: Training-goal wizard — implement (GREEN)

Create `frontend/src/features/goal-wizard/GoalWizardStep.tsx`:

```typescript
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { recommendPlan } from '../../api/plans'
import { ApiError } from '../../api/client'
import type { TrainingGoal, TrainingPlanResponse } from '../../api/types'

interface GoalWizardStepProps {
  projectId: string
  modelProfileId: string
  onPlanRecommended: (plan: TrainingPlanResponse) => void
}

function errorDisplay(error: unknown): { message: string; needsProviderSetup: boolean } {
  if (error instanceof ApiError) {
    return { message: error.message, needsProviderSetup: error.status === 409 && /profile_id/.test(error.message) }
  }
  return { message: 'Something went wrong. Try again.', needsProviderSetup: false }
}

export function GoalWizardStep({ projectId, modelProfileId, onPlanRecommended }: GoalWizardStepProps) {
  const [goal, setGoal] = useState<TrainingGoal>('domain_adaptation')
  const [desiredBehavior, setDesiredBehavior] = useState('')
  const [language, setLanguage] = useState('en')
  const [targetRows, setTargetRows] = useState(200)

  const recommendMutation = useMutation({
    mutationFn: () =>
      recommendPlan(projectId, modelProfileId, {
        goal,
        desired_behavior: desiredBehavior,
        language,
        target_rows: targetRows,
      }),
    onSuccess: (plan) => onPlanRecommended(plan),
  })

  const error = recommendMutation.isError ? errorDisplay(recommendMutation.error) : null

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        recommendMutation.mutate()
      }}
    >
      <label htmlFor="goal">Training goal</label>
      <select id="goal" value={goal} onChange={(event) => setGoal(event.target.value as TrainingGoal)}>
        <option value="domain_adaptation">Domain adaptation</option>
        <option value="single_turn_instruction">Single-turn instruction</option>
        <option value="multi_turn_conversation">Multi-turn conversation</option>
        <option value="preference_alignment">Preference alignment</option>
      </select>

      <label htmlFor="desired-behavior">Desired behavior</label>
      <textarea
        id="desired-behavior"
        value={desiredBehavior}
        onChange={(event) => setDesiredBehavior(event.target.value)}
      />

      <label htmlFor="language">Language</label>
      <input id="language" value={language} onChange={(event) => setLanguage(event.target.value)} />

      <label htmlFor="target-rows">Target rows</label>
      <input
        id="target-rows"
        type="number"
        value={targetRows}
        onChange={(event) => setTargetRows(Number(event.target.value))}
      />

      <button type="submit" disabled={recommendMutation.isPending}>
        Get recommendation
      </button>

      {error && (
        <p role="alert">
          {error.message}
          {error.needsProviderSetup && ' — finish provider setup, then try again.'}
        </p>
      )}
    </form>
  )
}
```

**Do not pass `onSuccess: onPlanRecommended` directly** — TanStack Query's mutation `onSuccess` calls its callback with `(data, variables, context)`, and forwarding all three straight to a prop typed as `(plan: TrainingPlanResponse) => void` still type-checks (TypeScript allows a function requiring fewer parameters where more are supplied) but silently changes what a test asserting `toHaveBeenCalledWith(plan)` sees — the mock records all three arguments, not just the first. Wrap it: `onSuccess: (plan) => onPlanRecommended(plan)`. This was caught by running the test, not by inspection.

Run the tests again:

```powershell
corepack pnpm test -- src/features/goal-wizard
```

Expected: all 4 pass.

### Step 16: Plan confirmation modal — write the failing tests (RED)

Create `frontend/src/features/plan-confirmation/PlanConfirmationStep.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { PlanConfirmationStep } from './PlanConfirmationStep'

vi.mock('../../api/plans', () => ({
  approvePlan: vi.fn(),
}))

import { approvePlan } from '../../api/plans'

const mockApprovePlan = vi.mocked(approvePlan)

const plan = {
  id: 'plan-1',
  objective: 'sft_conversation' as const,
  canonical_schema: 'SFTConversationRecord',
  target_rows: 500,
  examples_per_chunk: 2,
  generator_profile_id: null,
  judge_profile_id: null,
  required_validators: ['structural', 'dedup'],
  evidence: [],
  confidence: 0.9,
  plan_hash: 'hash123',
}

describe('PlanConfirmationStep', () => {
  it('renders the recommended plan details', () => {
    renderWithProviders(<PlanConfirmationStep plan={plan} onApproved={vi.fn()} />)

    expect(screen.getByText('sft_conversation')).toBeInTheDocument()
    expect(screen.getByText('SFTConversationRecord')).toBeInTheDocument()
    expect(screen.getByText('500')).toBeInTheDocument()
    expect(screen.getByText(/structural, dedup/i)).toBeInTheDocument()
  })

  it('approves the plan and calls onApproved', async () => {
    const user = userEvent.setup()
    mockApprovePlan.mockResolvedValue({ id: 'plan-1', approved_at: '2026-08-15T00:00:00Z' })
    const onApproved = vi.fn()
    renderWithProviders(<PlanConfirmationStep plan={plan} onApproved={onApproved} />)

    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect(await screen.findByText(/approved/i)).toBeInTheDocument()
    expect(mockApprovePlan).toHaveBeenCalledWith('plan-1')
    expect(onApproved).toHaveBeenCalled()
  })
})
```

Run it and confirm it fails on the missing module:

```powershell
corepack pnpm test -- src/features/plan-confirmation
```

Expected: fails to resolve `./PlanConfirmationStep`.

### Step 17: Plan confirmation modal — implement (GREEN)

Create `frontend/src/features/plan-confirmation/PlanConfirmationStep.tsx`:

```typescript
import { useMutation } from '@tanstack/react-query'
import { approvePlan } from '../../api/plans'
import { ApiError } from '../../api/client'
import type { TrainingPlanResponse } from '../../api/types'

interface PlanConfirmationStepProps {
  plan: TrainingPlanResponse
  onApproved: () => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function PlanConfirmationStep({ plan, onApproved }: PlanConfirmationStepProps) {
  const approveMutation = useMutation({
    mutationFn: () => approvePlan(plan.id),
    onSuccess: onApproved,
  })

  return (
    <section>
      <h2>Confirm training plan</h2>
      <dl>
        <dt>Objective</dt>
        <dd>{plan.objective}</dd>
        <dt>Canonical schema</dt>
        <dd>{plan.canonical_schema}</dd>
        <dt>Target rows</dt>
        <dd>{plan.target_rows}</dd>
        <dt>Examples per chunk</dt>
        <dd>{plan.examples_per_chunk}</dd>
        <dt>Required validators</dt>
        <dd>{plan.required_validators.join(', ')}</dd>
        <dt>Confidence</dt>
        <dd>{Math.round(plan.confidence * 100)}%</dd>
      </dl>

      <button type="button" disabled={approveMutation.isPending} onClick={() => approveMutation.mutate()}>
        Approve
      </button>

      {approveMutation.isSuccess && <p>Plan approved.</p>}
      {approveMutation.isError && <p role="alert">{errorMessage(approveMutation.error)}</p>}
    </section>
  )
}
```

Run the tests again:

```powershell
corepack pnpm test -- src/features/plan-confirmation
```

Expected: both pass.

### Step 18: Wire the four steps into `App.tsx`

Edit `frontend/src/App.tsx` — replace the whole file:

```typescript
import { useState } from 'react'
import { ProjectSetupStep } from './features/project-setup/ProjectSetupStep'
import { ModelSelectionStep } from './features/model-selection/ModelSelectionStep'
import { GoalWizardStep } from './features/goal-wizard/GoalWizardStep'
import { PlanConfirmationStep } from './features/plan-confirmation/PlanConfirmationStep'
import type { ModelProfileResponse, Project, TrainingPlanResponse } from './api/types'

type WizardStep = 'project' | 'model' | 'goal' | 'plan'

function App() {
  const [step, setStep] = useState<WizardStep>('project')
  const [project, setProject] = useState<Project | null>(null)
  const [modelProfile, setModelProfile] = useState<ModelProfileResponse | null>(null)
  const [plan, setPlan] = useState<TrainingPlanResponse | null>(null)

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
            // Provider setup, generation runs, and export are plan_9.md's scope.
          }}
        />
      )}
    </main>
  )
}

export default App
```

Edit `frontend/src/App.test.tsx` — replace the whole file (it now renders through `renderWithProviders` since `App` uses `useMutation` via its first step):

```typescript
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from './test-utils'
import App from './App'

describe('App', () => {
  it('renders the TuneForge heading and the first wizard step', () => {
    renderWithProviders(<App />)
    expect(screen.getByRole('heading', { name: 'TuneForge' })).toBeInTheDocument()
    expect(screen.getByLabelText(/project name/i)).toBeInTheDocument()
  })
})
```

### Step 19: Full suite, type-check, and a real browser walkthrough

```powershell
cd frontend
corepack pnpm test
corepack pnpm exec tsc -b --noEmit
```

Expected: 22 tests pass across 6 files; `tsc` prints nothing (clean).

Then, with both servers from Step 3 still running, open `http://localhost:5173/` in a real browser and drive the whole assembled flow by hand: create a project, upload any small text/markdown file, analyze `gpt2` (a fast, well-known model — this project's own history already validated its causal-LM/context-length detection, so it's a good real smoke test), fill in the goal wizard with "Domain adaptation" (works with no chat template, unlike the other three goals), get a recommendation, and approve it. Confirm in the browser's network tab that every request in that chain returns a 2xx — `GET /api/session`, `POST /api/projects`, `POST /api/projects/{id}/sources`, `POST /api/models/analyze`, `POST /api/plans/recommend`, `POST /api/plans/{id}/approve` — and check the console for errors. **This exact walkthrough is what caught the Step 3 Origin-header bug** — component tests with mocked `fetch` cannot catch a real browser/proxy header mismatch, so don't treat a green `vitest` run alone as proof the wizard works.

### Step 20: Commit

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
git add backend/tests/test_runtime_security.py backend/tuneforge/main.py
git add frontend/package.json frontend/pnpm-lock.yaml frontend/vite.config.ts
git add frontend/src/main.tsx frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/test-utils.tsx
git add frontend/src/api frontend/src/features
git commit -m "feat: add TuneForge guided workflow (part 1 — setup through plan confirmation)"
```

---

## When you're done

Do not start anything from `plan_9.md`'s list (provider config, column mapping, preview, run progress, export, styling). Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` from `backend/` and `corepack pnpm test` + `corepack pnpm exec tsc -b --noEmit` from `frontend/`.
2. Output of `git log --oneline` — should show one new commit.
3. Confirmation that the Step 3 proxy fix actually mattered on your machine too (did you see the 403→401 change, or did it work without the `configure`/`proxyReq` block? — if the latter, say so, since that would mean this fix is more environment-specific than this document assumes).
4. Confirmation the Step 19 browser walkthrough was actually done by hand, not skipped, and what (if anything) didn't behave as this document describes.
5. Anything else you had to deviate from in this document, and why.
6. If you find a correctness issue anywhere in the code exactly as given here — not a style preference, an actual bug — stop and describe it rather than silently changing behavior.
