# TuneForge Implementation Plan — Part 3 (Tasks 5 & 6)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec. Tasks 1–4 are already implemented and committed: the FastAPI shell, SQLite persistence, the provider client (`tuneforge.providers`), credential storage (`tuneforge.security.credentials`), and the model analyzer (`tuneforge.models.analyzer`). This part builds the deterministic training planner on top of the analyzer's output, plus a research fallback that only runs when a user rejects what the planner recommends. Do not implement anything beyond Task 5 and Task 6 — `plan_4.md` covers what's next.
>
> Every code block here has already been run and verified (35 tests, all green) — copy it as-is. Only write your own code where a step explicitly says so and gives you the test it must pass.
>
> When both tasks are done, stop and produce the completion report at the bottom. Do not push to GitHub.

**Goal (this part):** Turn a user's stated training goal plus a model's analyzed capabilities into a concrete, hashable `TrainingPlan` — and when the user rejects that recommendation, re-check local evidence and official sources before falling back to letting them pick manually.

**Architecture:** Two independent, framework-free modules. `tuneforge.planning` is pure and synchronous — no I/O, just the objective matrix and hash computation. `tuneforge.research` is async and does the one kind of I/O this part touches: fetching a Hugging Face model card through an allowlist, after re-running the (already-built) analyzer locally first. Neither module touches FastAPI routes, SQLite, or the provider client — wiring plans into the API and persisting `TrainingPlanRecord` rows happens in a later part.

**Tech Stack (new in this part):** none — reuses `pydantic` and `httpx`, both already dependencies.

## Global Constraints

Repeated from Parts 1–2, still binding:

- Windows-first local web application. Bind only to `127.0.0.1` (unaffected here).
- Python 3.12, uv-managed environment, no conda.
- API keys/tokens go through Windows Credential Manager only, never `.env`/SQLite/logs.
- Training objectives: CPT, prompt-completion SFT, conversational SFT, DPO — nothing else.
- DPO requires a judge model different from the generator model.
- LLM judging is optional for CPT and SFT (this is a later-task/runtime concern — Task 5 just needs to not accidentally require it).

## Development Environment

Same as before — everything Python through **uv**, no conda, no direct `pip`.

```powershell
cd backend
uv sync
uv run pytest -q
```

No new dependencies this part, so `uv sync` should be a no-op if you've already run Part 2's setup.

## Repository State

Same repo, branch `main`, `origin` already set. Commit locally as instructed. **Do not run `git push`.**

## File Structure (this part)

```
backend/
  tuneforge/
    planning/
      __init__.py
      intents.py
      schemas.py
      planner.py
    research/
      __init__.py
      official_sources.py
      resolver.py
  tests/
    planning/
      __init__.py
      test_planner.py
    research/
      __init__.py
      test_official_sources.py
      test_resolver.py
```

---

### Task 5: Goal wizard and deterministic training planner

**Files:**
- Create: `backend/tuneforge/planning/__init__.py`
- Create: `backend/tuneforge/planning/intents.py`
- Create: `backend/tuneforge/planning/schemas.py`
- Create: `backend/tuneforge/planning/planner.py`
- Create: `backend/tests/planning/__init__.py`
- Create: `backend/tests/planning/test_planner.py`

**Interfaces consumed:** `tuneforge.models.analyzer.ModelProfile` (Task 4), `tuneforge.models.evidence.Evidence` (Task 4).

**Interfaces produced (Task 6 and later parts rely on these exact names):**
- `tuneforge.planning.intents.TrainingIntent` — matches `PLAN.md`'s canonical contract exactly (`goal`, `desired_behavior`, `language`, `output_style`)
- `tuneforge.planning.schemas.TrainingPlan` — matches `PLAN.md`'s canonical contract exactly (`objective`, `canonical_schema`, `target_rows`, `examples_per_chunk`, `generator_profile_id`, `judge_profile_id`, `required_validators`, `evidence`, `confidence`, `plan_hash`)
- `tuneforge.planning.planner.recommend_plan(intent, model_profile, *, target_rows, examples_per_chunk=1, generator_profile_id=None, judge_profile_id=None, objective_override=None) -> TrainingPlan`
- `tuneforge.planning.planner.ChatTemplateRequiredError`, `.DistinctJudgeRequiredError`
- `tuneforge.planning.planner.OBJECTIVE_BY_GOAL`, `.REQUIRED_VALIDATORS_BY_OBJECTIVE` (dicts later tasks can read directly rather than re-deriving)

**On `PLAN.md`'s "Approve, Change Objective, Inspect Evidence, and Cancel" checklist item:** there's no dedicated method for each of these in this module, and that's deliberate, not a gap — there's no API or persistence layer wired up yet for a plan to be "in progress" against. Here's how each maps to what's actually built:
- **Change Objective** → call `recommend_plan` again with `objective_override` set explicitly instead of letting `intent.goal` decide.
- **Approve** → the caller (a later task) persists the returned `TrainingPlan` (into `TrainingPlanRecord` from Task 2); nothing to do here.
- **Inspect Evidence** → read `.evidence` off the result.
- **Cancel** → discard the returned object.

#### Step 1: Write the failing tests (RED)

Create `backend/tuneforge/planning/__init__.py` (empty) and `backend/tests/planning/__init__.py` (empty).

Create `backend/tests/planning/test_planner.py`:

```python
import uuid

import pytest

from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.intents import TrainingIntent
from tuneforge.planning.planner import ChatTemplateRequiredError, DistinctJudgeRequiredError, recommend_plan


def _model_profile(*, chat_template_found: bool, model_id: str = "org/model", confidence: float = 0.9) -> ModelProfile:
    return ModelProfile(
        source="huggingface",
        model_id=model_id,
        architecture="Qwen2ForCausalLM",
        model_type="qwen2",
        is_causal_lm=True,
        is_chat_model=chat_template_found,
        chat_template_found=chat_template_found,
        context_length=32768,
        modalities=["text"],
        evidence=[],
        confidence=confidence,
    )


def _intent(goal: str) -> TrainingIntent:
    return TrainingIntent(goal=goal, desired_behavior="answer questions about policy", language="en")


def test_qwen_instruct_selects_conversational_sft():
    plan = recommend_plan(
        _intent("multi_turn_conversation"),
        _model_profile(chat_template_found=True, model_id="Qwen/Qwen2.5-7B-Instruct"),
        target_rows=1000,
    )
    assert plan.objective == "sft_conversation"
    assert plan.canonical_schema == "SFTConversationRecord"


def test_base_model_supports_cpt():
    plan = recommend_plan(
        _intent("domain_adaptation"),
        _model_profile(chat_template_found=False, model_id="meta-llama/Llama-3-8B"),
        target_rows=1000,
    )
    assert plan.objective == "cpt"


def test_base_model_supports_prompt_completion_sft():
    plan = recommend_plan(
        _intent("single_turn_instruction"),
        _model_profile(chat_template_found=False, model_id="meta-llama/Llama-3-8B"),
        target_rows=1000,
    )
    assert plan.objective == "sft_prompt_completion"


def test_user_can_override_recommended_objective():
    plan = recommend_plan(
        _intent("domain_adaptation"),
        _model_profile(chat_template_found=False),
        target_rows=1000,
        objective_override="sft_prompt_completion",
    )
    assert plan.objective == "sft_prompt_completion"
    assert any("overridden" in e.detail for e in plan.evidence if e.field == "objective")


def test_conversational_sft_requires_chat_template():
    with pytest.raises(ChatTemplateRequiredError):
        recommend_plan(
            _intent("multi_turn_conversation"),
            _model_profile(chat_template_found=False),
            target_rows=1000,
        )


def test_dpo_requires_chat_template():
    with pytest.raises(ChatTemplateRequiredError):
        recommend_plan(
            _intent("preference_alignment"),
            _model_profile(chat_template_found=False),
            target_rows=1000,
            judge_profile_id=uuid.uuid4(),
            generator_profile_id=uuid.uuid4(),
        )


def test_dpo_requires_a_judge():
    with pytest.raises(DistinctJudgeRequiredError):
        recommend_plan(
            _intent("preference_alignment"),
            _model_profile(chat_template_found=True),
            target_rows=1000,
            generator_profile_id=uuid.uuid4(),
        )


def test_dpo_rejects_same_generator_and_judge():
    shared_id = uuid.uuid4()
    with pytest.raises(DistinctJudgeRequiredError):
        recommend_plan(
            _intent("preference_alignment"),
            _model_profile(chat_template_found=True),
            target_rows=1000,
            generator_profile_id=shared_id,
            judge_profile_id=shared_id,
        )


def test_dpo_succeeds_with_distinct_generator_and_judge():
    plan = recommend_plan(
        _intent("preference_alignment"),
        _model_profile(chat_template_found=True),
        target_rows=1000,
        generator_profile_id=uuid.uuid4(),
        judge_profile_id=uuid.uuid4(),
    )
    assert plan.objective == "dpo"
    assert "judge_required" in plan.required_validators


def test_plan_hash_is_stable_for_identical_inputs():
    profile = _model_profile(chat_template_found=False)
    intent = _intent("domain_adaptation")
    plan_a = recommend_plan(intent, profile, target_rows=1000)
    plan_b = recommend_plan(intent, profile, target_rows=1000)
    assert plan_a.plan_hash == plan_b.plan_hash


def test_plan_hash_changes_when_target_rows_changes():
    profile = _model_profile(chat_template_found=False)
    intent = _intent("domain_adaptation")
    plan_a = recommend_plan(intent, profile, target_rows=1000)
    plan_b = recommend_plan(intent, profile, target_rows=2000)
    assert plan_a.plan_hash != plan_b.plan_hash
```

This covers every objective-selection scenario `PLAN.md` names: Qwen instruct → conversational SFT, base model → CPT and prompt-completion SFT, user override, chat-template gating for conversational SFT and DPO, and DPO's distinct-judge requirement (missing judge, same judge as generator, and the success case).

Run it and confirm it fails on the missing modules:

```powershell
cd backend
uv run pytest tests/planning/test_planner.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.planning.intents'`.

#### Step 2: Implement (GREEN)

Create `backend/tuneforge/planning/intents.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class TrainingIntent(BaseModel):
    goal: Literal[
        "domain_adaptation",
        "single_turn_instruction",
        "multi_turn_conversation",
        "preference_alignment",
    ]
    desired_behavior: str
    language: str
    output_style: str | None = None
```

Create `backend/tuneforge/planning/schemas.py`:

```python
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

from tuneforge.models.evidence import Evidence


class TrainingPlan(BaseModel):
    objective: Literal["cpt", "sft_prompt_completion", "sft_conversation", "dpo"]
    canonical_schema: str
    target_rows: int
    examples_per_chunk: int
    generator_profile_id: uuid.UUID | None
    judge_profile_id: uuid.UUID | None
    required_validators: list[str]
    evidence: list[Evidence]
    confidence: float
    plan_hash: str
```

Create `backend/tuneforge/planning/planner.py`:

```python
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Literal

from tuneforge.models.analyzer import ModelProfile
from tuneforge.models.evidence import Evidence
from tuneforge.planning.intents import TrainingIntent
from tuneforge.planning.schemas import TrainingPlan

OBJECTIVE_BY_GOAL: dict[str, str] = {
    "domain_adaptation": "cpt",
    "single_turn_instruction": "sft_prompt_completion",
    "multi_turn_conversation": "sft_conversation",
    "preference_alignment": "dpo",
}

CANONICAL_SCHEMA_BY_OBJECTIVE: dict[str, str] = {
    "cpt": "CPTRecord",
    "sft_prompt_completion": "SFTPromptCompletionRecord",
    "sft_conversation": "SFTConversationRecord",
    "dpo": "DPORecord",
}

_BASE_VALIDATORS = ["structural", "deduplication", "source_grounding"]

REQUIRED_VALIDATORS_BY_OBJECTIVE: dict[str, list[str]] = {
    "cpt": [*_BASE_VALIDATORS],
    "sft_prompt_completion": [*_BASE_VALIDATORS],
    "sft_conversation": [*_BASE_VALIDATORS, "chat_role_order"],
    "dpo": [*_BASE_VALIDATORS, "chat_role_order", "judge_required"],
}

CHAT_TEMPLATE_REQUIRED_OBJECTIVES = {"sft_conversation", "dpo"}


class ChatTemplateRequiredError(RuntimeError):
    pass


class DistinctJudgeRequiredError(RuntimeError):
    pass


def _compute_plan_hash(
    *,
    objective: str,
    canonical_schema: str,
    target_rows: int,
    examples_per_chunk: int,
    generator_profile_id: uuid.UUID | None,
    judge_profile_id: uuid.UUID | None,
    required_validators: list[str],
) -> str:
    payload = {
        "objective": objective,
        "canonical_schema": canonical_schema,
        "target_rows": target_rows,
        "examples_per_chunk": examples_per_chunk,
        "generator_profile_id": str(generator_profile_id) if generator_profile_id else None,
        "judge_profile_id": str(judge_profile_id) if judge_profile_id else None,
        "required_validators": sorted(required_validators),
    }
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def recommend_plan(
    intent: TrainingIntent,
    model_profile: ModelProfile,
    *,
    target_rows: int,
    examples_per_chunk: int = 1,
    generator_profile_id: uuid.UUID | None = None,
    judge_profile_id: uuid.UUID | None = None,
    objective_override: Literal["cpt", "sft_prompt_completion", "sft_conversation", "dpo"] | None = None,
) -> TrainingPlan:
    """Deterministically recommend a training plan.

    `objective_override` is how a caller implements "Change Objective": call
    again with an explicit objective instead of the one the intent maps to.
    "Approve" and "Cancel" have no dedicated methods here — the caller either
    persists the returned TrainingPlan (approve) or discards it (cancel);
    "Inspect Evidence" is just reading `.evidence` off the result.
    """
    objective = objective_override or OBJECTIVE_BY_GOAL[intent.goal]

    if objective in CHAT_TEMPLATE_REQUIRED_OBJECTIVES and not model_profile.chat_template_found:
        raise ChatTemplateRequiredError(
            f"{model_profile.model_id} has no chat template, which {objective!r} requires"
        )

    if objective == "dpo":
        if judge_profile_id is None:
            raise DistinctJudgeRequiredError("dpo requires a judge_profile_id")
        if generator_profile_id is not None and judge_profile_id == generator_profile_id:
            raise DistinctJudgeRequiredError("dpo requires a judge model different from the generator model")

    canonical_schema = CANONICAL_SCHEMA_BY_OBJECTIVE[objective]
    required_validators = REQUIRED_VALIDATORS_BY_OBJECTIVE[objective]

    evidence = [
        *model_profile.evidence,
        Evidence(
            field="objective",
            value=objective,
            source="objective_matrix",
            detail=f"goal={intent.goal!r} mapped to objective={objective!r}"
            + (" (overridden)" if objective_override else ""),
        ),
    ]

    plan_hash = _compute_plan_hash(
        objective=objective,
        canonical_schema=canonical_schema,
        target_rows=target_rows,
        examples_per_chunk=examples_per_chunk,
        generator_profile_id=generator_profile_id,
        judge_profile_id=judge_profile_id,
        required_validators=required_validators,
    )

    return TrainingPlan(
        objective=objective,
        canonical_schema=canonical_schema,
        target_rows=target_rows,
        examples_per_chunk=examples_per_chunk,
        generator_profile_id=generator_profile_id,
        judge_profile_id=judge_profile_id,
        required_validators=required_validators,
        evidence=evidence,
        confidence=model_profile.confidence,
        plan_hash=plan_hash,
    )
```

Run the tests again:

```powershell
uv run pytest tests/planning/test_planner.py -q
```

Expected: all pass.

#### Step 3: Run the full backend suite and commit

```powershell
uv run pytest -q
```

Expected: every test from Parts 1–2 and this task passes.

```powershell
git add backend
git commit -m "feat: add model-aware training planner"
```

---

### Task 6: Official-evidence fallback

**Files:**
- Create: `backend/tuneforge/research/__init__.py`
- Create: `backend/tuneforge/research/official_sources.py`
- Create: `backend/tuneforge/research/resolver.py`
- Create: `backend/tests/research/__init__.py`
- Create: `backend/tests/research/test_official_sources.py`
- Create: `backend/tests/research/test_resolver.py`

**Interfaces consumed:** `tuneforge.models.analyzer.analyze_model`/`.ModelProfile` (Task 4), `tuneforge.planning.intents.TrainingIntent`, `tuneforge.planning.planner.recommend_plan`/`.ChatTemplateRequiredError`, `tuneforge.planning.schemas.TrainingPlan` (this part's Task 5).

**Interfaces produced:**
- `tuneforge.research.official_sources.fetch_source(url, client) -> FetchedSource`, `.model_card_url(model_id) -> str`, `.SourceNotAllowedError`, `.FetchedSource`
- `tuneforge.research.resolver.resolve_rejected_recommendation(intent, model_profile, *, client, target_rows, **plan_kwargs) -> ResearchResult`, `.ResearchResult`

**Scope note on what "research" actually means here:** the temptation is to scrape a model card's free text and guess whether it implies a chat template exists. That's not implemented, deliberately — turning prose into a boolean capability claim without an LLM would be fabricating precision `PLAN.md`'s own "avoid hallucinating capabilities" spirit doesn't support, and Task 4's `chat_template_found` is already the authoritative, deterministic answer to that question. What "research" does instead: re-run the same deterministic analyzer (in case the original result was stale — e.g. a transient fetch that's now cached differently), and if it's still inconclusive, fetch the model card purely so its URL/hash/excerpt can be shown to the human as **citations** next to a fallback to manual selection — not to auto-decide anything from parsing it.

#### Step 1: Official sources allowlist — write the failing tests (RED)

Create `backend/tuneforge/research/__init__.py` (empty) and `backend/tests/research/__init__.py` (empty).

Create `backend/tests/research/test_official_sources.py`:

```python
import httpx
import pytest

from tuneforge.research.official_sources import SourceNotAllowedError, fetch_source, model_card_url


def test_model_card_url_points_at_huggingface():
    assert model_card_url("Qwen/Qwen2.5-7B-Instruct") == "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct"


async def test_fetch_source_rejects_non_allowlisted_host():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("https://evil.example.com/page", client)


async def test_fetch_source_rejects_lookalike_host():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("https://huggingface.co.attacker.com/page", client)


async def test_fetch_source_rejects_prefixed_lookalike_host():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("https://evil-huggingface.co/page", client)


async def test_fetch_source_rejects_disallowed_github_repo():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("https://github.com/some-random/repo", client)


async def test_fetch_source_rejects_non_https():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("http://huggingface.co/org/model", client)


async def test_fetch_source_allows_huggingface_model_card():
    def handler(request):
        return httpx.Response(200, text="This model uses a chat template for conversations.")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await fetch_source("https://huggingface.co/Qwen/Qwen2.5-7B-Instruct", client)

    assert result.url == "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct"
    assert result.sha256
    assert "chat template" in result.excerpt


async def test_fetch_source_allows_official_transformers_repo():
    def handler(request):
        return httpx.Response(200, text="docs")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await fetch_source("https://github.com/huggingface/transformers/blob/main/README.md", client)
    assert result.sha256


async def test_fetch_source_raises_on_http_error(monkeypatch):
    def handler(request):
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_source("https://huggingface.co/org/missing-model", client)
```

The lookalike-host tests matter: a naive check like `"huggingface.co" in url` would let `https://huggingface.co.attacker.com` and `https://evil-huggingface.co` both through — this is exactly the kind of allowlist bug that turns "fetch only official sources" into "fetch anything with the right substring in its name." The implementation below parses the actual hostname and checks exact/subdomain matches, not substrings.

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/research/test_official_sources.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.research.official_sources'`.

#### Step 2: Official sources allowlist — implement (GREEN)

Create `backend/tuneforge/research/official_sources.py`:

```python
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

# (host, path prefix) pairs. Both must match — "github.com" alone would let
# through any repo on GitHub, not just the official ones we trust.
ALLOWED_SOURCES = (
    ("huggingface.co", "/"),
    ("github.com", "/huggingface/transformers"),
    ("github.com", "/huggingface/trl"),
    ("github.com", "/unslothai/unsloth"),
    ("docs.unsloth.ai", "/"),
)


class SourceNotAllowedError(RuntimeError):
    pass


class FetchedSource(BaseModel):
    url: str
    retrieved_at: datetime
    sha256: str
    excerpt: str


def _is_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    hostname = parsed.hostname or ""
    path = parsed.path or "/"
    for host, prefix in ALLOWED_SOURCES:
        host_matches = hostname == host or hostname.endswith(f".{host}")
        if host_matches and path.startswith(prefix):
            return True
    return False


async def fetch_source(url: str, client: httpx.AsyncClient) -> FetchedSource:
    if not _is_allowed(url):
        raise SourceNotAllowedError(f"{url} is not on the official-sources allowlist")
    response = await client.get(url)
    response.raise_for_status()
    text = response.text
    return FetchedSource(
        url=url,
        retrieved_at=datetime.now(timezone.utc),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        excerpt=text[:500],
    )


def model_card_url(model_id: str) -> str:
    return f"https://huggingface.co/{model_id}"
```

Run the tests again:

```powershell
uv run pytest tests/research/test_official_sources.py -q
```

Expected: all pass.

#### Step 3: Resolver — write the failing tests (RED)

Create `backend/tests/research/test_resolver.py`:

```python
import httpx

from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.intents import TrainingIntent
from tuneforge.research.resolver import resolve_rejected_recommendation


def _model_profile(*, chat_template_found: bool, model_id="org/model", source="huggingface") -> ModelProfile:
    return ModelProfile(
        source=source,
        model_id=model_id,
        architecture="LlamaForCausalLM",
        model_type="llama",
        is_causal_lm=True,
        is_chat_model=chat_template_found,
        chat_template_found=chat_template_found,
        context_length=4096,
        modalities=["text"],
        evidence=[],
        confidence=0.9,
    )


def _intent() -> TrainingIntent:
    return TrainingIntent(goal="multi_turn_conversation", desired_behavior="chat", language="en")


async def test_reinspection_succeeds_without_network_when_template_now_found(monkeypatch):
    profile = _model_profile(chat_template_found=False)

    def fake_analyze(model_id, *, source):
        return _model_profile(chat_template_found=True, model_id=model_id, source=source)

    monkeypatch.setattr("tuneforge.research.resolver.analyze_model", fake_analyze)

    def handler(request):
        raise AssertionError("should not fetch anything when reinspection already resolves it")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await resolve_rejected_recommendation(_intent(), profile, client=client, target_rows=1000)

    assert result.requires_manual_selection is False
    assert result.plan is not None
    assert result.plan.objective == "sft_conversation"
    assert result.citations == []


async def test_falls_back_to_manual_selection_with_citations_when_still_missing(monkeypatch):
    profile = _model_profile(chat_template_found=False)
    monkeypatch.setattr("tuneforge.research.resolver.analyze_model", lambda model_id, *, source: profile)

    def handler(request):
        return httpx.Response(200, text="no chat template mentioned here")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await resolve_rejected_recommendation(_intent(), profile, client=client, target_rows=1000)

    assert result.requires_manual_selection is True
    assert result.plan is None
    assert len(result.citations) == 1
    assert result.citations[0].url == "https://huggingface.co/org/model"


async def test_local_model_skips_network_and_falls_back_to_manual_selection():
    profile = _model_profile(chat_template_found=False, source="local")

    def handler(request):
        raise AssertionError("local models have no HF model card to fetch")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await resolve_rejected_recommendation(_intent(), profile, client=client, target_rows=1000)

    assert result.requires_manual_selection is True
    assert result.citations == []
```

Run it and confirm it fails on the missing module:

```powershell
uv run pytest tests/research/test_resolver.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.research.resolver'`.

#### Step 4: Resolver — implement (GREEN)

Create `backend/tuneforge/research/resolver.py`:

```python
from __future__ import annotations

import httpx
from pydantic import BaseModel

from tuneforge.models.analyzer import ModelProfile, analyze_model
from tuneforge.planning.intents import TrainingIntent
from tuneforge.planning.planner import ChatTemplateRequiredError, recommend_plan
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.research.official_sources import FetchedSource, fetch_source, model_card_url


class ResearchResult(BaseModel):
    plan: TrainingPlan | None
    citations: list[FetchedSource]
    confidence: float
    requires_manual_selection: bool


async def resolve_rejected_recommendation(
    intent: TrainingIntent,
    model_profile: ModelProfile,
    *,
    client: httpx.AsyncClient,
    target_rows: int,
    **plan_kwargs,
) -> ResearchResult:
    """Only call this after the user has rejected `recommend_plan`'s result.

    Order matters here: local metadata is always rechecked before any
    network call, and a Hugging Face model card is only fetched for
    `source="huggingface"` profiles that are still inconclusive after that
    recheck — a local model has no HF model card to fetch at all.
    """
    if model_profile.source == "huggingface":
        refreshed_profile = analyze_model(model_profile.model_id, source=model_profile.source)
    else:
        refreshed_profile = model_profile

    try:
        plan = recommend_plan(intent, refreshed_profile, target_rows=target_rows, **plan_kwargs)
        return ResearchResult(plan=plan, citations=[], confidence=plan.confidence, requires_manual_selection=False)
    except ChatTemplateRequiredError:
        pass

    if refreshed_profile.source != "huggingface":
        return ResearchResult(plan=None, citations=[], confidence=0.0, requires_manual_selection=True)

    card = await fetch_source(model_card_url(refreshed_profile.model_id), client)
    return ResearchResult(plan=None, citations=[card], confidence=0.0, requires_manual_selection=True)
```

`resolve_rejected_recommendation` only reacts to `ChatTemplateRequiredError` — that's the one rejection reason official evidence could plausibly change. `DistinctJudgeRequiredError` (missing/duplicate DPO judge) isn't a research problem, it's a form-input problem; don't route it through here.

Run the tests again:

```powershell
uv run pytest tests/research/test_resolver.py -q
```

Expected: all pass.

#### Step 5: Run the full backend suite and commit

```powershell
uv run pytest -q
```

Expected: every test from Parts 1–2 and this part's Tasks 5–6 passes.

```powershell
git add backend
git commit -m "feat: add official evidence research fallback"
```

---

## When you're done

Do not start Task 7. Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` (full pass/fail summary) from `backend/`.
2. Output of `git log --oneline` — should show two new commits on top of Part 2's tip: `feat: add model-aware training planner` and `feat: add official evidence research fallback`.
3. Anything you had to deviate from in this document, and why.
4. If you find a correctness issue in the code exactly as given here — not a style preference, an actual bug — stop and describe it rather than silently changing behavior. Pay particular attention to the `_is_allowed` host-matching logic in `official_sources.py` if you touch it at all; that's a security boundary, not a convenience check.
