"""One-time setup: store the Gemini API key and Hugging Face token in Windows
Credential Manager, so the backend never asks for them again.

Run once from backend/:
    uv run python scripts/set_secrets.py

Leave a prompt blank to skip it (e.g. re-run just to update one key).
Nothing here ever touches a file, the database, or a log — see
tuneforge/security/credentials.py and CLAUDE.md's "no .env file" rule.
"""

from __future__ import annotations

import getpass

from tuneforge.api.providers import GEMINI_API_KEY_CREDENTIAL_NAME
from tuneforge.models.analyzer import HF_TOKEN_CREDENTIAL_NAME
from tuneforge.security.credentials import store_api_key

_SECRETS = (
    ("Gemini API key", GEMINI_API_KEY_CREDENTIAL_NAME),
    ("Hugging Face token", HF_TOKEN_CREDENTIAL_NAME),
)


def main() -> None:
    for label, credential_name in _SECRETS:
        value = getpass.getpass(f"{label} (blank to skip): ").strip()
        if not value:
            print(f"  skipped {label}")
            continue
        store_api_key(credential_name, value)
        print(f"  stored {label} in Windows Credential Manager")


if __name__ == "__main__":
    main()
