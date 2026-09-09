from app.drafting.export import export_to_docx, export_to_pdf
from app.drafting.generator import extract_placeholders, generate_draft, render_deterministic


def _context(**facts_overrides):
    facts = {
        "affected_clients_pct": 15,
        "downtime_minutes": 200,
        "critical_services_affected": True,
        "member_states_affected_count": 3,
        "economic_impact_amount_eur": 500000,
    }
    facts.update(facts_overrides)
    return {
        "incident": {"id": "abc-123", "title": "Phishing-borne data exfiltration", "description": None},
        "facts": facts,
        "customer": {
            "entity_name": "Acme Fintech BV",
            "member_state": "NL",
            "dora_authority_name": "De Nederlandsche Bank",
            "dora_authority_contact": "dora@dnb.nl",
            "nis2_csirt_or_authority_name": "",
            "nis2_csirt_or_authority_contact": "",
            "gdpr_supervisory_authority_name": "",
            "gdpr_supervisory_authority_contact": "",
        },
        "timestamps": {
            "detected_at": "2026-01-10T08:00:00+00:00",
            "awareness_at": "2026-01-10T08:00:00+00:00",
            "classification_confirmed_at": "2026-01-10T09:00:00+00:00",
        },
        "classification": {"explanations": ["[MET] Impact spreads to two or more EU member states (dora.geographical_spread)"]},
        "deadline_due_at": "2026-01-10T13:00:00+00:00",
        "deadline_basis": "4 hours from classification as major",
        "data_subject_notification_required": False,
        "confirmed_by": "Alice Analyst (analyst)",
    }


def test_deterministic_render_fills_known_facts_and_placeholders_unknowns():
    content = render_deterministic("dora_initial", _context())
    assert "Acme Fintech BV" in content
    assert "15%" in content or "15.0%" in content  # affected_clients_pct rendered
    assert "[PLACEHOLDER: a description of the incident" in content
    # A field present in facts must never show up as a placeholder.
    assert "[PLACEHOLDER: percentage of clients affected]" not in content


def test_generate_draft_without_llm_client_falls_back_to_deterministic():
    result = generate_draft(stage="dora_initial", context=_context(), llm_client=None)
    assert result.model_used == "deterministic-template"
    assert "no LLM configured" in result.prompt_used
    assert len(result.placeholders) > 0


def test_placeholder_extraction():
    text = "Foo [PLACEHOLDER: bar] baz [PLACEHOLDER: qux]"
    assert extract_placeholders(text) == ["[PLACEHOLDER: bar]", "[PLACEHOLDER: qux]"]


def test_gdpr_template_renders_high_risk_branch():
    ctx = _context()
    ctx["data_subject_notification_required"] = True
    ctx["facts"]["personal_data_involved"] = True
    ctx["facts"]["breach_likely_risk_to_individuals"] = True
    content = render_deterministic("gdpr_article_33", ctx)
    assert "high risk to the rights and freedoms" in content


def test_docx_and_pdf_export_produce_nonempty_files():
    content = render_deterministic("dora_initial", _context())
    docx_bytes = export_to_docx(content, title="Test")
    pdf_bytes = export_to_pdf(content, title="Test")
    assert docx_bytes[:2] == b"PK"  # docx is a zip archive
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(docx_bytes) > 1000
    assert len(pdf_bytes) > 1000
