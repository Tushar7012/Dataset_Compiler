# DGX Spark + vLLM + Concurrent Chunk Processing — Plan

Status: **PLAN ONLY — nothing implemented, nothing installed on the DGX, nothing changed in the app.** Written for review. Do not start implementation until explicitly told to.

---

## 0. What changed the plan: hardware reality check

SSH access confirmed working (`ligaadmin@100.95.183.32`, key-based, no password). Before writing a deployment plan I checked the actual hardware instead of assuming a rack-style multi-GPU DGX. It is not that.

### Discovered hardware

```
GPU:        1x NVIDIA GB10 (Grace Blackwell Superchip)
CPU:        ARM Cortex-X925 / Cortex-A725, aarch64, 20 cores
Memory:     121 GiB total, UNIFIED (shared between CPU and GPU — not discrete VRAM)
            Currently: ~25 GiB used, ~95 GiB free
Disk:       3.7 TB, 3.0 TB free
OS:         Ubuntu 24.04.4 LTS (aarch64)
Driver:     580.142, CUDA 13.0
```

This is an **NVIDIA DGX Spark** ("Project DIGITS"), not a DGX H100/H200 server. It has one GPU, ARM64 CPU, and a single shared memory pool instead of per-GPU discrete VRAM. `nvidia-smi` reports GPU memory as `N/A` — normal for this architecture, confirmed via `nvidia-smi -q`, not a query error.

### Already running on the box (owned by you, not touched, not stopped without asking)

```
qwen3vl-env           uvicorn server   ~10.7 GiB GPU
pdf-parser-agent      uvicorn server   ~4.2 GiB GPU
unsloth-ai-backend    python3 process  ~0.17 GiB GPU
```

### Software present

```
Python 3.12.3, pip 24.0, Docker 29.2.1
uv:    NOT installed
nvcc:  NOT installed (fine — vLLM ships its own CUDA runtime via wheels/containers)
vllm:  NOT installed
```

### The finding that matters

**The two models from the HF router plan (`Qwen3-Next-80B-A3B-Instruct` generator + `Qwen3-235B-A22B-Instruct-2507` judge) do not fit on this box, at any quantization level, together or even separately in the judge's case.**

MoE models must keep *all* experts resident in memory regardless of how many activate per token — "3B active" doesn't mean "3B footprint."

| Model | Params | fp16 | int8 | int4/NVFP4 |
|---|---|---|---|---|
| Qwen3-Next-80B-A3B-Instruct | 80B | 160 GB | 80 GB | ~40 GB |
| Qwen3-235B-A22B-Instruct-2507 | 235B | 470 GB | 235 GB | ~117 GB |

Available headroom on the box: **~95 GB free right now, but that's the whole CPU+GPU pool**, shared with OS, your three existing services, Docker overhead, and — critically — vLLM's KV cache, which grows with concurrent requests (and concurrency is the entire point of step 2 below). A safe number to actually reserve for new model weights is more like **60–70 GB**, not 95.

Against that budget:
- The 235B judge (~117 GB at 4-bit) **does not fit under any circumstance** on this box.
- The 80B generator (~40 GB at 4-bit) fits *only* if it's the sole model loaded and nothing else needs headroom — leaves nothing for a judge and no real margin for KV cache growth under concurrency.

So the plan as literally stated ("both models on the DGX via vLLM") is not something I can build — not a matter of effort, the memory doesn't exist. This needed to be said plainly rather than quietly shipping something smaller and letting it look like the same thing.

---

## 1. Revised options for local hosting (pick one, or none)

### Option A — Hybrid (recommended)
- **Generator, local on DGX via vLLM:** a smaller but still capable model — `Qwen2.5-32B-Instruct` or `Qwen3-30B-A3B-Instruct-2507`, served at AWQ/INT4 (~16–18 GB weights + KV cache headroom). This is the high-volume call (1 question + up to 4 candidate answers per chunk) — the one that benefits most from killing network latency.
- **Judge, stays on the HF router:** `Qwen/Qwen3-235B-A22B-Instruct-2507` (the model actually in use today, unchanged). Judge calls are lower-volume (1 scoring call per candidate) and already fast (~1s measured) — the router is not the bottleneck there. This also sidesteps the "235B literally cannot fit" problem entirely.
- Fits comfortably inside the safe 60–70 GB budget with real headroom left for KV cache under concurrent load and your three existing services.

### Option B — Fully local, both models downsized
- Generator: `Qwen2.5-32B-Instruct` (AWQ/INT4, ~18 GB) + Judge: `Qwen2.5-7B-Instruct` or `Qwen2.5-14B-Instruct` (INT4, ~4–8 GB).
- Zero network dependency, fastest possible round-trip, but a real quality drop from the 80B/235B pair — most exposed on DPO's preference-scoring task, which needs the judge to discriminate reliably between two candidate answers.
- Worth noting from the actual DPO runs we already did: even the 235B non-thinking judge scored most candidates a tied 10/10 on this document's factual short-answer content — a smaller judge likely does no worse on *this specific kind* of content, but that's document-dependent and won't generalize to judgment-heavy prompts.

### Option C — No local hosting at all
- Keep both models exactly as they are today (HF router). Do **only** step 2 (concurrency) below.
- Zero DGX risk, zero model-quality tradeoff, ships fastest. Concurrency helps regardless of where the models live — it's the app that's currently serial, not just the network.

**My recommendation: Option C first, Option A as a follow-up.** Concurrency is the change with no downside and no hardware risk; it's worth landing and measuring on its own before deciding whether local hosting is still worth the added operational surface (a vLLM process to keep alive, model downloads, GPU contention with your other three services).

This is a decision for you, not something to default silently — pick A, B, or C (or "C now, revisit A/B later") before I touch anything.

---

## 2. Part 1 — vLLM on the DGX (once a model choice is made)

Applies regardless of A vs B, only the model names change.

1. **Deployment method:** Docker is already installed (29.2.1) — use NVIDIA's official vLLM container built for ARM/SBSA+Blackwell rather than a bare pip install, since `nvcc`/CUDA toolkit isn't present system-wide and vLLM's CUDA-dependent build has historically been finicky on aarch64 outside a maintained container. **To verify at implementation time, not assumed:** confirm current vLLM ARM64+GB10 container support (image tag, minimum vLLM version with confirmed Blackwell/GB10 kernels) directly against NVIDIA's docs before pulling anything — this is a fast-moving target and I won't guess a tag.
2. **Serve the chosen model(s)** as OpenAI-compatible endpoints on dedicated ports not already in use (existing services are on whatever ports `qwen3vl-env`/`pdf-parser-agent`/`unsloth-ai-backend` bound — check with `ss -tlnp` before assigning new ones, e.g. `:8001` generator, `:8002` judge if Option B).
3. **Quantization:** AWQ or NVFP4 (Blackwell has native FP4 tensor core support — worth benchmarking against AWQ once running, since FP4 is likely faster on this specific chip).
4. **Memory guard:** set vLLM's `--gpu-memory-utilization` conservatively (not the default 0.9) given the unified-memory sharing with your other services and the OS — start low, measure, raise only if headroom proves real under load.
5. **App-side change: none.** `OpenAICompatibleProvider` already speaks the OpenAI chat-completions shape. Point the provider's `base_url` at `http://100.95.183.32:PORT/v1` instead of `https://router.huggingface.co/v1`, blank `api_key` (vLLM doesn't need one by default, or set a shared token if you want one). This is a config change in `ProviderConfigStep` (or a new preset alongside the existing HF router ones), not a provider-layer code change.
6. **Timeout:** with local GPU serving, `ProviderProfile.timeout_seconds` (currently 30s default) should be fine or even reducible — the whole reason it broke before was a *remote, queued, Thinking-mode* model; a local instruct model should respond in low single-digit seconds.

---

## 3. Part 2 — Concurrent chunk processing (independent of Part 1, safe to do regardless)

Current state (`backend/tuneforge/jobs/runner.py`, `_run_generation_async`): the per-chunk loop `await`s `generate_record(...)` for one chunk, writes it, then moves to the next — strictly serial, even though nothing about chunk *i*'s generation depends on chunk *i-1*'s result. Each chunk is embarrassingly parallel.

For DPO specifically (`backend/tuneforge/generation/generator.py`, `generate_dpo_record`), there's a second, nested serialization: the `max_candidates` (default 4) candidate-generation + judge-scoring calls inside one chunk are also a plain `for` loop of sequential `await`s, when the 4 candidates are independent draws that could be requested together.

### Plan

1. **Chunk-level concurrency in `_run_generation_async`:** replace the sequential `for chunk in chunks: record = await generate_record(...)` with `asyncio.gather` over chunks, bounded by an `asyncio.Semaphore(N)` so we don't fire all 80 chunks at once against a server that can't actually serve that many concurrently. `N` should be a config value, not hardcoded — start conservative (e.g. 4–8) and tune against whatever backend is actually serving (HF router's real concurrent-request ceiling is unknown/rate-limited; a local vLLM instance's ceiling is `--max-num-seqs`, which we'd read/configure directly once Part 1 exists).
2. **Preserve existing behavior that depends on ordering/resumability:** the current code writes each accepted record to `records.jsonl` as it completes and updates `RunRecord.completed_rows` incrementally (this is what powers the live progress bar in `PreviewStep`/`RunProgressStep`, and what makes crash-resume work). Concurrent chunks completing out of order is fine for the JSONL append (order doesn't matter for training data) but the progress-counter update and the resume checkpoint need to stay correct under concurrent writes — this needs a lock or a queue-and-single-writer pattern, not naive concurrent file appends from N coroutines.
3. **DPO's inner candidate loop:** change `generate_dpo_record`'s `for _candidate_index in range(spec.max_candidates)` to `asyncio.gather` across the 4 candidate-generation-and-score calls. This is the more impactful of the two changes for DPO specifically, since it's 1 (question) + 4×2 (candidate + score) = 9 sequential calls per chunk today, collapsible to 1 + 1 round of 4 concurrent pairs.
4. **Respect `max_retries`:** retries currently happen in an outer `for _ in range(spec.max_retries + 1)` loop around the whole per-chunk attempt — this stays sequential per chunk (a failed chunk retries against itself, not against other chunks), only the *cross-chunk* and *cross-candidate* dimensions become concurrent.
5. **Cancellation:** `RunRecord` already supports `cancel_requested` — with concurrent in-flight requests, cancellation needs to actually cancel the outstanding `asyncio` tasks (via the semaphore-gathered group), not just stop scheduling new ones, or a cancel click would still wait for N in-flight chunks to finish before honoring it.
6. **Testing approach (per this repo's TDD convention):** write a test that asserts N `MockTransport` calls can be in-flight concurrently (e.g. using an `asyncio.Event` the mock handler waits on, released only after confirming ≥N requests arrived before any resolves) — proves the concurrency is real, not just "doesn't crash." Then re-run the full existing suite to confirm ordering-independent record writing and progress counting still hold.

### Not in scope for this change
- SFT/CPT generation shares the same `_run_generation_async` loop, so the chunk-level concurrency (item 1) benefits them automatically — no separate work needed there. CPT specifically has no LLM call at all (`build_cpt_record` is a pure passthrough), so it was never bottlenecked by this in the first place; only the chunk-iteration overhead (Docling-adjacent, not generation) applies to it.
- Docling GPU/FAST-mode changes (mentioned in the earlier discussion) are **not** part of this plan — separate piece of work, not requested to be planned here yet.

---

## 4. Open decisions before implementation starts

1. **A, B, or C** from section 1 — which model-hosting shape do you want.
2. If A or B: **exact model names** for the downsized generator/judge (proposed candidates given above, not final).
3. **Concurrency limit (`N`)** for chunk-level fan-out — start conservative and tune, or do you have a number in mind already based on other things running on this box.
4. Confirm it's fine to **not touch** the three existing services on the DGX (qwen3vl-env, pdf-parser-agent, unsloth-ai-backend) — plan assumes they keep running untouched and vLLM gets whatever memory is left over, not the reverse.
5. Order of implementation: Part 2 (concurrency) has no hardware dependency and could ship first/independently; Part 1 (DGX+vLLM) depends on your answers to 1–2 above. Confirm you want them in the original stated order (1 then 2) rather than 2 first.
