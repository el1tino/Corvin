"""The rules engine's building blocks: every operator, three-valued
combinators, the loader's YAML parsing and version selection."""

import pytest

from app.rules_engine import Result, evaluate_framework, load_all_rulesets
from app.rules_engine.loader import parse_ruleset
from app.rules_engine.models import Combinator, Condition, Tri


@pytest.mark.parametrize(
    ("op", "value", "fact", "expected"),
    [
        ("eq", 5, 5, Tri.TRUE),
        ("ne", 5, 5, Tri.FALSE),
        ("gt", 5, 6, Tri.TRUE),
        ("lt", 5, 6, Tri.FALSE),
        ("lte", 5, 5, Tri.TRUE),
        ("in", ["a", "b"], "a", Tri.TRUE),
        ("not_in", ["a", "b"], "c", Tri.TRUE),
        ("contains", "x", ["x", "y"], Tri.TRUE),
        ("is_false", None, False, Tri.TRUE),
        ("is_true", None, 0, Tri.FALSE),
    ],
)
def test_every_operator(op, value, fact, expected):
    assert Condition(field="f", op=op, value=value).evaluate({"f": fact}) is expected


def test_incomparable_types_are_unknown_not_a_crash():
    assert Condition(field="f", op="gte", value=10).evaluate({"f": "lots"}) is Tri.UNKNOWN


def test_unknown_operator_is_rejected_loudly():
    with pytest.raises(ValueError, match="Unknown condition operator"):
        Condition(field="f", op="approx", value=1).evaluate({"f": 1})


def test_not_and_all_combinators_propagate_unknown():
    known = Condition(field="a", op="is_true")
    unknown = Condition(field="missing", op="is_true")
    assert Combinator("not", (known,)).evaluate({"a": True}) is Tri.FALSE
    assert Combinator("not", (unknown,)).evaluate({}) is Tri.UNKNOWN
    assert Combinator("all", (known, unknown)).evaluate({"a": True}) is Tri.UNKNOWN
    assert Combinator("all", (known, unknown)).evaluate({"a": False}) is Tri.FALSE
    assert Combinator("all", (known, unknown)).missing_fields({"a": True}) == {"missing"}
    assert "NOT (" in Combinator("not", (known,)).describe()
    assert " AND " in Combinator("all", (known, unknown)).describe()


def test_loader_rejects_malformed_logic():
    with pytest.raises(ValueError, match="Unrecognized logic node"):
        parse_ruleset(
            {
                "version": 1,
                "framework": "x",
                "rules": [{"id": "r", "description": "d", "logic": {"bogus": 1}}],
            }
        )


def test_all_combinator_ruleset_needs_every_rule():
    ruleset = parse_ruleset(
        {
            "version": 3,
            "framework": "toy",
            "combinator": "all",
            "rules": [
                {"id": "a", "description": "A", "logic": {"field": "a", "op": "is_true"}},
                {"id": "b", "description": "B", "logic": {"not": {"field": "b", "op": "is_true"}}},
            ],
        }
    )
    assert evaluate_framework({"a": True, "b": False}, ruleset).result is Result.REPORTABLE
    assert evaluate_framework({"a": True, "b": True}, ruleset).result is Result.NOT_REPORTABLE
    assert evaluate_framework({"a": True}, ruleset).result is Result.NEEDS_HUMAN_INPUT
    assert evaluate_framework({"a": True}, ruleset).ruleset_version == 3


def test_highest_version_per_framework_wins(tmp_path):
    for version in (1, 2):
        (tmp_path / f"toy_v{version}.yaml").write_text(
            f"version: {version}\nframework: toy\nrules:\n"
            f"  - id: toy.r\n    description: v{version}\n    logic: {{field: x, op: is_true}}\n"
        )
    rulesets = load_all_rulesets(tmp_path)
    assert list(rulesets) == ["toy"]
    assert rulesets["toy"].version == 2
    assert rulesets["toy"].rules[0].description == "v2"
