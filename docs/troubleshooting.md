# TuneForge troubleshooting

## The AI suggestion says “credential not configured”

Create a `.env` at the repo root (next to `README.md`) with:

```
GEMINI_API_KEY=...
HF_TOKEN=...
```

Restart the backend after editing `.env`. Keys are loaded at process start.

## My run stopped before I expected

TuneForge caps accepted rows at **100,000** per run. The goal step’s estimate may show that your sources contain more rows than will be processed. Check the plan’s `target_rows` and any truncation warning on the goal step.

## Continue is disabled after upload

Structured files (CSV/JSON/JSONL) must finish column mapping (Preview → Confirm). Document uploads must finish the automatic format probe. A non-422 probe error shows Retry — fix the backend/network issue rather than treating the file as a document.

## Model analyze rejected my model

Only text decoder-only causal LMs are supported. GGUF and multimodal models are rejected. GPT-2-class models use the older `LMHeadModel` architecture suffix — that path is intentional.

## DPO plan / run fails about the judge

DPO requires a **judge model distinct from the generator**. Configure two different model names (they can both be local). Remote judges also need consent threading; remote judging is a known limitation if consent is not passed through.

## Provider calls fail with odd URL errors

`base_url` must already include the API path prefix (for example `http://127.0.0.1:11434/v1` or Gemini’s OpenAI-compatible base). TuneForge appends `/chat/completions` and `/models` only — it does not add `/v1` for you.

## App won’t start / data directory

On Windows the default data dir is `%LOCALAPPDATA%\TuneForge`. Override with `TUNEFORGE_DATA_DIR` if needed.

## Linux credential store errors

Dynamically configured provider keys still use `keyring`. Headless Linux needs a Secret Service (`gnome-keyring`, KWallet, …). Gemini/HF from `.env` do not need keyring.
