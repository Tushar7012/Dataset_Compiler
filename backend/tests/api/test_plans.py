import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.plans import router
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ModelProfileRecord, TrainingPlanRecord
from tuneforge.storage.repositories import ProjectRepository


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(tmp_path / "data")
    app.include_router(router, prefix="/api")
    test_client = TestClient(app)
    test_client.session_factory = app.state.session_factory
    test_client.artifact_store = app.state.artifact_store
    return test_client


def _stored_model_profile(client, project_id):
    from tuneforge.models.analyzer import ModelProfile

    profile = ModelProfile(
        source="huggingface", model_id="meta-llama/Llama-3-8B", architecture="LlamaForCausalLM", model_type="llama",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=4096,
        modalities=["text"], evidence=[], confidence=0.9,
    )
    session = client.session_factory()
    record = ModelProfileRecord(
        id=uuid.uuid4(), project_id=project_id, model_id=profile.model_id, source=profile.source,
        profile_json=__import__("json").loads(profile.model_dump_json()), confidence=profile.confidence,
    )
    session.add(record)
    session.commit()
    return record


def _project_id(client) -> uuid.UUID:
    session = client.session_factory()
    return ProjectRepository(session, client.artifact_store).create("proj").id


def test_recommend_persists_a_training_plan(client):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)

    response = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id),
            "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation",
            "desired_behavior": "understand HR policy",
            "language": "en",
            "target_rows": 500,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["objective"] == "cpt"

    session = client.session_factory()
    stored = session.query(TrainingPlanRecord).one()
    assert stored.objective == "cpt"


def test_recommend_returns_409_when_chat_template_required_but_missing(client):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)  # chat_template_found=False

    response = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id),
            "model_profile_id": str(model_profile_record.id),
            "goal": "multi_turn_conversation",
            "desired_behavior": "chat",
            "language": "en",
            "target_rows": 500,
        },
    )

    assert response.status_code == 409


def test_estimated_rows_counts_chunks_without_any_provider_configured(client, tmp_path):
    from tuneforge.models.analyzer import ModelProfile
    from tuneforge.storage.repositories import SourceRepository

    project_id = _project_id(client)
    session = client.session_factory()
    # gpt2, not the gated Llama fixture _stored_model_profile uses elsewhere in
    # this file — this test's endpoint really calls build_tokenizer(model_id),
    # so it needs a real, public, downloadable tokenizer.
    profile = ModelProfile(
        source="huggingface", model_id="gpt2", architecture="GPT2LMHeadModel", model_type="gpt2",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=1024,
        modalities=["text"], evidence=[], confidence=0.9,
    )
    model_profile_record = ModelProfileRecord(
        id=uuid.uuid4(), project_id=project_id, model_id=profile.model_id, source=profile.source,
        profile_json=json.loads(profile.model_dump_json()), confidence=profile.confidence,
    )
    session.add(model_profile_record)
    session.commit()

    doc_path = tmp_path / "a.md"
    doc_path.write_text("# Doc\n\nSome content here.\n")
    SourceRepository(session, client.artifact_store).add_source(project_id, doc_path)

    response = client.get(
        f"/api/plans/estimated-rows",
        params={"project_id": str(project_id), "model_profile_id": str(model_profile_record.id)},
    )

    assert response.status_code == 200
    assert response.json() == {"total_rows": 1, "truncated": False, "capped_at": 100_000}


def test_estimated_rows_for_unknown_model_profile_returns_404(client):
    project_id = _project_id(client)
    response = client.get(
        "/api/plans/estimated-rows",
        params={"project_id": str(project_id), "model_profile_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


def _upload_doc_source(client, project_id, tmp_path, text="# HR Policy\n\nThis handbook covers leave and conduct.\n"):
    from tuneforge.storage.repositories import SourceRepository

    session = client.session_factory()
    doc_path = tmp_path / "policy.md"
    doc_path.write_text(text)
    SourceRepository(session, client.artifact_store).add_source(project_id, doc_path)


def _gemini_test_provider(handler):
    import httpx

    from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
    from tuneforge.providers.protocol import ProviderProfile

    transport = httpx.MockTransport(handler)
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    provider_client = httpx.AsyncClient(transport=transport, base_url=base_url)
    profile = ProviderProfile(
        name="gemini-goal-suggestion", base_url=base_url, model="gemini-2.5-flash",
        endpoint_scope="remote", credential_reference="gemini",
    )
    return OpenAICompatibleProvider(profile, provider_client)


def test_suggest_goal_requires_remote_consent(client):
    project_id = _project_id(client)
    response = client.post("/api/plans/suggest-goal", json={"project_id": str(project_id)})
    assert response.status_code == 422
    assert "remote_consent" in response.json()["detail"]


def test_suggest_goal_returns_422_when_no_document_source_uploaded(client):
    project_id = _project_id(client)
    response = client.post(
        "/api/plans/suggest-goal", json={"project_id": str(project_id), "remote_consent": True}
    )
    assert response.status_code == 422
    assert "document source" in response.json()["detail"]


def test_suggest_goal_returns_422_when_document_has_no_extractable_text(client, monkeypatch, tmp_path):
    monkeypatch.setattr("tuneforge.providers.openai_compatible.get_api_key", lambda ref: "fake-key")
    project_id = _project_id(client)
    _upload_doc_source(client, project_id, tmp_path)

    class _EmptyDoc:
        def export_to_markdown(self):
            return "   "  # e.g. an image-only PDF Docling parsed but couldn't extract text from (do_ocr=False)

    monkeypatch.setattr(
        "tuneforge.ingestion.documents.convert_document_cached", lambda path, cache_dir: (_EmptyDoc(), "hash")
    )

    response = client.post(
        "/api/plans/suggest-goal", json={"project_id": str(project_id), "remote_consent": True}
    )
    assert response.status_code == 422
    assert "extractable text" in response.json()["detail"]


def test_suggest_goal_returns_422_when_gemini_credential_missing(client, monkeypatch, tmp_path):
    from tuneforge.security.credentials import CredentialNotFoundError

    def _raise(ref):
        raise CredentialNotFoundError(f"no credential stored for provider: {ref}")

    monkeypatch.setattr("tuneforge.providers.openai_compatible.get_api_key", _raise)
    project_id = _project_id(client)
    _upload_doc_source(client, project_id, tmp_path)

    response = client.post(
        "/api/plans/suggest-goal", json={"project_id": str(project_id), "remote_consent": True}
    )
    assert response.status_code == 422
    assert "credential" in response.json()["detail"].lower()


def test_suggest_goal_returns_the_parsed_suggestion_on_success(client, monkeypatch, tmp_path):
    import httpx

    monkeypatch.setattr("tuneforge.providers.openai_compatible.get_api_key", lambda ref: "fake-key")
    project_id = _project_id(client)
    _upload_doc_source(client, project_id, tmp_path)

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "goal": "domain_adaptation",
            "rationale": "The document is an HR policy handbook.",
            "desired_behavior": "Answer questions about HR policy accurately.",
        })}}]})

    monkeypatch.setattr("tuneforge.api.plans._gemini_provider", lambda: _gemini_test_provider(handler))

    response = client.post(
        "/api/plans/suggest-goal", json={"project_id": str(project_id), "remote_consent": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["goal"] == "domain_adaptation"
    assert body["desired_behavior"] == "Answer questions about HR policy accurately."


def test_suggest_goal_closes_the_gemini_http_client_after_use(client, monkeypatch, tmp_path):
    import httpx

    monkeypatch.setattr("tuneforge.providers.openai_compatible.get_api_key", lambda ref: "fake-key")
    project_id = _project_id(client)
    _upload_doc_source(client, project_id, tmp_path)

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "goal": "domain_adaptation", "rationale": "x", "desired_behavior": "y",
        })}}]})

    created = {}

    def _make_provider():
        provider = _gemini_test_provider(handler)
        created["provider"] = provider
        return provider

    monkeypatch.setattr("tuneforge.api.plans._gemini_provider", _make_provider)

    response = client.post("/api/plans/suggest-goal", json={"project_id": str(project_id), "remote_consent": True})

    assert response.status_code == 200
    assert created["provider"]._client.is_closed is True


def test_suggest_goal_returns_502_when_gemini_suggests_an_invalid_goal(client, monkeypatch, tmp_path):
    import httpx

    monkeypatch.setattr("tuneforge.providers.openai_compatible.get_api_key", lambda ref: "fake-key")
    project_id = _project_id(client)
    _upload_doc_source(client, project_id, tmp_path)

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"goal": "not_a_real_goal", "rationale": "x", "desired_behavior": "y"}'
        }}]})

    monkeypatch.setattr("tuneforge.api.plans._gemini_provider", lambda: _gemini_test_provider(handler))

    response = client.post(
        "/api/plans/suggest-goal", json={"project_id": str(project_id), "remote_consent": True}
    )
    assert response.status_code == 502


def test_suggest_goal_returns_502_on_malformed_json_response(client, monkeypatch, tmp_path):
    import httpx

    monkeypatch.setattr("tuneforge.providers.openai_compatible.get_api_key", lambda ref: "fake-key")
    project_id = _project_id(client)
    _upload_doc_source(client, project_id, tmp_path)

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]})

    monkeypatch.setattr("tuneforge.api.plans._gemini_provider", lambda: _gemini_test_provider(handler))

    response = client.post(
        "/api/plans/suggest-goal", json={"project_id": str(project_id), "remote_consent": True}
    )
    assert response.status_code == 502


def test_approve_sets_approved_at(client):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    recommend_response = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )
    plan_id = recommend_response.json()["id"]

    response = client.post(f"/api/plans/{plan_id}/approve")

    assert response.status_code == 200
    session = client.session_factory()
    stored = session.query(TrainingPlanRecord).one()
    assert stored.approved_at is not None


def _stub_research_analyze(monkeypatch, model_profile_record):
    from tuneforge.models.analyzer import ModelProfile

    profile = ModelProfile.model_validate(model_profile_record.profile_json)
    monkeypatch.setattr("tuneforge.research.resolver.analyze_model", lambda *args, **kwargs: profile)


def test_research_returns_404_for_unknown_plan(client, monkeypatch):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    _stub_research_analyze(monkeypatch, model_profile_record)
    response = client.post(
        f"/api/plans/{uuid.uuid4()}/research",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )
    assert response.status_code == 404


def test_research_returns_a_new_plan_when_the_retry_succeeds(client, monkeypatch):
    # _stored_model_profile's fixture model (meta-llama/Llama-3-8B) has
    # chat_template_found=False — a multi_turn_conversation goal fails
    # ChatTemplateRequiredError on the first attempt inside resolve_rejected_recommendation
    # too, same as it would on /plans/recommend. Use domain_adaptation (cpt)
    # instead so the *local* recheck succeeds without ever needing the network
    # call — proves the "recheck local metadata first" behavior end to end
    # without needing to mock an HF model-card fetch for this test.
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    _stub_research_analyze(monkeypatch, model_profile_record)
    rejected = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    ).json()

    response = client.post(
        f"/api/plans/{rejected['id']}/research",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 200,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["objective"] == "cpt"
    assert body["citations"] == []
    assert body["requires_manual_selection"] is False


def test_research_fetches_official_evidence_when_local_recheck_still_fails(client, monkeypatch):
    from datetime import datetime, timezone

    from tuneforge.research.official_sources import FetchedSource

    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)  # chat_template_found=False
    _stub_research_analyze(monkeypatch, model_profile_record)
    rejected = client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    ).json()

    fake_source = FetchedSource(
        url="https://huggingface.co/meta-llama/Llama-3-8B/blob/main/README.md",
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        sha256="deadbeef",
        excerpt="no chat template documented",
    )
    # Patch where resolve_rejected_recommendation looks up the name — not plans.py's
    # unused import (plans imports it for monkeypatch compatibility with the plan's note,
    # but the call site is resolver.py).
    monkeypatch.setattr("tuneforge.research.resolver.fetch_model_card_readme", lambda model_id: fake_source)

    response = client.post(
        f"/api/plans/{rejected['id']}/research",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "multi_turn_conversation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None
    assert body["requires_manual_selection"] is True
    assert len(body["citations"]) == 1


def _rejected_plan_id(client, project_id, model_profile_record) -> str:
    return client.post(
        "/api/plans/recommend",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    ).json()["id"]


def test_research_missing_required_fields_returns_422(client, monkeypatch):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    _stub_research_analyze(monkeypatch, model_profile_record)
    plan_id = _rejected_plan_id(client, project_id, model_profile_record)

    response = client.post(f"/api/plans/{plan_id}/research", json={"project_id": str(project_id)})

    assert response.status_code == 422


def test_research_returns_404_for_unknown_model_profile(client, monkeypatch):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    _stub_research_analyze(monkeypatch, model_profile_record)
    plan_id = _rejected_plan_id(client, project_id, model_profile_record)

    response = client.post(
        f"/api/plans/{plan_id}/research",
        json={
            "project_id": str(project_id), "model_profile_id": str(uuid.uuid4()),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )

    assert response.status_code == 404


def test_research_returns_422_for_malformed_model_profile_id(client, monkeypatch):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    _stub_research_analyze(monkeypatch, model_profile_record)
    plan_id = _rejected_plan_id(client, project_id, model_profile_record)

    response = client.post(
        f"/api/plans/{plan_id}/research",
        json={
            "project_id": str(project_id), "model_profile_id": "not-a-uuid",
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )

    assert response.status_code == 422


def test_research_returns_422_for_malformed_generator_profile_id(client, monkeypatch):
    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    _stub_research_analyze(monkeypatch, model_profile_record)
    plan_id = _rejected_plan_id(client, project_id, model_profile_record)

    response = client.post(
        f"/api/plans/{plan_id}/research",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "domain_adaptation", "desired_behavior": "x", "language": "en", "target_rows": 100,
            "generator_profile_id": "not-a-uuid",
        },
    )

    assert response.status_code == 422


def test_research_returns_409_when_dpo_lacks_a_distinct_judge(client, monkeypatch):
    from tuneforge.models.analyzer import ModelProfile

    project_id = _project_id(client)
    model_profile_record = _stored_model_profile(client, project_id)
    plan_id = _rejected_plan_id(client, project_id, model_profile_record)

    # dpo needs chat_template_found=True to get past the earlier
    # ChatTemplateRequiredError check (which resolve_rejected_recommendation
    # swallows internally) before it can reach the distinct-judge check.
    chat_profile = ModelProfile.model_validate(
        {**model_profile_record.profile_json, "is_chat_model": True, "chat_template_found": True}
    )
    monkeypatch.setattr("tuneforge.research.resolver.analyze_model", lambda *args, **kwargs: chat_profile)

    response = client.post(
        f"/api/plans/{plan_id}/research",
        json={
            "project_id": str(project_id), "model_profile_id": str(model_profile_record.id),
            "goal": "preference_alignment", "desired_behavior": "x", "language": "en", "target_rows": 100,
        },
    )

    assert response.status_code == 409
