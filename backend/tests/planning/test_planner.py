import uuid

import pytest

from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.intents import TrainingIntent
from tuneforge.planning.planner import ChatTemplateRequiredError, DistinctJudgeRequiredError, recommend_plan


def _model_profile(*, chat_template_found: bool, model_id: str = "org/model", confidence: float = 0.9) -> ModelProfile:
    return ModelProfile(
        source="huggingface",
        model_id=model_id,
        architecture="Qwen2ForCausalLM",
        model_type="qwen2",
        is_causal_lm=True,
        is_chat_model=chat_template_found,
        chat_template_found=chat_template_found,
        context_length=32768,
        modalities=["text"],
        evidence=[],
        confidence=confidence,
    )


def _intent(goal: str) -> TrainingIntent:
    return TrainingIntent(goal=goal, desired_behavior="answer questions about policy", language="en")


def test_qwen_instruct_selects_conversational_sft():
    plan = recommend_plan(
        _intent("multi_turn_conversation"),
        _model_profile(chat_template_found=True, model_id="Qwen/Qwen2.5-7B-Instruct"),
        target_rows=1000,
    )
    assert plan.objective == "sft_conversation"
    assert plan.canonical_schema == "SFTConversationRecord"


def test_base_model_supports_cpt():
    plan = recommend_plan(
        _intent("domain_adaptation"),
        _model_profile(chat_template_found=False, model_id="meta-llama/Llama-3-8B"),
        target_rows=1000,
    )
    assert plan.objective == "cpt"


def test_base_model_supports_prompt_completion_sft():
    plan = recommend_plan(
        _intent("single_turn_instruction"),
        _model_profile(chat_template_found=False, model_id="meta-llama/Llama-3-8B"),
        target_rows=1000,
    )
    assert plan.objective == "sft_prompt_completion"


def test_user_can_override_recommended_objective():
    plan = recommend_plan(
        _intent("domain_adaptation"),
        _model_profile(chat_template_found=False),
        target_rows=1000,
        objective_override="sft_prompt_completion",
    )
    assert plan.objective == "sft_prompt_completion"
    assert any("overridden" in e.detail for e in plan.evidence if e.field == "objective")


def test_conversational_sft_requires_chat_template():
    with pytest.raises(ChatTemplateRequiredError):
        recommend_plan(
            _intent("multi_turn_conversation"),
            _model_profile(chat_template_found=False),
            target_rows=1000,
        )


def test_dpo_requires_chat_template():
    with pytest.raises(ChatTemplateRequiredError):
        recommend_plan(
            _intent("preference_alignment"),
            _model_profile(chat_template_found=False),
            target_rows=1000,
            judge_profile_id=uuid.uuid4(),
            generator_profile_id=uuid.uuid4(),
        )


def test_dpo_requires_a_judge():
    with pytest.raises(DistinctJudgeRequiredError):
        recommend_plan(
            _intent("preference_alignment"),
            _model_profile(chat_template_found=True),
            target_rows=1000,
            generator_profile_id=uuid.uuid4(),
        )


def test_dpo_rejects_same_generator_and_judge():
    shared_id = uuid.uuid4()
    with pytest.raises(DistinctJudgeRequiredError):
        recommend_plan(
            _intent("preference_alignment"),
            _model_profile(chat_template_found=True),
            target_rows=1000,
            generator_profile_id=shared_id,
            judge_profile_id=shared_id,
        )


def test_dpo_succeeds_with_distinct_generator_and_judge():
    plan = recommend_plan(
        _intent("preference_alignment"),
        _model_profile(chat_template_found=True),
        target_rows=1000,
        generator_profile_id=uuid.uuid4(),
        judge_profile_id=uuid.uuid4(),
    )
    assert plan.objective == "dpo"
    assert "judge_required" in plan.required_validators


def test_plan_hash_is_stable_for_identical_inputs():
    profile = _model_profile(chat_template_found=False)
    intent = _intent("domain_adaptation")
    plan_a = recommend_plan(intent, profile, target_rows=1000)
    plan_b = recommend_plan(intent, profile, target_rows=1000)
    assert plan_a.plan_hash == plan_b.plan_hash


def test_plan_hash_changes_when_target_rows_changes():
    profile = _model_profile(chat_template_found=False)
    intent = _intent("domain_adaptation")
    plan_a = recommend_plan(intent, profile, target_rows=1000)
    plan_b = recommend_plan(intent, profile, target_rows=2000)
    assert plan_a.plan_hash != plan_b.plan_hash
