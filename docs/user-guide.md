# TuneForge user guide

TuneForge turns documents and structured datasets into validated training bundles for Unsloth fine-tuning. Everything runs on your machine and binds only to `127.0.0.1`.

## Before you start

1. Create a repo-root `.env` with `GEMINI_API_KEY` and `HF_TOKEN` (see README).
2. Build or run the app:
   - Website mode: `corepack pnpm build` in `frontend/`, then `uv run python -m tuneforge.main` in `backend/`, open `http://127.0.0.1:8420/`.
   - Dev mode: backend as above plus `corepack pnpm exec vite` in `frontend/` (proxied API).

## Wizard walkthrough

### 1. Project setup

Name the project, then upload sources. Documents (PDF, DOCX, Markdown, …) are chunked for generation. CSV/JSON/JSONL that match a known training shape open **column mapping** — confirm the mapping before Continue. Continue stays disabled until every upload is either a plain document or a confirmed mapping.

### 2. Model selection

Pick Hugging Face or a local directory, enter the model id/path, Analyze. TuneForge only accepts text decoder-only causal LMs. Review architecture evidence, then Continue.

### 3. Suggested training goal (optional)

Consent is required before any document sample is sent to Gemini. Accept the suggestion, reject and describe your own purpose, or skip and choose the goal yourself on the next step.

### 4. Training goal

Choose goal, desired behavior, and language. Target row count is estimated automatically from your sources (capped at 100,000). Get recommendation.

### 5. Confirm plan

Review objective, schema, validators, and confidence. Approve to proceed.

### 6. Provider configuration

Configure an OpenAI-compatible generator (local Ollama-style or remote). Remote endpoints require an explicit consent checkbox before Continue. Leave API key blank to use the pre-configured Gemini credential from `.env` when applicable.

### 7. Preview

Generate a small preview run, inspect accepted rows, then approve the full run.

### 8. Run progress

Watch status and counts. Cancel if needed; Resume continues from the last checkpoint.

### 9. Export

Download the zip (Parquet/JSONL, manifest, provenance, training plan). Load the files with Hugging Face `datasets` into Unsloth’s trainers as described on the export screen.
