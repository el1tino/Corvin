"""Draft generation: a deterministic, template-based renderer that is
always correct and always available, optionally polished into better prose
by an LLM under a hard grounding constraint.

Why deterministic-first: the build spec requires the LLM to "receive only
the incident's structured data and the template", "not invent facts", and
"leave a visible placeholder wherever information is missing". The
surest way to guarantee zero hallucinated facts is to not depend on the LLM
to *decide* what the facts are in the first place -- Jinja2 fills every
field itself, verbatim from the incident's own data, and marks anything
missing with a `[PLACEHOLDER: ...]` marker before the LLM ever sees the
document. The LLM's only job, when available, is to smooth the resulting
prose without touching any placeholder or fact. If no LLM is configured
(or the EU-residency guard blocks it), the deterministic draft is the
final output -- a fully functional mode, not a degraded one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .llm_client import LLMClient, NonEuLlmBlocked

TEMPLATES_DIR = Path(__file__).parent / "templates"

PLACEHOLDER_PATTERN = re.compile(r"\[PLACEHOLDER: [^\]]+\]")


def _placeholder(value: Any, description: str) -> str:
    if value is None or value == "":
        return f"[PLACEHOLDER: {description}]"
    return str(value)


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["ph"] = _placeholder
    return env


_ENV = _build_env()

TEMPLATE_BY_STAGE = {
    "dora_initial": "dora_initial.md.j2",
    "dora_intermediate": "dora_intermediate.md.j2",
    "dora_final": "dora_final.md.j2",
    "nis2_early_warning": "nis2_early_warning.md.j2",
    "nis2_notification": "nis2_notification.md.j2",
    "nis2_final": "nis2_final.md.j2",
    "gdpr_article_33": "gdpr_article33.md.j2",
}

_POLISH_SYSTEM_PROMPT = """\
You are polishing the prose of a regulatory incident notification for readability only.

Hard rules, no exceptions:
1. You may ONLY use facts that already appear in the document you are given.
2. You must NEVER add, infer, guess, or embellish any fact, number, date, or name.
3. Every `[PLACEHOLDER: ...]` marker in the input MUST appear verbatim, unchanged, \
in your output, in the same relative position. Never fill in a placeholder yourself.
4. You may improve sentence structure, tone, and formatting for a professional \
regulatory audience, and correct grammar.
5. Do not add new sections. Do not remove any section, heading, or data field.
6. Output only the revised document text -- no preamble, no commentary.
"""


@dataclass
class DraftResult:
    content: str
    placeholders: list[str]
    prompt_used: str
    model_used: str


def render_deterministic(stage: str, context: dict[str, Any]) -> str:
    template_name = TEMPLATE_BY_STAGE.get(stage)
    if template_name is None:
        raise ValueError(f"Unknown draft stage: {stage!r}")
    template = _ENV.get_template(template_name)
    return template.render(**context)


def extract_placeholders(content: str) -> list[str]:
    return sorted(set(PLACEHOLDER_PATTERN.findall(content)))


def _validate_llm_output(original: str, polished: str) -> bool:
    """Refuse an LLM revision that dropped or altered a placeholder --
    that would mean it silently "resolved" missing information, which is
    exactly what the grounding rule forbids."""
    return extract_placeholders(original) == extract_placeholders(polished)


def generate_draft(
    *,
    stage: str,
    context: dict[str, Any],
    llm_client: LLMClient | None,
    model_label: str = "deterministic-template",
) -> DraftResult:
    deterministic = render_deterministic(stage, context)
    placeholders = extract_placeholders(deterministic)

    if llm_client is None:
        return DraftResult(
            content=deterministic,
            placeholders=placeholders,
            prompt_used="(no LLM configured -- deterministic template only)",
            model_used=model_label,
        )

    try:
        polished = llm_client.complete(system=_POLISH_SYSTEM_PROMPT, user=deterministic)
    except NonEuLlmBlocked:
        return DraftResult(
            content=deterministic,
            placeholders=placeholders,
            prompt_used="(LLM blocked by EU data-residency guard -- deterministic template only)",
            model_used=model_label,
        )

    if not _validate_llm_output(deterministic, polished):
        # Fail safe to the deterministic draft rather than risk a
        # hallucinated or dropped fact reaching a regulator.
        return DraftResult(
            content=deterministic,
            placeholders=placeholders,
            prompt_used=(
                "(LLM output rejected: placeholder set changed -- fell back to "
                "deterministic template)"
            ),
            model_used=model_label,
        )

    return DraftResult(
        content=polished,
        placeholders=extract_placeholders(polished),
        prompt_used=_POLISH_SYSTEM_PROMPT,
        model_used=getattr(llm_client, "model", model_label),
    )
