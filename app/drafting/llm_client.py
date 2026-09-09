"""LLM access, gated hard by data residency.

Build spec: "Do not send incident data to any LLM provider outside the EU
without an explicit configuration flag and a warning." This module is the
single choke point every drafting call goes through, so that guarantee
can't be bypassed by a new call site forgetting to check it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from ..config import Settings

logger = logging.getLogger("corvin.drafting.llm")


class NonEuLlmBlocked(Exception):
    """Raised when a non-EU-hosted LLM provider would be used without the
    explicit opt-in flag. This is a compliance control, not a bug -- callers
    should catch it and fall back to the deterministic template renderer."""


class LLMClient(Protocol):
    def complete(self, *, system: str, user: str) -> str: ...


@dataclass
class AnthropicLLMClient:
    api_key: str
    model: str

    def complete(self, *, system: str, user: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


def build_llm_client(settings: Settings) -> LLMClient | None:
    """Returns a ready-to-use client, or None if drafting should fall back to
    the deterministic renderer (no key configured -- a legitimate, fully
    supported mode, not just a degraded one).

    Raises NonEuLlmBlocked if a key is configured but the provider region
    is non-EU and the operator has not explicitly opted in.
    """
    if not settings.anthropic_api_key:
        return None

    if settings.llm_provider_region.lower() != "eu" and not settings.allow_non_eu_llm:
        logger.warning(
            "Refusing to send incident data to a non-EU LLM provider region=%s. "
            "Set ALLOW_NON_EU_LLM=true to override, or point LLM_PROVIDER_REGION "
            "at an EU-hosted deployment.",
            settings.llm_provider_region,
        )
        raise NonEuLlmBlocked(
            f"LLM provider region '{settings.llm_provider_region}' is not EU-hosted and "
            "ALLOW_NON_EU_LLM is not set. Drafting will use the deterministic template "
            "renderer instead of sending incident data off-region."
        )

    if settings.llm_provider_region.lower() != "eu":
        logger.warning(
            "Sending incident data to a non-EU LLM provider (region=%s) because "
            "ALLOW_NON_EU_LLM=true is explicitly set. This is a deliberate compliance "
            "trade-off made by the operator, not a default.",
            settings.llm_provider_region,
        )

    return AnthropicLLMClient(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
