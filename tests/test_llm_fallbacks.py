"""The LLM is an optional prose-polishing layer. Every way it can fail must
degrade to the deterministic draft *with the reason recorded*, never to a
500 and never to a draft with a silently altered placeholder set."""

from dataclasses import dataclass

import pytest

from app.config import Settings
from app.drafting.generator import DETERMINISTIC_MODEL_LABEL, generate_draft
from app.drafting.llm_client import LLMUnavailable, NonEuLlmBlocked, build_llm_client

CONTEXT = {
    "incident": {"id": "i-1", "title": "Test", "description": "Something happened"},
    "facts": {"affected_clients_pct": 12},
    "customer": {
        "entity_name": "Acme",
        "member_state": "NL",
        "dora_authority_name": "DNB",
        "dora_authority_contact": "",
        "nis2_csirt_or_authority_name": "",
        "nis2_csirt_or_authority_contact": "",
        "gdpr_supervisory_authority_name": "",
        "gdpr_supervisory_authority_contact": "",
    },
    "timestamps": {
        "detected_at": None,
        "awareness_at": "2026-01-01T00:00:00+00:00",
        "classification_confirmed_at": None,
    },
    "classification": {"explanations": ["[MET] something"]},
    "deadline_due_at": None,
    "deadline_basis": None,
    "data_subject_notification_required": False,
    "confirmed_by": "Cara (compliance)",
}


@dataclass
class FakeClient:
    model: str = "fake-model"
    behaviour: str = "polish"

    def complete(self, *, system: str, user: str) -> str:
        if self.behaviour == "polish":
            return user.replace("Something happened", "An incident occurred")
        if self.behaviour == "fill_placeholder":
            return user.replace("[PLACEHOLDER: downtime in minutes]", "45")
        if self.behaviour == "unavailable":
            raise LLMUnavailable("provider rate limit")
        raise AssertionError(self.behaviour)


def test_polished_output_is_used_when_placeholders_survive():
    result = generate_draft(stage="dora_initial", context=CONTEXT, llm_client=FakeClient())
    assert result.model_used == "fake-model"
    assert "An incident occurred" in result.content
    assert "polished" in result.llm_note


def test_output_that_resolves_a_placeholder_is_rejected():
    result = generate_draft(
        stage="dora_initial", context=CONTEXT, llm_client=FakeClient(behaviour="fill_placeholder")
    )
    assert result.model_used == DETERMINISTIC_MODEL_LABEL
    assert "[PLACEHOLDER: downtime in minutes]" in result.content
    assert "rejected" in result.llm_note


def test_provider_failure_falls_back_with_reason():
    result = generate_draft(
        stage="dora_initial", context=CONTEXT, llm_client=FakeClient(behaviour="unavailable")
    )
    assert result.model_used == DETERMINISTIC_MODEL_LABEL
    assert "rate limit" in result.llm_note


def test_caller_supplied_note_is_preserved_when_no_client():
    result = generate_draft(
        stage="dora_initial", context=CONTEXT, llm_client=None, llm_note="blocked: non-EU"
    )
    assert result.llm_note == "blocked: non-EU"


def test_eu_residency_guard_blocks_non_eu_provider_by_default():
    settings = Settings(anthropic_api_key="sk-test", llm_provider_region="non-eu", allow_non_eu_llm=False)
    with pytest.raises(NonEuLlmBlocked):
        build_llm_client(settings)


def test_eu_residency_guard_can_be_explicitly_overridden():
    settings = Settings(anthropic_api_key="sk-test", llm_provider_region="non-eu", allow_non_eu_llm=True)
    client = build_llm_client(settings)
    assert client is not None
    assert client.model == "claude-opus-5"


def test_no_api_key_means_no_client_not_an_error():
    assert build_llm_client(Settings(anthropic_api_key="")) is None
