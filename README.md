# TuneForge

Windows-first local web app. Turn documents (PDF, DOCX, HTML, Markdown, TXT, CSV, JSON, JSONL) into validated, model-aware training datasets (CPT, SFT prompt-completion, SFT conversation, DPO) for fine-tuning.

Local-only. Binds to `127.0.0.1`, never `0.0.0.0`.

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

Serves on `http://127.0.0.1:8420`. `/api/health` and `/api/version` are public.

## Repo layout

```
backend/    FastAPI app, all business logic (tuneforge/), tests
frontend/   React + Vite + TypeScript shell
```
