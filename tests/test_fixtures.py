"""Runs the rules engine against six realistic, hand-authored incident
fixtures (tests/fixtures/*.json), one per build-spec-required scenario:
DORA-only, GDPR-only, NIS2-only, all three, none, and needs-human-input.

Kept separate from test_rules_engine.py (which exercises the engine's
mechanics with minimal synthetic facts) -- these fixtures are meant to read
as incidents a real SOC analyst would recognize, and to double as sample
payloads for manual testing of the webhook/manual-intake path.
"""

import json
from pathlib import Path

import pytest

from app.rules_engine import Result, evaluate_all, load_all_rulesets

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RULESETS = load_all_rulesets()

FIXTURE_FILES = sorted(FIXTURES_DIR.glob("incident_*.json"))


@pytest.mark.parametrize("fixture_path", FIXTURE_FILES, ids=lambda p: p.stem)
def test_fixture_matches_expected_classification(fixture_path):
    fixture = json.loads(fixture_path.read_text())
    evaluations = evaluate_all(fixture["facts"], RULESETS)
    actual = {fw: ev.result.value for fw, ev in evaluations.items()}
    assert actual == fixture["expected"], (
        f"{fixture_path.name}: expected {fixture['expected']}, got {actual}\nTitle: {fixture['title']}"
    )


def test_all_six_required_scenarios_are_present():
    stems = {p.stem for p in FIXTURE_FILES}
    required = {
        "incident_dora_only",
        "incident_gdpr_only",
        "incident_nis2_only",
        "incident_all_three",
        "incident_none",
        "incident_needs_human_input",
    }
    assert required <= stems, f"Missing fixtures: {required - stems}"


def test_needs_human_input_fixture_reports_missing_fields_for_every_framework():
    fixture = json.loads((FIXTURES_DIR / "incident_needs_human_input.json").read_text())
    evaluations = evaluate_all(fixture["facts"], RULESETS)
    for evaluation in evaluations.values():
        assert evaluation.result is Result.NEEDS_HUMAN_INPUT
        assert len(evaluation.missing_fields) > 0
