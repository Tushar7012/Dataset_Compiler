import pytest

from tuneforge.models.compatibility import (
    IncompatibleModelError,
    is_causal_lm_architecture,
    reject_if_incompatible,
)


@pytest.mark.parametrize(
    "architecture",
    [
        "LlamaForCausalLM",
        "Qwen2ForCausalLM",
        "MistralForCausalLM",
        "GPT2LMHeadModel",  # real GPT-2 — the older "LMHeadModel" naming convention
        "GPTJForCausalLM",
        "GPTNeoXForCausalLM",
        "OPTForCausalLM",
    ],
)
def test_recognizes_both_real_causal_lm_naming_conventions(architecture):
    assert is_causal_lm_architecture([architecture]) is True


@pytest.mark.parametrize(
    "architecture",
    ["BertForSequenceClassification", "BertForTokenClassification", "ViTForImageClassification"],
)
def test_rejects_non_causal_architectures(architecture):
    assert is_causal_lm_architecture([architecture]) is False


def test_reject_if_incompatible_accepts_gpt2_naming():
    reject_if_incompatible(is_gguf=False, architectures=["GPT2LMHeadModel"], model_type="gpt2")


def test_reject_if_incompatible_rejects_classifier():
    with pytest.raises(IncompatibleModelError):
        reject_if_incompatible(is_gguf=False, architectures=["BertForSequenceClassification"], model_type="bert")
