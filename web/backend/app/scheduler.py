"""Pure scheduling: plan expansion, timezone math, and message uniqueness tags.

Ported from desktop QualSched (`src-tauri/src/scheduler/`). No IO, no Qualtrics client.
Clock and RNG are injected so the rules are unit-testable.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from random import Random
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.eligibility import Slot

DEFAULT_TIMEZONE = "America/Chicago"
MINUTES_PER_DAY = 1440
# A slot this close to now is treated as already past — the POST would land after it.
PAST_MARGIN_SECONDS = 60

SURVEY_LABEL = "original"


@dataclass(frozen=True)
class ResolvedTime:
    minutes: int
    extra_days: int


@dataclass(frozen=True)
class PlanInputs:
    contact_id: str
    contact_name: str
    destination: str
    method: str
    slots: list[Slot]
    survey_id: str
    survey_label: str
    num_days: int
    start_date: str
    timezone: str
    expire_minutes: int


@dataclass
class BuiltItem:
    contact_id: str
    contact_name: str
    destination: str
    method: str
    day_index: int
    slot_label: str
    survey_id: str
    survey_label: str
    send_local: str
    send_utc: datetime
    expire_utc: datetime


@dataclass(frozen=True)
class SkippedSlot:
    contact_id: str
    contact_name: str
    reason: str


def hhmm_to_minutes(hhmm: int) -> int:
    return (hhmm // 100) * 60 + (hhmm % 100)


def resolve_slot(slot: Slot, rng: Random) -> ResolvedTime:
    if slot.kind == "fixed":
        return ResolvedTime(minutes=hhmm_to_minutes(slot.start), extra_days=0)
    start_m = hhmm_to_minutes(slot.start)
    end_m = hhmm_to_minutes(slot.end if slot.end is not None else slot.start)
    # A window whose end is before its start wraps past midnight; sample on the
    # unwrapped line, then fold back and carry the day.
    span_end = end_m if end_m >= start_m else end_m + MINUTES_PER_DAY
    if span_end == start_m:
        picked = start_m
    else:
        picked = rng.randint(start_m, span_end)
    return ResolvedTime(minutes=picked % MINUTES_PER_DAY, extra_days=picked // MINUTES_PER_DAY)


def parse_start_date(raw: str) -> date | None:
    raw = raw.strip()
    # Tolerate a full timestamp; only the date part is meaningful.
    date_part = raw.replace("T", " ").split(" ", 1)[0]
    try:
        return datetime.strptime(date_part, "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_minutes(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def slot_label(slot: Slot) -> str:
    if slot.kind == "fixed":
        return f"{slot.start:04d}"
    end = slot.end if slot.end is not None else slot.start
    return f"[{slot.start:04d},{end:04d}]"


def local_to_utc(tz: ZoneInfo, day: date, minutes: int) -> datetime | None:
    """Convert a local wall-clock time to UTC, resolving DST transitions.

    Fall-back (time occurs twice) picks the earlier instant. Spring-forward
    (time does not exist) advances to the first valid minute, up to two hours.
    """
    for offset in range(121):
        total = minutes + offset
        day_shift, wrapped = divmod(total, MINUTES_PER_DAY)
        try:
            d = day + timedelta(days=day_shift)
        except OverflowError:
            return None
        naive = datetime(d.year, d.month, d.day, wrapped // 60, wrapped % 60, 0)
        aware = _from_local(tz, naive)
        if aware is not None:
            return aware.astimezone(timezone.utc)
    return None


def _from_local(tz: ZoneInfo, naive: datetime) -> datetime | None:
    # zoneinfo will construct a datetime for a spring-forward gap; the two folds
    # even have different offsets, which looks like fall-back ambiguity. A UTC
    # round-trip is what distinguishes them:
    #   fall-back 01:30 — fold=0 (earlier) survives the round-trip
    #   spring-forward 02:30 — neither fold comes back as 02:30
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=tz, fold=fold)
        back = candidate.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
        if back == naive:
            return candidate
    return None


def build_contact_plan(
    input: PlanInputs, now: datetime, rng: Random
) -> tuple[list[BuiltItem], list[SkippedSlot]]:
    """Expand one contact into future distributions plus a reason for each dropped slot."""
    items: list[BuiltItem] = []
    skipped: list[SkippedSlot] = []

    def skip(reason: str) -> SkippedSlot:
        return SkippedSlot(input.contact_id, input.contact_name, reason)

    try:
        tz = ZoneInfo(input.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return (
            items,
            [
                skip(
                    f"unknown timezone {input.timezone!r} "
                    "(expected an IANA name like America/Chicago)"
                )
            ],
        )

    start = parse_start_date(input.start_date)
    if start is None:
        return items, [skip(f"StartDate {input.start_date!r} is not a YYYY-MM-DD date")]

    cutoff = now + timedelta(seconds=PAST_MARGIN_SECONDS)

    for day in range(input.num_days):
        for slot in input.slots:
            resolved = resolve_slot(slot, rng)
            try:
                send_date = start + timedelta(days=day + resolved.extra_days)
            except OverflowError:
                skipped.append(skip("date arithmetic overflowed"))
                continue

            send_utc = local_to_utc(tz, send_date, resolved.minutes)
            if send_utc is None:
                skipped.append(
                    skip(
                        f"{send_date} {fmt_minutes(resolved.minutes)} "
                        f"has no valid time in {input.timezone}"
                    )
                )
                continue

            if send_utc <= cutoff:
                skipped.append(
                    skip(f"{send_date} {fmt_minutes(resolved.minutes)} is in the past")
                )
                continue

            local = send_utc.astimezone(tz)
            items.append(
                BuiltItem(
                    contact_id=input.contact_id,
                    contact_name=input.contact_name,
                    destination=input.destination,
                    method=input.method,
                    day_index=day,
                    slot_label=slot_label(slot),
                    survey_id=input.survey_id,
                    survey_label=input.survey_label,
                    send_local=local.strftime("%Y-%m-%d %H:%M %Z"),
                    send_utc=send_utc,
                    expire_utc=send_utc + timedelta(minutes=input.expire_minutes),
                )
            )

    return items, skipped


def decorate_message(body: str, method: str, rng: Random) -> str:
    """Attach a unique tag so Qualtrics does not drop same-body SMS (Duplicates=1).

    SMS uniqueness has to sit *before* the survey-link piped text. Email keeps the
    desktop trailing suffix.
    """
    tag = random_tag(rng)
    if method == "sms":
        return decorate_sms(body, tag)
    return f"{body}\n&nbsp;\n{tag}\n"


def decorate_sms(body: str, tag: str) -> str:
    tag = tag.lstrip("\n")
    idx = first_survey_link_index(body)
    if idx is not None:
        before, after = body[:idx], body[idx:]
        sep = "" if (not before or before.endswith("\n")) else "\n"
        return f"{before}{sep}{tag}\n{after}"
    return f"{tag}\n{body}"


def first_survey_link_index(body: str) -> int | None:
    """Index of the first Qualtrics survey-link piped token, if the template has one."""
    search_from = 0
    while True:
        rel = body.find("${", search_from)
        if rel < 0:
            return None
        end = body.find("}", rel)
        if end < 0:
            return None
        token = body[rel : end + 1].lower()
        if "surveyurl" in token or "surveylink" in token:
            return rel
        search_from = rel + 2


def random_tag(rng: Random) -> str:
    # Two letters, a digit, two letters, a digit, two letters — as the CLI built it.
    letters = string.ascii_letters
    digits = string.digits
    pattern = (False, False, True, False, False, True, False, False)
    chars = [(digits if is_digit else letters)[rng.randrange(len(digits if is_digit else letters))] for is_digit in pattern]
    return "\n[" + "".join(chars) + "]"


def fmt_qualtrics_time(t: datetime) -> str:
    """UTC ISO that Qualtrics accepts as sendDate / expirationDate."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
