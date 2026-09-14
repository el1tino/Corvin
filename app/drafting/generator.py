"""Draft generation: a deterministic, template-based renderer that is
always correct and always available, optionally polished into better prose
by an LLM under a hard grounding constraint.

Why deterministic-first: the build spec requires the LLM to "receive only
the incident's structured data and the template", "not invent facts", and
"leave a visible placeholder wherever information is missing". The surest
way to guarantee zero hallucinated facts is to not let the LLM decide what
the facts are: Jinja2 fills every field itself, verbatim from the
incident's own data, and marks anything missing with a `[PLACEHOLDER: ...]`
marker before the LLM ever sees the document. The LLM's only job, when
available, is to smooth prose without touching any placeholder or fact --
and its output is rejected if the placeholder set changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .llm_client import LLMClient, LLMUnavailable, NonEuLlmBlocked

TEMPLATES_DIR = Path(__file__).parent / "templates"
PLACEHOLDER_PATTERN = re.compile(r"\[PLACEHOLDER: [^\]]+\]")
DETERMINISTIC_MODEL_LABEL = "deterministic-template"

TEMPLATE_BY_STAGE = {
    "dora_initial": "dora_initial.md.j2",
    "dora_intermediate": "dora_intermediate.md.j2",
    "dora_final": "dora_final.md.j2",
    "nis2_early_warning": "nis2_early_warning.md.j2",
    "nis2_notification": "nis2_notification.md.j2",
    "nis2_final": "nis2_final.md.j2",
    "gdpr_article_33": "gdpr_article33.md.j2",
}

POLISH_SYSTEM_PROMPT = """\
You are polishing the prose of a regulatory incident notification for readability only.

Hard rules, no exceptions:
1. You may ONLY use facts that already appear in the document you are given.
2. You must NEVER add, infer, guess, or embellish any fact, number, date, or name.
3. Every `[PLACEHOLDER: ...]` marker in the input MUST appear verbatim, unchanged, \
in your output, in the same relative position. Never fill in a placeholder yourself.
4. You may improve sentence structure, tone, and formatting for a professional \
regulatory audience, and correct grammar.
5. Do not add new sections. Do not remove any section, heading, or data field.
6. Output only the revised document text, with no preamble and no commentary.
"""


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
        autoescape=False,  # output is Markdown for DOCX/PDF export, never rendered as HTML
    )
    env.filters["ph"] = _placeholder
    return env


_ENV = _build_env()


@dataclass
class DraftResult:
    content: str
    placeholders: list[str]
    model_used: str
    prompt_used: str
    llm_note: str  # human-readable provenance: what the LLM did, or why it wasn't used


def render_deterministic(stage: str, context: dict[str, Any]) -> str:
    template_name = TEMPLATE_BY_STAGE.get(stage)
    if template_name is None:
        raise ValueError(f"Unknown draft stage: {stage!r}")
    return _ENV.get_template(template_name).render(**context)


def extract_placeholders(content: str) -> list[str]:
    return sorted(set(PLACEHOLDER_PATTERN.findall(content)))


def generate_draft(
    *,
    stage: str,
    context: dict[str, Any],
    llm_client: LLMClient | None,
    llm_note: str | None = None,
) -> DraftResult:
    """Render the deterministic draft, then optionally polish it.

    `llm_note` lets the caller pass through why no client was supplied
    (e.g. the EU-residency guard fired) so the reason lands in the draft's
    provenance and the audit trail rather than being lost.
    """
    deterministic = render_deterministic(stage, context)
    placeholders = extract_placeholders(deterministic)

    def fallback(note: str) -> DraftResult:
        return DraftResult(
            content=deterministic,
            placeholders=placeholders,
            model_used=DETERMINISTIC_MODEL_LABEL,
            prompt_used="",
            llm_note=note,
        )

    if llm_client is None:
        return fallback(llm_note or "No LLM configured; deterministic template only.")

    try:
        polished = llm_client.complete(system=POLISH_SYSTEM_PROMPT, user=deterministic)
    except NonEuLlmBlocked as exc:
        return fallback(f"LLM blocked by EU data-residency guard: {exc}")
    except LLMUnavailable as exc:
        return fallback(f"LLM unavailable ({exc}); deterministic template only.")

    if extract_placeholders(polished) != placeholders:
        # The model resolved, dropped, or altered a placeholder, exactly
        # what the grounding rule forbids. Fail safe to the deterministic text.
        return fallback("LLM output rejected: placeholder set changed; deterministic template only.")

    return DraftResult(
        content=polished,
        placeholders=placeholders,
        model_used=llm_client.model,
        prompt_used=POLISH_SYSTEM_PROMPT,
        llm_note=f"Prose polished by {llm_client.model}; all placeholders preserved.",
    )
