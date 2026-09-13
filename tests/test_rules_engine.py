from app.rules_engine import Result, evaluate_all, load_all_rulesets

RULESETS = load_all_rulesets()


def test_all_three_frameworks_fire_when_thresholds_are_crossed():
    facts = {
        "affected_clients_pct": 15,
        "critical_services_affected": True,
        "downtime_minutes": 200,
        "member_states_affected_count": 3,
        "data_loss_confidentiality": True,
        "economic_impact_amount_eur": 500_000,
        "severe_operational_disruption": True,
        "significant_financial_loss": True,
        "affects_other_persons_considerable_damage": True,
        "personal_data_involved": True,
        "breach_likely_risk_to_individuals": True,
    }
    evals = evaluate_all(facts, RULESETS)
    assert evals["dora"].result is Result.REPORTABLE
    assert evals["nis2"].result is Result.REPORTABLE
    assert evals["gdpr"].result is Result.REPORTABLE
    assert "dora.clients_or_counterparts" in evals["dora"].fired_rules


def test_dora_only_incident_does_not_trip_gdpr_or_nis2():
    facts = {
        "affected_clients_pct": 20,
        "critical_services_affected": True,
        "downtime_minutes": 300,
        "member_states_affected_count": 1,
        "data_loss_confidentiality": False,
        "data_loss_integrity": False,
        "data_loss_availability": False,
        "data_loss_authenticity": False,
        "economic_impact_amount_eur": 50_000,
        "severe_operational_disruption": False,
        "significant_financial_loss": False,
        "affects_other_persons_considerable_damage": False,
        "personal_data_involved": False,
        "breach_likely_risk_to_individuals": False,
    }
    evals = evaluate_all(facts, RULESETS)
    assert evals["dora"].result is Result.REPORTABLE
    assert evals["nis2"].result is Result.NOT_REPORTABLE
    assert evals["gdpr"].result is Result.NOT_REPORTABLE


def test_missing_fields_produce_needs_human_input_not_a_crash():
    evals = evaluate_all({"personal_data_involved": True}, RULESETS)
    assert evals["dora"].result is Result.NEEDS_HUMAN_INPUT
    assert evals["gdpr"].result is Result.NEEDS_HUMAN_INPUT
    assert "breach_likely_risk_to_individuals" in evals["gdpr"].missing_fields
    # a rule that already has its answer is not reported as "missing"
    assert "personal_data_involved" not in evals["gdpr"].missing_fields


def test_gdpr_requires_both_breach_and_risk_all_combinator():
    # personal data involved but risk explicitly ruled out -> not reportable,
    # not "needs human input": both gating facts are known.
    facts = {"personal_data_involved": True, "breach_likely_risk_to_individuals": False}
    evals = evaluate_all(facts, RULESETS)
    assert evals["gdpr"].result is Result.NOT_REPORTABLE
    assert "gdpr.breach_occurred" in evals["gdpr"].fired_rules
    assert "gdpr.risk_to_individuals" in evals["gdpr"].not_fired_rules


def test_no_framework_applies():
    facts = {
        "affected_clients_pct": 0,
        "affected_financial_counterparts_pct": 0,
        "critical_services_affected": False,
        "downtime_minutes": 5,
        "member_states_affected_count": 1,
        "data_loss_confidentiality": False,
        "data_loss_integrity": False,
        "data_loss_availability": False,
        "data_loss_authenticity": False,
        "economic_impact_amount_eur": 100,
        "severe_operational_disruption": False,
        "significant_financial_loss": False,
        "affects_other_persons_considerable_damage": False,
        "personal_data_involved": False,
        "breach_likely_risk_to_individuals": False,
    }
    evals = evaluate_all(facts, RULESETS)
    assert all(ev.result is Result.NOT_REPORTABLE for ev in evals.values())


def test_ruleset_versions_are_loaded_and_explanations_are_plain_language():
    evals = evaluate_all(
        {"personal_data_involved": True, "breach_likely_risk_to_individuals": True}, RULESETS
    )
    gdpr_eval = evals["gdpr"]
    assert gdpr_eval.ruleset_version == 1
    assert any("[MET]" in e for e in gdpr_eval.explanations)
    assert gdpr_eval.label == "GDPR Article 33 notification required"
