from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.clocks import compute_dora_clock, compute_gdpr_clock, compute_nis2_clock
from app.clocks.utils import is_overdue, to_local

UTC = timezone.utc


def dl(clock, label):
    return next(d for d in clock.deadlines if d.label == label)


def test_dora_normal_case_four_hours_from_classification():
    awareness = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)
    classification = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)  # 1h after awareness
    clock = compute_dora_clock(awareness, classification)
    initial = dl(clock, "Initial notification")
    assert initial.due_at == datetime(2026, 1, 10, 13, 0, tzinfo=UTC)  # classification + 4h
    assert not clock.capped_by_24h_rule


def test_dora_24_hour_cap_kicks_in_when_classification_is_late():
    # Classification happens 21 hours after awareness -- more than the spec's
    # "more than 20 hours" trigger point for the cap.
    awareness = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)
    classification = awareness + timedelta(hours=21)
    clock = compute_dora_clock(awareness, classification)
    initial = dl(clock, "Initial notification")
    # Nominal would be classification + 4h = awareness + 25h, but the cap at
    # awareness + 24h must win.
    assert initial.due_at == awareness + timedelta(hours=24)
    assert clock.capped_by_24h_rule


def test_dora_intermediate_and_final_run_from_previous_report_not_awareness():
    awareness = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    classification = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
    actual_initial_sent = datetime(2026, 1, 1, 5, 0, tzinfo=UTC)  # later than the 4h due date
    clock = compute_dora_clock(
        awareness, classification, initial_notification_sent_at=actual_initial_sent
    )
    intermediate = dl(clock, "Intermediate report")
    # 72h from the actual send time, not from awareness and not from the due date.
    assert intermediate.due_at == actual_initial_sent + timedelta(hours=72)
    assert not intermediate.provisional

    final = dl(clock, "Final report")
    # No intermediate report sent yet -> provisional, projected off the
    # intermediate deadline, one calendar month later.
    assert final.provisional
    assert final.due_at.month == (intermediate.due_at.month % 12) + 1 or final.due_at.year > intermediate.due_at.year


def test_dora_final_report_uses_calendar_month_not_thirty_days():
    awareness = datetime(2026, 1, 30, 0, 0, tzinfo=UTC)
    classification = datetime(2026, 1, 30, 1, 0, tzinfo=UTC)
    initial_sent = datetime(2026, 1, 30, 2, 0, tzinfo=UTC)
    intermediate_sent = datetime(2026, 1, 31, 2, 0, tzinfo=UTC)
    clock = compute_dora_clock(
        awareness,
        classification,
        initial_notification_sent_at=initial_sent,
        intermediate_report_sent_at=intermediate_sent,
    )
    final = dl(clock, "Final report")
    # 31 Jan + 1 calendar month -> 28 Feb 2026 (not a leap year), never 2 Mar
    # (which a naive +30-days rule would produce).
    assert final.due_at.date().isoformat() == "2026-02-28"


def test_nis2_all_clocks_run_from_awareness():
    awareness = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    clock = compute_nis2_clock(awareness)
    assert dl(clock, "Early warning").due_at == awareness + timedelta(hours=24)
    assert dl(clock, "Incident notification").due_at == awareness + timedelta(hours=72)
    assert dl(clock, "Final report").due_at.date().isoformat() == "2026-04-01"


def test_gdpr_72_hour_clock_and_high_risk_flag():
    awareness = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    clock = compute_gdpr_clock(awareness, high_risk_to_individuals=True)
    assert dl(clock, "Supervisory authority notification").due_at == awareness + timedelta(hours=72)
    assert clock.data_subject_notification_required is True


def test_backdated_awareness_shifts_every_clock_that_depends_on_it():
    original_awareness = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
    classification = datetime(2026, 6, 10, 9, 30, tzinfo=UTC)
    original_clock = compute_dora_clock(original_awareness, classification)

    # The analyst later discovers awareness actually happened two days
    # earlier and corrects the record.
    corrected_awareness = original_awareness - timedelta(days=2)
    corrected_clock = compute_dora_clock(corrected_awareness, classification)

    original_cap = dl(original_clock, "Initial notification")
    corrected_cap = dl(corrected_clock, "Initial notification")
    # Classification stayed fixed, but the 24h cap is now anchored two days
    # earlier, so it now governs (deadline moved earlier, and is now in the past).
    assert corrected_cap.due_at < original_cap.due_at
    assert corrected_cap.due_at == corrected_awareness + timedelta(hours=24)


def test_backdated_awareness_can_produce_an_already_overdue_deadline():
    now = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    backdated_awareness = now - timedelta(days=5)
    clock = compute_nis2_clock(backdated_awareness)
    early_warning = dl(clock, "Early warning")
    assert is_overdue(early_warning.due_at, now=now)


def test_dst_spring_forward_local_display_does_not_corrupt_utc_duration():
    # Europe/Brussels goes CET (+1) -> CEST (+2) at 02:00 local on the last
    # Sunday of March. Awareness just before the jump.
    awareness = datetime(2026, 3, 29, 0, 30, tzinfo=UTC)  # 01:30 CET local
    clock = compute_gdpr_clock(awareness)
    due = dl(clock, "Supervisory authority notification").due_at
    # The UTC duration must be exactly 72 hours regardless of the DST
    # transition that occurs inside the window.
    assert due - awareness == timedelta(hours=72)

    local_awareness = to_local(awareness, "Europe/Brussels")
    local_due = to_local(due, "Europe/Brussels")
    # Local wall-clock offsets differ (CET vs CEST) even though the
    # underlying UTC gap is fixed -- proof the app must never do the +72h
    # arithmetic in local time.
    assert local_awareness.utcoffset() != local_due.utcoffset()
    assert local_awareness.tzinfo is not None and isinstance(local_due.tzinfo, type(ZoneInfo("Europe/Brussels")))


def test_naive_timestamp_is_rejected_rather_than_silently_assumed_utc():
    import pytest

    naive = datetime(2026, 1, 1, 0, 0)
    with pytest.raises(ValueError):
        compute_gdpr_clock(naive)
