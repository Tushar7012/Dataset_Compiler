# TuneForge

Windows-first local web app. Turn documents (PDF, DOCX, HTML, Markdown, TXT, CSV, JSON, JSONL) into validated, model-aware training datasets (CPT, SFT prompt-completion, SFT conversation, DPO) for Unsloth fine-tuning.

Local-only. Binds to `127.0.0.1`, never `0.0.0.0`. No document text or credentials leave your machine unless you explicitly approve a remote provider call.

## Status

Backend logic (Tasks 1-12 of `PLAN.md`) built, tested, pushed. React UI (Task 13), Windows installer (Task 14), final verification (Task 15) not started. Full REST API wiring in progress (`plan_7.md`).

193+ backend tests passing. No app UI yet — backend is a tested library, not yet a clickable tool.

## Architecture

FastAPI backend, separate OS worker process for generation (crash isolation), SQLite as the only shared state between the two. See system design diagram (linked in project docs).

Pipeline: ingest document → analyze target model (no LLM call, reads config.json) → recommend training objective (deterministic rules) → chunk with target tokenizer → generate via OpenAI-compatible provider (CPT needs no LLM call at all) → validate (structural + dedup + optional/mandatory judging) → export (Parquet + JSONL + manifest).

## Tech stack

Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite (WAL), Docling (document parsing), Hugging Face Hub/Transformers/Datasets, uv (dependency management). React + Vite + TypeScript frontend (scaffolded, minimal).

## Setup

```powershell
cd backend
uv sync
uv run pytest -q
```

```powershell
cd frontend
pnpm install
pnpm test --run
pnpm build
```

Run the backend:

```powershell
cd backend
uv run python -m tuneforge.main
```

Serves on `http://127.0.0.1:8420`. `/api/health` and `/api/version` are public; everything else needs a bearer session token (issued at launch, held in memory only).

## Security constraints

- Loopback bind only, strict origin checking, redacted logs.
- API keys stored in Windows Credential Manager only — never SQLite, logs, or exports.
- Remote provider calls require explicit per-run consent before any document text is sent.
- DPO requires a judge model distinct from the generator model.

## Repo layout

```
backend/    FastAPI app, all business logic (tuneforge/), tests
frontend/   React + Vite + TypeScript shell
plan_*.md   Implementation plans, one per work session, task-by-task with tests
PLAN.md     Master spec — all 15 tasks, canonical data contracts, API surface
```

## Docs

- `PLAN.md` — master spec.
- `plan_1.md` through `plan_7.md` — implementation history, one file per delivered chunk of work, each with real code and tests an executing AI followed task-by-task.
