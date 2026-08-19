# DGX-Accelerated Docling Parsing + Caching — Plan

Status: **Implemented, deployed, ENABLED, and verified end-to-end (2026-08-18).** `TUNEFORGE_DOCLING_REMOTE_URL` is live in the repo-root `.env`, pointed at the deployed DGX service. Matches this repo's `DGX_plan.md` convention — a cross-cutting design doc written before implementation, kept updated as the work lands.

## 10. Real bug found and fixed after enabling it for real

Turning the setting on for real (not just in isolated tests) immediately surfaced a genuine frontend gap: `ProviderConfigStep.tsx`'s consent screen decided whether to show the consent checkbox purely from provider `endpoint_scope` — it had no way to know the backend now also required consent for remote *parsing*. A project using only local LLM providers would never see the checkbox, and `POST /runs/preview` would 422 forever with no way to grant consent through the UI. Found via the project's own (previously stale) Playwright e2e suite once run against the real, enabled setting — not by inspection alone. Fixed: `GET /api/session` now also returns `remote_parsing_enabled`, consumed by the wizard. See commit `9f1dbec`. The two pre-existing Playwright specs were also stale for unrelated reasons (predating an earlier wizard reorder and the judge-choice screen) and were brought current in the same pass.

## 9. Implementation summary (post-build)

- **`dgx_docling_service/`** (new top-level, own `pyproject.toml`, `[tool.uv] package = false`): `app.py` — `POST /convert` (raw bytes + `X-Document-Filename` header → `DoclingDocument` JSON), bearer-token auth via `DGX_PARSER_TOKEN` (logs a startup warning if unset — a service with no token accepts all requests), `SecurityError`/`ConversionError` → 422. Deployed to the DGX at `~/dgx_docling_service/`, running as a systemd **user** service (`~/.config/systemd/user/dgx-docling.service`, lingering already enabled on that account), bound to `100.95.183.32:9100` — the Tailscale interface specifically, confirmed NOT reachable via loopback or the box's public WiFi IP (`69.212.78.174`). Token lives in `~/dgx_docling_service/.env` (mode 600) on the DGX and in this repo's root `.env` as `DGX_PARSER_TOKEN`, same precedent as `GEMINI_API_KEY`/`HF_TOKEN`.
- **`backend/tuneforge/ingestion/remote_parser.py`** — `convert_document_remote`, sync `httpx.Client`, retries on `{502,503,504}`/connection errors (3 retries), translates 422 to `EncryptedDocumentError`/`CorruptDocumentError`, else `RemoteParsingUnavailableError`.
- **`backend/tuneforge/ingestion/documents.py`** — `convert_document_cached` gained `remote_parser_url`/`remote_parser_token`. **Correctness fix found in review**: a fallback (remote unreachable → local CPU) result is cached under a distinct `-fallback.json` file, never the `-remote.json` file a genuine remote success uses — otherwise one transient DGX outage would permanently pin a document to its CPU-parsed result, since a cache hit is checked before remote is ever retried. The plain (`-local`, no suffix) cache file is reused as-is in either mode, since it only ever holds a parse that was never routed through a failed remote attempt.
- **`backend/tuneforge/jobs/runner.py`, `api/runs.py`, `settings.py`** — wired exactly as designed in section 4 below: `TUNEFORGE_DOCLING_REMOTE_URL` global setting, consent extended via `_requires_remote_consent(..., remote_parsing_enabled=...)`, `estimate_total_rows` untouched (stays local-only by construction — no remote kwargs ever passed at that call site).
- Full backend suite: 343 passed. `dgx_docling_service` suite (runs on both Windows/CPU for logic tests and the real DGX for the CUDA path): 9 passed in both places.
- **Real end-to-end verification against the live deployed service** (not mocked): a 40-page/40-table PDF parsed via the real DGX service in 14.17s (first call, cold model load) then 0.138s (second call, cache hit) with identical markdown output both times. Fallback verified against a genuinely unreachable port: connection refused fast, warning logged, local CPU parse completed successfully, valid `DoclingDocument` returned.
- Independent code review (fresh subagent) run before deployment: 1 Important finding (the cache-poisoning issue above, fixed) and a few nits (also addressed — `DGX_PARSER_TOKEN` redaction added to `main.py`, retry-count assertion added, DGX service now warns at startup if unauthenticated).

---

## 0. Why this exists

Two questions were raised: (1) can Docling parsing be GPU-accelerated via the DGX Spark, given it handles multi-column layouts, complex tables, and other structured text; (2) does "parsed-document caching" need to be built, given re-hitting a GPU for every parse "is definitely not a convenient way."

## 1. Finding: caching already exists and works — nothing to build

`backend/tuneforge/ingestion/documents.py::convert_document_cached` is a real, tested cache, not a stub:

```python
def convert_document_cached(path, *, cache_dir, converter=None):
    source_hash = hash_file(path)                                   # sha256 of file bytes
    cache_path = cache_dir / f"{source_hash}-{docling.__version__}.json"
    if cache_path.exists():
        return DoclingDocument.load_from_json(cache_path), source_hash
    document = convert_document(path, converter=converter)
    cache_dir.mkdir(parents=True, exist_ok=True)
    document.save_as_json(cache_path)
    return document, source_hash
```

Content-hash + docling-version keyed, shared across every project/run at `artifact_store.base_dir / "_docling_cache"`, proven by `test_cache_hit_never_calls_the_converter` (`backend/tests/ingestion/test_documents.py`). Chunking downstream is not cached — confirmed acceptable (cheap, CPU-only, tokenizer-dependent).

**Decision: the GPU/remote parsing path slots in behind this SAME cache's miss branch.** A cache hit never touches the network or the DGX. No new caching layer.

## 2. Finding: no GPU config exists, and "connect to GPU" means a remote service, not a flag

Verified against the actually-installed `docling==2.120.1` source:

- `AcceleratorOptions(device=...)` is strictly local (`.to(device)` on in-process tensors) — cannot reach a remote machine.
- Docling does ship real remote-inference engines for layout/OCR (KServe v2) and VLM stages (OpenAI/vLLM-compatible API) — but **TableFormer (table extraction) has no remote option in this version**, always runs in-process.
- Since this app uses neither OCR nor VLM stages, and TableFormer can't be split out, a GPU-bearing process on the DGX is needed regardless — running layout in that same process is free. Standing up Docling's KServe/Triton machinery would be more infrastructure for no extra coverage.

**Decision: one FastAPI service on the DGX wrapping a whole `DocumentConverter`** (`AcceleratorOptions(device="cuda")`), not Docling's built-in remote engines. Full design in section 4.

## 3. Verification spike — RESULTS (2026-08-18)

Performed on the real DGX (`ligaadmin@100.95.183.32`, NVIDIA GB10, aarch64, Ubuntu 24.04.4), isolated in `~/tuneforge_docling_spike/` (own `uv` project, doesn't touch the 3 existing GPU services — confirmed still running afterward: qwen3vl-env, pdf-parser-agent, unsloth-ai-backend, all untouched).

1. **`uv` installed** on the DGX (was absent) — v0.12.5, user-space install (`~/.local/bin`), no sudo.
2. **`uv add docling==2.120.1` resolved a real CUDA-capable ARM64 torch wheel**: `torch==2.13.0+cu130`, plus `nvidia-nvshmem-cu13`/etc. — this was the single biggest unknown (zero prior documentation for GB10/ARM64+CUDA) and it resolved cleanly.
3. **`torch.cuda.is_available()` → `True`**, device name `NVIDIA GB10`, CUDA 13.0 — confirmed working.
4. **Benchmark**, real 40-page/40-table PDF (`output/pdf/customer_service_test_fixture_40_pages.pdf`), same `do_ocr=False` and `compile_torch_models=False` settings this app already uses:

   | | Cold | Warm |
   |---|---|---|
   | **DGX GPU** (GB10, CUDA) | 7.38s | 4.51s |
   | **Local CPU** (Windows dev machine, this app's actual `build_converter()`) | 110.91s | 115.11s |

   **~25x speedup warm, ~15x cold** — well above Docling's own published "~6x" figure (that figure is for a consumer RTX card on a lighter workload; this test's 40 real tables specifically exercise TableFormer, the most GPU-sensitive stage, against a comparatively weaker CPU).

   Initial run (before matching the app's `compile_torch_models=False` setting) took 95s on GPU due to one-time `torch.compile()` JIT overhead — re-run with the app's actual setting applied gave the real number above. This confirms that setting matters for the DGX service too, not just as a Windows workaround.

5. **Correctness parity**: markdown export diffed line-by-line. 785/786 lines identical (including **all 40 tables**, exact match). One line differed — a single heading misclassified as plain text vs. an `##`-level heading on one page. Minor, isolated, not a systemic table/layout extraction problem. Worth a note in the eventual implementation, not a blocker.

**Verdict: spike passed. GPU parsing on the DGX is real, fast, and correct enough to build on.**

## 4. Recommended design

### DGX-side service

- `POST /convert`: raw document bytes in body, filename in `X-Document-Filename` header (Docling needs the extension). Handler wraps bytes in a `docling_core` `DocumentStream`, calls `converter.convert(...)` — no temp files.
- Response: `DoclingDocument.model_dump_json()` — same JSON shape the existing cache already round-trips via `save_as_json`/`load_from_json`. No new serialization format.
- `DocumentConverter` built once at process startup with `do_ocr=False`, `compile_torch_models=False` (confirmed necessary above), `AcceleratorOptions(device="cuda")`, `TableStructureOptions.mode=ACCURATE` (unchanged quality, only location changes).
- `SecurityError`/`ConversionError` → `422` with `{"error": "encrypted"|"corrupt"}`, re-raised client-side as the same `EncryptedDocumentError`/`CorruptDocumentError` types callers already handle.
- Bind to the Tailscale interface only, never `0.0.0.0` (mirrors this app's own `127.0.0.1`-only rule). Shared-secret bearer token (`DGX_PARSER_TOKEN`, resolved from `.env` like `GEMINI_API_KEY`/`HF_TOKEN`) as cheap defense-in-depth.

### TuneForge-side integration

- `convert_document_cached` gets one new optional param: `remote_parser_url: str | None = None`. On cache miss, if set, calls new sync `convert_document_remote(path, base_url=...)` (new file `backend/tuneforge/ingestion/remote_parser.py`) instead of local `convert_document`. Cache key/scope unchanged.
- **Stays synchronous** — `httpx.Client`, not `AsyncClient`. `_load_project_sources` runs before `asyncio.run(...)` starts in the worker; `estimate_total_rows` is already called unawaited from an async route today. Making this async would be an unrequested, much bigger refactor for no benefit.
- Borrow `OpenAICompatibleProvider`'s retry/timeout/typed-exception *pattern*, not the class itself (it's async/chat-shaped, doesn't fit bytes-in/JSON-out).
- **Consent**: extend `RunConsent`/`_requires_remote_consent` (`backend/tuneforge/api/runs.py`) to also require consent when remote parsing is configured — document bytes leaving the machine is the same category of event as the existing "remote provider" consent rule covers.
- **`estimate_total_rows` always stays local/cache-only** — confirmed by user — it has no run/consent mechanism today and won't get one just for row estimates.
- **No silent fallback to local CPU on DGX failure.** Retry a few times (mirroring `openai_compatible.py`'s retry-then-fail shape), then fail the run loudly. Silent fallback would mask a broken DGX/network as a mysteriously slow run.
- New setting: `TUNEFORGE_DOCLING_REMOTE_URL` in `backend/tuneforge/settings.py` — **global app-level toggle, confirmed by user**, not per-project.

### Deployment shape

New top-level `dgx_docling_service/` in this repo, own `pyproject.toml` (cannot be a workspace member of `backend/` — different platform/CUDA-ARM64 dependency tree entirely; keeps `cd backend && uv sync` on Windows untouched). Deploy by copying to the DGX (the scratch project at `~/tuneforge_docling_spike/` on the DGX already proves the exact dependency set resolves there) and running `uv sync && uv run uvicorn` — matches this project's existing manual, no-installer deploy philosophy.

## 5. Confirmed decisions (from user, 2026-08-18)

1. Direction: build the DGX parsing microservice (not local-GPU-only, not CPU-only-for-now).
2. `estimate_total_rows` always uses local/cache — never the DGX.
3. Remote parsing is a single **global** setting (`TUNEFORGE_DOCLING_REMOTE_URL`), not per-project.

## 6. Still open before implementation starts

1. **Process supervision on the DGX** — systemd user service vs. `tmux`/manual restart after reboot. Not decided.
2. **Retry count/timeout for the new remote call** — spike showed warm parses in single-digit seconds, but a cold multi-table PDF could take longer; propose `~3 retries`, `~30-60s timeout`, tune once the real service exists.
3. **The one heading-misclassification diff found in section 3** — worth a quick look when the real service is built (is it GPU-nondeterminism, or a genuine edge case in how Heron's layout confidence behaves on CUDA vs CPU?), not blocking.
4. **OCR stays out of scope** — `do_ocr=False` is a deliberate CLAUDE.md decision (avoiding OCR model downloads, not CPU speed) — a DGX GPU doesn't address that reasoning, not being reopened here.
5. **`TableFormerMode` stays `ACCURATE`** on both paths — this plan only changes *where* parsing runs.

## 7. Critical files (for the eventual `plan_N.md`)

- `backend/tuneforge/ingestion/documents.py` — `convert_document_cached`'s cache-miss branch, new `remote_parser_url` param.
- New: `backend/tuneforge/ingestion/remote_parser.py` — sync HTTP client to the DGX service.
- `backend/tuneforge/jobs/runner.py` — `_load_project_sources` (thread remote-parsing decision + consent through), `estimate_total_rows` (force local-only).
- `backend/tuneforge/settings.py` — new `TUNEFORGE_DOCLING_REMOTE_URL`.
- `backend/tuneforge/api/runs.py` — extend `_requires_remote_consent`.
- `backend/tuneforge/providers/openai_compatible.py` — reference pattern only, not modified.
- New top-level `dgx_docling_service/` — the FastAPI wrapper, own `pyproject.toml`. (A working scratch version of its dependency set already proven at `~/tuneforge_docling_spike/` on the DGX.)

## 8. Verification plan (once implementation happens)

- TDD per this repo's convention: failing test for `convert_document_cached`'s new branch (mock the remote call), confirm RED, implement, confirm GREEN — same pattern as `test_cache_hit_never_calls_the_converter`.
- Real run through the app's wizard with `TUNEFORGE_DOCLING_REMOTE_URL` set, confirming chunk output matches local parsing for the same file, and that a second run against the same file hits the cache (checked via the DGX service's own request log — no second call).
