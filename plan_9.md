# TuneForge Implementation Plan — Part 9 (React UI: provider config + remote-consent threading)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec. Tasks 1–12, the Part 7 API-composition pass, and `plan_8.md` (project/upload, model selection, goal wizard, plan confirmation) are already implemented, committed, and pushed to `main`.
>
> **This part is not just a UI screen.** Researching Task 13's remaining scope surfaced a real, previously-invisible backend gap: `providers/openai_compatible.py` refuses to call a `"remote"`-scoped provider unless it receives a `RunConsent(run_id, granted_at)` object — but **nothing anywhere in the codebase ever built or threaded one through**. `POST /api/runs/preview`, `POST /api/runs/{id}/approve-full`, `jobs/runner.py`, and `generation/generator.py` all called straight through with no consent argument at all. Before this part, any run against a remote provider would have failed unconditionally the moment it tried to generate. This is why this part exists on its own, isolated from the other four remaining Task 13 screens (column mapping, preview, run progress, export) — the fix touches five files across two layers and is comparable in risk to Part 6, the previous highest-risk part in this project.
>
> Do not implement column mapping, the 20-row preview, run progress/cancel/resume, export download, or any visual styling as part of this — those are `plan_10.md` and later.
>
> Every code block below was actually written, run, and verified before being put in this document. Two real things were found and are described inline rather than glossed over: (1) SQLite round-trips a stored `datetime` as timezone-*naive* even when the original Python value was timezone-aware — a test written against strict equality caught this and had to be adjusted, and the finding is left in place as a comment; (2) live-testing this fix against a real running backend (not just `pytest`) required a scratch data directory, and the first attempt at setting one via an inline shell-prefixed env var silently failed to propagate to the backgrounded process, which as a result wrote real test data into the actual `%LOCALAPPDATA%\TuneForge` directory this app will use once shipped. That data was inspected (only ever this session's own test projects — the app has no installer yet, so nothing else could have put real data there) and deleted before writing this document. If you hit the same silent-propagation issue, export the env var as its own statement before starting the process, don't inline-prefix a backgrounded command with it.

**Goal (this part):** Close the remote-consent gap for real (schema + full call-chain threading, TDD'd and live-verified against a real remote-scoped provider), and add the provider configuration + remote-consent screen to the guided workflow.

**Architecture:** `RunRecord` gains a `remote_consent_granted_at` column. `api/runs.py` requires an explicit `remote_consent: true` in the request body whenever the chosen generator *or* judge provider is `"remote"`-scoped, for **both** `POST /api/runs/preview` and `POST /api/runs/{id}/approve-full` independently — a full run is its own run, not an inherited grant from the preview that scoped it, matching `PLAN.md`'s "every remote run requires explicit transmission approval." `jobs/runner.py`'s `run_generation_worker` reconstructs a `RunConsent` from that stored timestamp and threads it through `_run_generation_async` → `generation/generator.py`'s whole call chain (`generate_record` → the three per-objective generators → `_generate_qa_candidate`/`_score_candidate`) down to both `provider.generate()` and `judge.generate()` — the same consent object serves both, since PLAN.md's model is "consent for this run," not "consent per provider call." On the frontend, `ProviderConfigStep` creates a provider profile via the existing `POST /api/providers` (Part 7, unchanged) and, only when the created provider's `endpoint_scope` is `"remote"`, blocks its own `Continue` button behind an explicit consent checkbox.

**Deliberately out of scope (this part):** structured column mapping (needs its own new backend endpoint — Task 8's `detect_schema`/`apply_column_mapping`/`preview_normalization` logic exists and is tested but nothing calls it over HTTP), the 20-row preview screen (there's currently no endpoint to fetch a run's actual generated rows — `GET /api/runs/{id}` returns only status/counts), run progress/cancel/resume (the SSE endpoint can't be reached with a native browser `EventSource` at all, since it doesn't support the custom `Authorization` header this app's auth model requires — the fix is a `fetch` + `ReadableStream` reader instead, a frontend-only concern with no backend change needed, deferred to keep this part scoped to the consent fix), export download, and any visual styling.

## Global Constraints

Repeated from Parts 1–8, still binding:

- Windows-first, Python 3.12/`uv` on the backend, `pnpm` (via `corepack pnpm` in this environment) on the frontend.
- Bind only to `127.0.0.1`. Bearer session token, memory-only.
- Every remote provider call requires explicit, per-run transmission consent — this part is what actually makes that constraint true in code, not just in `PLAN.md`'s prose.
- API keys through Windows Credential Manager only — unchanged by this part; `POST /api/providers` (Part 7) already does this correctly and isn't touched here.

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
    storage/
      models.py                       (modified — RunRecord gains remote_consent_granted_at)
    api/
      runs.py                         (modified — consent gate on preview + approve-full)
    jobs/
      runner.py                       (modified — builds RunConsent, threads it through)
    generation/
      generator.py                    (modified — consent param threaded through every call site)
  tests/
    api/
      test_runs.py                    (modified — 5 new consent tests)
    generation/
      test_generator.py               (modified — 4 new consent-forwarding tests)
    jobs/
      test_runner.py                  (modified — env fixture fix + 3 new consent tests)

frontend/
  src/
    App.tsx                           (modified — adds the 'provider' wizard step)
    api/
      types.ts                        (modified — adds ProviderProfile/ProviderProfileInput/EndpointScope)
      providers.ts                    (new)
    features/
      provider-config/
        ProviderConfigStep.tsx         (new)
        ProviderConfigStep.test.tsx    (new)
```

---

### Step 1: `RunRecord` schema change

Edit `backend/tuneforge/storage/models.py`. Add this field to the existing `RunRecord` class, directly after `assurance_level`:

```python
    remote_consent_granted_at: Mapped[datetime | None] = mapped_column(default=None)
```

No migration tooling exists yet in this pre-release codebase — `Base.metadata.create_all` picks up new nullable columns on any fresh database. Nothing else changes here.

### Step 2: Consent forwarding through `generation/generator.py` — write the failing tests (RED)

This is the deepest part of the chain: `generate_record` dispatches to `generate_sft_prompt_completion_record` / `generate_sft_conversation_record` / `generate_dpo_record`, which call `_generate_qa_candidate` and `_score_candidate` — the two actual `provider.generate()`/`judge.generate()` call sites. Every one of these needs a `consent` parameter threaded through to the end.

Edit `backend/tests/generation/test_generator.py`. Replace the top imports and the `_provider` helper:

```python
from datetime import datetime, timezone

import httpx
import pytest

from tuneforge.generation.generator import (
    build_cpt_record,
    generate_dpo_record,
    generate_record,
    generate_sft_conversation_record,
    generate_sft_prompt_completion_record,
)
from tuneforge.generation.specs import GenerationSpec
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider, RemoteConsentRequiredError
from tuneforge.providers.protocol import ProviderProfile, RunConsent
from tuneforge.records import SourceRecord

SOURCE_TEXT = "Employees get 20 days of paid vacation per year."


def _source() -> SourceRecord:
    return SourceRecord(
        document_id=uuid.uuid4(),
        chunk_id="doc-0",
        text=SOURCE_TEXT,
        source_name="policy.md",
        source_hash="deadbeef",
        page=None,
        heading="Vacation Policy",
    )


def _provider(handler, *, endpoint_scope: str = "local") -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(
        name="test", base_url="http://127.0.0.1:9999", model="test-model", endpoint_scope=endpoint_scope
    )
    return OpenAICompatibleProvider(profile, client)


def _consent() -> RunConsent:
    return RunConsent(run_id=uuid.uuid4(), granted_at=datetime.now(timezone.utc))
```

(`uuid` and `json` are already imported at the top of the existing file — keep them.)

Append these tests at the end of the file:

```python
def _qa_response(request):
    return _chat_response(
        {"question": "How many vacation days?", "answer": "20 days.", "supporting_quote": "20 days of paid vacation"}
    )


async def test_sft_prompt_completion_forwards_consent_to_a_remote_provider():
    provider = _provider(_qa_response, endpoint_scope="remote")

    with pytest.raises(RemoteConsentRequiredError):
        await generate_sft_prompt_completion_record(provider, _source(), GenerationSpec(desired_behavior="qa"))

    record = await generate_sft_prompt_completion_record(
        provider, _source(), GenerationSpec(desired_behavior="qa"), consent=_consent()
    )
    assert record is not None


async def test_sft_conversation_forwards_consent_to_a_remote_provider():
    provider = _provider(_qa_response, endpoint_scope="remote")

    with pytest.raises(RemoteConsentRequiredError):
        await generate_sft_conversation_record(provider, _source(), GenerationSpec(desired_behavior="chat"))

    record = await generate_sft_conversation_record(
        provider, _source(), GenerationSpec(desired_behavior="chat"), consent=_consent()
    )
    assert record is not None


async def test_dpo_forwards_consent_to_both_a_remote_generator_and_a_remote_judge():
    answer_scores = {"bad answer": 2.0, "best answer": 9.0}
    candidate_answers_factory = lambda: iter(["throwaway", "bad answer", "best answer"])  # noqa: E731
    candidate_answers = candidate_answers_factory()

    def handler(request):
        payload = json.loads(request.content)
        prompt = payload["messages"][0]["content"]
        if "QUESTION:" in prompt:
            for answer, score in answer_scores.items():
                if f"ANSWER: {answer}" in prompt:
                    return _chat_response({"score": score})
            raise AssertionError(f"unscored answer in judge prompt: {prompt}")
        return _chat_response(
            {"question": "How many vacation days?", "answer": next(candidate_answers), "supporting_quote": "20 days of paid vacation"}
        )

    generator = _provider(handler, endpoint_scope="remote")
    judge = _provider(handler, endpoint_scope="remote")
    spec = GenerationSpec(desired_behavior="dpo", max_candidates=2, score_margin=2.0)

    with pytest.raises(RemoteConsentRequiredError):
        await generate_dpo_record(generator, judge, _source(), spec)

    candidate_answers = candidate_answers_factory()
    record = await generate_dpo_record(generator, judge, _source(), spec, consent=_consent())
    assert record is not None
    assert record.chosen[0].content == "best answer"


async def test_generate_record_forwards_consent_through_the_objective_dispatch():
    provider = _provider(_qa_response, endpoint_scope="remote")
    plan = TrainingPlan(
        objective="sft_prompt_completion", canonical_schema="SFTPromptCompletionRecord", target_rows=1,
        examples_per_chunk=1, generator_profile_id=None, judge_profile_id=None, required_validators=[],
        evidence=[], confidence=0.9, plan_hash="hash1",
    )
    spec = GenerationSpec(desired_behavior="qa")

    with pytest.raises(RemoteConsentRequiredError):
        await generate_record(plan=plan, source=_source(), generator=provider, judge=None, spec=spec)

    record = await generate_record(
        plan=plan, source=_source(), generator=provider, judge=None, spec=spec, consent=_consent()
    )
    assert record is not None
```

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/generation/test_generator.py -k forwards_consent -q
```

Expected: 4 failures, each `TypeError: ...() got an unexpected keyword argument 'consent'` (the first assertion in each test — the no-consent rejection — already passes today, since the provider layer already enforces this; it's the *forwarding* that's missing).

### Step 3: Consent forwarding through `generation/generator.py` — implement (GREEN)

Edit `backend/tuneforge/generation/generator.py`. Add `RunConsent` to the existing protocol import:

```python
from tuneforge.providers.protocol import GenerationRequest, RunConsent
```

Add a `consent: RunConsent | None = None` parameter to `_generate_qa_candidate`, forward it to `provider.generate`:

```python
async def _generate_qa_candidate(
    provider: OpenAICompatibleProvider, source: SourceRecord, consent: RunConsent | None = None
) -> dict:
    prompt = (
        "You are generating a training example strictly grounded in the source text "
        "below. Ask one clear question a reader could answer using only this text, "
        "answer it accurately, and quote the exact sentence(s) from the source that "
        "support your answer — the quote must appear verbatim in the source.\n\n"
        f"Source text:\n{source.text}\n\n"
        'Respond with only a JSON object: {"question": "...", "answer": "...", '
        '"supporting_quote": "..."}'
    )
    response = await provider.generate(
        GenerationRequest(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        ),
        consent=consent,
    )
    try:
        candidate = json.loads(response.content)
    except json.JSONDecodeError as exc:
        raise MalformedGenerationError(f"response was not valid JSON: {exc}") from exc
    for field in ("question", "answer", "supporting_quote"):
        if not isinstance(candidate.get(field), str) or not candidate[field].strip():
            raise MalformedGenerationError(f"missing or empty field: {field!r}")
    if candidate["supporting_quote"] not in source.text:
        raise GroundingError(f"supporting_quote not found verbatim in source chunk {source.chunk_id}")
    return candidate
```

Add the same parameter to `generate_sft_prompt_completion_record` and `generate_sft_conversation_record`, forwarding it into their `_generate_qa_candidate` calls (only the signature line and the one call-site line change in each — everything else in these two functions is untouched):

```python
async def generate_sft_prompt_completion_record(
    provider: OpenAICompatibleProvider, source: SourceRecord, spec: GenerationSpec, consent: RunConsent | None = None
) -> SFTPromptCompletionRecord | None:
    ...
            candidate = await _generate_qa_candidate(provider, source, consent)
```

```python
async def generate_sft_conversation_record(
    provider: OpenAICompatibleProvider, source: SourceRecord, spec: GenerationSpec, consent: RunConsent | None = None
) -> SFTConversationRecord | None:
    ...
            candidate = await _generate_qa_candidate(provider, source, consent)
```

Add it to `_score_candidate`, forwarding to `judge.generate`:

```python
async def _score_candidate(
    judge: OpenAICompatibleProvider,
    *,
    question: str,
    answer: str,
    source: SourceRecord,
    consent: RunConsent | None = None,
) -> float:
    prompt = (
        "Rate how well the ANSWER responds to the QUESTION using only the SOURCE "
        "text below, on a scale from 0 (useless or wrong) to 10 (excellent, fully "
        "grounded in the source).\n\n"
        f"SOURCE:\n{source.text}\n\nQUESTION: {question}\n\nANSWER: {answer}\n\n"
        'Respond with only a JSON object: {"score": <number 0-10>}'
    )
    response = await judge.generate(
        GenerationRequest(messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}),
        consent=consent,
    )
    try:
        data = json.loads(response.content)
        return float(data["score"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise MalformedGenerationError(f"judge response was not a valid score: {exc}") from exc
```

Add it to `generate_dpo_record`, forwarding to both its `_generate_qa_candidate` calls and its `_score_candidate` call:

```python
async def generate_dpo_record(
    generator: OpenAICompatibleProvider,
    judge: OpenAICompatibleProvider,
    source: SourceRecord,
    spec: GenerationSpec,
    consent: RunConsent | None = None,
) -> DPORecord | None:
    last_error: Exception | None = None
    for _ in range(spec.max_retries + 1):
        try:
            question_candidate = await _generate_qa_candidate(generator, source, consent)
            question = question_candidate["question"]

            scored: list[tuple[float, str]] = []
            for _candidate_index in range(spec.max_candidates):
                candidate = await _generate_qa_candidate(generator, source, consent)
                score = await _score_candidate(
                    judge, question=question, answer=candidate["answer"], source=source, consent=consent
                )
                scored.append((score, candidate["answer"]))

            scored.sort(key=lambda pair: pair[0])
            worst_score, worst_answer = scored[0]
            best_score, best_answer = scored[-1]
            if best_score - worst_score < spec.score_margin:
                raise MalformedGenerationError(
                    f"candidate scores too close ({best_score} vs {worst_score}) — no clear preference"
                )
        except (MalformedGenerationError, GroundingError) as exc:
            last_error = exc
            continue

        return DPORecord(
            prompt=[ChatMessage(role="user", content=question)],
            chosen=[ChatMessage(role="assistant", content=best_answer)],
            rejected=[ChatMessage(role="assistant", content=worst_answer)],
            metadata=_metadata(source),
        )
    logger.warning("rejected DPO candidate for chunk %s after %d attempts: %s", source.chunk_id, spec.max_retries + 1, last_error)
    return None
```

Finally, add it to the top-level dispatcher `generate_record`, forwarding to whichever objective function it calls:

```python
async def generate_record(
    *,
    plan: TrainingPlan,
    source: SourceRecord,
    generator: OpenAICompatibleProvider,
    judge: OpenAICompatibleProvider | None,
    spec: GenerationSpec,
    consent: RunConsent | None = None,
):
    if plan.objective == "cpt":
        return build_cpt_record(source)
    if plan.objective == "sft_prompt_completion":
        return await generate_sft_prompt_completion_record(generator, source, spec, consent)
    if plan.objective == "sft_conversation":
        return await generate_sft_conversation_record(generator, source, spec, consent)
    if plan.objective == "dpo":
        if judge is None:
            raise ValueError("dpo generation requires a judge provider")
        return await generate_dpo_record(generator, judge, source, spec, consent)
    raise ValueError(f"unknown objective: {plan.objective}")
```

Run the tests again:

```powershell
uv run pytest tests/generation/test_generator.py -q
```

Expected: all 11 pass (7 existing + 4 new).

### Step 4: Threading consent through `jobs/runner.py` — write the failing tests (RED)

`run_generation_worker` is where `RunRecord.remote_consent_granted_at` actually gets read and turned into a `RunConsent` — this is the one place that matters for the whole fix to be real, not just plumbing.

First, the shared `env` fixture in `backend/tests/jobs/test_runner.py` has a latent bug this step exposes: its `plan_record.plan_json={}` is fine for `_run_generation_async` (which takes `plan` as a direct parameter and never reads `plan_json`), but `run_generation_worker` parses `plan_record.plan_json` for real via `TrainingPlan.model_validate(...)` — an empty dict fails that validation. Fix the fixture first:

```python
    plan_record = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project.id, objective="cpt",
        plan_json=json.loads(_cpt_plan().model_dump_json()), plan_hash="hash1",
    )
```

Update the imports at the top of the file:

```python
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from tuneforge.generation.specs import GenerationSpec
from tuneforge.jobs.checkpoints import get_latest_checkpoint
from tuneforge.jobs.runner import MAX_ACCEPTED_ROWS, _run_generation_async, run_generation_worker, run_output_path
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile, RunConsent
from tuneforge.records import SourceRecord
```

Add these tests directly above `test_worker_process_can_be_spawned_and_joins_cleanly`:

```python
async def test_run_forwards_consent_to_generate_record(env, monkeypatch):
    session, artifact_store, project, run = env
    granted_at = datetime.now(timezone.utc)
    run.remote_consent_granted_at = granted_at
    session.commit()

    captured = {}

    async def fake_generate_record(*, plan, source, generator, judge, spec, consent=None):
        captured["consent"] = consent
        return None

    monkeypatch.setattr("tuneforge.jobs.runner.generate_record", fake_generate_record)

    await _run_generation_async(
        session=session, run=run, plan=_cpt_plan(), sources=_sources(uuid.uuid4(), 1),
        generator=_provider(lambda request: (_ for _ in ()).throw(AssertionError("not expected"))),
        judge=None, spec=GenerationSpec(desired_behavior="cpt"), tokenizer=_FakeTokenizer(), max_tokens=512,
        target_rows=1000, resume_from_chunk=0,
        output_path=run_output_path(artifact_store.base_dir, project.id, run.id),
        consent=RunConsent(run_id=run.id, granted_at=granted_at),
    )

    assert captured["consent"] is not None
    assert captured["consent"].run_id == run.id
    assert captured["consent"].granted_at.replace(tzinfo=None) == granted_at.replace(tzinfo=None)


def test_worker_builds_consent_from_the_runs_remote_consent_timestamp(env, monkeypatch):
    session, artifact_store, project, run = env
    granted_at = datetime.now(timezone.utc)
    run.remote_consent_granted_at = granted_at
    session.commit()
    db_path = session.get_bind().url.database
    session.close()

    captured = {}

    class _FakeProfile:
        model_id = "gpt2"
        context_length = 512

    class _FakeTok:
        tokenizer = object()

    monkeypatch.setattr("tuneforge.models.analyzer.analyze_model", lambda model_id, *, source: _FakeProfile())
    monkeypatch.setattr("tuneforge.ingestion.chunking.build_tokenizer", lambda model_id: _FakeTok())
    monkeypatch.setattr(
        "tuneforge.jobs.runner._load_project_sources", lambda session, artifact_store, project_id, tokenizer: []
    )
    monkeypatch.setattr("tuneforge.jobs.runner._load_provider", lambda session, profile_id: object())

    async def fake_run_generation_async(**kwargs):
        captured["consent"] = kwargs.get("consent")

    monkeypatch.setattr("tuneforge.jobs.runner._run_generation_async", fake_run_generation_async)

    run_generation_worker(db_path=db_path, base_data_dir=str(artifact_store.base_dir), run_id=str(run.id))

    assert captured["consent"] is not None
    assert captured["consent"].run_id == run.id
    assert captured["consent"].granted_at.replace(tzinfo=None) == granted_at.replace(tzinfo=None)


def test_worker_builds_no_consent_when_none_was_granted(env, monkeypatch):
    session, artifact_store, project, run = env
    db_path = session.get_bind().url.database
    session.close()

    captured = {}

    class _FakeProfile:
        model_id = "gpt2"
        context_length = 512

    class _FakeTok:
        tokenizer = object()

    monkeypatch.setattr("tuneforge.models.analyzer.analyze_model", lambda model_id, *, source: _FakeProfile())
    monkeypatch.setattr("tuneforge.ingestion.chunking.build_tokenizer", lambda model_id: _FakeTok())
    monkeypatch.setattr(
        "tuneforge.jobs.runner._load_project_sources", lambda session, artifact_store, project_id, tokenizer: []
    )
    monkeypatch.setattr("tuneforge.jobs.runner._load_provider", lambda session, profile_id: object())

    async def fake_run_generation_async(**kwargs):
        captured["consent"] = kwargs.get("consent")

    monkeypatch.setattr("tuneforge.jobs.runner._run_generation_async", fake_run_generation_async)

    run_generation_worker(db_path=db_path, base_data_dir=str(artifact_store.base_dir), run_id=str(run.id))

    assert captured["consent"] is None
```

**On the `.replace(tzinfo=None)` calls — this is not a workaround for a bug in this fix, it's a real, pre-existing characteristic of this codebase's SQLite storage that a strict-equality test happened to surface for the first time.** SQLite has no native timezone-aware datetime type; SQLAlchemy round-trips every `Mapped[datetime]` column here as naive, even though `datetime.now(timezone.utc)` was timezone-aware when it went in. Every other datetime column in this schema (`created_at`, `approved_at`, etc.) has exactly the same characteristic — nothing before this compared one for exact `tzinfo` equality across a real DB round-trip, so it was never visible before. `RunConsent.granted_at` is only ever used for presence-checking downstream (`openai_compatible.py`'s `generate()` only checks `consent is None`, never inspects `.granted_at`'s value), so the naive-vs-aware difference is harmless in practice — but don't assume `.granted_at` is timezone-aware if you build something new that reads it.

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/jobs/test_runner.py -k consent -q
```

Expected: `test_run_forwards_consent_to_generate_record` fails with `TypeError: _run_generation_async() got an unexpected keyword argument 'consent'`; the two worker tests fail on the plan_json validation error until the fixture fix above is applied, then fail on the `captured["consent"] is not None` assertion (both `None`, since nothing builds it yet).

### Step 5: Threading consent through `jobs/runner.py` — implement (GREEN)

Edit `backend/tuneforge/jobs/runner.py`. Add `RunConsent` to the existing protocol import:

```python
from tuneforge.providers.protocol import ProviderProfile, RunConsent
```

Add a `consent: RunConsent | None = None` parameter to `_run_generation_async`'s signature (it's the last parameter, directly after `output_path: Path,`), and forward it into the `generate_record` call inside the loop:

```python
            record = await generate_record(
                plan=plan, source=source, generator=generator, judge=judge, spec=spec, consent=consent
            )
```

In `run_generation_worker`, directly before the `asyncio.run(...)` call, build the consent object from the loaded `run`:

```python
    consent = (
        RunConsent(run_id=run.id, granted_at=run.remote_consent_granted_at)
        if run.remote_consent_granted_at
        else None
    )

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
```

Run the tests again:

```powershell
uv run pytest tests/jobs/test_runner.py -q
```

Expected: all 10 pass.

### Step 6: Requiring and storing consent in `api/runs.py` — write the failing tests (RED)

Add to `backend/tests/api/test_runs.py`. First, the import line needs `datetime`/`timezone`:

```python
from datetime import datetime, timezone
```

Append these tests directly after `test_preview_creates_a_run_with_is_preview_true`:

```python
def _make_remote_provider(client, project_id):
    session = _session(client)
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project_id, name="openai", base_url="https://api.openai.com/v1",
        model="gpt-4", endpoint_scope="remote",
    )
    session.add(provider)
    session.commit()
    return provider


def test_preview_rejects_remote_generator_without_consent(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, _local_provider = _make_plan_and_provider(client, project.id)
    remote_provider = _make_remote_provider(client, project.id)

    response = client.post(
        "/api/runs/preview",
        json={"plan_id": str(plan.id), "generator_profile_id": str(remote_provider.id)},
    )

    assert response.status_code == 422
    assert "consent" in response.json()["detail"].lower()


def test_preview_accepts_remote_generator_with_consent_and_stores_the_timestamp(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, _local_provider = _make_plan_and_provider(client, project.id)
    remote_provider = _make_remote_provider(client, project.id)

    response = client.post(
        "/api/runs/preview",
        json={"plan_id": str(plan.id), "generator_profile_id": str(remote_provider.id), "remote_consent": True},
    )

    assert response.status_code == 201
    session = _session(client)
    stored = session.get(RunRecord, uuid.UUID(response.json()["id"]))
    assert stored.remote_consent_granted_at is not None


def test_preview_rejects_remote_judge_without_consent_even_when_generator_is_local(client):
    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, local_provider = _make_plan_and_provider(client, project.id)
    remote_judge = _make_remote_provider(client, project.id)

    response = client.post(
        "/api/runs/preview",
        json={
            "plan_id": str(plan.id),
            "generator_profile_id": str(local_provider.id),
            "judge_profile_id": str(remote_judge.id),
        },
    )

    assert response.status_code == 422
    assert "consent" in response.json()["detail"].lower()


def test_approve_full_rejects_remote_generator_without_consent(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, _local_provider = _make_plan_and_provider(client, project.id)
    remote_provider = _make_remote_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=remote_provider.id,
        is_preview=True, status="completed", remote_consent_granted_at=datetime.now(timezone.utc),
    )
    session = _session(client)
    session.add(preview_run)
    session.commit()
    client.post(f"/api/plans/{plan.id}/approve")

    response = client.post(f"/api/runs/{preview_run.id}/approve-full")

    assert response.status_code == 422
    assert "consent" in response.json()["detail"].lower()


def test_approve_full_accepts_remote_generator_with_consent_and_stores_the_timestamp(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    session = _session(client)
    project = ProjectRepository(session, client.artifact_store).create("proj")
    plan, _local_provider = _make_plan_and_provider(client, project.id)
    remote_provider = _make_remote_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=remote_provider.id,
        is_preview=True, status="completed", remote_consent_granted_at=datetime.now(timezone.utc),
    )
    session = _session(client)
    session.add(preview_run)
    session.commit()
    client.post(f"/api/plans/{plan.id}/approve")

    response = client.post(f"/api/runs/{preview_run.id}/approve-full", json={"remote_consent": True})

    assert response.status_code == 200
    session = _session(client)
    full_run = session.get(RunRecord, uuid.UUID(response.json()["id"]))
    assert full_run.remote_consent_granted_at is not None
```

Run it and confirm it fails:

```powershell
cd backend
uv run pytest tests/api/test_runs.py -k consent -q
```

Expected: the two "rejects" tests get `200`/`201` instead of `422` (nothing blocks them yet); the two "accepts and stores" tests get `None` instead of a real timestamp.

### Step 7: Requiring and storing consent in `api/runs.py` — implement (GREEN)

Edit `backend/tuneforge/api/runs.py`. Update the imports and add a consent-error constant plus two helpers, directly after the existing `_get_run_or_404`:

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
from tuneforge.storage.models import ProviderProfileRecord, RunRecord, TrainingPlanRecord

router = APIRouter()

_CANCELLABLE_STATUSES = {"pending", "running"}

_CONSENT_ERROR = "remote provider requires explicit consent — set 'remote_consent': true"


def _get_run_or_404(session: Session, run_id: uuid.UUID) -> RunRecord:
    run = session.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return run


def _requires_remote_consent(
    session: Session, generator_profile_id: uuid.UUID, judge_profile_id: uuid.UUID | None
) -> bool:
    generator = session.get(ProviderProfileRecord, generator_profile_id)
    if generator is not None and generator.endpoint_scope == "remote":
        return True
    if judge_profile_id is not None:
        judge = session.get(ProviderProfileRecord, judge_profile_id)
        if judge is not None and judge.endpoint_scope == "remote":
            return True
    return False


def _resolve_remote_consent(
    session: Session,
    payload: dict,
    generator_profile_id: uuid.UUID,
    judge_profile_id: uuid.UUID | None,
) -> datetime | None:
    if not _requires_remote_consent(session, generator_profile_id, judge_profile_id):
        return None
    if not payload.get("remote_consent"):
        raise HTTPException(status_code=422, detail=_CONSENT_ERROR)
    return datetime.now(timezone.utc)
```

Edit `create_preview` — resolve consent before building the `RunRecord`, and store it:

```python
@router.post("/runs/preview", status_code=201)
async def create_preview(payload: dict, request: Request, session: Session = Depends(get_session)):
    plan_id = payload.get("plan_id")
    generator_profile_id = payload.get("generator_profile_id")
    if not plan_id or not generator_profile_id:
        raise HTTPException(status_code=422, detail="'plan_id' and 'generator_profile_id' are required")

    plan = session.get(TrainingPlanRecord, uuid.UUID(plan_id))
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")

    generator_uuid = uuid.UUID(generator_profile_id)
    judge_uuid = uuid.UUID(payload["judge_profile_id"]) if payload.get("judge_profile_id") else None
    remote_consent_granted_at = _resolve_remote_consent(session, payload, generator_uuid, judge_uuid)

    run = RunRecord(
        id=uuid.uuid4(),
        project_id=plan.project_id,
        plan_id=plan.id,
        generator_profile_id=generator_uuid,
        judge_profile_id=judge_uuid,
        is_preview=True,
        remote_consent_granted_at=remote_consent_granted_at,
    )
    session.add(run)
    session.commit()
    start_run(db_path=request.app.state.db_path, base_data_dir=request.app.state.artifact_store.base_dir, run_id=run.id)
    return {"id": str(run.id), "status": run.status, "is_preview": run.is_preview}
```

Edit `approve_full` — it needs a request body now (it previously took none), independently re-checks and re-stores consent for the new full run rather than inheriting the preview's grant:

```python
@router.post("/runs/{run_id}/approve-full")
async def approve_full(
    run_id: uuid.UUID, request: Request, payload: dict | None = None, session: Session = Depends(get_session)
):
    payload = payload or {}
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

    # A full run is its own run, distinct from the preview that scoped it —
    # PLAN.md requires explicit consent per run, so this doesn't inherit the
    # preview's grant even though it reuses the same provider profiles.
    remote_consent_granted_at = _resolve_remote_consent(
        session, payload, preview_run.generator_profile_id, preview_run.judge_profile_id
    )

    full_run = RunRecord(
        id=uuid.uuid4(),
        project_id=preview_run.project_id,
        plan_id=preview_run.plan_id,
        generator_profile_id=preview_run.generator_profile_id,
        judge_profile_id=preview_run.judge_profile_id,
        is_preview=False,
        remote_consent_granted_at=remote_consent_granted_at,
    )
    session.add(full_run)
    session.commit()
    start_run(db_path=request.app.state.db_path, base_data_dir=request.app.state.artifact_store.base_dir, run_id=full_run.id)
    return {"id": str(full_run.id), "status": full_run.status}
```

Every other function in `runs.py` (`get_run`, `cancel_run`, `resume_run`, `stream_events`) is untouched.

Run the tests again:

```powershell
uv run pytest tests/api/test_runs.py -q
```

Expected: all 15 pass.

### Step 8: Full backend suite

```powershell
cd backend
uv run pytest -q
```

Expected: 233 passed (221 from Parts 1–7/plan_8 plus 12 new: 4 generator, 3 runner, 5 runs).

### Step 9: Frontend types + API function for providers

Edit `frontend/src/api/types.ts`, appending at the end:

```typescript
export type EndpointScope = 'local' | 'remote'

export interface ProviderProfileInput {
  name: string
  base_url: string
  model: string
  endpoint_scope: EndpointScope
  api_key?: string
}

export interface ProviderProfile {
  id: string
  name: string
  endpoint_scope: EndpointScope
}
```

Create `frontend/src/api/providers.ts`:

```typescript
import { apiFetch } from './client'
import type { ProviderProfile, ProviderProfileInput } from './types'

export function createProvider(projectId: string, input: ProviderProfileInput): Promise<ProviderProfile> {
  return apiFetch<ProviderProfile>('/api/providers', {
    method: 'POST',
    json: { project_id: projectId, ...input },
  })
}
```

### Step 10: `ProviderConfigStep` — write the failing tests (RED)

Create `frontend/src/features/provider-config/ProviderConfigStep.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../test-utils'
import { ApiError } from '../../api/client'
import { ProviderConfigStep } from './ProviderConfigStep'

vi.mock('../../api/providers', () => ({
  createProvider: vi.fn(),
}))

import { createProvider } from '../../api/providers'

const mockCreateProvider = vi.mocked(createProvider)

describe('ProviderConfigStep', () => {
  it('renders the provider fields with no consent section yet', () => {
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    expect(screen.getByLabelText(/provider name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/base url/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^model$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/endpoint scope/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/api key/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/consent/i)).not.toBeInTheDocument()
  })

  it('creates a local provider and enables Continue with no consent step', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockResolvedValue({ id: 'prov-1', name: 'ollama', endpoint_scope: 'local' })
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await user.type(screen.getByLabelText(/provider name/i), 'ollama')
    await user.type(screen.getByLabelText(/base url/i), 'http://127.0.0.1:11434')
    await user.type(screen.getByLabelText(/^model$/i), 'llama3')
    await user.click(screen.getByRole('button', { name: /create provider/i }))

    expect(await screen.findByRole('button', { name: /continue/i })).toBeEnabled()
    expect(mockCreateProvider).toHaveBeenCalledWith('proj-1', {
      name: 'ollama',
      base_url: 'http://127.0.0.1:11434',
      model: 'llama3',
      endpoint_scope: 'local',
      api_key: '',
    })
  })

  it('calls onProviderReady with remoteConsentGranted=false for a local provider', async () => {
    const user = userEvent.setup()
    const provider = { id: 'prov-1', name: 'ollama', endpoint_scope: 'local' as const }
    mockCreateProvider.mockResolvedValue(provider)
    const onProviderReady = vi.fn()
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={onProviderReady} />)

    await user.type(screen.getByLabelText(/provider name/i), 'ollama')
    await user.type(screen.getByLabelText(/base url/i), 'http://127.0.0.1:11434')
    await user.type(screen.getByLabelText(/^model$/i), 'llama3')
    await user.click(screen.getByRole('button', { name: /create provider/i }))
    await user.click(await screen.findByRole('button', { name: /continue/i }))

    expect(onProviderReady).toHaveBeenCalledWith(provider, false)
  })

  it('requires an explicit consent checkbox for a remote provider before Continue is enabled', async () => {
    const user = userEvent.setup()
    const provider = { id: 'prov-1', name: 'openai', endpoint_scope: 'remote' as const }
    mockCreateProvider.mockResolvedValue(provider)
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await user.selectOptions(screen.getByLabelText(/endpoint scope/i), 'remote')
    await user.type(screen.getByLabelText(/provider name/i), 'openai')
    await user.type(screen.getByLabelText(/base url/i), 'https://api.openai.com/v1')
    await user.type(screen.getByLabelText(/^model$/i), 'gpt-4')
    await user.click(screen.getByRole('button', { name: /create provider/i }))

    const consentCheckbox = await screen.findByLabelText(/consent/i)
    const continueButton = screen.getByRole('button', { name: /continue/i })
    expect(continueButton).toBeDisabled()

    await user.click(consentCheckbox)
    expect(continueButton).toBeEnabled()
  })

  it('calls onProviderReady with remoteConsentGranted=true once consent is checked', async () => {
    const user = userEvent.setup()
    const provider = { id: 'prov-1', name: 'openai', endpoint_scope: 'remote' as const }
    mockCreateProvider.mockResolvedValue(provider)
    const onProviderReady = vi.fn()
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={onProviderReady} />)

    await user.selectOptions(screen.getByLabelText(/endpoint scope/i), 'remote')
    await user.type(screen.getByLabelText(/provider name/i), 'openai')
    await user.type(screen.getByLabelText(/base url/i), 'https://api.openai.com/v1')
    await user.type(screen.getByLabelText(/^model$/i), 'gpt-4')
    await user.click(screen.getByRole('button', { name: /create provider/i }))
    await user.click(await screen.findByLabelText(/consent/i))
    await user.click(screen.getByRole('button', { name: /continue/i }))

    expect(onProviderReady).toHaveBeenCalledWith(provider, true)
  })

  it('shows a validation error when provider creation fails', async () => {
    const user = userEvent.setup()
    mockCreateProvider.mockRejectedValue(new ApiError(422, "endpoint_scope must be 'local' or 'remote'"))
    renderWithProviders(<ProviderConfigStep projectId="proj-1" onProviderReady={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /create provider/i }))

    expect(await screen.findByText("endpoint_scope must be 'local' or 'remote'")).toBeInTheDocument()
  })
})
```

Run it and confirm it fails:

```powershell
corepack pnpm test -- src/features/provider-config
```

Expected: fails to resolve `./ProviderConfigStep`.

### Step 11: `ProviderConfigStep` — implement (GREEN)

Create `frontend/src/features/provider-config/ProviderConfigStep.tsx`:

```typescript
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { createProvider } from '../../api/providers'
import { ApiError } from '../../api/client'
import type { EndpointScope, ProviderProfile } from '../../api/types'

interface ProviderConfigStepProps {
  projectId: string
  onProviderReady: (provider: ProviderProfile, remoteConsentGranted: boolean) => void
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong. Try again.'
}

export function ProviderConfigStep({ projectId, onProviderReady }: ProviderConfigStepProps) {
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [endpointScope, setEndpointScope] = useState<EndpointScope>('local')
  const [apiKey, setApiKey] = useState('')
  const [consentGranted, setConsentGranted] = useState(false)

  const createMutation = useMutation({
    mutationFn: () =>
      createProvider(projectId, { name, base_url: baseUrl, model, endpoint_scope: endpointScope, api_key: apiKey }),
  })

  const provider = createMutation.data
  const needsConsent = provider?.endpoint_scope === 'remote'
  const canContinue = provider !== undefined && (!needsConsent || consentGranted)

  if (!provider) {
    return (
      <form
        onSubmit={(event) => {
          event.preventDefault()
          createMutation.mutate()
        }}
      >
        <label htmlFor="provider-name">Provider name</label>
        <input id="provider-name" value={name} onChange={(event) => setName(event.target.value)} />

        <label htmlFor="provider-base-url">Base URL</label>
        <input id="provider-base-url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />

        <label htmlFor="provider-model">Model</label>
        <input id="provider-model" value={model} onChange={(event) => setModel(event.target.value)} />

        <label htmlFor="provider-scope">Endpoint scope</label>
        <select
          id="provider-scope"
          value={endpointScope}
          onChange={(event) => setEndpointScope(event.target.value as EndpointScope)}
        >
          <option value="local">Local</option>
          <option value="remote">Remote</option>
        </select>

        <label htmlFor="provider-api-key">API key (optional)</label>
        <input
          id="provider-api-key"
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
        />

        <button type="submit" disabled={createMutation.isPending}>
          Create provider
        </button>
        {createMutation.isError && <p role="alert">{errorMessage(createMutation.error)}</p>}
      </form>
    )
  }

  return (
    <section>
      <p>
        Provider <strong>{provider.name}</strong> ready ({provider.endpoint_scope}).
      </p>

      {needsConsent && (
        <label htmlFor="remote-consent">
          <input
            id="remote-consent"
            type="checkbox"
            checked={consentGranted}
            onChange={(event) => setConsentGranted(event.target.checked)}
          />
          I consent to sending project document text to this remote provider
        </label>
      )}

      <button type="button" disabled={!canContinue} onClick={() => onProviderReady(provider, consentGranted)}>
        Continue
      </button>
    </section>
  )
}
```

Run the tests again:

```powershell
corepack pnpm test -- src/features/provider-config
```

Expected: all 6 pass.

### Step 12: Wire the new step into `App.tsx`

Edit `frontend/src/App.tsx`. Add the import and the new step to the union type:

```typescript
import { ProviderConfigStep } from './features/provider-config/ProviderConfigStep'

type WizardStep = 'project' | 'model' | 'goal' | 'plan' | 'provider'
```

Change `PlanConfirmationStep`'s `onApproved` to advance instead of being a no-op, and add the new step's render block directly after it:

```typescript
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
          onProviderReady={() => {
            // Preview, run progress, and export are plan_10.md's scope.
          }}
        />
      )}
```

Nothing else in `App.tsx` changes. `onProviderReady`'s arguments aren't captured into state here — there's no plan_9-scoped consumer for them yet, and storing them in `useState` without ever reading the value back trips `tsc`'s `noUnusedLocals`. `plan_10.md` will thread `(provider, remoteConsentGranted)` into the preview-creation call it adds.

### Step 13: Full frontend suite, type-check, and a live consent check against a real backend

```powershell
cd frontend
corepack pnpm test
corepack pnpm exec tsc -b --noEmit
```

Expected: 28 tests pass across 7 files; `tsc` prints nothing.

Then verify the consent gate for real, against a running backend — not just `pytest` — since this is the highest-risk fix in this part:

1. Start the backend with a **scratch** data directory so this doesn't write into the real `%LOCALAPPDATA%\TuneForge` the shipped app will use:
   ```powershell
   $env:TUNEFORGE_DATA_DIR = "C:\tmp\tf-scratch"
   cd backend
   uv run python -m tuneforge.main
   ```
   **Set the env var as its own statement, before starting the process.** An inline-prefixed form (`TUNEFORGE_DATA_DIR=... uv run ...`) run as a backgrounded job did not reliably propagate in this environment during this document's own verification, and the process silently fell back to the real `LOCALAPPDATA` default — writing real-looking test data into the exact directory the shipped app will use. Confirm which directory actually got used by checking where `tuneforge.db` shows up, not by trusting the env var was received.
2. In a browser, drive the wizard through to the new provider step, create a **remote**-scoped provider, and confirm the UI behavior from Steps 10–11 (Continue disabled until consent is checked).
3. With a real bearer token (`GET /api/session`) and the real `plan_id`/remote `provider_id` from that session (query the scratch `tuneforge.db` directly, or add temporary logging), `POST /api/runs/preview`:
   - without `"remote_consent": true` → expect `422` with the consent-required message.
   - with `"remote_consent": true` → expect `201`, and confirm `runs.remote_consent_granted_at` is non-null in the database for that run.

Both outcomes were confirmed exactly as designed during this document's own verification. Delete the scratch data directory afterward.

### Step 14: Commit

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
git add backend/tuneforge/storage/models.py backend/tuneforge/api/runs.py
git add backend/tuneforge/jobs/runner.py backend/tuneforge/generation/generator.py
git add backend/tests/api/test_runs.py backend/tests/generation/test_generator.py backend/tests/jobs/test_runner.py
git add frontend/src/App.tsx frontend/src/api/types.ts frontend/src/api/providers.ts
git add frontend/src/features/provider-config
git commit -m "feat: require and thread explicit consent for remote provider runs"
```

---

## When you're done

Do not start anything from `plan_10.md`'s list (column mapping, preview, run progress, export, styling). Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` from `backend/` (expect 233) and `corepack pnpm test` + `corepack pnpm exec tsc -b --noEmit` from `frontend/` (expect 28).
2. Output of `git log --oneline` — should show one new commit.
3. Confirmation that Step 13's live consent check actually happened by hand (422 without consent, 201 with) and which directory the scratch backend actually wrote to — this document flags a real risk of that env var silently not propagating.
4. Anything else you had to deviate from in this document, and why.
5. If you find a correctness issue anywhere in the code exactly as given here — not a style preference, an actual bug — stop and describe it rather than silently changing behavior.
