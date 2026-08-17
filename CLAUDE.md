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
- **Pre-configured Gemini + Hugging Face credentials.** Run `cd backend && uv run python scripts/set_secrets.py` once to store both in Windows Credential Manager (`gemini`, `huggingface` — see `tuneforge.api.providers.GEMINI_API_KEY_CREDENTIAL_NAME`, `tuneforge.models.analyzer.HF_TOKEN_CREDENTIAL_NAME`). A remote `POST /providers` call with no `api_key` automatically falls back to the pre-seeded `gemini` credential, so the frontend never needs the key typed in per project. HF token is used automatically wherever `hf_hub_download`/`list_repo_files` run.

## Known gaps — check before assuming something works end-to-end

- **Fixed (was here as a gap before):** structured-data (CSV/JSON/JSONL) sources now merge into a run. A source only merges once its mapping is confirmed via `POST /projects/{id}/sources/{sid}/confirm-mapping` (persists `Source.confirmed_schema`/`column_mapping`), and only when its detected schema's canonical record type matches the plan's objective — a mismatched source is skipped, not silently mixed in, and recorded on `RunRecord.structured_sources_skipped`. Merged rows are tagged `metadata.source_kind = "structured"` (vs. `"document"` for generated rows) and counted separately on `RunRecord.accepted_generated`/`accepted_normalized`. `_load_project_sources` (`tuneforge/jobs/runner.py`) now skips any source with a confirmed mapping, and the crash this used to cause (`UnsupportedDocumentError` outside the worker's `try/except`, run stuck without ever reaching `status="failed"`) is fixed — the try block now wraps model-profile resolution through the structured-merge step. The wizard (`ProjectSetupStep.tsx`) probes each upload via `GET .../schema` right after it lands and shows `ColumnMappingStep` only when that resolves, gating `Continue` until it's confirmed.
- `POST /api/plans/{id}/research` (Task 6) has no HTTP endpoint yet — pending a decision on `httpx.AsyncClient` lifecycle ownership.
- React UI (Task 13): functionally done (setup through export, including structured column mapping) except a dedicated styling/WCAG-AA pass. Windows installer (Task 14), final verification pass (Task 15): not started.
- `OpenAICompatibleProvider` (`tuneforge/providers/openai_compatible.py`) builds request URLs as `f"{base_url}/chat/completions"` / `f"{base_url}/models"` — the full API path must already be in `base_url` (e.g. `http://127.0.0.1:11434/v1` for Ollama, `https://generativelanguage.googleapis.com/v1beta/openai` for Gemini). It does not assume or append `/v1` itself.
- Structured-merge guards against re-running on a resumed run via `RunRecord.structured_merge_completed_at` (set once the merge commits), but the guard and the `records.jsonl` append aren't atomic with each other — a crash in that exact window, followed by a resume, could still double-append once. A second resume after that would not compound further. Revisit with an atomic write (temp file + rename) if this ever proves to matter in practice.

## Testing conventions

- Real libraries over mocks where the library's *own* behavior is what's being verified (e.g., real Docling parsing, real HF Datasets Parquet round-trip). Mocks (`httpx.MockTransport`, fake tokenizers) where a call is expensive/slow/network-dependent and only the calling code's logic is under test.
- Before trusting an unfamiliar third-party API, check it against the real installed package (`importlib.metadata`, actual imports, a real call) — this repo's history has multiple bugs from unverified assumptions about NeMo, Docling, and `transformers` internals. Don't repeat that.
