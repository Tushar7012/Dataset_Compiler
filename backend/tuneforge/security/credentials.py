from __future__ import annotations

import keyring
from keyring.errors import PasswordDeleteError

_SERVICE_NAME = "TuneForge"


class CredentialNotFoundError(RuntimeError):
    pass


def store_api_key(provider_name: str, api_key: str) -> None:
    keyring.set_password(_SERVICE_NAME, provider_name, api_key)


def get_api_key(provider_name: str) -> str:
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
