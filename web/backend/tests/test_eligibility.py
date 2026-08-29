"""Eligibility skip reasons must match desktop QualSched's contact_eligibility."""

from app.eligibility import (
    DEFAULT_TIMEZONE,
    EligibilityDefaults,
    Eligible,
    Slot,
    contact_eligibility,
    delivery_method,
    parse_time_slots,
    slots_from_time_n,
)


def embedded(pairs: list[tuple[str, str]]) -> dict[str, str]:
    return dict(pairs)


def defaults() -> EligibilityDefaults:
    return EligibilityDefaults(timezone=DEFAULT_TIMEZONE, minutes_expire=60)


def reason_of(e: dict[str, str]) -> str:
    result = contact_eligibility(e, defaults())
    assert isinstance(result, str), f"expected skip, got {result!r}"
    return result


def test_parses_plain_and_window_slots():
    assert parse_time_slots("800,1200,1600,2000") == [
        Slot("fixed", 800),
        Slot("fixed", 1200),
        Slot("fixed", 1600),
        Slot("fixed", 2000),
    ]
    assert parse_time_slots(" 800 , [1200,1300] ,2000 ") == [
        Slot("fixed", 800),
        Slot("window", 1200, 1300),
        Slot("fixed", 2000),
    ]


def test_rejects_malformed_slots():
    for raw in ("2366", "2500", "[800]", "[800,900", "eight"):
        try:
            parse_time_slots(raw)
        except ValueError:
            continue
        raise AssertionError(f"expected {raw!r} to be rejected")


def test_reads_time_n_fields_in_order():
    e = embedded(
        [
            ("Time1", "800"),
            ("Time2", "1200"),
            ("Time3", "2000"),
            ("TimeZone", "America/Chicago"),
        ]
    )
    assert slots_from_time_n(e) == [Slot("fixed", 800), Slot("fixed", 1200), Slot("fixed", 2000)]


def test_eligible_contact_reads_all_fields():
    e = embedded(
        [
            ("SurveysScheduled", "0"),
            ("NumDays", "5"),
            ("ContactMethod", "sms"),
            ("TimeSlots", "800,1200"),
            ("StartDate", "2026-07-15"),
            ("TimeZone", "America/New_York"),
            ("ExpireMinutes", "90"),
        ]
    )
    result = contact_eligibility(e, defaults())
    assert isinstance(result, Eligible)
    assert result.method == "sms"
    assert len(result.slots) == 2
    assert result.num_days == 5
    assert result.timezone == "America/New_York"
    assert result.expire_minutes == 90


def test_contact_method_overrides_use_sms():
    e = embedded(
        [
            ("SurveysScheduled", "0"),
            ("NumDays", "1"),
            ("ContactMethod", "email"),
            ("UseSMS", "1"),
            ("TimeSlots", "800"),
            ("StartDate", "2026-07-15"),
        ]
    )
    result = contact_eligibility(e, defaults())
    assert isinstance(result, Eligible)
    assert result.method == "email"


def test_falls_back_to_use_sms_and_project_defaults():
    e = embedded(
        [
            ("SurveysScheduled", "0"),
            ("NumDays", "1"),
            ("UseSMS", "1"),
            ("TimeSlots", "800"),
            ("StartDate", "2026-07-15"),
        ]
    )
    result = contact_eligibility(e, defaults())
    assert isinstance(result, Eligible)
    assert result.method == "sms"
    assert result.timezone == DEFAULT_TIMEZONE
    assert result.expire_minutes == 60


def test_delivery_method_resolves_for_ineligible_contacts():
    already = embedded(
        [("SurveysScheduled", "68"), ("NumDays", "0"), ("ContactMethod", "email")]
    )
    assert isinstance(contact_eligibility(already, defaults()), str)
    assert delivery_method(already) == "email"


def test_skip_reasons_are_specific():
    base = [
        ("SurveysScheduled", "0"),
        ("NumDays", "3"),
        ("ContactMethod", "sms"),
        ("TimeSlots", "800"),
        ("StartDate", "2026-07-15"),
    ]

    def with_field(key: str, val: str) -> dict[str, str]:
        e = embedded(base)
        e[key] = val
        return e

    assert "already scheduled" in reason_of(with_field("SurveysScheduled", "12"))
    assert "NumDays" in reason_of(with_field("NumDays", "0"))
    assert "no time slots" in reason_of(with_field("TimeSlots", ""))
    assert "TimeSlots invalid" in reason_of(with_field("TimeSlots", "2366"))
    assert "StartDate" in reason_of(with_field("StartDate", ""))
    assert "not 'sms' or 'email'" in reason_of(with_field("ContactMethod", "carrier-pigeon"))

    no_method = embedded(base)
    del no_method["ContactMethod"]
    assert "UseSMS" in reason_of(no_method)
