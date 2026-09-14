"""Loads rulesets from plain YAML data files.

Rules are data, not code, on purpose (see build spec: "Store the criteria
as editable rules with a version number, not as hard-coded logic"). A
customer or an operator can tune thresholds by editing these files and
bumping `version`; no Python change or redeploy of engine logic required.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Combinator, Condition, LogicNode, Rule, RuleSet

RULES_DIR = Path(__file__).parent / "rules"


def _parse_logic(node: dict[str, Any]) -> LogicNode:
    if "any" in node:
        return Combinator(kind="any", children=tuple(_parse_logic(c) for c in node["any"]))
    if "all" in node:
        return Combinator(kind="all", children=tuple(_parse_logic(c) for c in node["all"]))
    if "not" in node:
        return Combinator(kind="not", children=(_parse_logic(node["not"]),))
    if "field" in node:
        return Condition(field=node["field"], op=node["op"], value=node.get("value"))
    raise ValueError(f"Unrecognized logic node: {node!r}")


def parse_ruleset(data: dict[str, Any]) -> RuleSet:
    outcome = data.get("outcome", {})
    rules = tuple(
        Rule(id=r["id"], description=r["description"].strip(), logic=_parse_logic(r["logic"]))
        for r in data["rules"]
    )
    return RuleSet(
        framework=data["framework"],
        version=int(data["version"]),
        title=data.get("title", data["framework"]),
        combinator=data.get("combinator", "any"),
        rules=rules,
        disclaimer=data.get("disclaimer", "").strip(),
        reportable_label=outcome.get("reportable_label", "Reportable"),
        not_reportable_label=outcome.get("not_reportable_label", "Not reportable"),
        needs_human_input_label=outcome.get("needs_human_input_label", "Needs human input"),
    )


def load_ruleset(path: str | Path) -> RuleSet:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return parse_ruleset(data)


def load_all_rulesets(directory: str | Path = RULES_DIR) -> dict[str, RuleSet]:
    """Load every *.yaml file in `directory`, keyed by framework name.

    If a framework has more than one version file (e.g. dora_v1.yaml and a
    future dora_v2.yaml), the highest `version` wins. This is how a
    customer-tuned ruleset supersedes the shipped default without deleting
    the audit history of what the old rules said.
    """
    directory = Path(directory)
    by_framework: dict[str, RuleSet] = {}
    for path in sorted(directory.glob("*.yaml")):
        ruleset = load_ruleset(path)
        current = by_framework.get(ruleset.framework)
        if current is None or ruleset.version > current.version:
            by_framework[ruleset.framework] = ruleset
    return by_framework
