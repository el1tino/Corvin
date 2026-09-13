"""LLM access, gated hard by data residency.

Build spec: "Do not send incident data to any LLM provider outside the EU
without an explicit configuration flag and a warning." This module is the
single choke point every drafting call goes through, so that guarantee
can't be bypassed by a new call site forgetting to check it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import anthropic

from ..config import Settings

logger = logging.getLogger("corvin.drafting.llm")


class NonEuLlmBlocked(Exception):
    """A non-EU-hosted LLM provider would be used without the explicit
    opt-in flag. A compliance control, not a bug: callers fall back to the
    deterministic template renderer and record why."""


class LLMUnavailable(Exception):
    """The provider was reachable in principle but this call produced no
    usable text (rate limit, outage, refusal, truncation). Callers fall
    back to the deterministic renderer and record the reason."""


class LLMClient(Protocol):
    model: str

    def complete(self, *, system: str, user: str) -> str: ...


@dataclass
class AnthropicLLMClient:
    api_key: str
    model: str
    max_tokens: int = 16000
    _client: anthropic.Anthropic = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=self.api_key, timeout=120.0, max_retries=2)

    def complete(self, *, system: str, user: str) -> str:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable("provider rate limit") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"provider returned HTTP {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("could not reach provider") from exc

        if response.stop_reason == "refusal":
            raise LLMUnavailable("model declined the request")
        if response.stop_reason == "max_tokens":
            # A truncated notification is worse than a plain one.
            raise LLMUnavailable("response was truncated")
        return "".join(block.text for block in response.content if block.type == "text")


def build_llm_client(settings: Settings) -> LLMClient | None:
    """Returns a ready client, or None when drafting should use the
    deterministic renderer only (no key configured -- a fully supported
    mode, not a degraded one).

    Raises NonEuLlmBlocked if a key is configured but the provider region
    is non-EU and the operator has not explicitly opted in.
    """
    if not settings.anthropic_api_key:
        return None

    non_eu = settings.llm_provider_region.lower() != "eu"
    if non_eu and not settings.allow_non_eu_llm:
        logger.warning(
            "Refusing to send incident data to a non-EU LLM provider (LLM_PROVIDER_REGION=%s). "
            "Set ALLOW_NON_EU_LLM=true to override, or point at an EU-hosted deployment.",
            settings.llm_provider_region,
        )
        raise NonEuLlmBlocked(
            f"LLM provider region '{settings.llm_provider_region}' is not EU-hosted and "
            "ALLOW_NON_EU_LLM is not set; incident data was not sent off-region."
        )
    if non_eu:
        logger.warning(
            "Sending incident data to a non-EU LLM provider (%s) because ALLOW_NON_EU_LLM=true "
            "is explicitly set -- an operator decision, not a default.",
            settings.llm_provider_region,
        )

    return AnthropicLLMClient(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
