from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from huggingface_hub import hf_hub_download, list_repo_files
from huggingface_hub.utils import EntryNotFoundError, GatedRepoError, LocalEntryNotFoundError
from pydantic import BaseModel

from tuneforge.models.compatibility import IncompatibleModelError, is_causal_lm_architecture, reject_if_incompatible
from tuneforge.models.evidence import Evidence
from tuneforge.security.credentials import CredentialNotFoundError, get_api_key

CHAT_NAME_HINTS = ("instruct", "chat", "-it")
HF_TOKEN_CREDENTIAL_NAME = "huggingface"


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


def _hf_token() -> str | None:
    # Resolves via tuneforge.security.credentials — HF_TOKEN from repo-root .env
    # first, then keyring fallback. Absent is normal for public models.
    try:
        return get_api_key(HF_TOKEN_CREDENTIAL_NAME)
    except CredentialNotFoundError:
        return None


def _load_hub_json(model_id: str, filename: str) -> dict | None:
    try:
        cached_path = hf_hub_download(repo_id=model_id, filename=filename, token=_hf_token())
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


# Priority order matters: newer model families (Llama, Qwen, Mistral...)
# use max_position_embeddings; GPT-2 and other older architectures have no
# such key at all and use n_positions (aliased as n_ctx) instead — verified
# against the real sshleifer/tiny-gpt2 config.json, which has neither
# max_position_embeddings nor max_sequence_length.
_CONTEXT_LENGTH_FIELDS = ("max_position_embeddings", "n_positions", "n_ctx", "max_sequence_length")


def _extract_context_length(config: dict) -> tuple[int, str | None]:
    for field_name in _CONTEXT_LENGTH_FIELDS:
        value = config.get(field_name)
        if value:
            return int(value), field_name
    return 0, None


def _has_gguf_file(model_id: str) -> bool:
    try:
        files = list_repo_files(model_id, token=_hf_token())
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

    context_length, context_length_field = _extract_context_length(config)
    evidence.append(
        Evidence(
            field="context_length",
            value=str(context_length),
            source="config.json",
            detail=f"from {context_length_field!r}" if context_length_field else "unknown",
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
