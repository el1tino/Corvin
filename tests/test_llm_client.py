"""The Anthropic client wrapper, with the SDK stubbed out: every provider
outcome must map to either text or an LLMUnavailable the generator can
fall back from. No network."""

from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from app.config import Settings
from app.drafting import llm_client
from app.drafting.llm_client import AnthropicLLMClient, LLMUnavailable, build_llm_client


class FakeMessages:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _client(monkeypatch, outcome) -> tuple[AnthropicLLMClient, FakeMessages]:
    messages = FakeMessages(outcome)
    monkeypatch.setattr(
        llm_client.anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=messages, kwargs=kw)
    )
    return AnthropicLLMClient(api_key="sk-test", model="claude-opus-5"), messages


def _response(stop_reason="end_turn", text="polished"):
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


def _http_error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def test_successful_completion_returns_text_and_sends_the_grounding_prompt(monkeypatch):
    client, messages = _client(monkeypatch, _response())
    assert client.complete(system="rules", user="doc") == "polished"
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5" and call["system"] == "rules"
    assert call["messages"] == [{"role": "user", "content": "doc"}]
    assert call["max_tokens"] >= 8000


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (_http_error(anthropic.RateLimitError, 429), "rate limit"),
        (_http_error(anthropic.InternalServerError, 500), "HTTP 500"),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), "reach"),
        (_response(stop_reason="refusal"), "declined"),
        (_response(stop_reason="max_tokens"), "truncated"),
    ],
)
def test_every_failure_mode_becomes_llm_unavailable(monkeypatch, outcome, reason):
    client, _ = _client(monkeypatch, outcome)
    with pytest.raises(LLMUnavailable, match=reason):
        client.complete(system="s", user="u")


def test_build_uses_configured_model_and_key(monkeypatch):
    monkeypatch.setattr(llm_client.anthropic, "Anthropic", lambda **kw: SimpleNamespace(kwargs=kw))
    settings = Settings(
        anthropic_api_key="sk-live", anthropic_model="claude-sonnet-5", llm_provider_region="eu"
    )
    client = build_llm_client(settings)
    assert client.model == "claude-sonnet-5"
    assert client._client.kwargs["api_key"] == "sk-live"
