"""Scheduling eligibility for a Qualtrics contact's embedded data.

Ported from desktop QualSched (`scheduler::contact_eligibility`) so the Contacts
badge cannot disagree with what a later Schedule milestone will actually do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DEFAULT_TIMEZONE = "America/Chicago"


@dataclass(frozen=True)
class Slot:
    kind: Literal["fixed", "window"]
    start: int
    end: int | None = None


@dataclass(frozen=True)
class EligibilityDefaults:
    timezone: str
    minutes_expire: int


@dataclass(frozen=True)
class Eligible:
    method: str
    slots: list[Slot]
    num_days: int
    start_date: str
    timezone: str
    expire_minutes: int


def parse_hhmm(token: str) -> int:
    token = token.strip()
    if not token:
        raise ValueError("empty time value")
    try:
        n = int(token)
    except ValueError as exc:
        raise ValueError(f"{token!r} is not a whole number time like 800 or 1430") from exc
    hours, minutes = divmod(n, 100)
    if hours > 23:
        raise ValueError(f"{token!r} has an hour above 23")
    if minutes > 59:
        raise ValueError(f"{token!r} has a minute above 59")
    return n


def parse_time_slots(raw: str) -> list[Slot]:
    """Parse `TimeSlots`, e.g. `"800,[1200,1300],2000"`."""
    slots: list[Slot] = []
    rest = raw.strip()
    while rest:
        rest = rest.lstrip(", \t")
        if not rest:
            break
        if rest.startswith("["):
            after = rest[1:]
            if "]" not in after:
                raise ValueError(f"unclosed '[' in time slots: {raw!r}")
            inner, tail = after.split("]", 1)
            parts = [p.strip() for p in inner.split(",")]
            if len(parts) != 2:
                raise ValueError(f"a time window needs exactly two times, got {inner.strip()!r}")
            slots.append(Slot("window", parse_hhmm(parts[0]), parse_hhmm(parts[1])))
            rest = tail
        else:
            end = rest.find(",")
            if end < 0:
                end = len(rest)
            token, tail = rest[:end], rest[end:]
            slots.append(Slot("fixed", parse_hhmm(token)))
            rest = tail
    return slots


def slots_from_time_n(embedded: dict[str, str]) -> list[Slot]:
    """Fallback for studies that store `Time1`, `Time2`, … instead of `TimeSlots`."""
    keys = [
        k
        for k in embedded
        if k.startswith("Time") and "TimeZone" not in k and "TimeSlots" not in k
    ]
    keys.sort()
    out: list[Slot] = []
    for key in keys:
        try:
            out.append(Slot("fixed", parse_hhmm(embedded[key])))
        except ValueError as exc:
            raise ValueError(f"{key}: {exc}") from exc
    return out


def int_field(embedded: dict[str, str], key: str) -> int | None:
    raw = embedded.get(key)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        try:
            return int(float(raw))
        except ValueError:
            return None


def delivery_method(embedded: dict[str, str]) -> str:
    """How this participant is contacted, even if they are not currently eligible."""
    contact_method = (embedded.get("ContactMethod") or "").strip().upper()
    use_sms = int_field(embedded, "UseSMS")
    if use_sms is None:
        use_sms = 0
    if contact_method == "EMAIL":
        return "email"
    if contact_method == "SMS":
        return "sms"
    if use_sms == 1:
        return "sms"
    if contact_method == "":
        raise ValueError("no ContactMethod and UseSMS is not 1")
    raise ValueError(f"ContactMethod {contact_method!r} is not 'sms' or 'email'")


def contact_eligibility(
    embedded: dict[str, str], defaults: EligibilityDefaults
) -> Eligible | str:
    """Eligible details, or a skip reason string. Never raises on a bad record."""
    surveys_scheduled = int_field(embedded, "SurveysScheduled")
    if surveys_scheduled is None:
        surveys_scheduled = 0
    if surveys_scheduled != 0:
        return f"already scheduled (SurveysScheduled = {surveys_scheduled})"

    num_days = int_field(embedded, "NumDays")
    if num_days is None:
        num_days = 0
    if num_days <= 0:
        return "NumDays is 0 or unset"

    try:
        method = delivery_method(embedded)
    except ValueError as exc:
        return str(exc)

    if "TimeSlots" in embedded:
        try:
            slots = parse_time_slots(embedded["TimeSlots"])
        except ValueError as exc:
            return f"TimeSlots invalid: {exc}"
    else:
        try:
            slots = slots_from_time_n(embedded)
        except ValueError as exc:
            return f"TimeN fields invalid: {exc}"
    if not slots:
        return "no time slots set"

    start_date = (embedded.get("StartDate") or "").strip()
    if not start_date:
        return "StartDate is not set"

    timezone = (embedded.get("TimeZone") or "").strip() or defaults.timezone
    expire = int_field(embedded, "ExpireMinutes")
    if expire is None:
        expire = defaults.minutes_expire

    return Eligible(
        method=method,
        slots=slots,
        num_days=num_days,
        start_date=start_date,
        timezone=timezone,
        expire_minutes=expire,
    )
