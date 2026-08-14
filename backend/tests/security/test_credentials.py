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
