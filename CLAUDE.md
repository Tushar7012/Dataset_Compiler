# TuneForge — CLAUDE.md

Windows-first local app. Docs/datasets in, Unsloth-ready training bundle out. Master spec: `PLAN.md` (15 tasks, canonical data contracts, API surface). Do not edit `PLAN.md`.

## Workflow used on this repo

Work happens in `plan_N.md` files — one per delivered chunk, each self-contained (no need to read `PLAN.md` to execute one), task-by-task, TDD (write failing test, confirm RED, implement, confirm GREEN, commit). Every code block in a `plan_N.md` was run and verified before being written down — not guessed. Follow a `plan_N.md` literally unless it explicitly flags a step as incomplete or a deliberate placeholder.

Commit per task, message format `feat: ...` / `fix: ...`. Push only when told to.

## Tooling — hard rules

- **uv only.** No conda, no plain `pip`, no venv by hand. `cd backend && uv sync && uv run pytest -q`.
- **Windows PowerShell**, not bash, for the user's own terminal. No `&&` chaining — separate statements with `;` or newlines.
- Frontend: `pnpm`, not npm/yarn.

## Non-negotiable constraints (from `PLAN.md`, enforced in code and tests)

- Bind `127.0.0.1` only. Never `0.0.0.0`.
- Bearer session token, held in memory only, never persisted.
- API keys/tokens: Windows Credential Manager only (`tuneforge.security.credentials`). Never SQLite, never logs, never exports, never a `.env` file.
- Remote provider calls require explicit per-run consent before transmitting document text.
- DPO requires a judge model distinct from the generator model — enforced twice (planner rejects at plan time, validation pipeline requires judging at run time).
- Text decoder-only causal LMs only. GGUF and multimodal rejected. Causal-LM detection checks both `ForCausalLM` and `LMHeadModel` suffixes — GPT-2 uses the older one, don't regress this.
- Max 100,000 accepted rows per run.
- Existing structured data (CSV/JSON/JSONL matching a known training shape) normalizes without any LLM call. Never rewrite it.

## Architecture decisions that deviate from `PLAN.md`, on purpose

- **No NVIDIA NeMo Data Designer.** `PLAN.md`'s Task 9 originally specified it; decided against it after checking the real SDK — it needs a separately deployed microservice (NVIDIA-hosted or self-hosted), not something that runs locally. Generation goes straight through the OpenAI-compatible provider client (`tuneforge.providers`) instead. Do not reintroduce a NeMo dependency without re-confirming this decision with the user.
- **OCR is disabled** in Docling (`do_ocr=False` in `tuneforge.ingestion.documents`). Scanned/image-only PDFs won't extract text. Deliberate, to avoid installing OCR models — `torch`/`torchvision` are still unavoidable pip dependencies of Docling itself, but that's a fixed cost, not a runtime one.
- **Generation is a real OS process**, not an asyncio background task (`tuneforge.jobs.runner`). SQLite is the only channel between the API process and the worker — no queues, no shared memory. This is what makes crash isolation and resume free.

## Known gaps — check before assuming something works end-to-end

- Structured-data (CSV/JSON/JSONL) records from Task 8 are not merged into a run's generated output. A run only pulls in document-shaped sources.
- `POST /api/plans/{id}/research` (Task 6) has no HTTP endpoint yet — pending a decision on `httpx.AsyncClient` lifecycle ownership.
- React UI (Task 13), Windows installer (Task 14), final verification pass (Task 15): not started.

## Testing conventions

- Real libraries over mocks where the library's *own* behavior is what's being verified (e.g., real Docling parsing, real HF Datasets Parquet round-trip). Mocks (`httpx.MockTransport`, fake tokenizers) where a call is expensive/slow/network-dependent and only the calling code's logic is under test.
- Before trusting an unfamiliar third-party API, check it against the real installed package (`importlib.metadata`, actual imports, a real call) — this repo's history has multiple bugs from unverified assumptions about NeMo, Docling, and `transformers` internals. Don't repeat that.
