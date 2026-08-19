# TuneForge Implementation Plan — Part 5 (Tasks 9 & 10)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec. Tasks 1–8 are already implemented and committed. This part is a deliberate deviation from `PLAN.md`'s original Task 9, decided directly by Tushar: **generation goes straight through the OpenAI-compatible provider client from Task 3 — there is no NVIDIA NeMo Data Designer integration and no external "Ligaments AI" service call in this codebase.** `PLAN.md`'s Task 9 file list (`generation/protocol.py`, `generation/nemo_adapter.py`, `generation/specs.py`) is superseded by what's below. Do not add a NeMo dependency, do not add an HTTP client pointed at any external synthetic-data service. Do not implement anything beyond Task 9 and Task 10 as scoped here — `plan_6.md` covers what's next.
>
> Every code block has already been run and verified (114 tests, all green, including simulated multi-turn LLM conversations via `httpx.MockTransport`) — copy it as-is. Only write your own code where a step explicitly says so.
>
> When both tasks are done, stop and produce the completion report at the bottom. Do not push to GitHub.

**Goal (this part):** Turn `SourceRecord` chunks (Task 7) into canonical training records by calling the LLM directly through the existing provider client — no generation needed at all for CPT, a single grounded Q&A call for SFT, and a generate-then-judge candidate selection for DPO. Then run every record (whether it came from this generation step or from Task 8's normalization) through one shared quality gate: structural validation, deduplication, and judging.

**Architecture:** `tuneforge.generation` depends only on `tuneforge.providers` (Task 3), `tuneforge.planning` (Task 5), and `tuneforge.records` (Task 7) — no new external service of any kind. `tuneforge.validation` is objective-agnostic: it doesn't care whether a record came from generation or normalization, it just enforces the same gate on whatever canonical records it's handed. This part also does a small, deliberate refactor of Task 8's `normalization/mappers.py` to remove a duplicated role-alternation check now that `tuneforge.validation.structural` is the one place that logic lives.

**Tech Stack (new in this part):** `datasketch` (MinHash LSH for near-duplicate detection — pure Python + numpy, no heavy dependencies; verified against the real package before being added here).

## Global Constraints

Repeated from Parts 1–4, still binding, with the Task 9 deviation noted above:

- Windows-first, Python 3.12, uv-managed, no conda.
- Every remote run requires explicit transmission approval — already enforced by `RemoteConsentRequiredError` in the Task 3 provider client; this part's generation calls go through that same client, so nothing new is needed here to satisfy this.
- DPO requires a judge model different from the generator model — already enforced by Task 5's planner (`DistinctJudgeRequiredError`) before a plan is ever approved; this part receives already-distinct generator/judge providers, it doesn't re-check distinctness itself.
- LLM judging is optional for CPT and SFT, mandatory for DPO.
- Preview exactly 20 rows before full generation — **not implemented in this part**; that's a job/run-orchestration concern (`PLAN.md` Task 11), which doesn't exist yet. This part produces the generation and validation building blocks Task 11 will call per-row.

## Development Environment

Same as before — **uv**, no conda, no direct `pip`.

```powershell
cd backend
uv sync
uv run pytest -q
```

No heavy dependencies this part — `datasketch` is small (numpy is already a dependency via Docling).

## Repository State

Same repo, branch `main`, `origin` already set. Commit locally as instructed. **Do not run `git push`.**

## File Structure (this part)

```
backend/
  pyproject.toml                        (modified — add datasketch)
  tuneforge/
    generation/
      __init__.py
      specs.py
      generator.py
    validation/
      __init__.py
      structural.py
      deduplication.py
      judging.py
      pipeline.py
    normalization/
      mappers.py                        (modified — reuse shared role-alternation check)
  tests/
    generation/
      __init__.py
      test_generator.py
    validation/
      __init__.py
      test_structural.py
      test_deduplication.py
      test_judging.py
      test_pipeline.py
```

---

### Task 9: Generation via the existing provider client

**Files:**
- Create: `backend/tuneforge/generation/__init__.py`
- Create: `backend/tuneforge/generation/specs.py`
- Create: `backend/tuneforge/generation/generator.py`
- Create: `backend/tests/generation/__init__.py`
- Create: `backend/tests/generation/test_generator.py`

**Interfaces consumed:** `tuneforge.providers.openai_compatible.OpenAICompatibleProvider` (Task 3), `tuneforge.providers.protocol.GenerationRequest` (Task 3), `tuneforge.planning.schemas.TrainingPlan` (Task 5), `tuneforge.records.*` (Task 7).

**Interfaces produced (Task 10 and later parts rely on these exact names):**
- `tuneforge.generation.specs.GenerationSpec`
- `tuneforge.generation.generator.build_cpt_record(source) -> CPTRecord`
- `tuneforge.generation.generator.generate_sft_prompt_completion_record(provider, source, spec) -> SFTPromptCompletionRecord | None`
- `tuneforge.generation.generator.generate_sft_conversation_record(provider, source, spec) -> SFTConversationRecord | None`
- `tuneforge.generation.generator.generate_dpo_record(generator, judge, source, spec) -> DPORecord | None`
- `tuneforge.generation.generator.generate_record(*, plan, source, generator, judge, spec)` — dispatches on `plan.objective`
- `tuneforge.generation.generator.MalformedGenerationError`, `.GroundingError`

**On why CPT needs no LLM call:** CPT (continued pretraining) trains directly on the source text — the training data *is* the document, not a derivative of it. Calling an LLM to "generate" CPT data would be rewriting text that `PLAN.md`'s own constraints say should pass through unmodified. `build_cpt_record` is a plain field mapping.

**On the retry design (`spec.max_retries`):** each generation function makes up to `max_retries + 1` attempts, and returns `None` (not an exception) if every attempt fails — the caller (Task 11's job runner, later) is expected to count `None`s as rejections rather than have one bad chunk crash an entire run. Malformed JSON and ungrounded quotes are both retryable; nothing else is caught, so a real transport/auth error from the provider still propagates and stops the run, which is correct — that's not a "try again" situation.

#### Step 1: Add dependencies

No new dependency for Task 9 itself (`httpx`, `pydantic` already present). Skip to Step 2.

#### Step 2: Write the failing tests (RED)

Create `backend/tuneforge/generation/__init__.py` (empty), `backend/tests/generation/__init__.py` (empty).

Create `backend/tests/generation/test_generator.py`:

```python
import json
import uuid

import httpx

from tuneforge.generation.generator import (
    build_cpt_record,
    generate_dpo_record,
    generate_sft_conversation_record,
    generate_sft_prompt_completion_record,
)
from tuneforge.generation.specs import GenerationSpec
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile
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


def _provider(handler) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(name="test", base_url="http://127.0.0.1:9999", model="test-model", endpoint_scope="local")
    return OpenAICompatibleProvider(profile, client)


def _chat_response(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


def test_cpt_record_is_a_passthrough_with_no_generation():
    source = _source()
    record = build_cpt_record(source)
    assert record.text == SOURCE_TEXT
    assert record.metadata.chunk_id == "doc-0"


async def test_sft_prompt_completion_accepts_grounded_candidate():
    def handler(request):
        return _chat_response(
            {"question": "How many vacation days?", "answer": "20 days.", "supporting_quote": "20 days of paid vacation"}
        )

    provider = _provider(handler)
    record = await generate_sft_prompt_completion_record(provider, _source(), GenerationSpec(desired_behavior="qa"))

    assert record is not None
    assert record.prompt == "How many vacation days?"
    assert record.completion == "20 days."
    assert record.metadata.extra["supporting_quote"] == "20 days of paid vacation"


async def test_sft_prompt_completion_rejects_ungrounded_quote_after_retries():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return _chat_response(
            {"question": "How many days?", "answer": "20", "supporting_quote": "this text is not in the source"}
        )

    provider = _provider(handler)
    record = await generate_sft_prompt_completion_record(
        provider, _source(), GenerationSpec(desired_behavior="qa", max_retries=2)
    )

    assert record is None
    assert calls["count"] == 3  # initial attempt + 2 retries


async def test_sft_prompt_completion_recovers_after_one_malformed_attempt():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return _chat_response(
            {"question": "How many days?", "answer": "20 days.", "supporting_quote": "20 days of paid vacation"}
        )

    provider = _provider(handler)
    record = await generate_sft_prompt_completion_record(
        provider, _source(), GenerationSpec(desired_behavior="qa", max_retries=2)
    )

    assert record is not None
    assert calls["count"] == 2


async def test_sft_conversation_produces_user_assistant_pair():
    def handler(request):
        return _chat_response(
            {"question": "How many vacation days?", "answer": "20 days.", "supporting_quote": "20 days of paid vacation"}
        )

    provider = _provider(handler)
    record = await generate_sft_conversation_record(provider, _source(), GenerationSpec(desired_behavior="chat"))

    assert record is not None
    assert [m.role for m in record.messages] == ["user", "assistant"]
    assert record.messages[0].content == "How many vacation days?"


async def test_dpo_record_picks_highest_and_lowest_scored_candidates():
    # generate_dpo_record makes one generator call to settle on a *question*
    # (its answer is discarded), then max_candidates more generator calls
    # each immediately followed by one judge call scoring that candidate's
    # answer. Matching on the answer text embedded in the judge prompt is
    # more robust here than counting call order.
    answer_scores = {"bad answer": 2.0, "ok answer": 5.0, "best answer": 9.0}
    candidate_answers = iter(["throwaway", "bad answer", "ok answer", "best answer"])

    def handler(request):
        payload = json.loads(request.content)
        prompt = payload["messages"][0]["content"]
        if "QUESTION:" in prompt:
            for answer, score in answer_scores.items():
                if f"ANSWER: {answer}" in prompt:
                    return _chat_response({"score": score})
            raise AssertionError(f"unscored answer in judge prompt: {prompt}")
        return _chat_response(
            {
                "question": "How many vacation days?",
                "answer": next(candidate_answers),
                "supporting_quote": "20 days of paid vacation",
            }
        )

    generator = _provider(handler)
    judge = _provider(handler)
    record = await generate_dpo_record(
        generator, judge, _source(), GenerationSpec(desired_behavior="dpo", max_candidates=3, score_margin=2.0)
    )

    assert record is not None
    assert record.chosen[0].content == "best answer"
    assert record.rejected[0].content == "bad answer"
    assert record.prompt[0].content == "How many vacation days?"


async def test_dpo_rejects_when_candidate_scores_are_too_close():
    answer_scores = {"answer-a": 5.0, "answer-b": 5.5, "answer-c": 5.2}
    candidate_answers = iter(["throwaway", "answer-a", "answer-b", "answer-c"])

    def handler(request):
        payload = json.loads(request.content)
        prompt = payload["messages"][0]["content"]
        if "QUESTION:" in prompt:
            for answer, score in answer_scores.items():
                if f"ANSWER: {answer}" in prompt:
                    return _chat_response({"score": score})
            raise AssertionError(f"unscored answer in judge prompt: {prompt}")
        return _chat_response(
            {
                "question": "How many days?",
                "answer": next(candidate_answers),
                "supporting_quote": "20 days of paid vacation",
            }
        )

    generator = _provider(handler)
    judge = _provider(handler)
    record = await generate_dpo_record(
        generator,
        judge,
        _source(),
        GenerationSpec(desired_behavior="dpo", max_candidates=3, score_margin=2.0, max_retries=0),
    )

    assert record is None
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/generation/test_generator.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.generation.specs'`.

#### Step 3: Implement (GREEN)

Create `backend/tuneforge/generation/specs.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class GenerationSpec(BaseModel):
    """Provider-independent description of what to generate — no provider
    or transport detail here, just the knobs that affect the output.
    """

    desired_behavior: str
    language: str = "en"
    max_candidates: int = 4  # DPO only: how many candidate answers to score
    score_margin: float = 2.0  # DPO only: min score gap to accept a pair (0-10 scale)
    max_retries: int = 2
```

Create `backend/tuneforge/generation/generator.py`:

```python
from __future__ import annotations

import json
import logging

from tuneforge.generation.specs import GenerationSpec
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import GenerationRequest
from tuneforge.records import (
    ChatMessage,
    CPTRecord,
    DPORecord,
    RecordMetadata,
    SFTConversationRecord,
    SFTPromptCompletionRecord,
    SourceRecord,
)

logger = logging.getLogger("tuneforge.generation")


class MalformedGenerationError(RuntimeError):
    pass


class GroundingError(RuntimeError):
    pass


def _metadata(source: SourceRecord, *, extra: dict | None = None) -> RecordMetadata:
    return RecordMetadata(
        document_id=source.document_id,
        source_name=source.source_name,
        source_hash=source.source_hash,
        chunk_id=source.chunk_id,
        extra=extra or {},
    )


def build_cpt_record(source: SourceRecord) -> CPTRecord:
    """CPT needs no generation at all — the training data *is* the source
    text. Calling an LLM here would be rewriting text PLAN.md says should
    pass through unmodified.
    """
    return CPTRecord(text=source.text, metadata=_metadata(source))


async def _generate_qa_candidate(provider: OpenAICompatibleProvider, source: SourceRecord) -> dict:
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
        )
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


async def generate_sft_prompt_completion_record(
    provider: OpenAICompatibleProvider, source: SourceRecord, spec: GenerationSpec
) -> SFTPromptCompletionRecord | None:
    last_error: Exception | None = None
    for _ in range(spec.max_retries + 1):
        try:
            candidate = await _generate_qa_candidate(provider, source)
        except (MalformedGenerationError, GroundingError) as exc:
            last_error = exc
            continue
        return SFTPromptCompletionRecord(
            prompt=candidate["question"],
            completion=candidate["answer"],
            metadata=_metadata(source, extra={"supporting_quote": candidate["supporting_quote"]}),
        )
    logger.warning("rejected chunk %s after %d attempts: %s", source.chunk_id, spec.max_retries + 1, last_error)
    return None


async def generate_sft_conversation_record(
    provider: OpenAICompatibleProvider, source: SourceRecord, spec: GenerationSpec
) -> SFTConversationRecord | None:
    last_error: Exception | None = None
    for _ in range(spec.max_retries + 1):
        try:
            candidate = await _generate_qa_candidate(provider, source)
        except (MalformedGenerationError, GroundingError) as exc:
            last_error = exc
            continue
        return SFTConversationRecord(
            messages=[
                ChatMessage(role="user", content=candidate["question"]),
                ChatMessage(role="assistant", content=candidate["answer"]),
            ],
            metadata=_metadata(source, extra={"supporting_quote": candidate["supporting_quote"]}),
        )
    logger.warning("rejected chunk %s after %d attempts: %s", source.chunk_id, spec.max_retries + 1, last_error)
    return None


async def _score_candidate(judge: OpenAICompatibleProvider, *, question: str, answer: str, source: SourceRecord) -> float:
    prompt = (
        "Rate how well the ANSWER responds to the QUESTION using only the SOURCE "
        "text below, on a scale from 0 (useless or wrong) to 10 (excellent, fully "
        "grounded in the source).\n\n"
        f"SOURCE:\n{source.text}\n\nQUESTION: {question}\n\nANSWER: {answer}\n\n"
        'Respond with only a JSON object: {"score": <number 0-10>}'
    )
    response = await judge.generate(
        GenerationRequest(messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
    )
    try:
        data = json.loads(response.content)
        return float(data["score"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise MalformedGenerationError(f"judge response was not a valid score: {exc}") from exc


async def generate_dpo_record(
    generator: OpenAICompatibleProvider,
    judge: OpenAICompatibleProvider,
    source: SourceRecord,
    spec: GenerationSpec,
) -> DPORecord | None:
    last_error: Exception | None = None
    for _ in range(spec.max_retries + 1):
        try:
            question_candidate = await _generate_qa_candidate(generator, source)
            question = question_candidate["question"]

            scored: list[tuple[float, str]] = []
            for _candidate_index in range(spec.max_candidates):
                candidate = await _generate_qa_candidate(generator, source)
                score = await _score_candidate(judge, question=question, answer=candidate["answer"], source=source)
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


async def generate_record(
    *,
    plan: TrainingPlan,
    source: SourceRecord,
    generator: OpenAICompatibleProvider,
    judge: OpenAICompatibleProvider | None,
    spec: GenerationSpec,
):
    if plan.objective == "cpt":
        return build_cpt_record(source)
    if plan.objective == "sft_prompt_completion":
        return await generate_sft_prompt_completion_record(generator, source, spec)
    if plan.objective == "sft_conversation":
        return await generate_sft_conversation_record(generator, source, spec)
    if plan.objective == "dpo":
        if judge is None:
            raise ValueError("dpo generation requires a judge provider")
        return await generate_dpo_record(generator, judge, source, spec)
    raise ValueError(f"unknown objective: {plan.objective}")
```

Run the tests again:

```powershell
uv run pytest tests/generation/test_generator.py -q
```

Expected: all pass.

#### Step 4: Run the full backend suite and commit

```powershell
uv run pytest -q
```

```powershell
git add backend
git commit -m "feat: generate training records via the provider client"
```

---

### Task 10: Validation and deduplication pipeline

**Files:**
- Create: `backend/tuneforge/validation/__init__.py`
- Create: `backend/tuneforge/validation/structural.py`
- Create: `backend/tuneforge/validation/deduplication.py`
- Create: `backend/tuneforge/validation/judging.py`
- Create: `backend/tuneforge/validation/pipeline.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/tuneforge/normalization/mappers.py`
- Create: `backend/tests/validation/__init__.py`
- Create: `backend/tests/validation/test_structural.py`
- Create: `backend/tests/validation/test_deduplication.py`
- Create: `backend/tests/validation/test_judging.py`
- Create: `backend/tests/validation/test_pipeline.py`

**Interfaces consumed:** `tuneforge.records.*` (Task 7), `tuneforge.providers.openai_compatible.OpenAICompatibleProvider` (Task 3).

**Interfaces produced:**
- `tuneforge.validation.structural.StructuralValidationError`, `.validate_role_alternation(messages)`, `.validate_structure(record)`, `.render_record_text(record) -> str`, `.validate_token_length(record, *, tokenizer, max_tokens)`
- `tuneforge.validation.deduplication.DeduplicationResult`, `.deduplicate(records, *, near_duplicate_threshold=0.85, num_perm=128) -> DeduplicationResult`
- `tuneforge.validation.judging.JudgingError`, `.judge_quality(judge, record, *, pass_threshold=6.0) -> bool`, `.judge_dpo_preference(judge, record, *, margin=1.0) -> bool`
- `tuneforge.validation.pipeline.ValidationReport`, `.run_validation_pipeline(records, *, tokenizer, max_tokens, judge=None, apply_sft_judging=False, dpo_judge_margin=1.0) -> ValidationReport`

**On the mappers.py refactor:** Task 8's `normalization/mappers.py` has its own private `_validate_role_alternation` that duplicates the exact same algorithm this task needs for conversation-shaped records. Rather than have two copies of the same role-ordering logic drift apart over time, this task moves the real implementation into `validation.structural.validate_role_alternation` and has `mappers.py` call through to it — translating the exception type back to `InvalidRecordError` so nothing about `normalization`'s existing public behavior or its own test suite changes.

**On source-grounding not being re-checked here:** `PLAN.md`'s Task 10 checklist mentions rejecting source-grounding failures, but that's already a hard gate in Task 9's generator — an ungrounded candidate is never turned into a record in the first place. By the time a record reaches this pipeline it's either already grounded (came from generation) or has no source chunk to ground against at all (came from Task 8's normalization, which works from structured rows, not document text). This pipeline only ever receives canonical records, not the original source text, so there's nothing to re-verify against here — re-implementing it would mean threading source text through every call site for a check that's already guaranteed.

#### Step 1: Add dependencies

Edit `backend/pyproject.toml` — add `datasketch` to `dependencies`:

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

#### Step 2: Structural validation — write the failing tests (RED)

Create `backend/tuneforge/validation/__init__.py` (empty), `backend/tests/validation/__init__.py` (empty).

Create `backend/tests/validation/test_structural.py`:

```python
import uuid

import pytest

from tuneforge.records import ChatMessage, CPTRecord, DPORecord, RecordMetadata, SFTConversationRecord, SFTPromptCompletionRecord
from tuneforge.validation.structural import StructuralValidationError, validate_structure, validate_token_length


def _metadata() -> RecordMetadata:
    return RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef")


class _FakeTokenizer:
    """Counts words as tokens — good enough to test the length-check logic
    without needing a real (network-downloaded) tokenizer.
    """

    def encode(self, text: str) -> list[int]:
        return text.split()


def test_valid_cpt_record_passes():
    validate_structure(CPTRecord(text="some real content", metadata=_metadata()))


def test_empty_cpt_record_fails():
    with pytest.raises(StructuralValidationError):
        validate_structure(CPTRecord(text="   ", metadata=_metadata()))


def test_valid_prompt_completion_record_passes():
    validate_structure(SFTPromptCompletionRecord(prompt="hi", completion="hello", metadata=_metadata()))


def test_empty_completion_fails():
    with pytest.raises(StructuralValidationError):
        validate_structure(SFTPromptCompletionRecord(prompt="hi", completion="  ", metadata=_metadata()))


def test_valid_conversation_passes():
    validate_structure(
        SFTConversationRecord(
            messages=[ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content="hello")],
            metadata=_metadata(),
        )
    )


def test_conversation_with_broken_role_order_fails():
    with pytest.raises(StructuralValidationError):
        validate_structure(
            SFTConversationRecord(
                messages=[ChatMessage(role="user", content="a"), ChatMessage(role="user", content="b")],
                metadata=_metadata(),
            )
        )


def test_valid_dpo_record_passes():
    validate_structure(
        DPORecord(
            prompt=[ChatMessage(role="user", content="q")],
            chosen=[ChatMessage(role="assistant", content="good")],
            rejected=[ChatMessage(role="assistant", content="bad")],
            metadata=_metadata(),
        )
    )


def test_dpo_record_with_empty_chosen_fails():
    with pytest.raises(StructuralValidationError):
        validate_structure(
            DPORecord(
                prompt=[ChatMessage(role="user", content="q")],
                chosen=[],
                rejected=[ChatMessage(role="assistant", content="bad")],
                metadata=_metadata(),
            )
        )


def test_record_within_token_limit_passes():
    record = CPTRecord(text="one two three", metadata=_metadata())
    validate_token_length(record, tokenizer=_FakeTokenizer(), max_tokens=10)


def test_record_over_token_limit_fails():
    record = CPTRecord(text="one two three four five", metadata=_metadata())
    with pytest.raises(StructuralValidationError):
        validate_token_length(record, tokenizer=_FakeTokenizer(), max_tokens=3)
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/validation/test_structural.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.validation.structural'`.

#### Step 3: Structural validation — implement (GREEN)

Create `backend/tuneforge/validation/structural.py`:

```python
from __future__ import annotations

from tuneforge.records import ChatMessage, CPTRecord, DPORecord, SFTConversationRecord, SFTPromptCompletionRecord


class StructuralValidationError(RuntimeError):
    pass


def validate_role_alternation(messages: list[ChatMessage]) -> None:
    if not messages:
        raise StructuralValidationError("conversation has no messages")
    non_system = [m for m in messages if m.role != "system"]
    if not non_system:
        raise StructuralValidationError("conversation has only a system message")
    if non_system[0].role != "user":
        raise StructuralValidationError("conversation must start with a user message (after any system message)")
    for previous, current in zip(non_system, non_system[1:]):
        if previous.role == current.role:
            raise StructuralValidationError(f"consecutive {current.role!r} messages — roles must alternate")


def validate_structure(record) -> None:
    """Schema-appropriate non-empty checks + role alternation for chat-shaped
    records. Pydantic already enforces field *types*; this catches
    technically-valid-but-useless content (empty strings) that types alone
    don't rule out.
    """
    if isinstance(record, CPTRecord):
        if not record.text.strip():
            raise StructuralValidationError("CPT record has empty text")
    elif isinstance(record, SFTPromptCompletionRecord):
        if not record.prompt.strip() or not record.completion.strip():
            raise StructuralValidationError("SFT prompt/completion record has an empty field")
    elif isinstance(record, SFTConversationRecord):
        if any(not m.content.strip() for m in record.messages):
            raise StructuralValidationError("conversation has an empty message")
        validate_role_alternation(record.messages)
    elif isinstance(record, DPORecord):
        for field_name, messages in (("prompt", record.prompt), ("chosen", record.chosen), ("rejected", record.rejected)):
            if not messages or any(not m.content.strip() for m in messages):
                raise StructuralValidationError(f"DPO record has an empty {field_name!r}")
    else:
        raise StructuralValidationError(f"unrecognized record type: {type(record).__name__}")


def render_record_text(record) -> str:
    """Flattens any canonical record to plain text — shared by token-length
    checking, deduplication, and judging, which all need "the text of this
    record" but don't care about the schema differences otherwise.
    """
    if isinstance(record, CPTRecord):
        return record.text
    if isinstance(record, SFTPromptCompletionRecord):
        return f"{record.prompt}\n{record.completion}"
    if isinstance(record, SFTConversationRecord):
        return "\n".join(m.content for m in record.messages)
    if isinstance(record, DPORecord):
        return "\n".join(m.content for m in record.prompt + record.chosen + record.rejected)
    raise StructuralValidationError(f"unrecognized record type: {type(record).__name__}")


def validate_token_length(record, *, tokenizer, max_tokens: int) -> None:
    token_count = len(tokenizer.encode(render_record_text(record)))
    if token_count > max_tokens:
        raise StructuralValidationError(f"record renders to {token_count} tokens, exceeding the {max_tokens} limit")
```

Run the tests again:

```powershell
uv run pytest tests/validation/test_structural.py -q
```

Expected: all pass.

#### Step 4: Refactor `normalization/mappers.py` to reuse the shared check

Edit `backend/tuneforge/normalization/mappers.py`. Add these two imports alongside the existing ones:

```python
from tuneforge.validation.structural import StructuralValidationError
from tuneforge.validation.structural import validate_role_alternation as _shared_validate_role_alternation
```

Then replace the existing `_validate_role_alternation` function body:

```python
def _validate_role_alternation(messages: list[ChatMessage]) -> None:
    # Shared with the validation pipeline (Task 10) — same algorithm, one
    # place it lives. Translated back to this module's own exception type
    # so callers here don't need to know about tuneforge.validation.
    try:
        _shared_validate_role_alternation(messages)
    except StructuralValidationError as exc:
        raise InvalidRecordError(str(exc)) from exc
```

Run Task 8's existing test suite to confirm this refactor changes nothing observable:

```powershell
uv run pytest tests/normalization -q
```

Expected: all pass, unchanged from before this edit.

#### Step 5: Deduplication — write the failing tests (RED)

Create `backend/tests/validation/test_deduplication.py`:

```python
import uuid

from tuneforge.records import CPTRecord, RecordMetadata
from tuneforge.validation.deduplication import deduplicate


def _record(text: str) -> CPTRecord:
    return CPTRecord(text=text, metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef"))


def test_exact_duplicates_are_removed():
    records = [_record("Employees get 20 days of vacation."), _record("Employees get 20 days of vacation.")]
    result = deduplicate(records)
    assert len(result.kept) == 1
    assert result.exact_duplicates == 1


def test_exact_duplicate_detection_ignores_whitespace_and_case():
    records = [_record("Employees get 20 days of vacation."), _record("  employees   get 20 DAYS of vacation.  ")]
    result = deduplicate(records)
    assert len(result.kept) == 1
    assert result.exact_duplicates == 1


def test_near_duplicates_are_removed():
    records = [
        _record("The quick brown fox jumps over the lazy dog in the park today"),
        _record("The quick brown fox jumps over the lazy dog in the park yesterday"),
    ]
    result = deduplicate(records, near_duplicate_threshold=0.5)
    assert len(result.kept) == 1
    assert result.near_duplicates == 1


def test_distinct_content_is_all_kept():
    records = [
        _record("Employees get 20 days of paid vacation per year."),
        _record("The office is closed on all federal holidays."),
        _record("Remote work requests must be approved by a manager."),
    ]
    result = deduplicate(records)
    assert len(result.kept) == 3
    assert result.exact_duplicates == 0
    assert result.near_duplicates == 0
```

Run it and confirm it fails on the missing module:

```powershell
uv run pytest tests/validation/test_deduplication.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.validation.deduplication'`.

#### Step 6: Deduplication — implement (GREEN)

Create `backend/tuneforge/validation/deduplication.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from datasketch import MinHash, MinHashLSH

from tuneforge.validation.structural import render_record_text


def _normalized_hash(text: str) -> str:
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class DeduplicationResult:
    kept: list = field(default_factory=list)
    exact_duplicates: int = 0
    near_duplicates: int = 0


def deduplicate(records: list, *, near_duplicate_threshold: float = 0.85, num_perm: int = 128) -> DeduplicationResult:
    """Two passes: exact duplicates first (cheap, a normalized-text hash),
    then near-duplicates via local MinHash LSH on whatever survives — no
    point running the more expensive LSH pass over rows already dropped.
    """
    seen_hashes: set[str] = set()
    exact_pass: list = []
    exact_duplicates = 0

    for record in records:
        text_hash = _normalized_hash(render_record_text(record))
        if text_hash in seen_hashes:
            exact_duplicates += 1
            continue
        seen_hashes.add(text_hash)
        exact_pass.append(record)

    lsh = MinHashLSH(threshold=near_duplicate_threshold, num_perm=num_perm)
    kept: list = []
    near_duplicates = 0
    for index, record in enumerate(exact_pass):
        minhash = MinHash(num_perm=num_perm)
        for shingle in render_record_text(record).split():
            minhash.update(shingle.encode("utf-8"))
        if lsh.query(minhash):
            near_duplicates += 1
            continue
        lsh.insert(str(index), minhash)
        kept.append(record)

    return DeduplicationResult(kept=kept, exact_duplicates=exact_duplicates, near_duplicates=near_duplicates)
```

Run the tests again:

```powershell
uv run pytest tests/validation/test_deduplication.py -q
```

Expected: all pass.

#### Step 7: Judging — write the failing tests (RED)

Create `backend/tests/validation/test_judging.py`:

```python
import json
import uuid

import httpx
import pytest

from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile
from tuneforge.records import ChatMessage, CPTRecord, DPORecord, RecordMetadata
from tuneforge.validation.judging import JudgingError, judge_dpo_preference, judge_quality


def _metadata() -> RecordMetadata:
    return RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef")


def _provider(handler) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(name="judge", base_url="http://127.0.0.1:9999", model="judge-model", endpoint_scope="local")
    return OpenAICompatibleProvider(profile, client)


def _chat_response(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


async def test_judge_quality_passes_above_threshold():
    def handler(request):
        return _chat_response({"score": 8})

    judge = _provider(handler)
    record = CPTRecord(text="Employees get 20 days of paid vacation.", metadata=_metadata())
    assert await judge_quality(judge, record, pass_threshold=6.0) is True


async def test_judge_quality_fails_below_threshold():
    def handler(request):
        return _chat_response({"score": 3})

    judge = _provider(handler)
    record = CPTRecord(text="garbled nonsense", metadata=_metadata())
    assert await judge_quality(judge, record, pass_threshold=6.0) is False


async def test_judge_quality_raises_on_malformed_response():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    judge = _provider(handler)
    record = CPTRecord(text="text", metadata=_metadata())
    with pytest.raises(JudgingError):
        await judge_quality(judge, record)


async def test_judge_dpo_preference_confirms_clear_winner():
    def handler(request):
        return _chat_response({"score_a": 9, "score_b": 3})

    judge = _provider(handler)
    record = DPORecord(
        prompt=[ChatMessage(role="user", content="q")],
        chosen=[ChatMessage(role="assistant", content="good")],
        rejected=[ChatMessage(role="assistant", content="bad")],
        metadata=_metadata(),
    )
    assert await judge_dpo_preference(judge, record, margin=1.0) is True


async def test_judge_dpo_preference_rejects_when_too_close():
    def handler(request):
        return _chat_response({"score_a": 5, "score_b": 4.8})

    judge = _provider(handler)
    record = DPORecord(
        prompt=[ChatMessage(role="user", content="q")],
        chosen=[ChatMessage(role="assistant", content="good")],
        rejected=[ChatMessage(role="assistant", content="bad")],
        metadata=_metadata(),
    )
    assert await judge_dpo_preference(judge, record, margin=1.0) is False
```

Run it and confirm it fails on the missing module:

```powershell
uv run pytest tests/validation/test_judging.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.validation.judging'`.

#### Step 8: Judging — implement (GREEN)

Create `backend/tuneforge/validation/judging.py`:

```python
from __future__ import annotations

import json

from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import GenerationRequest
from tuneforge.records import DPORecord
from tuneforge.validation.structural import render_record_text


class JudgingError(RuntimeError):
    pass


async def judge_quality(judge: OpenAICompatibleProvider, record, *, pass_threshold: float = 6.0) -> bool:
    """A general quality gate: does this training example look coherent and
    useful? Used as an optional pass for SFT/CPT (PLAN.md: judging is
    optional for those) and as one half of the mandatory DPO gate below.
    """
    text = render_record_text(record)
    prompt = (
        "Rate the quality of this training example from 0 (incoherent or "
        "useless) to 10 (clear, coherent, and useful for fine-tuning).\n\n"
        f"{text}\n\n"
        'Respond with only a JSON object: {"score": <number 0-10>}'
    )
    response = await judge.generate(
        GenerationRequest(messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
    )
    try:
        data = json.loads(response.content)
        score = float(data["score"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise JudgingError(f"judge response was not a valid score: {exc}") from exc
    return score >= pass_threshold


async def judge_dpo_preference(judge: OpenAICompatibleProvider, record: DPORecord, *, margin: float = 1.0) -> bool:
    """DPO-specific and mandatory (PLAN.md): an *independent* re-check that
    chosen is actually better than rejected. Separate from whatever judging
    happened during generation (Task 9) — a normalized/imported DPO dataset
    never went through that at all, so this is the only judging it gets.
    """
    prompt_text = "\n".join(m.content for m in record.prompt)
    chosen_text = "\n".join(m.content for m in record.chosen)
    rejected_text = "\n".join(m.content for m in record.rejected)
    prompt = (
        "Given the PROMPT below, rate answer A and answer B independently from "
        "0 (bad) to 10 (excellent).\n\n"
        f"PROMPT: {prompt_text}\n\nANSWER A: {chosen_text}\n\nANSWER B: {rejected_text}\n\n"
        'Respond with only a JSON object: {"score_a": <0-10>, "score_b": <0-10>}'
    )
    response = await judge.generate(
        GenerationRequest(messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
    )
    try:
        data = json.loads(response.content)
        score_a = float(data["score_a"])
        score_b = float(data["score_b"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise JudgingError(f"judge response was not valid: {exc}") from exc
    return (score_a - score_b) >= margin
```

Run the tests again:

```powershell
uv run pytest tests/validation/test_judging.py -q
```

Expected: all pass.

#### Step 9: Pipeline orchestration — write the failing tests (RED)

Create `backend/tests/validation/test_pipeline.py`:

```python
import json
import uuid

import httpx
import pytest

from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile
from tuneforge.records import ChatMessage, CPTRecord, DPORecord, RecordMetadata, SFTPromptCompletionRecord
from tuneforge.validation.pipeline import run_validation_pipeline


class _FakeTokenizer:
    def encode(self, text: str) -> list[int]:
        return text.split()


def _metadata() -> RecordMetadata:
    return RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef")


def _provider(handler) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(name="judge", base_url="http://127.0.0.1:9999", model="judge-model", endpoint_scope="local")
    return OpenAICompatibleProvider(profile, client)


def _chat_response(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


async def test_pipeline_without_judging_marks_lower_assurance():
    records = [
        CPTRecord(text="Employees get 20 days of vacation.", metadata=_metadata()),
        CPTRecord(text="The office closes at 5pm on Fridays.", metadata=_metadata()),
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100)

    assert len(report.accepted) == 2
    assert report.assurance_level == "lower_assurance"
    assert report.rejection_counts == {}


async def test_pipeline_drops_structurally_invalid_records():
    records = [
        CPTRecord(text="valid content here", metadata=_metadata()),
        SFTPromptCompletionRecord(prompt="hi", completion="   ", metadata=_metadata()),
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100)

    assert len(report.accepted) == 1
    assert report.rejection_counts["structural"] == 1


async def test_pipeline_drops_records_over_token_limit():
    records = [CPTRecord(text="one two three four five six seven", metadata=_metadata())]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=3)

    assert len(report.accepted) == 0
    assert report.rejection_counts["structural"] == 1


async def test_pipeline_dedups_before_accepting():
    records = [
        CPTRecord(text="Employees get 20 days of vacation.", metadata=_metadata()),
        CPTRecord(text="Employees get 20 days of vacation.", metadata=_metadata()),
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100)

    assert len(report.accepted) == 1
    assert report.rejection_counts["exact_duplicate"] == 1


async def test_pipeline_requires_judge_for_dpo_records():
    records = [
        DPORecord(
            prompt=[ChatMessage(role="user", content="q")],
            chosen=[ChatMessage(role="assistant", content="good")],
            rejected=[ChatMessage(role="assistant", content="bad")],
            metadata=_metadata(),
        )
    ]
    with pytest.raises(ValueError, match="judge"):
        await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=None)


async def test_pipeline_accepts_dpo_record_confirmed_by_judge_and_marks_standard_assurance():
    def handler(request):
        return _chat_response({"score_a": 9, "score_b": 2})

    judge = _provider(handler)
    records = [
        DPORecord(
            prompt=[ChatMessage(role="user", content="q")],
            chosen=[ChatMessage(role="assistant", content="good")],
            rejected=[ChatMessage(role="assistant", content="bad")],
            metadata=_metadata(),
        )
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=judge)

    assert len(report.accepted) == 1
    assert report.assurance_level == "standard_assurance"


async def test_pipeline_rejects_dpo_record_when_judge_disagrees():
    def handler(request):
        return _chat_response({"score_a": 5, "score_b": 5.2})

    judge = _provider(handler)
    records = [
        DPORecord(
            prompt=[ChatMessage(role="user", content="q")],
            chosen=[ChatMessage(role="assistant", content="good")],
            rejected=[ChatMessage(role="assistant", content="bad")],
            metadata=_metadata(),
        )
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=judge)

    assert len(report.accepted) == 0
    assert report.rejection_counts["dpo_preference_not_confirmed"] == 1


async def test_pipeline_applies_optional_sft_judging_when_requested():
    def handler(request):
        return _chat_response({"score": 2})

    judge = _provider(handler)
    records = [SFTPromptCompletionRecord(prompt="hi", completion="hello", metadata=_metadata())]
    report = await run_validation_pipeline(
        records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=judge, apply_sft_judging=True
    )

    assert len(report.accepted) == 0
    assert report.rejection_counts["quality_judged_insufficient"] == 1
    assert report.assurance_level == "standard_assurance"


async def test_pipeline_skips_sft_judging_by_default():
    records = [SFTPromptCompletionRecord(prompt="hi", completion="hello", metadata=_metadata())]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=None)

    assert len(report.accepted) == 1
    assert report.assurance_level == "lower_assurance"
```

Run it and confirm it fails on the missing module:

```powershell
uv run pytest tests/validation/test_pipeline.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.validation.pipeline'`.

#### Step 10: Pipeline orchestration — implement (GREEN)

Create `backend/tuneforge/validation/pipeline.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.records import DPORecord
from tuneforge.validation.deduplication import deduplicate
from tuneforge.validation.judging import JudgingError, judge_dpo_preference, judge_quality
from tuneforge.validation.structural import StructuralValidationError, validate_structure, validate_token_length


@dataclass
class ValidationReport:
    accepted: list = field(default_factory=list)
    rejection_counts: dict[str, int] = field(default_factory=dict)
    assurance_level: Literal["standard_assurance", "lower_assurance"] = "lower_assurance"

    def record_rejection(self, reason: str) -> None:
        self.rejection_counts[reason] = self.rejection_counts.get(reason, 0) + 1


async def run_validation_pipeline(
    records: list,
    *,
    tokenizer,
    max_tokens: int,
    judge: OpenAICompatibleProvider | None = None,
    apply_sft_judging: bool = False,
    dpo_judge_margin: float = 1.0,
) -> ValidationReport:
    """Order: structural + length checks (cheap, no I/O) -> deduplication
    (cheap, no I/O) -> judging (expensive, real LLM calls) — so the priciest
    step only ever runs on rows everything else has already accepted.

    Source-grounding is enforced upstream, at generation time (Task 9's
    generator rejects an ungrounded candidate before a record is ever
    produced) — it is not re-checked here. By the time a record reaches
    this pipeline, either it came from generation (already grounded) or
    from normalization (Task 8, no source chunk to ground against at all),
    and this pipeline only ever sees canonical records, not the original
    source text, so there is nothing here to re-verify against.
    """
    report = ValidationReport()
    structurally_valid = []

    for record in records:
        try:
            validate_structure(record)
            validate_token_length(record, tokenizer=tokenizer, max_tokens=max_tokens)
        except StructuralValidationError:
            report.record_rejection("structural")
            continue
        structurally_valid.append(record)

    dedup_result = deduplicate(structurally_valid)
    if dedup_result.exact_duplicates:
        report.rejection_counts["exact_duplicate"] = dedup_result.exact_duplicates
    if dedup_result.near_duplicates:
        report.rejection_counts["near_duplicate"] = dedup_result.near_duplicates

    judged_any = False
    accepted = []
    for record in dedup_result.kept:
        if isinstance(record, DPORecord):
            if judge is None:
                raise ValueError("DPO records require a judge provider — judging is mandatory, not optional")
            judged_any = True
            try:
                if not await judge_dpo_preference(judge, record, margin=dpo_judge_margin):
                    report.record_rejection("dpo_preference_not_confirmed")
                    continue
            except JudgingError:
                report.record_rejection("judging_error")
                continue
        elif apply_sft_judging and judge is not None:
            judged_any = True
            try:
                if not await judge_quality(judge, record):
                    report.record_rejection("quality_judged_insufficient")
                    continue
            except JudgingError:
                report.record_rejection("judging_error")
                continue
        accepted.append(record)

    report.accepted = accepted
    report.assurance_level = "standard_assurance" if judged_any else "lower_assurance"
    return report
```

Run the tests again:

```powershell
uv run pytest tests/validation/test_pipeline.py -q
```

Expected: all pass.

#### Step 11: Run the full backend suite and commit

```powershell
uv run pytest -q
```

Expected: every test from Parts 1–4 and this part's Tasks 9–10 passes, with the Task 8 normalization suite still passing unchanged after Step 4's refactor.

```powershell
git add backend
git commit -m "feat: add dataset quality gates"
```

---

## When you're done

Do not start Task 11. Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` (full pass/fail summary) from `backend/`.
2. Output of `git log --oneline` — should show two new commits: `feat: generate training records via the provider client` and `feat: add dataset quality gates`.
3. Confirm `backend/uv.lock` picked up `datasketch` and is committed.
4. Confirm the Task 8 normalization test suite still passes after the Step 4 refactor, with no behavior change (same test file, same assertions, still all green).
5. Anything you had to deviate from in this document, and why.
6. If you find a correctness issue in the code exactly as given here — not a style preference, an actual bug — stop and describe it rather than silently changing behavior. Pay particular attention to the DPO candidate-scoring loop in `generator.py` (`generate_dpo_record`) if you touch it — the call-count arithmetic there is easy to get subtly wrong (one question-determining call whose answer is discarded, plus `max_candidates` more calls that are each scored).
