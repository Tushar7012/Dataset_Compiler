from __future__ import annotations

import os
from pathlib import Path

import keyring
from dotenv import load_dotenv
from keyring.errors import PasswordDeleteError

_SERVICE_NAME = "TuneForge"

# The two credentials this app pre-configures from .env. Anything else
# (a project's own provider profile, created via ProviderConfigStep) is
# never in .env — those still resolve via keyring only, below.
_ENV_VAR_BY_WELL_KNOWN_NAME = {
    "gemini": "GEMINI_API_KEY",
    "huggingface": "HF_TOKEN",
}

# credentials.py -> security/ -> tuneforge/ -> backend/ -> repo root.
_DOTENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_DOTENV_PATH)  # no-op, does not raise, if the file doesn't exist


class CredentialNotFoundError(RuntimeError):
    pass


def store_api_key(provider_name: str, api_key: str) -> None:
    keyring.set_password(_SERVICE_NAME, provider_name, api_key)


def get_api_key(provider_name: str) -> str:
    env_var = _ENV_VAR_BY_WELL_KNOWN_NAME.get(provider_name)
    if env_var:
        value = os.environ.get(env_var)
        if value:
            return value

    value = keyring.get_password(_SERVICE_NAME, provider_name)
    if value is None:
        raise CredentialNotFoundError(f"no credential stored for provider: {provider_name}")
    return value


# provider_name is often shared across records (e.g. "gemini", "huggingface" — see
# tuneforge.api.providers.GEMINI_API_KEY_CREDENTIAL_NAME and
# tuneforge.models.analyzer.HF_TOKEN_CREDENTIAL_NAME): never delete-by-reference without
# first checking whether other ProviderProfileRecord rows still point at the same name.
def delete_api_key(provider_name: str) -> None:
    try:
        keyring.delete_password(_SERVICE_NAME, provider_name)
    except PasswordDeleteError:
        pass
