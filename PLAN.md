# TuneForge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Use checkbox syntax for tracking.

**Goal:** Build a Windows-first local web application that converts structured and unstructured documents into validated, model-aware CPT, SFT, conversational SFT, or DPO datasets for Unsloth.

**Architecture:** FastAPI owns deterministic model analysis, objective planning, validation, storage, jobs, and exports. React provides the guided workflow. NVIDIA NeMo Data Designer runs behind a replaceable adapter and handles synthetic generation. Docling handles local document extraction.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite WAL, Docling, NVIDIA NeMo Data Designer, Hugging Face Hub/Transformers, React, TypeScript, Vite, TanStack Query, pytest, Vitest, Playwright, PyInstaller, Inno Setup.

## Global Constraints

- Product name: TuneForge.
- Windows-first local web application.
- Bind only to `127.0.0.1`.
- Text decoder-only causal language models only.
- Target models come from Hugging Face IDs or local Transformers directories.
- Training objectives: CPT, prompt-completion SFT, conversational SFT, DPO.
- GRPO, multimodal models, embeddings, classifiers, audio, diffusion, and model training are outside v1.
- Input formats: PDF, DOCX, TXT, Markdown, HTML, CSV, JSON, JSONL.
- Output formats: Parquet and JSONL.
- Maximum supported output: 100,000 rows.
- Existing compatible structured data is normalized without LLM rewriting.
- OpenAI-compatible endpoints support local and remote generation.
- Every remote run requires explicit transmission approval.
- Preview exactly 20 rows before full generation.
- DPO requires a judge model different from the generator model.
- LLM judging is optional for CPT and SFT.
- No direct writes into Unsloth Studio internals.
- NeMo telemetry must be disabled.
- API keys must use Windows Credential Manager and never SQLite, logs, or exports.

## Canonical Data Contracts

```python
class SourceRecord(BaseModel):
    document_id: UUID
    chunk_id: str
    text: str
    source_name: str
    source_hash: str
    page: int | None
    heading: str | None
    metadata: dict[str, JsonValue]

class CPTRecord(BaseModel):
    text: str
    metadata: RecordMetadata

class SFTPromptCompletionRecord(BaseModel):
    prompt: str
    completion: str
    metadata: RecordMetadata

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class SFTConversationRecord(BaseModel):
    messages: list[ChatMessage]
    metadata: RecordMetadata

class DPORecord(BaseModel):
    prompt: list[ChatMessage]
    chosen: list[ChatMessage]
    rejected: list[ChatMessage]
    metadata: RecordMetadata
```

## Model and Planning Contracts

```python
class ModelProfile(BaseModel):
    source: Literal["huggingface", "local"]
    model_id: str
    architecture: str
    model_type: str
    is_causal_lm: bool
    is_chat_model: bool
    chat_template_found: bool
    context_length: int
    modalities: list[str]
    evidence: list[Evidence]
    confidence: float

class TrainingIntent(BaseModel):
    goal: Literal[
        "domain_adaptation",
        "single_turn_instruction",
        "multi_turn_conversation",
        "preference_alignment",
    ]
    desired_behavior: str
    language: str
    output_style: str | None

class TrainingPlan(BaseModel):
    objective: Literal["cpt", "sft_prompt_completion", "sft_conversation", "dpo"]
    canonical_schema: str
    target_rows: int
    examples_per_chunk: int
    generator_profile_id: UUID | None
    judge_profile_id: UUID | None
    required_validators: list[str]
    evidence: list[Evidence]
    confidence: float
    plan_hash: str
```

## Provider Interface

```python
class ChatProvider(Protocol):
    async def health(self) -> ProviderHealth: ...
    async def generate(self, request: GenerationRequest) -> GenerationResponse: ...
```

Support the OpenAI-compatible endpoints:

```text
GET  /v1/models
POST /v1/chat/completions
```

Provider profiles contain:

```text
name
base_url
model
endpoint_scope: local | remote
api_key_credential_reference
timeout_seconds
max_concurrency
structured_output_supported
```

## API Surface

```text
POST   /api/projects
POST   /api/projects/{id}/sources
POST   /api/models/analyze
POST   /api/plans/recommend
POST   /api/plans/{id}/research
POST   /api/plans/{id}/approve
POST   /api/providers
POST   /api/runs/preview
POST   /api/runs/{id}/approve-full
POST   /api/runs/{id}/cancel
POST   /api/runs/{id}/resume
GET    /api/runs/{id}
GET    /api/runs/{id}/events
GET    /api/exports/{id}/download
DELETE /api/projects/{id}
```

Run events use server-sent events. Each event contains `run_id`, `sequence`, `stage`, `completed_rows`, `total_rows`, `message`, and `timestamp`.

## Implementation Tasks

### Task 1: Application shell and secure localhost runtime

**Files:**

- Create `backend/tuneforge/main.py`
- Create `backend/tuneforge/settings.py`
- Create `backend/tests/test_runtime_security.py`
- Create `frontend/`
- Create `installer/`

- [ ] Create Python and React workspaces with locked dependencies.
- [ ] Write failing tests for loopback-only binding, bearer-session authentication, strict origin checking, and redacted logs.
- [ ] Implement a launcher-generated 256-bit session token held only in memory.
- [ ] Serve the compiled React application from FastAPI.
- [ ] Add `/api/health` and `/api/version`.
- [ ] Verify backend, frontend, and production static serving.
- [ ] Commit as `chore: scaffold secure TuneForge runtime`.

### Task 2: Persistence, projects, and artifact storage

**Files:**

- Create `backend/tuneforge/storage/models.py`
- Create `backend/tuneforge/storage/repositories.py`
- Create `backend/tuneforge/storage/artifacts.py`
- Test under `backend/tests/storage/`

- [ ] Define SQLite entities for projects, sources, model profiles, plans, provider profiles, runs, checkpoints, evidence, and exports.
- [ ] Store files under `%LOCALAPPDATA%\\TuneForge\\projects\\<project-id>`.
- [ ] Enable SQLite WAL, foreign keys, and transactional state changes.
- [ ] Import source files by copying them into project storage and computing SHA-256.
- [ ] Implement recoverable project deletion through a local trash directory.
- [ ] Test interrupted writes, duplicate imports, missing artifacts, and project recovery.
- [ ] Commit as `feat: add project and artifact persistence`.

### Task 3: OpenAI-compatible provider subsystem

**Files:**

- Create `backend/tuneforge/providers/protocol.py`
- Create `backend/tuneforge/providers/openai_compatible.py`
- Create `backend/tuneforge/security/credentials.py`
- Test under `backend/tests/providers/`

- [ ] Implement provider creation and health checking without transmitting documents.
- [ ] Store API keys through Windows Credential Manager.
- [ ] Classify endpoint profiles as local or remote explicitly.
- [ ] Require a signed run-specific consent record before remote source transmission.
- [ ] Add bounded retries for 429, 502, 503, 504, and timeout failures.
- [ ] Never retry authentication errors or invalid structured output indefinitely.
- [ ] Add request IDs while redacting prompts, document text, and credentials from logs.
- [ ] Commit as `feat: add secure model provider profiles`.

### Task 4: Target-model analyzer

**Files:**

- Create `backend/tuneforge/models/analyzer.py`
- Create `backend/tuneforge/models/evidence.py`
- Create `backend/tuneforge/models/compatibility.py`
- Test under `backend/tests/models/`

- [ ] Inspect `config.json`, tokenizer configuration, generation configuration, chat template, processor metadata, and model card.
- [ ] Fetch Hugging Face metadata and tokenizer files without downloading model weights.
- [ ] Analyze local models with `trust_remote_code=False`.
- [ ] Detect base versus instruct/chat using template and metadata evidence.
- [ ] Reject GGUF and non-causal architectures with actionable errors.
- [ ] Produce confidence plus field-level evidence.
- [ ] Test Qwen instruct, Llama base, missing template, gated model, offline model, GGUF, and classifier cases.
- [ ] Commit as `feat: add deterministic model analyzer`.

### Task 5: Goal wizard and deterministic training planner

**Files:**

- Create `backend/tuneforge/planning/intents.py`
- Create `backend/tuneforge/planning/planner.py`
- Create `backend/tuneforge/planning/schemas.py`
- Test under `backend/tests/planning/`

- [ ] Encode the objective matrix: domain adaptation to CPT, single-turn behavior to prompt-completion SFT, multi-turn assistant to conversational SFT, and preference alignment to DPO.
- [ ] Combine user intent, target-model capabilities, and selected training objective.
- [ ] Require a chat template for conversational SFT and DPO.
- [ ] Require distinct generator and judge model IDs for DPO.
- [ ] Generate a stable SHA-256 `plan_hash` from all approved settings.
- [ ] Expose evidence, assumptions, warnings, output schema, expected row count, and confidence.
- [ ] Implement Approve, Change Objective, Inspect Evidence, and Cancel actions.
- [ ] Commit as `feat: add model-aware training planner`.

### Task 6: Official-evidence fallback

**Files:**

- Create `backend/tuneforge/research/official_sources.py`
- Create `backend/tuneforge/research/resolver.py`
- Test under `backend/tests/research/`

- [ ] Trigger research only after the user rejects a recommendation.
- [ ] Reinspect local metadata before network access.
- [ ] Fetch only Hugging Face model cards and allowlisted official Transformers, TRL, Unsloth, and model-publisher documentation.
- [ ] Store source URL, retrieval timestamp, SHA-256, and relevant excerpt.
- [ ] Present a revised recommendation with citations and confidence.
- [ ] Fall back to manual objective selection when official evidence remains inconclusive.
- [ ] Commit as `feat: add official evidence research fallback`.

### Task 7: Document ingestion and chunking

**Files:**

- Create `backend/tuneforge/ingestion/documents.py`
- Create `backend/tuneforge/ingestion/structured.py`
- Create `backend/tuneforge/ingestion/chunking.py`
- Test under `backend/tests/ingestion/`

- [ ] Parse PDF, DOCX, HTML, Markdown, and TXT through Docling.
- [ ] Parse CSV, JSON, and JSONL without converting them to plain text first.
- [ ] Enable local OCR for scanned PDFs.
- [ ] Preserve page, heading, row, source hash, and document identifiers.
- [ ] Apply tokenizer-aware hybrid chunking using the target tokenizer.
- [ ] Reject encrypted, corrupt, empty, oversized, or unsupported files clearly.
- [ ] Cache extraction results by source hash and parser-version fingerprint.
- [ ] Commit as `feat: add provenance-aware document ingestion`.

### Task 8: Existing structured-dataset normalization

**Files:**

- Create `backend/tuneforge/normalization/detector.py`
- Create `backend/tuneforge/normalization/mappers.py`
- Create `backend/tuneforge/normalization/preview.py`
- Test under `backend/tests/normalization/`

- [ ] Detect `text`, `prompt/completion`, `instruction/input/output`, `messages`, `conversations`, and `prompt/chosen/rejected` schemas.
- [ ] Normalize compatible rows into canonical Pydantic records.
- [ ] Provide manual column mapping when detection confidence is insufficient.
- [ ] Never call an LLM merely to rename or map obvious fields.
- [ ] Validate role alternation, required values, types, and message ordering.
- [ ] Preserve original row IDs and source metadata.
- [ ] Commit as `feat: normalize existing training datasets`.

### Task 9: NeMo Data Designer adapter

**Files:**

- Create `backend/tuneforge/generation/protocol.py`
- Create `backend/tuneforge/generation/nemo_adapter.py`
- Create `backend/tuneforge/generation/specs.py`
- Test under `backend/tests/generation/`

- [ ] Define a provider-independent `GenerationSpec`.
- [ ] Translate canonical generation requests into NeMo model, seed, structured-output, expression, and validator columns.
- [ ] Disable NeMo telemetry with `NEMO_TELEMETRY_ENABLED=false`.
- [ ] Generate source-grounded questions, answers, supporting quotes, and metadata.
- [ ] Require each supporting quote to exist in the source chunk after normalization.
- [ ] Generate DPO candidate sets, judge each candidate, and retain only pairs meeting the configured score margin.
- [ ] Retry malformed rows no more than twice, then record rejection.
- [ ] Keep NeMo types outside domain and API interfaces.
- [ ] Commit as `feat: integrate NeMo generation adapter`.

### Task 10: Validation and deduplication pipeline

**Files:**

- Create `backend/tuneforge/validation/pipeline.py`
- Create `backend/tuneforge/validation/structural.py`
- Create `backend/tuneforge/validation/deduplication.py`
- Create `backend/tuneforge/validation/judging.py`
- Test under `backend/tests/validation/`

- [ ] Enforce canonical schema validation and non-empty required fields.
- [ ] Validate role order and tokenizer length.
- [ ] Reject source-grounding failures.
- [ ] Remove exact duplicates by normalized hash.
- [ ] Remove near duplicates through local MinHash LSH.
- [ ] Apply optional LLM judging for SFT.
- [ ] Require independent LLM judging for DPO.
- [ ] Mark each run `standard_assurance` or `lower_assurance`.
- [ ] Persist rejection reason counts without storing prompts in logs.
- [ ] Commit as `feat: add dataset quality gates`.

### Task 11: Preview, jobs, checkpoints, cancellation, and resume

**Files:**

- Create `backend/tuneforge/jobs/runner.py`
- Create `backend/tuneforge/jobs/checkpoints.py`
- Create `backend/tuneforge/api/runs.py`
- Test under `backend/tests/jobs/`

- [ ] Run generation outside the FastAPI request lifecycle.
- [ ] Keep the worker in a separate local process so generation crashes do not kill the UI.
- [ ] Generate exactly 20 preview rows.
- [ ] Require preview approval before creating a full run.
- [ ] Invalidate approval whenever `plan_hash` changes.
- [ ] Checkpoint every 100 accepted rows and after each source document.
- [ ] Support graceful cancellation and resume from the last committed checkpoint.
- [ ] Stream ordered progress through server-sent events.
- [ ] Enforce a hard maximum of 100,000 accepted rows.
- [ ] Commit as `feat: add resumable generation runs`.

### Task 12: Dataset splitting and export bundle

**Files:**

- Create `backend/tuneforge/export/splitting.py`
- Create `backend/tuneforge/export/bundle.py`
- Create `backend/tuneforge/export/compatibility.py`
- Test under `backend/tests/export/`

- [ ] Split 90/10 by source document using a fixed seed.
- [ ] Do not create an evaluation split when only one source document exists; show a leakage warning.
- [ ] Export canonical train and evaluation datasets as Parquet and JSONL.
- [ ] Include `manifest.json`, `model-profile.json`, `training-plan.json`, `validation-report.json`, and `provenance.jsonl`.
- [ ] Include rendered tokenizer samples for compatibility inspection.
- [ ] Verify exported records by reloading them through Hugging Face Datasets.
- [ ] Verify the target tokenizer can apply its chat template to conversational examples.
- [ ] Produce clear Unsloth import and column-mapping instructions.
- [ ] Commit as `feat: export validated Unsloth dataset bundles`.

### Task 13: React workflow

**Files:**

- Create feature modules under `frontend/src/features/`
- Create API client under `frontend/src/api/`
- Test under `frontend/src/**/*.test.tsx`
- Add browser tests under `frontend/e2e/`

- [ ] Build project creation and source-upload screens.
- [ ] Build Hugging Face/local model selection and evidence display.
- [ ] Build the training-goal wizard.
- [ ] Build the recommendation confirmation modal.
- [ ] Build provider configuration and remote-consent dialog.
- [ ] Build structured column mapping.
- [ ] Build 20-row preview with source evidence and validation status.
- [ ] Build full-run progress, cancel, resume, and failure recovery.
- [ ] Build export download and Unsloth instructions.
- [ ] Meet keyboard navigation, focus management, error summaries, and WCAG AA contrast requirements.
- [ ] Commit as `feat: add TuneForge guided workflow`.

### Task 14: Windows packaging and installation

**Files:**

- Create `installer/tuneforge.spec`
- Create `installer/TuneForge.iss`
- Create `installer/launcher.py`
- Create `scripts/build-windows.ps1`

- [ ] Compile the frontend into FastAPI static assets.
- [ ] Package backend and Python runtime using PyInstaller onedir.
- [ ] Exclude model weights and OCR assets from the installer.
- [ ] Download extraction assets on first use with visible progress and checksums.
- [ ] Build an Inno Setup installer with Start Menu and uninstall entries.
- [ ] Preserve user projects during upgrades and normal uninstall.
- [ ] Offer explicit data removal during uninstall.
- [ ] Launch on an available loopback port and open the default browser.
- [ ] Commit as `build: add Windows TuneForge installer`.

### Task 15: Final verification and documentation

**Files:**

- Create `README.md`
- Create `docs/user-guide.md`
- Create `docs/privacy.md`
- Create `docs/troubleshooting.md`

- [ ] Run backend unit and integration tests.
- [ ] Run frontend unit, accessibility, and production-build tests.
- [ ] Run Playwright workflows for CPT, SFT, conversational SFT, DPO, cancellation, resume, and export.
- [ ] Test local and remote OpenAI-compatible mock endpoints.
- [ ] Install on a clean Windows VM without Python or Node.
- [ ] Verify no API key, document content, or prompt appears in logs or bundles unexpectedly.
- [ ] Verify a 100,000-row synthetic stub run remains resumable and memory-bounded.
- [ ] Import every exported schema into a supported Unsloth training flow.
- [ ] Run independent review and resolve all critical/high findings.
- [ ] Commit as `docs: finalize TuneForge v1 release`.

## Test Plan

Run for every task:

```powershell
uv run pytest -q
pnpm --dir frontend test --run
pnpm --dir frontend lint
pnpm --dir frontend build
```

Final checks:

```powershell
uv run pytest --cov=tuneforge --cov-fail-under=85
pnpm --dir frontend playwright test
powershell -File scripts/build-windows.ps1
```

Required scenarios:

- Qwen instruct selects conversational SFT correctly.
- Base causal model supports CPT and prompt-completion SFT.
- User can override the recommended objective.
- Rejected recommendation triggers official-source research.
- Valid existing ChatML data bypasses generation.
- FineWiki-like raw text maps to CPT, not conversational SFT.
- Remote generation cannot start without run-specific consent.
- SFT can run without a judge and receives lower-assurance labeling.
- DPO cannot run without a distinct judge.
- Preview approval becomes invalid after configuration changes.
- Cancelled run resumes without duplicate output rows.
- Corrupt and scanned documents produce actionable results.
- Exported Parquet and JSONL contain equivalent records.
- Clean Windows machine installs, starts, exports, and uninstalls successfully.

## Assumptions and Defaults

- Single-user local application with no account system.
- Python 3.12 is the fixed backend runtime.
- SQLite stores metadata; filesystem artifacts store documents and datasets.
- Default split is 90% train and 10% evaluation by source document.
- Default preview size is fixed at 20 accepted rows.
- Default checkpoint interval is 100 accepted rows.
- Full runs remain user-requested; TuneForge does not block on RAG recommendations.
- Model analysis downloads metadata and tokenizer assets, not model weights.
- Local and remote inference both use the OpenAI-compatible protocol.
- Source rights and licensing remain the user’s responsibility.
- Unsloth training, model export, deployment, GRPO reward environments, and direct Studio registry integration are outside v1.
