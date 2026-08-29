"""Plan building, timezone math, and SMS uniqueness — ported from desktop scheduler tests."""

from datetime import datetime, timedelta, timezone
from random import Random
from zoneinfo import ZoneInfo

from app.eligibility import Slot
from app.scheduler import (
    PlanInputs,
    ResolvedTime,
    build_contact_plan,
    decorate_message,
    decorate_sms,
    fmt_qualtrics_time,
    resolve_slot,
)


def rng() -> Random:
    return Random(0xC0FFEE)


def plan_inputs(slots: list[Slot], start: str, num_days: int, **overrides) -> PlanInputs:
    values = dict(
        contact_id="CID_1",
        contact_name="Test Participant",
        destination="+15555550100",
        method="sms",
        slots=slots,
        survey_id="SV_original",
        survey_label="original",
        num_days=num_days,
        start_date=start,
        timezone="America/Chicago",
        expire_minutes=60,
    )
    values.update(overrides)
    return PlanInputs(**values)


def test_fixed_slot_resolves_literally():
    assert resolve_slot(Slot("fixed", 830), rng()) == ResolvedTime(minutes=8 * 60 + 30, extra_days=0)


def test_window_stays_within_bounds():
    generator = rng()
    for _ in range(500):
        resolved = resolve_slot(Slot("window", 800, 900), generator)
        assert resolved.extra_days == 0
        assert 480 <= resolved.minutes <= 540


def test_midnight_crossing_window_wraps_and_carries_the_day():
    generator = rng()
    saw_before = saw_after = False
    for _ in range(1000):
        resolved = resolve_slot(Slot("window", 2350, 10), generator)
        late = 1430 <= resolved.minutes <= 1439
        early = resolved.minutes <= 10
        assert late or early
        if late:
            assert resolved.extra_days == 0
            saw_before = True
        else:
            assert resolved.extra_days == 1
            saw_after = True
    assert saw_before and saw_after


def test_converts_local_to_utc_across_dst():
    slots = [Slot("fixed", 800)]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    winter, _ = build_contact_plan(plan_inputs(slots, "2026-01-15", 1), now, rng())
    assert winter[0].send_utc.strftime("%H:%M") == "14:00"
    summer, _ = build_contact_plan(plan_inputs(slots, "2026-07-15", 1), now, rng())
    assert summer[0].send_utc.strftime("%H:%M") == "13:00"


def test_spring_forward_gap_advances_to_a_valid_time():
    slots = [Slot("fixed", 230)]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items, skipped = build_contact_plan(plan_inputs(slots, "2026-03-08", 1), now, rng())
    assert skipped == []
    assert len(items) == 1
    local = items[0].send_utc.astimezone(ZoneInfo("America/Chicago"))
    assert local.strftime("%H:%M") == "03:00"


def test_fall_back_ambiguity_picks_the_earlier_instant():
    slots = [Slot("fixed", 130)]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items, _ = build_contact_plan(plan_inputs(slots, "2026-11-01", 1), now, rng())
    assert len(items) == 1
    assert items[0].send_utc.strftime("%H:%M") == "06:30"


def test_unknown_timezone_is_skipped_not_raised():
    slots = [Slot("fixed", 800)]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items, skipped = build_contact_plan(
        plan_inputs(slots, "2026-07-15", 1, timezone="Mars/Olympus"), now, rng()
    )
    assert items == []
    assert "unknown timezone" in skipped[0].reason


def test_expands_days_times_slots():
    slots = [Slot("fixed", 800), Slot("fixed", 1200), Slot("fixed", 2000)]
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    items, skipped = build_contact_plan(plan_inputs(slots, "2026-07-01", 4), now, rng())
    assert len(items) == 12
    assert skipped == []
    assert sum(1 for i in items if i.day_index == 3) == 3
    assert all(i.survey_id == "SV_original" and i.survey_label == "original" for i in items)


def test_skips_past_slots_and_reports_them():
    slots = [Slot("fixed", 800), Slot("fixed", 2000)]
    now = datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc)
    items, skipped = build_contact_plan(plan_inputs(slots, "2026-07-15", 2), now, rng())
    assert len(items) == 3
    assert len(skipped) == 1
    assert "in the past" in skipped[0].reason
    assert all(i.send_utc > now for i in items)


def test_expiration_follows_send_time():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    items, _ = build_contact_plan(
        plan_inputs([Slot("fixed", 800)], "2026-07-15", 1, expire_minutes=45), now, rng()
    )
    assert items[0].expire_utc - items[0].send_utc == timedelta(minutes=45)


def test_bad_start_date_is_skipped_with_a_reason():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    items, skipped = build_contact_plan(plan_inputs([Slot("fixed", 800)], "07/15/2026", 1), now, rng())
    assert items == []
    assert "YYYY-MM-DD" in skipped[0].reason


def test_send_local_shows_zone_abbreviation():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    items, _ = build_contact_plan(plan_inputs([Slot("fixed", 800)], "2026-07-15", 1), now, rng())
    assert items[0].send_local == "2026-07-15 08:00 CDT"


def test_qualtrics_send_date_is_utc_z():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    items, _ = build_contact_plan(plan_inputs([Slot("fixed", 800)], "2026-07-15", 1), now, rng())
    assert fmt_qualtrics_time(items[0].send_utc) == "2026-07-15T13:00:00Z"


def test_sms_inserts_tag_before_piped_survey_link():
    decorated = decorate_message("Time for your survey ${l://SurveyURL}", "sms", rng())
    assert decorated.find("[") < decorated.find("${l://SurveyURL}")
    assert "&nbsp;" not in decorated


def test_sms_inserts_tag_before_uppercase_i_survey_url():
    decorated = decorate_message("Please complete ${I://SurveyURL} today", "sms", rng())
    assert decorated.find("[") < decorated.find("${I://SurveyURL}")


def test_sms_prepends_tag_when_template_has_no_piped_link():
    decorated = decorate_message("Time for your survey", "sms", rng())
    assert decorated.lstrip("\n").startswith("[")
    assert "Time for your survey" in decorated
    assert "&nbsp;" not in decorated


def test_sms_decorations_of_the_same_body_differ():
    generator = rng()
    body = "Check in ${l://SurveyURL}"
    assert decorate_message(body, "sms", generator) != decorate_message(body, "sms", generator)


def test_email_suffix_is_unique_per_call():
    generator = rng()
    a = decorate_message("Time for your survey", "email", generator)
    b = decorate_message("Time for your survey", "email", generator)
    assert a.startswith("Time for your survey")
    assert "&nbsp;" in a
    assert a != b


def test_decorate_sms_helper_matches_desktop_prefix():
    out = decorate_sms("Hello\n${l://SurveyURL}", "\n[Ab1Cd2Ef]")
    assert out == "Hello\n[Ab1Cd2Ef]\n${l://SurveyURL}"
