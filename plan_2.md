# TuneForge Implementation Plan — Part 2 (Tasks 3 & 4)

> **For the executing AI:** This document is self-contained — you don't need `PLAN.md` to do this work, though it exists in the repo as the master spec. Tasks 1 and 2 are already implemented and committed (`backend/tuneforge/main.py`, `backend/tuneforge/settings.py`, `backend/tuneforge/storage/`). This part builds two independent subsystems on top of that: the provider client used to talk to OpenAI-compatible LLM endpoints, and the analyzer that inspects a target Hugging Face/local model before any training plan can be built. Neither task touches what Tasks 1–2 built. Do not implement anything beyond Task 3 and Task 4 — later tasks arrive in `plan_3.md` onward once these are reviewed.
>
> Every code block in this document has already been run and verified against the actual installed library versions (httpx, keyring, huggingface_hub) — copy it as-is. Only write your own code where a step explicitly asks you to and gives you the test it must pass.
>
> When both tasks are done, stop and produce the completion report described at the bottom. Do not push to GitHub.

**Goal (this part):** Add a secure OpenAI-compatible provider client (local and remote endpoints, retries, credential storage) and a deterministic target-model analyzer (Hugging Face or local, causal-LM/chat-template/GGUF detection with evidence).

**Architecture:** Both subsystems are plain, framework-independent Python modules under `backend/tuneforge/` — nothing here is wired into FastAPI routes yet (that happens in later parts). Task 3 and Task 4 don't depend on each other and don't depend on Task 2's storage layer; they're pure logic + external API calls (HTTP to the provider, HTTP to the Hugging Face Hub) with domain-specific exceptions instead of leaking library exceptions to callers.

**Tech Stack (new in this part):** httpx (as a runtime dependency now, not just for tests), `keyring` (Windows Credential Manager backend), `huggingface_hub`, `pytest-asyncio`.

## Global Constraints

Same as Part 1 — repeated here since they apply to this part too:

- Windows-first local web application. Bind only to `127.0.0.1` (unaffected by this part, no server changes).
- Python 3.12 is the fixed backend runtime.
- API keys must go through Windows Credential Manager and must never touch SQLite, logs, or exported files.
- No hardcoded secrets anywhere.
- Text decoder-only causal language models only — GGUF, multimodal, and non-causal architectures are rejected, not silently accepted.

## Development Environment

Same as Part 1: everything Python goes through **uv**, no conda, no system Python, no direct `pip`.

```powershell
cd backend
uv sync
uv run pytest -q
```

`uv sync` will pick up the new dependencies added to `pyproject.toml` in Task 3 below and update `uv.lock` automatically.

## Repository State

Same repo, branch `main`, `origin` already set to `https://github.com/Tushar7012/Dataset_Compiler.git`. Commit locally as instructed below. **Do not run `git push`.**

## File Structure (this part)

```
backend/
  pyproject.toml                 (modified — new dependencies)
  tuneforge/
    security/
      __init__.py
      credentials.py
    providers/
      __init__.py
      protocol.py
      openai_compatible.py
    models/
      __init__.py
      evidence.py
      compatibility.py
      analyzer.py
  tests/
    security/
      __init__.py
      test_credentials.py
    providers/
      __init__.py
      test_openai_compatible.py
    models/
      __init__.py
      test_analyzer.py
```

---

### Task 3: OpenAI-compatible provider subsystem

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/tuneforge/security/__init__.py`
- Create: `backend/tuneforge/security/credentials.py`
- Create: `backend/tuneforge/providers/__init__.py`
- Create: `backend/tuneforge/providers/protocol.py`
- Create: `backend/tuneforge/providers/openai_compatible.py`
- Create: `backend/tests/security/__init__.py`
- Create: `backend/tests/security/test_credentials.py`
- Create: `backend/tests/providers/__init__.py`
- Create: `backend/tests/providers/test_openai_compatible.py`

**Interfaces produced (later parts of this plan rely on these exact names):**
- `tuneforge.security.credentials.store_api_key(provider_name, api_key)`, `.get_api_key(provider_name) -> str`, `.delete_api_key(provider_name)`, `.CredentialNotFoundError`
- `tuneforge.providers.protocol.ProviderHealth`, `.GenerationRequest`, `.GenerationResponse`, `.ProviderProfile`, `.RunConsent`, `.ChatProvider` (Protocol)
- `tuneforge.providers.openai_compatible.OpenAICompatibleProvider(profile, client)` with `.health() -> ProviderHealth`, `.generate(request, consent=None) -> GenerationResponse`
- `tuneforge.providers.openai_compatible.ProviderAuthError`, `.ProviderResponseError`, `.RemoteConsentRequiredError`

#### Step 1: Update dependencies

Edit `backend/pyproject.toml` — move `httpx` out of the dev group into real dependencies (the provider client needs it at runtime, not just in tests), and add `keyring` and `huggingface-hub`. Add `pytest-asyncio` to dev and turn on `asyncio_mode` so async tests don't need per-test decorators:

```toml
[project]
name = "tuneforge"
version = "0.1.0"
description = "TuneForge backend"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "sqlalchemy>=2.0.35",
    "httpx>=0.27",
    "keyring>=25.0",
    "huggingface-hub>=1.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["tuneforge*"]
```

```powershell
cd backend
uv sync
```

Create empty `backend/tuneforge/security/__init__.py`, `backend/tuneforge/providers/__init__.py`, `backend/tests/security/__init__.py`, `backend/tests/providers/__init__.py`.

#### Step 2: Credential storage — write the failing tests (RED)

Create `backend/tests/security/test_credentials.py`:

```python
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
```

The tests always run against a fake, in-memory keyring (via the autouse fixture) — this never touches the real Windows Credential Manager during test runs, so `pytest` stays fast and doesn't leave test entries behind on the developer's machine.

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/security/test_credentials.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.security.credentials'`.

#### Step 3: Credential storage — implement (GREEN)

Create `backend/tuneforge/security/credentials.py`:

```python
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


def delete_api_key(provider_name: str) -> None:
    try:
        keyring.delete_password(_SERVICE_NAME, provider_name)
    except PasswordDeleteError:
        pass
```

Run the tests again:

```powershell
uv run pytest tests/security/test_credentials.py -q
```

Expected: all pass.

#### Step 4: Provider client — write the failing tests (RED)

Create `backend/tuneforge/providers/protocol.py` first (needed by the tests):

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel


class ProviderHealth(BaseModel):
    healthy: bool
    detail: str


class GenerationRequest(BaseModel):
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int | None = None
    response_format: dict | None = None


class GenerationResponse(BaseModel):
    content: str
    raw: dict


class ProviderProfile(BaseModel):
    name: str
    base_url: str
    model: str
    endpoint_scope: Literal["local", "remote"]
    credential_reference: str | None = None
    timeout_seconds: float = 30.0
    max_concurrency: int = 4
    structured_output_supported: bool = False


class RunConsent(BaseModel):
    run_id: uuid.UUID
    granted_at: datetime


class ChatProvider(Protocol):
    async def health(self) -> ProviderHealth: ...
    async def generate(
        self, request: GenerationRequest, consent: RunConsent | None = None
    ) -> GenerationResponse: ...
```

`ProviderProfile.credential_reference` matches the field name already used on `ProviderProfileRecord` in `backend/tuneforge/storage/models.py` (Task 2) — the master spec's field list calls it `api_key_credential_reference`, but keeping it consistent with the already-shipped DB column matters more than matching that name exactly, since a future task will need to move data between the two without a rename.

Now create `backend/tests/providers/test_openai_compatible.py`:

```python
import logging
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from tuneforge.providers.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderAuthError,
    ProviderResponseError,
    RemoteConsentRequiredError,
)
from tuneforge.providers.protocol import GenerationRequest, ProviderProfile, RunConsent


def make_provider(handler, *, endpoint_scope="local", credential_reference=None):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(
        name="test",
        base_url="http://127.0.0.1:9999",
        model="test-model",
        endpoint_scope=endpoint_scope,
        credential_reference=credential_reference,
    )
    return OpenAICompatibleProvider(profile, client)


async def test_health_reports_ok_on_200():
    def handler(request):
        return httpx.Response(200, json={"data": []})

    provider = make_provider(handler)
    health = await provider.health()
    assert health.healthy is True


async def test_health_reports_unhealthy_on_error():
    def handler(request):
        return httpx.Response(500)

    provider = make_provider(handler)
    health = await provider.health()
    assert health.healthy is False


async def test_generate_returns_content_on_success():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    provider = make_provider(handler)
    result = await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))
    assert result.content == "hello"


async def test_generate_retries_on_503_then_succeeds():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = make_provider(handler)
    result = await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))
    assert result.content == "ok"
    assert calls["count"] == 3


async def test_generate_gives_up_after_max_retries():
    def handler(request):
        return httpx.Response(503)

    provider = make_provider(handler)
    with pytest.raises(ProviderResponseError):
        await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))


async def test_generate_does_not_retry_auth_errors():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(401)

    provider = make_provider(handler)
    with pytest.raises(ProviderAuthError):
        await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))
    assert calls["count"] == 1


async def test_remote_provider_refuses_generation_without_consent():
    def handler(request):
        raise AssertionError("should not reach the network without consent")

    provider = make_provider(handler, endpoint_scope="remote")

    with pytest.raises(RemoteConsentRequiredError):
        await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))


async def test_remote_provider_allows_generation_with_consent():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = make_provider(handler, endpoint_scope="remote")
    consent = RunConsent(run_id=uuid.uuid4(), granted_at=datetime.now(timezone.utc))

    result = await provider.generate(
        GenerationRequest(messages=[{"role": "user", "content": "hi"}]), consent=consent
    )
    assert result.content == "ok"


async def test_generate_logs_do_not_contain_prompt_or_credentials(caplog, monkeypatch):
    monkeypatch.setattr(
        "tuneforge.providers.openai_compatible.get_api_key", lambda ref: "super-secret-key"
    )

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = make_provider(handler, credential_reference="test-provider")
    secret_prompt = "the confidential document says XYZZY-SECRET"

    with caplog.at_level(logging.INFO, logger="tuneforge.providers"):
        await provider.generate(GenerationRequest(messages=[{"role": "user", "content": secret_prompt}]))

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "super-secret-key" not in log_text
    assert "XYZZY-SECRET" not in log_text
```

Every test drives the client through `httpx.MockTransport` — no real network call, no real server, fully deterministic (this is httpx's own recommended way to test retry/error-handling logic).

Run it and confirm it fails on the missing module:

```powershell
uv run pytest tests/providers/test_openai_compatible.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.providers.openai_compatible'`.

#### Step 5: Provider client — implement (GREEN)

Create `backend/tuneforge/providers/openai_compatible.py`:

```python
from __future__ import annotations

import logging
import uuid

import httpx

from tuneforge.providers.protocol import (
    GenerationRequest,
    GenerationResponse,
    ProviderHealth,
    ProviderProfile,
    RunConsent,
)
from tuneforge.security.credentials import get_api_key

logger = logging.getLogger("tuneforge.providers")

_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
_MAX_RETRIES = 3


class ProviderAuthError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    pass


class RemoteConsentRequiredError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(self, profile: ProviderProfile, client: httpx.AsyncClient):
        self.profile = profile
        self._client = client

    def _headers(self, request_id: str) -> dict[str, str]:
        headers = {"X-Request-ID": request_id}
        if self.profile.credential_reference:
            headers["Authorization"] = f"Bearer {get_api_key(self.profile.credential_reference)}"
        return headers

    async def health(self) -> ProviderHealth:
        request_id = uuid.uuid4().hex
        logger.info("provider health check request_id=%s provider=%s", request_id, self.profile.name)
        try:
            response = await self._client.get("/v1/models", headers=self._headers(request_id))
        except httpx.HTTPError as exc:
            return ProviderHealth(healthy=False, detail=f"request failed: {type(exc).__name__}")
        if response.status_code == 200:
            return ProviderHealth(healthy=True, detail="ok")
        return ProviderHealth(healthy=False, detail=f"status {response.status_code}")

    async def generate(
        self, request: GenerationRequest, consent: RunConsent | None = None
    ) -> GenerationResponse:
        if self.profile.endpoint_scope == "remote" and consent is None:
            raise RemoteConsentRequiredError(
                f"provider {self.profile.name!r} is remote; a run-specific consent "
                "record is required before sending anything to it"
            )

        request_id = uuid.uuid4().hex
        payload: dict = {
            "model": self.profile.model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.response_format is not None:
            payload["response_format"] = request.response_format

        attempt = 0
        while True:
            attempt += 1
            logger.info(
                "provider generate request_id=%s provider=%s attempt=%s",
                request_id,
                self.profile.name,
                attempt,
            )
            try:
                response = await self._client.post(
                    "/v1/chat/completions", json=payload, headers=self._headers(request_id)
                )
            except httpx.TimeoutException:
                if attempt > _MAX_RETRIES:
                    raise ProviderResponseError(f"request_id={request_id}: timed out after {attempt} attempts")
                continue

            if response.status_code in (401, 403):
                raise ProviderAuthError(f"request_id={request_id}: authentication rejected")

            if response.status_code in _RETRYABLE_STATUS_CODES:
                if attempt > _MAX_RETRIES:
                    raise ProviderResponseError(
                        f"request_id={request_id}: status {response.status_code} after {attempt} attempts"
                    )
                continue

            if response.status_code != 200:
                raise ProviderResponseError(f"request_id={request_id}: status {response.status_code}")

            data = response.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as exc:
                raise ProviderResponseError(f"request_id={request_id}: malformed response") from exc
            return GenerationResponse(content=content, raw=data)
```

The constructor always takes an explicit `httpx.AsyncClient` rather than creating and owning one internally — whoever wires this into the app (a later task) owns the client's lifetime, and tests always pass a mock-transport client. Don't add a "create my own client if none given" branch; nothing needs it yet.

Run the tests again:

```powershell
uv run pytest tests/providers/test_openai_compatible.py -q
```

Expected: all pass.

#### Step 6: Run the full backend suite and commit

```powershell
uv run pytest -q
```

Expected: every test from Parts 1 and 2's Task 3 passes (no regressions).

```powershell
git add backend
git commit -m "feat: add secure model provider profiles"
```

---

### Task 4: Target-model analyzer

**Files:**
- Create: `backend/tuneforge/models/__init__.py`
- Create: `backend/tuneforge/models/evidence.py`
- Create: `backend/tuneforge/models/compatibility.py`
- Create: `backend/tuneforge/models/analyzer.py`
- Create: `backend/tests/models/__init__.py`
- Create: `backend/tests/models/test_analyzer.py`

**Interfaces produced (later parts of this plan rely on these exact names):**
- `tuneforge.models.evidence.Evidence` (fields: `field`, `value`, `source`, `detail`)
- `tuneforge.models.compatibility.IncompatibleModelError`, `.is_causal_lm_architecture(architectures) -> bool`, `.reject_if_incompatible(*, is_gguf, architectures, model_type)`
- `tuneforge.models.analyzer.ModelProfile` — matches `PLAN.md`'s canonical `ModelProfile` contract exactly (`source`, `model_id`, `architecture`, `model_type`, `is_causal_lm`, `is_chat_model`, `chat_template_found`, `context_length`, `modalities`, `evidence`, `confidence`)
- `tuneforge.models.analyzer.analyze_model(model_id, *, source, local_path=None) -> ModelProfile`
- `tuneforge.models.analyzer.GatedModelError`, `.ModelNotAccessibleError`

Only `config.json` and `tokenizer_config.json` are inspected in this task (architecture, causal-LM check, chat template presence, context length). `generation_config.json`, processor metadata, and the model card mentioned in `PLAN.md`'s Task 4 description aren't consumed by any check yet — nothing downstream needs them until later tasks, so they're skipped rather than fetched and left unused.

#### Step 1: Evidence and compatibility — no test needed

These two files are simple enough (a data model, and two small pure functions) that a dedicated RED/GREEN cycle for each would just be test-the-language, not test-the-logic. They get exercised indirectly by the analyzer tests in Step 2 below, which is where the real behavior (and thus the real tests) lives.

Create `backend/tuneforge/models/__init__.py` (empty) and `backend/tests/models/__init__.py` (empty).

Create `backend/tuneforge/models/evidence.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class Evidence(BaseModel):
    field: str
    value: str
    source: str
    detail: str
```

Create `backend/tuneforge/models/compatibility.py`:

```python
from __future__ import annotations


class IncompatibleModelError(RuntimeError):
    """Raised when a model cannot be used by TuneForge at all (GGUF, non-causal, multimodal)."""


def is_causal_lm_architecture(architectures: list[str]) -> bool:
    return any(arch.endswith("ForCausalLM") for arch in architectures)


def reject_if_incompatible(*, is_gguf: bool, architectures: list[str], model_type: str) -> None:
    if is_gguf:
        raise IncompatibleModelError(
            "GGUF checkpoints are not supported — TuneForge works with Hugging Face "
            "Transformers-format models only."
        )
    if not is_causal_lm_architecture(architectures):
        raise IncompatibleModelError(
            f"model_type={model_type!r} with architectures={architectures!r} is not a "
            "text decoder-only causal language model, which is the only kind TuneForge supports."
        )
```

#### Step 2: Analyzer — write the failing tests (RED)

Create `backend/tests/models/test_analyzer.py`:

```python
import json
from pathlib import Path

import httpx
import pytest
from huggingface_hub.utils import EntryNotFoundError, GatedRepoError, LocalEntryNotFoundError

from tuneforge.models.analyzer import GatedModelError, ModelNotAccessibleError, analyze_model
from tuneforge.models.compatibility import IncompatibleModelError

QWEN_INSTRUCT_CONFIG = {
    "architectures": ["Qwen2ForCausalLM"],
    "model_type": "qwen2",
    "max_position_embeddings": 32768,
}
QWEN_INSTRUCT_TOKENIZER_CONFIG = {"chat_template": "{% for message in messages %}...{% endfor %}"}

LLAMA_BASE_CONFIG = {
    "architectures": ["LlamaForCausalLM"],
    "model_type": "llama",
    "max_position_embeddings": 4096,
}

CLASSIFIER_CONFIG = {
    "architectures": ["BertForSequenceClassification"],
    "model_type": "bert",
}


def _fake_downloads(files: dict[str, dict], tmp_path: Path):
    def fake_hf_hub_download(*, repo_id: str, filename: str) -> str:
        if filename not in files:
            raise EntryNotFoundError(f"{filename} not in {repo_id}")
        path = tmp_path / filename
        path.write_text(json.dumps(files[filename]))
        return str(path)

    return fake_hf_hub_download


def test_qwen_instruct_is_detected_as_chat_model(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "tuneforge.models.analyzer.hf_hub_download",
        _fake_downloads(
            {"config.json": QWEN_INSTRUCT_CONFIG, "tokenizer_config.json": QWEN_INSTRUCT_TOKENIZER_CONFIG},
            tmp_path,
        ),
    )

    profile = analyze_model("Qwen/Qwen2.5-7B-Instruct", source="huggingface")

    assert profile.is_causal_lm is True
    assert profile.is_chat_model is True
    assert profile.chat_template_found is True
    assert profile.context_length == 32768
    assert profile.confidence == 0.95


def test_llama_base_is_detected_as_non_chat_model(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "tuneforge.models.analyzer.hf_hub_download",
        _fake_downloads({"config.json": LLAMA_BASE_CONFIG}, tmp_path),
    )

    profile = analyze_model("meta-llama/Llama-3-8B", source="huggingface")

    assert profile.is_causal_lm is True
    assert profile.is_chat_model is False
    assert profile.chat_template_found is False


def test_missing_template_on_instruct_named_model_lowers_confidence(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "tuneforge.models.analyzer.hf_hub_download",
        _fake_downloads({"config.json": LLAMA_BASE_CONFIG}, tmp_path),
    )

    profile = analyze_model("some-org/mystery-Instruct-model", source="huggingface")

    assert profile.chat_template_found is False
    assert profile.confidence < 0.95
    assert any(e.field == "is_chat_model" for e in profile.evidence)


def test_gated_model_raises_actionable_error(monkeypatch):
    fake_response = httpx.Response(403, request=httpx.Request("GET", "https://huggingface.co"))

    def fake_download(*, repo_id, filename):
        raise GatedRepoError("gated", response=fake_response)

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_download)

    with pytest.raises(GatedModelError):
        analyze_model("meta-llama/Llama-3-8B", source="huggingface")


def test_offline_model_raises_actionable_error(monkeypatch):
    def fake_download(*, repo_id, filename):
        raise LocalEntryNotFoundError("offline")

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_download)

    with pytest.raises(ModelNotAccessibleError):
        analyze_model("meta-llama/Llama-3-8B", source="huggingface")


def test_gguf_only_repo_raises_actionable_error(monkeypatch):
    def fake_download(*, repo_id, filename):
        raise EntryNotFoundError("no config.json")

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_download)
    monkeypatch.setattr("tuneforge.models.analyzer.list_repo_files", lambda repo_id: ["model.Q4_K_M.gguf"])

    with pytest.raises(ModelNotAccessibleError, match="GGUF"):
        analyze_model("TheBloke/Llama-3-8B-GGUF", source="huggingface")


def test_classifier_model_is_rejected_as_incompatible(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "tuneforge.models.analyzer.hf_hub_download",
        _fake_downloads({"config.json": CLASSIFIER_CONFIG}, tmp_path),
    )

    with pytest.raises(IncompatibleModelError):
        analyze_model("some-org/sentiment-classifier", source="huggingface")


def test_local_model_analysis_reads_from_disk(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(LLAMA_BASE_CONFIG))

    profile = analyze_model("local-llama", source="local", local_path=tmp_path)

    assert profile.source == "local"
    assert profile.is_causal_lm is True
```

This covers every scenario `PLAN.md` names for Task 4: Qwen instruct, Llama base, missing template, gated model, offline model, GGUF, classifier, plus local analysis. All of it runs against faked Hugging Face Hub responses — no real network call, no rate limits, no flakiness from an actual model repo changing shape later.

Note on `GatedRepoError`: in the installed `huggingface_hub` version it's a subclass of `HfHubHTTPError` and requires a `response: httpx.Response` keyword argument to construct — that's why the test builds a throwaway one. This isn't a quirk to work around by installing an older version; it's what the real library actually raises.

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/models/test_analyzer.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.models.analyzer'`.

#### Step 3: Analyzer — implement (GREEN)

Create `backend/tuneforge/models/analyzer.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from huggingface_hub import hf_hub_download, list_repo_files
from huggingface_hub.utils import EntryNotFoundError, GatedRepoError, LocalEntryNotFoundError
from pydantic import BaseModel

from tuneforge.models.compatibility import IncompatibleModelError, is_causal_lm_architecture, reject_if_incompatible
from tuneforge.models.evidence import Evidence

CHAT_NAME_HINTS = ("instruct", "chat", "-it")


class ModelProfile(BaseModel):
    source: Literal["huggingface", "local"]
    model_id: str
    architecture: str
    model_type: str
    is_causal_lm: bool
    is_chat_model: bool
    chat_template_found: bool
    context_length: int
    modalities: list[str]
    evidence: list[Evidence]
    confidence: float


class GatedModelError(RuntimeError):
    pass


class ModelNotAccessibleError(RuntimeError):
    pass


def _load_local_json(local_path: Path, filename: str) -> dict | None:
    file_path = local_path / filename
    return json.loads(file_path.read_text()) if file_path.exists() else None


def _load_hub_json(model_id: str, filename: str) -> dict | None:
    try:
        cached_path = hf_hub_download(repo_id=model_id, filename=filename)
    except (GatedRepoError, LocalEntryNotFoundError):
        # LocalEntryNotFoundError is actually a subclass of EntryNotFoundError
        # in huggingface_hub — without this clause ahead of the broader catch
        # below, an offline/uncached lookup would be silently swallowed as
        # "file doesn't exist in the repo" instead of surfacing as "can't
        # reach the hub right now", and analyze_model's own except clauses
        # would never see it.
        raise
    except EntryNotFoundError:
        return None
    return json.loads(Path(cached_path).read_text())


def _has_gguf_file(model_id: str) -> bool:
    try:
        files = list_repo_files(model_id)
    except Exception:
        return False
    return any(name.endswith(".gguf") for name in files)


def analyze_model(
    model_id: str,
    *,
    source: Literal["huggingface", "local"],
    local_path: Path | None = None,
) -> ModelProfile:
    if source == "local":
        if local_path is None:
            raise ValueError("local_path is required when source='local'")

        def load(filename: str) -> dict | None:
            return _load_local_json(local_path, filename)
    else:

        def load(filename: str) -> dict | None:
            return _load_hub_json(model_id, filename)

    try:
        config = load("config.json")
    except GatedRepoError as exc:
        raise GatedModelError(f"{model_id} is gated; request access on Hugging Face first") from exc
    except LocalEntryNotFoundError as exc:
        raise ModelNotAccessibleError(f"{model_id} is unreachable (offline and not cached)") from exc

    if config is None:
        if source == "huggingface" and _has_gguf_file(model_id):
            raise ModelNotAccessibleError(
                f"{model_id} looks like a GGUF-only repository; TuneForge needs the "
                "Hugging Face Transformers config.json format, not GGUF."
            )
        raise ModelNotAccessibleError(f"{model_id} has no config.json — not a Transformers model repo")

    evidence: list[Evidence] = []

    architectures = config.get("architectures", [])
    architecture = architectures[0] if architectures else "unknown"
    model_type = config.get("model_type", "unknown")
    is_causal_lm = is_causal_lm_architecture(architectures)
    evidence.append(
        Evidence(
            field="architecture",
            value=architecture,
            source="config.json",
            detail=f"architectures={architectures!r}",
        )
    )

    modalities = ["text"]
    if "vision_config" in config:
        modalities.append("vision")
    if "audio_config" in config:
        modalities.append("audio")

    tokenizer_config = load("tokenizer_config.json") or {}
    chat_template_found = "chat_template" in tokenizer_config
    evidence.append(
        Evidence(
            field="chat_template_found",
            value=str(chat_template_found),
            source="tokenizer_config.json",
            detail="chat_template key present" if chat_template_found else "no chat_template key",
        )
    )

    name_suggests_chat = any(hint in model_id.lower() for hint in CHAT_NAME_HINTS)
    is_chat_model = chat_template_found
    confidence = 0.95
    if name_suggests_chat and not chat_template_found:
        confidence = 0.5
        evidence.append(
            Evidence(
                field="is_chat_model",
                value="False",
                source="model_id",
                detail=(
                    f"model id {model_id!r} suggests an instruct/chat model, but no "
                    "chat_template was found — treating as unconfirmed"
                ),
            )
        )

    context_length = int(config.get("max_position_embeddings") or config.get("max_sequence_length") or 0)
    evidence.append(
        Evidence(
            field="context_length",
            value=str(context_length),
            source="config.json",
            detail="from max_position_embeddings" if config.get("max_position_embeddings") else "unknown",
        )
    )

    reject_if_incompatible(is_gguf=False, architectures=architectures, model_type=model_type)
    if modalities != ["text"]:
        raise IncompatibleModelError(
            f"{model_id} is multimodal ({modalities}); TuneForge v1 supports text-only causal LMs"
        )

    return ModelProfile(
        source=source,
        model_id=model_id,
        architecture=architecture,
        model_type=model_type,
        is_causal_lm=is_causal_lm,
        is_chat_model=is_chat_model,
        chat_template_found=chat_template_found,
        context_length=context_length,
        modalities=modalities,
        evidence=evidence,
        confidence=confidence,
    )
```

Note the analyzer never calls `transformers.AutoConfig.from_pretrained(...)` or instantiates any model class — it only downloads and reads `config.json`/`tokenizer_config.json` as plain JSON. That's what makes `trust_remote_code=False` from `PLAN.md`'s checklist true by construction: there's no code execution path here for a malicious repo's custom modeling file to run through.

Run the tests again:

```powershell
uv run pytest tests/models/test_analyzer.py -q
```

Expected: all pass.

#### Step 4: Run the full backend suite and commit

```powershell
uv run pytest -q
```

Expected: every test from Part 1, Part 2 Task 3, and Part 2 Task 4 passes (no regressions).

```powershell
git add backend
git commit -m "feat: add deterministic model analyzer"
```

---

## When you're done

Do not start Task 5. Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` (full pass/fail summary) from `backend/`.
2. Output of `git log --oneline` — should show two new commits on top of Part 1's: `feat: add secure model provider profiles` and `feat: add deterministic model analyzer`.
3. Confirmation that `backend/uv.lock` picked up `httpx`, `keyring`, `huggingface-hub`, and `pytest-asyncio`, and that the lock file is committed.
4. Anything you had to deviate from in this document, and why.
5. If you found any correctness issue in the code exactly as given here (not a style preference — an actual bug), stop and describe it rather than silently changing behavior. Every code block in this document was tested before being written down, but flag anything that looks wrong regardless.
