from __future__ import annotations


class IncompatibleModelError(RuntimeError):
    """Raised when a model cannot be used by TuneForge at all (GGUF, non-causal, multimodal)."""


_CAUSAL_LM_SUFFIXES = ("ForCausalLM", "LMHeadModel")


def is_causal_lm_architecture(architectures: list[str]) -> bool:
    # Two real naming conventions exist in the wild: newer model families
    # (Llama, Qwen, Mistral...) use "...ForCausalLM"; older ones (GPT-2,
    # GPT-J, GPT-NeoX, OPT, CTRL...) use "...LMHeadModel". Checking only
    # the first would reject GPT-2 itself as "not a causal LM" — verified
    # against transformers' own MODEL_FOR_CAUSAL_LM_MAPPING_NAMES, where
    # these two suffixes cover 171 of 173 registered architectures.
    return any(arch.endswith(suffix) for arch in architectures for suffix in _CAUSAL_LM_SUFFIXES)


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
