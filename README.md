# TuneForge

Local web app. Turn documents (PDF, DOCX, HTML, Markdown, TXT, CSV, JSON, JSONL) into validated, model-aware training datasets (CPT, SFT prompt-completion, SFT conversation, DPO) for fine-tuning.

Local-only. Binds to `127.0.0.1`, never `0.0.0.0`. Runs the same on Windows, macOS, and Linux.

## Architecture

FastAPI backend, separate OS worker process for generation (crash isolation), SQLite as the only shared state between the two. See system design diagram (linked in project docs).

Pipeline: ingest document → analyze target model (no LLM call, reads config.json) → recommend training objective (deterministic rules) → chunk with target tokenizer → generate via OpenAI-compatible provider (CPT needs no LLM call at all) → validate (structural + dedup + optional/mandatory judging) → export (Parquet + JSONL + manifest).

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

API keys and tokens are stored in the OS credential store only (never SQLite, logs, exports, or a `.env` file). Set them once:

```bash
cd backend
uv run python scripts/set_secrets.py
```

Paste the Gemini API key and Hugging Face token when prompted. See `CLAUDE.md` for what each credential unlocks (AI goal suggestion / remote generation vs. Hub model analysis).

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

## Platform notes

- **Windows:** Credential Manager is always available. Default data dir: `%LOCALAPPDATA%\TuneForge`.
- **macOS:** Keychain is always available. Default data dir: `~/Library/Application Support/TuneForge`.
- **Linux:** Default data dir: `$XDG_DATA_HOME/TuneForge` or `~/.local/share/TuneForge`. Credential storage needs a running Secret Service provider (`gnome-keyring`, KWallet, or equivalent). Headless/server Linux without a desktop session typically has neither — `keyring` will fall back to a fail backend that rejects store/retrieve. Install and unlock a Secret Service for your environment before expecting credential APIs to work.

Override the data directory on any OS with `TUNEFORGE_DATA_DIR`.

## Repo layout

```
backend/    FastAPI app, all business logic (tuneforge/), tests
frontend/   React + Vite + TypeScript UI
```
