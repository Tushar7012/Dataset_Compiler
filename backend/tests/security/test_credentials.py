import os
import subprocess
from pathlib import Path

import pytest
from keyring.errors import PasswordDeleteError

from tuneforge.security import credentials


class _FakeKeyring:
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service, name, value):
        self._store[(service, name)] = value

    def get_password(self, service, name):
        return self._store.get((service, name))

    def delete_password(self, service, name):
        if (service, name) not in self._store:
            raise PasswordDeleteError(name)
        del self._store[(service, name)]


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(credentials, "keyring", fake)
    return fake


def test_store_and_retrieve_api_key():
    credentials.store_api_key("openai-local", "sk-test-123")
    assert credentials.get_api_key("openai-local") == "sk-test-123"


def test_missing_credential_raises_clear_error():
    with pytest.raises(credentials.CredentialNotFoundError):
        credentials.get_api_key("does-not-exist")


def test_delete_is_idempotent():
    credentials.store_api_key("openai-local", "sk-test-123")
    credentials.delete_api_key("openai-local")
    credentials.delete_api_key("openai-local")
    with pytest.raises(credentials.CredentialNotFoundError):
        credentials.get_api_key("openai-local")


def test_get_api_key_prefers_env_var_for_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert credentials.get_api_key("gemini") == "from-env"


def test_get_api_key_prefers_env_var_for_huggingface(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "from-env-hf")
    assert credentials.get_api_key("huggingface") == "from-env-hf"


def test_get_api_key_falls_back_to_keyring_when_env_var_absent(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    credentials.store_api_key("gemini", "from-keyring")
    assert credentials.get_api_key("gemini") == "from-keyring"


def test_get_api_key_env_var_does_not_affect_unrelated_provider_names(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    credentials.store_api_key("provider-abc123", "arbitrary-provider-key")
    assert credentials.get_api_key("provider-abc123") == "arbitrary-provider-key"


def test_resolved_secrets_tracks_keyring_sourced_values():
    credentials.store_api_key("provider-xyz", "tracked-keyring-secret")
    credentials.get_api_key("provider-xyz")
    assert "tracked-keyring-secret" in credentials.resolved_secrets()


def test_resolved_secrets_tracks_env_sourced_values(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "tracked-env-secret")
    credentials.get_api_key("gemini")
    assert "tracked-env-secret" in credentials.resolved_secrets()


def test_resolved_secrets_does_not_include_unresolved_credentials():
    credentials.store_api_key("provider-never-resolved", "should-not-appear")
    assert "should-not-appear" not in credentials.resolved_secrets()


def test_dotenv_loads_on_a_real_cold_interpreter_start(tmp_path):
    # monkeypatch.setenv only proves get_api_key reads os.environ correctly —
    # it never re-exercises the module-level `load_dotenv(_DOTENV_PATH)` call,
    # since that line only runs once per interpreter, at import time, and
    # tuneforge.security.credentials is already imported and cached for the
    # rest of this pytest process. Only a genuinely separate interpreter
    # (spawned the same way `uv run python -m tuneforge.main` is, in real
    # use) re-runs that line against a real file on disk.
    backend_dir = Path(__file__).resolve().parents[2]
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=cold-start-secret-value-123\n")

    # Must NOT inherit the parent test process's os.environ wholesale — this
    # process already ran the real load_dotenv() at import time (against the
    # real repo-root .env), so GEMINI_API_KEY may already be set here. Passing
    # os.environ through as-is would let the child see that real value via
    # plain inheritance, never actually exercising its own dotenv load — and
    # would leak a real secret into this test's output on any mismatch.
    clean_env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "HF_TOKEN")}
    clean_env["TUNEFORGE_DOTENV_PATH"] = str(env_file)

    script = "from tuneforge.security.credentials import get_api_key; print(get_api_key('gemini'), end='')"
    result = subprocess.run(
        ["uv", "run", "python", "-c", script],
        cwd=backend_dir,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "cold-start-secret-value-123"
