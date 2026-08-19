# TuneForge Implementation Plan — `upfront.md` (credentials pivot, Task 6, keyboard verification, Task 15)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec (do not edit it). Tasks 1–13 are implemented; Task 14 is redefined (website, not installer) and its code-level blocker is already fixed. This document has four independent pieces of work, in the order they should be done (B depends on A being done first; C and D depend on nothing here, but D's real-provider tests are much more useful once A is done):
>
> - **Part A** — switch Gemini/HF credential resolution from Windows Credential Manager to a repo-root `.env` file, per explicit instruction from the project owner. This is a **confirmed reversal of a non-negotiable rule** this project's own `CLAUDE.md` documented twice (once originally, once when the owner explicitly chose the credential-manager script over `.env` earlier in the same session that produced this document). Not a mistake to second-guess — implement it, but also update the documentation exactly as instructed below so the reversal is recorded, not silently overwritten.
> - **Part B** — `PLAN.md` Task 6's missing piece: `POST /plans/{plan_id}/research`. The underlying logic (`resolve_rejected_recommendation`) has been fully built and tested since early in this project — only the HTTP endpoint was ever missing, blocked on a decision about `httpx.AsyncClient` lifecycle. That decision is made below.
> - **Part C** — a **human task, not a coding task**: a real keyboard-only click-through of the entire 9-step wizard, which has never happened. Automated per-component focus tests exist; a real end-to-end walk does not.
> - **Part D** — Task 15, final verification. Scoped to **Windows only** per explicit instruction — no macOS/Linux boot testing.

## Global constraints, repeated

- Windows-only testing target for this document (Part D) — do not spend time on macOS/Linux verification.
- No `git push` — commit locally, leave pushing for later.
- TDD per this repo's established convention: write the failing test, confirm RED, implement, confirm GREEN, commit.

---

# Part A — Credentials from `.env`, not Windows Credential Manager

## A0. What's changing and why (read before touching code)

Today: `backend/tuneforge/security/credentials.py`'s `get_api_key(provider_name)` reads only from `keyring` (OS credential store). `backend/scripts/set_secrets.py` is the only way to populate it, and it requires interactive input — nobody has ever actually run it for real.

**New behavior, decided by the project owner:** the app reads `GEMINI_API_KEY` and `HF_TOKEN` from a `.env` file at the repo root (confirmed to already exist there, already gitignored via the repo's existing `*.env`/`.env.*` patterns — verified this session, no `.gitignore` change needed). `scripts/set_secrets.py` is removed — the owner does not want a second mechanism.

**What does NOT change:** `ProviderConfigStep`'s per-provider `api_key` field (a project's own configured generator/judge provider) still goes through `keyring` via `store_api_key` exactly as today — that's a different, dynamic, per-provider-record credential, not one of the two well-known pre-configured ones, and `.env` has no way to represent an arbitrary number of future provider credentials. Only the resolution of the two well-known names (`"gemini"`, `"huggingface"`) changes.

## A1. RED: `get_api_key` should prefer `.env`-sourced env vars for well-known names

Read `backend/tests/security/test_credentials.py` in full first (it's short, ~35 lines) — it already has a `_FakeKeyring` fixture pattern (`autouse=True`, monkeypatches the `keyring` module-level name in `credentials.py`) that every new test below should reuse, not reinvent.

Add:

```python
def test_get_api_key_prefers_env_var_for_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert credentials.get_api_key("gemini") == "from-env"


def test_get_api_key_prefers_env_var_for_huggingface(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "from-env-hf")
    assert credentials.get_api_key("huggingface") == "from-env-hf"


def test_get_api_key_falls_back_to_keyring_when_env_var_absent(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    credentials.store_api_key("gemini", "from-keyring")
    assert credentials.get_api_key("gemini") == "from-keyring"


def test_get_api_key_env_var_does_not_affect_unrelated_provider_names(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    credentials.store_api_key("provider-abc123", "arbitrary-provider-key")
    assert credentials.get_api_key("provider-abc123") == "arbitrary-provider-key"
```

Run `cd backend && uv run pytest tests/security/test_credentials.py -q` — the first two fail today (real keyring only, no env-var awareness).

## A2. GREEN: `backend/tuneforge/security/credentials.py`

```python
from __future__ import annotations

import os
from pathlib import Path

import keyring
from dotenv import load_dotenv
from keyring.errors import PasswordDeleteError

_SERVICE_NAME = "TuneForge"

# The two credentials this app pre-configures from .env. Anything else
# (a project's own provider profile, created via ProviderConfigStep) is
# never in .env — those still resolve via keyring only, below.
_ENV_VAR_BY_WELL_KNOWN_NAME = {
    "gemini": "GEMINI_API_KEY",
    "huggingface": "HF_TOKEN",
}

# credentials.py -> security/ -> tuneforge/ -> backend/ -> repo root.
_DOTENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_DOTENV_PATH)  # no-op, does not raise, if the file doesn't exist


class CredentialNotFoundError(RuntimeError):
    pass


def store_api_key(provider_name: str, api_key: str) -> None:
    keyring.set_password(_SERVICE_NAME, provider_name, api_key)


def get_api_key(provider_name: str) -> str:
    env_var = _ENV_VAR_BY_WELL_KNOWN_NAME.get(provider_name)
    if env_var:
        value = os.environ.get(env_var)
        if value:
            return value

    value = keyring.get_password(_SERVICE_NAME, provider_name)
    if value is None:
        raise CredentialNotFoundError(f"no credential stored for provider: {provider_name}")
    return value


def delete_api_key(provider_name: str) -> None:
    try:
        keyring.delete_password(_SERVICE_NAME, provider_name)
    except PasswordDeleteError:
        pass
```

**Flag, verify at RED time, don't trust this blindly:** `Path(__file__).resolve().parents[3]` — count it yourself against the real file location (`backend/tuneforge/security/credentials.py`) before trusting this resolves to the repo root where the real `.env` actually lives. Add a one-off `print(_DOTENV_PATH)` or a debugger check during development, then remove it — don't ship a silently-wrong path that just never loads anything and falls through to keyring unnoticed.

`python-dotenv` is already present in `uv.lock` as a transitive dependency (confirmed this session, pulled in by something else — pinned at `1.2.2`), but add it as an **explicit direct dependency** in `backend/pyproject.toml` — don't rely on an implicit transitive package for something imported directly; if the transitive chain that currently provides it ever changes, this import breaks silently otherwise.

```bash
cd backend
uv add python-dotenv
```

Run the credentials tests again — GREEN. Run the **full backend suite** (`uv run pytest -q`) — this touches a shared function every provider/analyzer/goal-suggestion code path calls, so a full run matters here, not just the touched file.

Commit (`feat: resolve Gemini/HF credentials from .env, keyring as fallback`).

## A3. Remove `set_secrets.py`

Delete `backend/scripts/set_secrets.py`. Grep the whole repo for references to it first (`grep -rn "set_secrets" backend CLAUDE.md README.md`) and remove every mention — as of this session that's `CLAUDE.md`'s "Pre-configured Gemini + Hugging Face credentials" bullet and `README.md`'s "Credentials" section, both of which need rewriting anyway (A4 below), plus check `plan_12.md`'s own text if it still references the script (historical doc, fine to leave referencing something that used to exist, but don't leave the *current* docs pointing at a deleted file).

No test to write for a deletion. Commit (`chore: remove set_secrets.py, superseded by .env credential resolution`).

## A4. Update `CLAUDE.md` and `README.md` — record the deviation, don't silently drop it

Edit `CLAUDE.md`'s **Non-negotiable constraints** section — remove `never a .env file` from that bullet (it's no longer true and this section is supposed to be things enforced everywhere) and move an accurate replacement into the **Architecture decisions that deviate from `PLAN.md`, on purpose** section, matching the existing NeMo-removal entry's own style exactly:

```markdown
- **Gemini API key and Hugging Face token come from a repo-root `.env` file, not Windows Credential Manager.** `PLAN.md`'s own global constraint says "API keys must use Windows Credential Manager and never SQLite, logs, or exports" — this is a confirmed, explicit reversal of that, decided by the project owner after being shown the trade-off twice (a plaintext file has no OS-level access control the way Credential Manager/Keychain/Secret-Service do, and risks ending up in a backup or a screen-share of the repo folder; the owner accepted this explicitly). `tuneforge.security.credentials.get_api_key` reads `GEMINI_API_KEY`/`HF_TOKEN` from `.env` first (loaded via `python-dotenv` at import time), falling back to `keyring` — which is still what a project's own dynamically-configured provider credentials (`ProviderConfigStep`) use, unchanged. Do not reintroduce Credential-Manager-only resolution for these two names without re-confirming with the owner, same as the NeMo decision above.
```

Also update the **Non-negotiable constraints** bullet itself:

```markdown
- API keys/tokens: Windows Credential Manager for dynamically-configured provider credentials. Gemini/HF are the one documented exception — see the `.env` deviation entry below. Never SQLite, never logs, never exports, regardless of source.
```

Rewrite `README.md`'s **Credentials** section (currently tells the reader to run `set_secrets.py`, which no longer exists):

```markdown
## Credentials

Create a `.env` file at the repo root (same directory as this README) with:

\`\`\`
GEMINI_API_KEY=...
HF_TOKEN=...
\`\`\`

Never commit this file (already gitignored). See `CLAUDE.md` for what each credential unlocks (AI goal suggestion / remote generation vs. Hub model analysis) and for the security trade-off of this approach vs. an OS credential store.
```

Commit (`docs: record the .env credential deviation from PLAN.md's non-negotiable rule`).

## A5. Live verification

Real end-to-end check against a real running backend — this is the first time in this project either credential has ever been exercised for real, not mocked:

```bash
cd backend
uv run python -m tuneforge.main
```

In another shell, confirm the app can actually reach Gemini now:

```bash
curl -X POST http://127.0.0.1:8420/api/session   # get a token first, use it below
```

Then drive a real `suggest-goal` call (needs a project with an uploaded document source — same steps as any earlier live check this session) with `remote_consent: true`. **Expect `200`, a real suggested goal, and a real Gemini API response** — if this still 422s with "Gemini credential not configured," the `.env` path resolution in A2 is wrong; go back and fix it before calling Part A done. This is real API spend (small — one Flash-tier call) and a real network call — that's the point, it's the only way to prove this actually works, not another mock.

Also confirm `HF_TOKEN` resolves: `uv run python -c "from tuneforge.security.credentials import get_api_key; print(bool(get_api_key('huggingface')))"` should print `True` without raising.

---

# Part B — `POST /plans/{plan_id}/research` (Task 6's missing endpoint)

## B0. What already exists (read before writing anything)

`backend/tuneforge/research/resolver.py`'s `resolve_rejected_recommendation(intent, model_profile, *, client, target_rows, **plan_kwargs)` — fully implemented, fully tested (`backend/tests/research/test_resolver.py`), does exactly what `PLAN.md`'s Task 6 checklist describes: re-checks local metadata, tries `recommend_plan` again, and only reaches out to Hugging Face's model card (`research/official_sources.py`'s `fetch_model_card_readme`/`fetch_source`) if a `ChatTemplateRequiredError` is hit and the model source is `"huggingface"`. Returns a `ResearchResult` (`plan: TrainingPlan | None`, `citations: list[FetchedSource]`, `confidence: float`, `requires_manual_selection: bool`).

**The `httpx.AsyncClient` lifecycle decision, made:** create one per request, scoped to the request with `async with` — matching the exact pattern already established this session for the ad-hoc Gemini provider in `suggest_goal` (`plans.py`). Do not build a shared app-lifespan client for this — `resolve_rejected_recommendation` only makes at most one network call per invocation (the HF model card fetch, and only when needed), so a shared client would be optimizing something that isn't a bottleneck, at the cost of lifecycle complexity this endpoint doesn't need.

**Payload shape decision, made:** the endpoint's payload is the exact same shape as the existing `POST /plans/recommend` (`project_id`, `model_profile_id`, `goal`, `desired_behavior`, `language`, `target_rows`, `generator_profile_id?`, `judge_profile_id?`, `objective_override?`) — **do not** try to reconstruct the original `TrainingIntent` from the stored `TrainingPlanRecord` (its `plan_json` only has the *output* `TrainingPlan`, never the `goal`/`desired_behavior`/`language` that produced it — those were never persisted anywhere). The frontend already has all of these values in its own React state at the exact moment a rejection happens (`GoalWizardStep`'s local state hasn't unmounted), so resending them is free and avoids inventing a recovery mechanism for data that was never designed to be recoverable.

`{plan_id}` in the URL identifies which earlier, rejected `TrainingPlanRecord` this retry is for — used to 404 if it doesn't exist and to know which project it belongs to, not used to recover intent fields.

## B1. RED

Read `backend/tests/api/test_plans.py`'s existing `_project_id`/`_stored_model_profile` helpers first (already used throughout that file) and reuse them.

```python
def test_research_returns_404_for_unknown_plan(client):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    response = client.post(
        f"/api/plans/{uuid.uuid4()}/research",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )
    assert response.status_code == 404


def test_research_returns_a_new_plan_when_the_retry_succeeds(client, monkeypatch):
    # _stored_model_profile's fixture model (meta-llama/Llama-3-8B) has
    # chat_template_found=False — a multi_turn_conversation goal fails
    # ChatTemplateRequiredError on the first attempt inside resolve_rejected_recommendation
    # too, same as it would on /plans/recommend. Use domain_adaptation (cpt)
    # instead so the *local* recheck succeeds without ever needing the network
    # call — proves the "recheck local metadata first" behavior end to end
    # without needing to mock an HF model-card fetch for this test.
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    rejected = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    ).json()

    response = client.post(
        f"/api/plans/{rejected['id']}/research",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 200,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["objective"] == "cpt"
    assert body["citations"] == []
    assert body["requires_manual_selection"] is False


def test_research_fetches_official_evidence_when_local_recheck_still_fails(client, monkeypatch):
    import httpx
    from tuneforge.research.official_sources import FetchedSource

    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)  # chat_template_found=False
    rejected = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    ).json()

    fake_source = FetchedSource(
        url="https://huggingface.co/meta-llama/Llama-3-8B/blob/main/README.md",
        retrieved_at="2026-01-01T00:00:00Z", sha256="deadbeef", excerpt="no chat template documented",
    )
    monkeypatch.setattr("tuneforge.api.plans.fetch_model_card_readme", lambda model_id: fake_source)

    response = client.post(
        f"/api/plans/{rejected['id']}/research",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "multi_turn_conversation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None
    assert body["requires_manual_selection"] is True
    assert len(body["citations"]) == 1
```

**Flag, verify before trusting:** `FetchedSource`'s real field names — read `backend/tuneforge/research/official_sources.py` yourself before writing this test for real; the field names above (`url`, `retrieved_at`, `sha256`, `excerpt`) are a reasonable guess matching `PLAN.md`'s Task 6 checklist wording ("Store source URL, retrieval timestamp, SHA-256, and relevant excerpt") but were not re-verified against the actual class this session — confirm the real field names before this test can even construct a `FetchedSource` instance, and fix them if wrong. This is exactly the kind of thing this repo's own convention says never to guess past RED — check it for real.

Run — fails (route doesn't exist).

## B2. GREEN — `backend/tuneforge/api/plans.py`

```python
import httpx

from tuneforge.planning.intents import TrainingIntent
from tuneforge.research.official_sources import fetch_model_card_readme, fetch_source, model_card_url
from tuneforge.research.resolver import resolve_rejected_recommendation


@router.post("/plans/{plan_id}/research")
async def research(plan_id: uuid.UUID, payload: dict, session: Session = Depends(get_session)):
    rejected_plan = session.get(TrainingPlanRecord, plan_id)
    if rejected_plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")

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

    async with httpx.AsyncClient() as client:
        result = await resolve_rejected_recommendation(
            intent,
            model_profile,
            client=client,
            target_rows=payload["target_rows"],
            objective_override=payload.get("objective_override"),
            generator_profile_id=uuid.UUID(payload["generator_profile_id"]) if payload.get("generator_profile_id") else None,
            judge_profile_id=uuid.UUID(payload["judge_profile_id"]) if payload.get("judge_profile_id") else None,
        )

    if result.plan is None:
        return {
            "plan": None,
            "citations": [json.loads(c.model_dump_json()) for c in result.citations],
            "confidence": result.confidence,
            "requires_manual_selection": result.requires_manual_selection,
        }

    plan_dict = json.loads(result.plan.model_dump_json())
    record = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=uuid.UUID(payload["project_id"]),
        objective=result.plan.objective, plan_json=plan_dict, plan_hash=result.plan.plan_hash,
    )
    session.add(record)
    session.commit()
    return {"id": str(record.id), **plan_dict, "citations": [], "requires_manual_selection": False}
```

**Flag:** the `test_research_fetches_official_evidence_...` test above monkeypatches `tuneforge.api.plans.fetch_model_card_readme` — that only works if `plans.py` imports it by name (`from tuneforge.research.official_sources import fetch_model_card_readme`) at module scope, which the code above does; if you change the import style, update the monkeypatch target to match, per this repo's own established "patch at the consuming module's bound name" convention (already used throughout `test_plans.py`, `test_runner.py`).

Run the new tests, then the full backend suite. Add the new path to `test_app_wiring.py`'s `test_all_routers_are_mounted` (`assert "/api/plans/{plan_id}/research" in paths` — verify the exact OpenAPI path-parameter spelling FastAPI actually produces before trusting this literal string; check the existing `/api/plans/{plan_id}/approve` assertion's own spelling in that same file as your reference, don't guess a different bracket style).

Commit (`feat: add POST /plans/{plan_id}/research, closing Task 6`).

## B3. Frontend — only if there's an actual UI need right now

**Do not build a frontend step for this unless you first check whether `GoalWizardStep`'s rejection paths (`ChatTemplateRequiredError`/`DistinctJudgeRequiredError`, both already surfaced as alerts today) have any existing hook for "try research instead" — read `GoalWizardStep.tsx` fresh before assuming.** If there's no existing UI moment where a rejection naturally offers "research this instead," don't invent one speculatively — ship the backend endpoint alone (Task 6's own checklist is entirely backend-scoped: "Fetch... Store... Present a revised recommendation with citations" reads as an API-level contract, not a mandated new screen) and note in your completion report that the frontend wiring is a separate, not-yet-scoped follow-up. Building a UI nobody asked for here would be exactly the kind of unrequested scope this project's own conventions warn against.

---

# Part C — Full keyboard-only click-through (human task)

**This cannot be automated or delegated to a coding AI in the way the rest of this document can — it requires a person with hands on a keyboard, watching a real browser.** If you are an AI executing this document, stop here and hand this specific part back to Tushar rather than attempting to simulate it — the whole point is a human confirming what automated focus tests can't: that the *experience* of using the wizard without a mouse is coherent, not just that each component individually passes an isolated test.

## Steps

1. `cd backend && uv run python -m tuneforge.main` (real backend, real data dir).
2. `cd frontend && corepack pnpm build` once, then let the backend serve the built UI at `http://127.0.0.1:8420/` (the real "website" mode from Part B14's work, not the Vite dev server — testing the actual deployed experience, not dev mode).
3. Unplug the mouse, or just don't touch it. Using only Tab, Shift+Tab, Enter, Space, and arrow keys where a `<select>` needs them:
   - Create a project.
   - Upload at least one real document **and** one structured (CSV) source, so the column-mapping step is actually exercised, not skipped.
   - Select or analyze a model.
   - Go through the AI-suggested-goal step at least twice across two different runs: once **accepting** the suggestion, once **rejecting** it and typing a free-text purpose — confirm both paths are fully keyboard-reachable, including the consent checkbox.
   - Complete the goal wizard, confirm the plan, configure a provider (try both a `local` and a `remote` provider across two runs, to exercise the consent checkbox there too).
   - Run a preview, approve the full run, watch progress, cancel one run and resume it via keyboard, export a completed one.
4. At every step, confirm: you always know where focus is (a visible ring, per this session's `:focus-visible` styling), Tab order matches what you'd expect visually, and nothing requires a mouse click to reach or activate.

**Report back:** every point where focus got lost, trapped, or jumped somewhere unexpected, named specifically (which step, which element) — not "it mostly worked." If nothing at all was wrong, say that plainly too; a suspiciously perfect report on the first-ever full run of this is itself worth double-checking once before trusting it.

---

# Part D — Task 15: final verification (Windows only)

## D0. Scope, explicitly

**Windows only.** No macOS/Linux boot testing, no cross-platform CI matrix — the project owner has explicitly deprioritized this. The cross-platform *code* (from the prior `plan_13_14.md` round) stays as-is; it's just not being *tested* cross-platform right now.

## D1. Playwright end-to-end tests

No Playwright config exists yet in this repo (confirm with `find frontend -iname "playwright*"` before assuming otherwise) — install and configure it fresh.

```bash
cd frontend
corepack pnpm add -D @playwright/test
corepack pnpm exec playwright install --with-deps chromium
```

Create `frontend/playwright.config.ts` pointed at the real backend + built frontend (mirroring Part C's own "test the real deployed mode, not Vite dev" approach) — `webServer` config that runs `uv run python -m tuneforge.main` from `../backend` as the server-under-test, `baseURL: 'http://127.0.0.1:8420'`.

Write `frontend/e2e/` specs covering, at minimum, one full run each for:
- **CPT** (`domain_adaptation` goal) — needs a `local` provider only, zero LLM calls at all for generation itself (confirmed this session: CPT never calls the provider), fastest and cheapest test to write and run.
- **SFT prompt-completion** and **SFT conversation** — need a real or locally-mocked OpenAI-compatible endpoint. If you don't have a local model server (Ollama or similar) available in the test environment, use `httpx.MockTransport`-backed... no — **Playwright drives a real browser against a real backend process**, it cannot inject a Python-level mock transport the way the unit tests do. You need an actual HTTP server responding on some local port for the frontend to point a `local` provider at. Stand up a minimal fake OpenAI-compatible server for this specifically (a ~20-line FastAPI or even `http.server`-based stub that returns a fixed valid `{"choices": [...]}` shape for `/v1/chat/completions` and `/v1/models`) — don't try to reuse the unit tests' `httpx.MockTransport` pattern, it doesn't apply here.
- **DPO** — needs generator + a *distinct* judge model. Use **two separate instances of the same fake server from above, or two different fixed-response stubs**, both `local` — this directly follows from the answer to Tushar's own question this session: DPO's judge only needs to be a different *model*, not a remote one. Do not configure a remote provider for this test.
- **Cancel and resume** — start a full run, cancel it mid-flight, confirm status, resume it, confirm it completes with the right row count (not double-counted, not reset).
- **Export** — download the bundle, confirm the manifest/provenance/training-plan files are all present (same shape already verified via API-level live checks earlier this session — Playwright's job here is confirming the *UI* download button actually works, not re-deriving the bundle contents from scratch).

## D2. 100,000-row resumable, memory-bounded run

**Use the CPT objective specifically for this** — it needs zero LLM calls (confirmed this session), so this test is about proving the *chunking → checkpoint → resume → export* pipeline is memory-bounded and correct at scale, not about spending on 100,000 real generation calls (which would be needlessly slow and costly for what this test is actually checking).

Construct a document (or several) whose combined chunk count is at or just above 100,000 — realistically this means either one very large synthetic text file or a generated fixture, not a real hand-written document. Run a full CPT run against it, and while it's running:
- Kill the worker process partway through (simulate a real crash, not a clean cancel) and confirm `resume` picks up from the last checkpoint without reprocessing or losing rows.
- Watch memory usage of the worker process during the run (Task Manager or `Get-Process` in PowerShell) — confirm it stays roughly flat as chunks progress rather than growing unbounded (the whole point of streaming to `records.jsonl` line-by-line rather than holding everything in memory — verify this is actually true in practice, not just true by code inspection).
- Confirm the final export at 100,000 rows completes and the exported Parquet/JSONL files are actually readable (reload them, don't just check they exist).

## D3. Secret-leak audit, holistic

Per-feature checks have happened all session (log redaction, response-body checks) but never one pass across the *whole* app at once. Grep the entire `backend/` source tree for anywhere a secret could reach a log line, an exception message, an exported bundle, or an API response body that isn't specifically the credential endpoints:

```bash
cd backend
grep -rn "get_api_key\|GEMINI_API_KEY\|HF_TOKEN" tuneforge/ --include="*.py" | grep -v "security/credentials.py"
```

For every hit, trace forward: does that value ever get logged, returned in a response, or written to an export file? Cross-check against `main.py`'s `_install_global_log_redaction` — confirm it actually covers every logger used in this codebase (it wraps the record factory globally, so it should — verify this claim by actually triggering a log line containing a real secret value in a test and confirming the redaction fires, rather than trusting the mechanism by inspection alone).

## D4. Documentation

Create `docs/user-guide.md` (the guided workflow, step by step, screenshots optional but a written walkthrough of what each wizard step does and why), `docs/privacy.md` (what's local-only vs. what leaves the machine and when — the consent model, in plain language), `docs/troubleshooting.md` (the known gaps already tracked in `CLAUDE.md`, rewritten for an end user rather than a developer — e.g. "why did my run stop before I expected" → target_rows/cap explanation; "the AI suggestion says credential not configured" → `.env` setup).

## D5. Final independent review

One more adversarial review pass, but this time scoped to the **whole application**, not one feature — the pattern already used repeatedly this session (a fresh reviewer agent, told not to trust the implementer's own claims, given the diff and asked to try to break it). Particular focus given everything that changed this round: the `.env` credential path (does it actually work under a real `uv run` invocation, not just a test that monkeypatches `os.environ` directly?) and the new research endpoint's error paths.

## D6. Commit discipline

Same as every other part of this project: TDD, commit per logical step, `feat:`/`fix:`/`docs:`/`test:` messages, no `git push` without being told.

---

## When you're done

Write a report covering, for **each of Parts A/B/D** (Part C is the human task, report separately if you did attempt any part of it, but flag clearly that a human still needs to do the real click-through if you did):

1. Full test-suite output (backin — `uv run pytest -q`, frontend — `corepack pnpm test -- --run` + `corepack pnpm exec tsc -b --noEmit`, and the new Playwright suite's own output).
2. `git log --oneline` for new commits.
3. Part A5's live Gemini call — the actual response, not just "it worked."
4. Part B's `FetchedSource` field-name flag — resolved how, and what the real fields turned out to be.
5. Part D2's 100k-row run — actual memory numbers observed, actual wall-clock time, confirmation the crash-and-resume actually happened (not just cancel-and-resume).
6. Every deviation from this document, named, with why — this repo's established convention, not a suggestion.
7. Any correctness issue found in this document itself, described rather than silently worked around.
