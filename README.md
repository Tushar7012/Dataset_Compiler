# TuneForge

Turn documents (PDF, DOCX, HTML, Markdown, TXT, CSV, JSON, JSONL) into validated, model-aware training datasets (CPT, SFT prompt-completion, SFT conversation, DPO) for fine-tuning.

## Architecture

Pipeline: ingest document → analyze target model (no LLM call, reads config.json) → chunk with target tokenizer → generate via OpenAI-compatible provider (CPT needs no LLM call at all) → validate (structural + dedup + optional/mandatory judging) → export (Parquet + JSONL).

## Tech stack

Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite (WAL), Docling (document parsing), Hugging Face Hub/Transformers/Datasets, uv (dependency management). React + Vite + TypeScript frontend.

## Setup

```bash
cd backend
uv sync
uv run pytest -q
```

```bash
cd frontend
corepack pnpm install
corepack pnpm test -- --run
corepack pnpm build
```

Run the backend (dev mode, with the Vite proxy for the UI):

```bash
cd backend
uv run python -m tuneforge.main
```

Serves on `http://127.0.0.1:8420`. `/api/health` and `/api/version` are public.

## Credentials

Create a `.env` file at the repo root (same directory as this README) with:

```
GEMINI_API_KEY=...
HF_TOKEN=...
```

See `CLAUDE.md` for what each credential unlocks (AI goal suggestion / remote generation vs. Hub model analysis)

## Running it as a website (not dev mode)

Build the frontend, then start the backend alone — `create_app()` mounts `frontend/dist` at `/` when that directory exists:

```bash
cd frontend
corepack pnpm install
corepack pnpm build

cd ../backend
uv sync
uv run python -m tuneforge.main
```

Open `http://127.0.0.1:8420/` — one process serves the API and the built UI. No separate frontend server in this mode.

## Repo layout

```
backend/    FastAPI app, all business logic (tuneforge/), tests
frontend/   React + Vite + TypeScript UI
```
