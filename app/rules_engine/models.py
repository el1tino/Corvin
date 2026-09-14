"""Pure-Python data model for the classification rules engine.

No web or database dependencies live here on purpose: this package is the
core differentiator (see build spec) and must stay fully unit-testable in
isolation from FastAPI/SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Tri(StrEnum):
    """Three-valued logic result for a single condition or rule."""

    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class Result(StrEnum):
    """The three outcomes the engine may report for a framework."""

    REPORTABLE = "reportable"
    NOT_REPORTABLE = "not_reportable"
    NEEDS_HUMAN_INPUT = "needs_human_input"


# Facts are deliberately a plain dict[str, Any] rather than a rigid schema:
# rule authors add new fields over time and the engine must not need a code
# change to consume them. `IncidentFacts` documents the conventional shape.
IncidentFacts = dict[str, Any]


@dataclass(frozen=True)
class Condition:
    """A single leaf condition: `field <op> value`.

    A field that is absent from the facts dict (or explicitly None)
    evaluates to Tri.UNKNOWN rather than False: an unanswered question,
    not a negative answer.
    """

    field: str
    op: str
    value: Any = None

    _OPS = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
        "in": lambda a, b: a in b,
        "not_in": lambda a, b: a not in b,
        "contains": lambda a, b: b in a,
        "is_true": lambda a, _b: bool(a) is True,
        "is_false": lambda a, _b: bool(a) is False,
    }

    def evaluate(self, facts: IncidentFacts) -> Tri:
        if self.field not in facts or facts[self.field] is None:
            return Tri.UNKNOWN
        fn = self._OPS.get(self.op)
        if fn is None:
            raise ValueError(f"Unknown condition operator: {self.op!r}")
        try:
            return Tri.TRUE if fn(facts[self.field], self.value) else Tri.FALSE
        except TypeError:
            # Comparing incompatible types (e.g. None slipped through, or a
            # string vs a number) is treated as "can't tell" rather than a
            # crash; the engine must degrade to needs_human_input, never 500.
            return Tri.UNKNOWN

    def missing_fields(self, facts: IncidentFacts) -> set[str]:
        if self.field not in facts or facts[self.field] is None:
            return {self.field}
        return set()

    def describe(self) -> str:
        return f"{self.field} {self.op} {self.value!r}"


@dataclass(frozen=True)
class Combinator:
    """`any`, `all`, or `not` composition of child logic nodes."""

    kind: str  # "any" | "all" | "not"
    children: tuple[LogicNode, ...]

    def evaluate(self, facts: IncidentFacts) -> Tri:
        results = [c.evaluate(facts) for c in self.children]
        if self.kind == "not":
            (r,) = results
            if r is Tri.UNKNOWN:
                return Tri.UNKNOWN
            return Tri.FALSE if r is Tri.TRUE else Tri.TRUE
        if self.kind == "any":
            if Tri.TRUE in results:
                return Tri.TRUE
            if Tri.UNKNOWN in results:
                return Tri.UNKNOWN
            return Tri.FALSE
        if self.kind == "all":
            if Tri.FALSE in results:
                return Tri.FALSE
            if Tri.UNKNOWN in results:
                return Tri.UNKNOWN
            return Tri.TRUE
        raise ValueError(f"Unknown combinator kind: {self.kind!r}")

    def missing_fields(self, facts: IncidentFacts) -> set[str]:
        out: set[str] = set()
        for c in self.children:
            out |= c.missing_fields(facts)
        return out

    def describe(self) -> str:
        joiner = {"any": " OR ", "all": " AND "}.get(self.kind)
        if self.kind == "not":
            return f"NOT ({self.children[0].describe()})"
        return "(" + joiner.join(c.describe() for c in self.children) + ")"


LogicNode = Condition | Combinator


@dataclass(frozen=True)
class Rule:
    """One named, explainable criterion within a framework's ruleset."""

    id: str
    description: str
    logic: LogicNode

    def evaluate(self, facts: IncidentFacts) -> Tri:
        return self.logic.evaluate(facts)

    def missing_fields(self, facts: IncidentFacts) -> set[str]:
        return self.logic.missing_fields(facts)


@dataclass(frozen=True)
class RuleSet:
    """All rules for one regulatory framework, at one editable version."""

    framework: str
    version: int
    title: str
    combinator: str  # "any" | "all": how rule outcomes combine to a verdict
    rules: tuple[Rule, ...]
    disclaimer: str = ""
    reportable_label: str = ""
    not_reportable_label: str = ""
    needs_human_input_label: str = ""


@dataclass
class RuleOutcome:
    """The evaluated state of a single rule, kept for the explanation."""

    rule_id: str
    description: str
    result: Tri
    missing_fields: frozenset[str] = field(default_factory=frozenset)


@dataclass
class FrameworkEvaluation:
    """The engine's verdict for one framework on one incident."""

    framework: str
    ruleset_version: int
    result: Result
    fired_rules: list[str]
    not_fired_rules: list[str]
    indeterminate_rules: list[str]
    missing_fields: list[str]
    explanations: list[str]
    label: str
