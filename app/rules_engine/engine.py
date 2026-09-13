"""The classification engine itself.

Deliberately tiny: all the domain knowledge lives in the YAML rulesets
(app/rules_engine/rules/*.yaml), loaded via `loader.py`. This module only
knows how to combine already-evaluated tri-state rule outcomes into one of
the three verdicts the build spec requires: reportable, not_reportable, or
needs_human_input -- always alongside which rules fired and which fields
are still missing, in plain language.
"""

from __future__ import annotations

from .models import FrameworkEvaluation, IncidentFacts, Result, RuleSet, Tri


def evaluate_framework(facts: IncidentFacts, ruleset: RuleSet) -> FrameworkEvaluation:
    fired: list[str] = []
    not_fired: list[str] = []
    indeterminate: list[str] = []
    missing: set[str] = set()
    explanations: list[str] = []

    per_rule_results: list[Tri] = []
    for rule in ruleset.rules:
        outcome = rule.evaluate(facts)
        per_rule_results.append(outcome)
        if outcome is Tri.TRUE:
            fired.append(rule.id)
            explanations.append(f"[MET] {rule.description} ({rule.id})")
        elif outcome is Tri.FALSE:
            not_fired.append(rule.id)
            explanations.append(f"[NOT MET] {rule.description} ({rule.id})")
        else:
            indeterminate.append(rule.id)
            rule_missing = rule.missing_fields(facts)
            missing |= rule_missing
            explanations.append(
                f"[UNKNOWN] {rule.description} ({rule.id}) -- missing: "
                f"{', '.join(sorted(rule_missing)) or 'n/a'}"
            )

    if ruleset.combinator == "all":
        if Tri.FALSE in per_rule_results:
            overall = Tri.FALSE
        elif Tri.UNKNOWN in per_rule_results:
            overall = Tri.UNKNOWN
        else:
            overall = Tri.TRUE
    else:  # "any" is the default combinator
        if Tri.TRUE in per_rule_results:
            overall = Tri.TRUE
        elif Tri.UNKNOWN in per_rule_results:
            overall = Tri.UNKNOWN
        else:
            overall = Tri.FALSE

    if overall is Tri.TRUE:
        result, label = Result.REPORTABLE, ruleset.reportable_label
    elif overall is Tri.FALSE:
        result, label = Result.NOT_REPORTABLE, ruleset.not_reportable_label
    else:
        result, label = Result.NEEDS_HUMAN_INPUT, ruleset.needs_human_input_label

    return FrameworkEvaluation(
        framework=ruleset.framework,
        ruleset_version=ruleset.version,
        result=result,
        fired_rules=fired,
        not_fired_rules=not_fired,
        indeterminate_rules=indeterminate,
        missing_fields=sorted(missing),
        explanations=explanations,
        label=label,
    )


def evaluate_all(facts: IncidentFacts, rulesets: dict[str, RuleSet]) -> dict[str, FrameworkEvaluation]:
    """Evaluate every framework's ruleset against one incident's facts.

    Frameworks are independent by design (see build spec overlap handling):
    an incident can be reportable under several at once, so each is
    evaluated on its own and the caller decides how to present them
    side by side.
    """
    return {name: evaluate_framework(facts, rs) for name, rs in rulesets.items()}
