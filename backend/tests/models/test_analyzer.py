import json
from pathlib import Path

import httpx
import pytest
from huggingface_hub.errors import HFValidationError, RepositoryNotFoundError
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

GPT2_BASE_CONFIG = {
    # Real shape from sshleifer/tiny-gpt2 — GPT-2's architecture class name
    # ends in "LMHeadModel", not "ForCausalLM". Caught a real bug: the
    # analyzer originally rejected actual GPT-2 as "not a causal LM".
    "architectures": ["GPT2LMHeadModel"],
    "model_type": "gpt2",
    "n_positions": 1024,
}

CLASSIFIER_CONFIG = {
    "architectures": ["BertForSequenceClassification"],
    "model_type": "bert",
}


def _fake_downloads(files: dict[str, dict], tmp_path: Path):
    def fake_hf_hub_download(*, repo_id: str, filename: str, token: str | None = None) -> str:
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


def test_gpt2_style_architecture_naming_is_recognized_as_causal_lm(monkeypatch, tmp_path):
    # Regression test: GPT-2's real architecture name ends in "LMHeadModel",
    # not "ForCausalLM" — this originally caused analyze_model to reject
    # real GPT-2 as incompatible. Also verifies context_length falls back
    # to n_positions when max_position_embeddings is absent, which is the
    # real config.json shape for GPT-2.
    monkeypatch.setattr(
        "tuneforge.models.analyzer.hf_hub_download",
        _fake_downloads({"config.json": GPT2_BASE_CONFIG}, tmp_path),
    )

    profile = analyze_model("sshleifer/tiny-gpt2", source="huggingface")

    assert profile.is_causal_lm is True
    assert profile.context_length == 1024


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

    def fake_download(*, repo_id, filename, token=None):
        raise GatedRepoError("gated", response=fake_response)

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_download)

    with pytest.raises(GatedModelError):
        analyze_model("meta-llama/Llama-3-8B", source="huggingface")


def test_offline_model_raises_actionable_error(monkeypatch):
    def fake_download(*, repo_id, filename, token=None):
        raise LocalEntryNotFoundError("offline")

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_download)

    with pytest.raises(ModelNotAccessibleError):
        analyze_model("meta-llama/Llama-3-8B", source="huggingface")


def test_nonexistent_repo_raises_actionable_error(monkeypatch):
    fake_response = httpx.Response(404, request=httpx.Request("GET", "https://huggingface.co"))

    def fake_download(*, repo_id, filename, token=None):
        raise RepositoryNotFoundError("not found", response=fake_response)

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_download)

    with pytest.raises(ModelNotAccessibleError, match="not found"):
        analyze_model("does-not/exist", source="huggingface")


def test_malformed_repo_id_raises_actionable_error(monkeypatch):
    def fake_download(*, repo_id, filename, token=None):
        raise HFValidationError("bad repo id")

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_download)

    with pytest.raises(ModelNotAccessibleError, match="not a valid Hugging Face repo id"):
        analyze_model("Qwen / Qwen2.5-1.5B-Instruct ", source="huggingface")


def test_gguf_only_repo_raises_actionable_error(monkeypatch):
    def fake_download(*, repo_id, filename, token=None):
        raise EntryNotFoundError("no config.json")

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_download)
    monkeypatch.setattr(
        "tuneforge.models.analyzer.list_repo_files", lambda repo_id, token=None: ["model.Q4_K_M.gguf"]
    )

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


def test_stored_hf_token_is_passed_to_hub_calls(monkeypatch, tmp_path):
    # Same credential store as the provider API keys (Task 3) — a token the
    # user has saved for accessing gated repos they have access to.
    monkeypatch.setattr("tuneforge.models.analyzer.get_api_key", lambda name: "hf_test_token")
    seen_tokens: list[str | None] = []

    def fake_hf_hub_download(*, repo_id, filename, token=None):
        seen_tokens.append(token)
        if filename != "config.json":
            raise EntryNotFoundError(filename)
        path = tmp_path / filename
        path.write_text(json.dumps(LLAMA_BASE_CONFIG))
        return str(path)

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_hf_hub_download)

    analyze_model("meta-llama/Llama-3-8B", source="huggingface")

    assert seen_tokens
    assert all(token == "hf_test_token" for token in seen_tokens)


def test_missing_hf_token_defaults_to_anonymous_access(monkeypatch, tmp_path):
    from tuneforge.security.credentials import CredentialNotFoundError

    def raise_not_found(name):
        raise CredentialNotFoundError(name)

    monkeypatch.setattr("tuneforge.models.analyzer.get_api_key", raise_not_found)
    seen_tokens: list[str | None] = []

    def fake_hf_hub_download(*, repo_id, filename, token=None):
        seen_tokens.append(token)
        if filename != "config.json":
            raise EntryNotFoundError(filename)
        path = tmp_path / filename
        path.write_text(json.dumps(LLAMA_BASE_CONFIG))
        return str(path)

    monkeypatch.setattr("tuneforge.models.analyzer.hf_hub_download", fake_hf_hub_download)

    analyze_model("meta-llama/Llama-3-8B", source="huggingface")

    assert seen_tokens
    assert all(token is None for token in seen_tokens)
