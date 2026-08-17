# TuneForge privacy

## What stays local

- Uploaded documents and datasets on disk under the TuneForge data directory.
- SQLite project/run metadata.
- Generation worker output (`records.jsonl`, exports).
- Dynamically configured provider API keys in the OS credential store (Windows Credential Manager / Keychain / Secret Service).
- Session bearer token — memory only for the process lifetime; never written to SQLite or exports.

## What can leave the machine

Remote calls happen only when you opt in:

| Action | Destination | Consent |
|--------|-------------|---------|
| AI suggested goal | Google Gemini (sample of document text) | Explicit checkbox on that step |
| Remote generator/judge | The provider URL you configured | Explicit checkbox when endpoint scope is `remote`, plus per-run consent flags on preview/full runs |
| Hugging Face Hub | Model configs / tokenizers / optional model cards | Uses `HF_TOKEN` from `.env` for authenticated Hub access when analyzing or researching models |

Local providers (`endpoint_scope=local`) do not send document text off-box through TuneForge’s remote-consent path.

## Credentials

`GEMINI_API_KEY` and `HF_TOKEN` live in a repo-root `.env` file (gitignored). That is a deliberate trade-off versus OS credential stores — see `CLAUDE.md`. Do not commit `.env` or paste keys into chat, tickets, or screenshots of the repo folder.
