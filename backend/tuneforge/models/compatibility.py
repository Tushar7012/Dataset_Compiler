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
