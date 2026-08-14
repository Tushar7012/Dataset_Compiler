import httpx
from huggingface_hub.utils import EntryNotFoundError

from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.intents import TrainingIntent
from tuneforge.research.resolver import resolve_rejected_recommendation


def _model_profile(*, chat_template_found: bool, model_id="org/model", source="huggingface") -> ModelProfile:
    return ModelProfile(
        source=source,
        model_id=model_id,
        architecture="LlamaForCausalLM",
        model_type="llama",
        is_causal_lm=True,
        is_chat_model=chat_template_found,
        chat_template_found=chat_template_found,
        context_length=4096,
        modalities=["text"],
        evidence=[],
        confidence=0.9,
    )


def _intent() -> TrainingIntent:
    return TrainingIntent(goal="multi_turn_conversation", desired_behavior="chat", language="en")


async def test_reinspection_succeeds_without_network_when_template_now_found(monkeypatch):
    profile = _model_profile(chat_template_found=False)

    def fake_analyze(model_id, *, source):
        return _model_profile(chat_template_found=True, model_id=model_id, source=source)

    monkeypatch.setattr("tuneforge.research.resolver.analyze_model", fake_analyze)

    def handler(request):
        raise AssertionError("should not fetch anything when reinspection already resolves it")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await resolve_rejected_recommendation(_intent(), profile, client=client, target_rows=1000)

    assert result.requires_manual_selection is False
    assert result.plan is not None
    assert result.plan.objective == "sft_conversation"
    assert result.citations == []


async def test_prefers_readme_over_webpage_when_available(monkeypatch, tmp_path):
    profile = _model_profile(chat_template_found=False)
    monkeypatch.setattr("tuneforge.research.resolver.analyze_model", lambda model_id, *, source: profile)

    readme_path = tmp_path / "README.md"
    readme_path.write_text("# org/model\nA base language model with no chat template.")
    monkeypatch.setattr(
        "tuneforge.research.official_sources.hf_hub_download",
        lambda *, repo_id, filename: str(readme_path),
    )

    def handler(request):
        raise AssertionError("should not fetch the webpage when README.md is available")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await resolve_rejected_recommendation(_intent(), profile, client=client, target_rows=1000)

    assert result.requires_manual_selection is True
    assert len(result.citations) == 1
    assert result.citations[0].url == "https://huggingface.co/org/model/blob/main/README.md"
    assert "no chat template" in result.citations[0].excerpt


async def test_falls_back_to_webpage_when_repo_has_no_readme(monkeypatch):
    profile = _model_profile(chat_template_found=False)
    monkeypatch.setattr("tuneforge.research.resolver.analyze_model", lambda model_id, *, source: profile)
    monkeypatch.setattr(
        "tuneforge.research.official_sources.hf_hub_download",
        lambda *, repo_id, filename: (_ for _ in ()).throw(EntryNotFoundError("no README.md")),
    )

    def handler(request):
        return httpx.Response(200, text="no chat template mentioned here")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await resolve_rejected_recommendation(_intent(), profile, client=client, target_rows=1000)

    assert result.requires_manual_selection is True
    assert result.plan is None
    assert len(result.citations) == 1
    assert result.citations[0].url == "https://huggingface.co/org/model"


async def test_local_model_skips_network_and_falls_back_to_manual_selection():
    profile = _model_profile(chat_template_found=False, source="local")

    def handler(request):
        raise AssertionError("local models have no HF model card to fetch")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await resolve_rejected_recommendation(_intent(), profile, client=client, target_rows=1000)

    assert result.requires_manual_selection is True
    assert result.citations == []
