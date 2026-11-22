"""Participant acquisition heatmap.

Completed Qualtrics responses over invitations Qualtrics still lists. Pure
aggregation has no IO. The fetch path holds export bytes in memory, reduces
them to completion fields, and wipes those buffers before returning. It does
not write a file, and it does not keep survey answers.

Matching is exact: a response counts only when its recipient id equals a
mailing-list contact's ``contactId`` (``CID_…``) or ``contactLookupId``
(``CGC_…``). Name, email, phone, and external reference are never join keys.
"""

from __future__ import annotations

import io
import json
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.contacts import (
    contact_id_of,
    display_name,
    embedded_of,
    find_in_list,
    list_raw,
    resolve_contact_lookup_id,
    str_field,
    update_contact,
)
from app.distributions import parse_send_date, survey_rotation
from app.errors import app_error
from app.models import QualtricsAccount, SurveyProfile
from app.qualtrics import QualtricsClient, QualtricsError, machine_code

MONITOR_FIELD = "QsMonitor"
MAX_SPAN_DAYS = 370

# Column ids from the Start Response Export schema's surveyMetadataIds list.
# Names, email, IP, and location are intentionally absent. RecipientID is not
# in this list; it is not an embedded-data field name we can safely request.
SAFE_METADATA = [
    "endDate",
    "status",
    "finished",
    "recordedDate",
    "_recordId",
    "distributionChannel",
    "startDate",
]
# JSON and NDJSON exports return HTTP 400 if any of these keys are present,
# even when the value is false. Documented on Start Response Export.
JSON_EXPORT_FORBIDDEN = frozenset(
    {
        "includeDisplayOrder",
        "useLabels",
        "formatDecimalAsComma",
        "seenUnansweredRecode",
        "multiselectSeenUnansweredRecode",
        "timeZone",
        "newlineReplacement",
        "breakoutSets",
    }
)

PREREQUISITE = (
    "A completion is counted only when the response is finished, its status is a "
    "real response (IP Address, Imported, or Offline — not preview, test, synthetic, "
    "or spam), and RecipientID or contactId exactly equals that participant's "
    "Qualtrics contactId (CID_…) or contactLookupId (CGC_…). Name, email, phone, "
    "and external data reference are not used. Qualtrics adds RecipientID for "
    "invitations sent to directory contacts; if the export has no such field, "
    "completions stay unmatched instead of being guessed."
)

DENOMINATOR_NOTE = (
    "Expected counts are invitations Qualtrics still lists, placed on the "
    "participant's local day by send time. The scheduler is not re-run, so "
    "changed or random windows follow the booked invitation. A cancelled "
    "invitation that is no longer listed is not in the denominator. The current "
    "day counts only prompts whose send time has already passed."
)

DayKind = Literal["ratio", "future", "none", "nonStudy", "unknown"]
ExportMode = Literal["columns", "metadata", "no-answers", "full"]


class AcquisitionParseError(Exception):
    """Export bytes could not be read. The message is static and has no payload."""


class DayCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    kind: DayKind
    completed: int | None = None
    expected: int | None = None
    later: int = 0


class ToDate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: int | None = None
    expected: int | None = None
    provisional: bool = False


class ExcludedCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview: int = 0
    test: int = 0
    synthetic: int = 0
    spam: int = 0
    unfinished: int = 0
    otherStatus: int = 0
    anonymous: int = 0
    unmatchedRecipient: int = 0
    conflict: int = 0
    duplicateIds: int = 0
    unjoinedInvitations: int = 0


class AcquisitionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contactId: str
    displayName: str
    monitor: Literal["active", "inactive"]
    timezone: str = ""
    timezoneSource: Literal["contact", "profile", "invalid", "missing"]
    today: str
    definitive: bool
    ambiguous: int = 0
    unmatchedCompletions: int = 0
    duplicateCompletions: int = 0
    days: list[DayCell]
    toDate: ToDate


class AcquisitionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generatedAt: str
    definitive: bool
    prerequisite: str
    limitations: list[str]
    exportMode: ExportMode
    excluded: ExcludedCounts
    rows: list[AcquisitionRow]


class MonitorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contactId: str
    monitor: Literal["active", "inactive"]


class MonitorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contactId: str
    status: str = Field(min_length=1)


@dataclass
class Participant:
    contact_id: str
    lookup_id: str
    display_name: str
    timezone_name: str
    start_date: str
    num_days: int
    monitor: str
    surveys_scheduled: int


@dataclass
class Invitation:
    distribution_id: str
    lookup_id: str
    send: datetime | None
    expire: datetime | None


@dataclass
class ParsedResponse:
    response_id: str
    finished: bool | None
    status: int | None
    channel: str
    recipient_id: str | None
    distribution_token: str | None
    q_dl: str | None
    completed_at: datetime | None


def export_request_bodies() -> list[tuple[ExportMode, dict[str, Any]]]:
    """Narrowest create-export body first.

    ``embeddedDataIds`` is omitted on every body. That field must name embedded
    data fields that exist on this survey; a name that does not (including
    ``RecipientID`` or ``Q_DL``) makes Qualtrics reject the create call with
    HTTP 400. Omitting it exports whatever embedded fields the survey has, and
    the parser keeps only recipient and distribution ids.

    ``questionIds: []`` asks for no answer columns. The later bodies drop that
    and then ``surveyMetadataIds``, because a 400 on a shared field has to be
    escaped by a body that no longer sends it. The last body is only format
    and compression, which Start Response Export accepts with no filters.
    Answers, when a broader body is required, are discarded while parsing.
    """
    metadata = list(SAFE_METADATA)
    columns: dict[str, Any] = {
        "format": "json",
        "compress": True,
        "surveyMetadataIds": metadata,
        "questionIds": [],
    }
    with_answers: dict[str, Any] = {
        "format": "json",
        "compress": True,
        "surveyMetadataIds": list(metadata),
    }
    no_answers: dict[str, Any] = {"format": "json", "compress": True, "questionIds": []}
    full: dict[str, Any] = {"format": "json", "compress": True}
    bodies: list[tuple[ExportMode, dict[str, Any]]] = [
        ("columns", columns),
        ("metadata", with_answers),
        ("no-answers", no_answers),
        ("full", full),
    ]
    for _, body in bodies:
        # These keys 400 a json/ndjson export even when false. Never send them.
        if JSON_EXPORT_FORBIDDEN.intersection(body):
            raise RuntimeError("export body includes a parameter Qualtrics rejects for json")
    return bodies


def normalize_monitor(value: str | None) -> Literal["active", "inactive"]:
    if (value or "").strip().lower() == "inactive":
        return "inactive"
    return "active"


def _wipe(buf: bytearray) -> None:
    """Best-effort overwrite. Does not clear swap, crash dumps, or other copies."""
    for i in range(len(buf)):
        buf[i] = 0


def _pick(sources: list[dict[str, Any]], keys: tuple[str, ...]) -> Any:
    for source in sources:
        for key in keys:
            if key in source and source[key] not in (None, ""):
                return source[key]
    return None


def _as_str(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def parse_status(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        labels = {
            "ip address": 0,
            "survey preview": 1,
            "survey test": 2,
            "imported": 4,
            "spam": 8,
            "offline": 16,
            "offline preview": 17,
            "synthetic": 256,
        }
        if text.lower() in labels:
            return labels[text.lower()]
        try:
            return int(text)
        except ValueError:
            return None
    return None


def parse_finished(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true"}:
            return True
        if text in {"0", "false"}:
            return False
    return None


def _sources(obj: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    values = obj.get("values")
    if isinstance(values, dict):
        found.append(values)
    embedded = obj.get("embeddedData")
    if isinstance(embedded, dict):
        found.append(embedded)
    found.append(obj)
    return found


def extract_response(obj: dict[str, Any], fallback_id: str) -> ParsedResponse:
    """Copy allowlisted completion fields and nothing else."""
    sources = _sources(obj)
    response_id = _as_str(
        _pick(sources, ("responseId", "responseID", "_recordId", "ResponseID"))
    )
    recipient = _as_str(
        _pick(sources, ("RecipientID", "recipientId", "recipientID", "ContactID", "contactId"))
    )
    token = _as_str(_pick(sources, ("DistributionID", "distributionId", "distributionID")))
    q_dl = _as_str(_pick(sources, ("Q_DL", "q_dl")))
    completed_raw = _as_str(_pick(sources, ("endDate", "recordedDate", "EndDate", "startDate")))
    channel = _as_str(_pick(sources, ("distributionChannel", "DistributionChannel"))) or ""
    return ParsedResponse(
        response_id=response_id or fallback_id,
        finished=parse_finished(_pick(sources, ("finished", "Finished"))),
        status=parse_status(_pick(sources, ("status", "Status"))),
        channel=channel.lower(),
        recipient_id=recipient,
        distribution_token=token,
        q_dl=q_dl,
        completed_at=parse_send_date(completed_raw) if completed_raw else None,
    )


def _parse_payload(payload: bytearray) -> list[ParsedResponse]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeError:
        raise AcquisitionParseError("Qualtrics response export could not be read.") from None
    stripped = text.strip()
    if not stripped:
        return []
    objects: list[Any]
    try:
        if stripped[0] == "[":
            objects = json.loads(stripped)
        elif stripped[0] == "{":
            data = json.loads(stripped)
            if isinstance(data, dict) and isinstance(data.get("responses"), list):
                objects = data["responses"]
            else:
                objects = [data]
        else:
            objects = []
            for line in text.splitlines():
                line = line.strip()
                if line:
                    objects.append(json.loads(line))
    except (json.JSONDecodeError, ValueError, TypeError):
        raise AcquisitionParseError("Qualtrics response export could not be read.") from None
    if not isinstance(objects, list):
        raise AcquisitionParseError("Qualtrics response export could not be read.")
    facts: list[ParsedResponse] = []
    for index, obj in enumerate(objects):
        if not isinstance(obj, dict):
            raise AcquisitionParseError("Qualtrics response export could not be read.")
        facts.append(extract_response(obj, f"missing-{index}"))
    return facts


def parse_export_bytes(data: bytes | bytearray) -> list[ParsedResponse]:
    """Read a Qualtrics export from memory. Never extracts the archive to disk."""
    raw = data if isinstance(data, bytearray) else bytearray(data)
    try:
        try:
            if bytes(raw[:2]) == b"PK":
                facts: list[ParsedResponse] = []
                try:
                    archive = zipfile.ZipFile(io.BytesIO(raw))
                except zipfile.BadZipFile:
                    raise AcquisitionParseError(
                        "Qualtrics response export could not be read."
                    ) from None
                with archive:
                    for info in archive.infolist():
                        if info.is_dir():
                            continue
                        payload = bytearray(archive.read(info))
                        try:
                            facts.extend(_parse_payload(payload))
                        finally:
                            _wipe(payload)
                return facts
            return _parse_payload(raw)
        except AcquisitionParseError:
            raise
        except (OSError, RuntimeError, ValueError, KeyError, TypeError):
            raise AcquisitionParseError(
                "Qualtrics response export could not be read."
            ) from None
    finally:
        _wipe(raw)


def _classify(fact: ParsedResponse) -> str:
    """Return ``ok`` or an exclusion bucket. Preview and test win over unfinished."""
    channel = fact.channel
    status = fact.status
    if status in {1, 17} or channel in {"preview", "surveypreview", "offlinepreview"}:
        return "preview"
    if status == 2 or channel == "test":
        return "test"
    if status == 256 or channel == "synthetic":
        return "synthetic"
    if status in {6, 8, 9, 12} or channel == "spam":
        return "spam"
    if fact.finished is not True:
        return "unfinished"
    if status not in {0, 4, 16}:
        return "other"
    if not fact.recipient_id:
        return "anonymous"
    return "ok"


def _resolve_zone(name: str, profile_timezone: str) -> tuple[ZoneInfo | None, str]:
    raw = name.strip()
    if raw:
        try:
            return ZoneInfo(raw), "contact"
        except ZoneInfoNotFoundError:
            return None, "invalid"
    fallback = profile_timezone.strip()
    if fallback:
        try:
            return ZoneInfo(fallback), "profile"
        except ZoneInfoNotFoundError:
            return None, "invalid"
    return None, "missing"


def _parse_start(raw: str) -> date | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _link_distribution(token: str | None, q_dl: str | None, known: set[str]) -> str | None:
    """Return a distribution id, ``""`` when a pointer was present but unusable, or None."""
    if token:
        return token
    if not q_dl:
        return None
    if q_dl in known:
        return q_dl
    matches = [did for did in known if q_dl.startswith(f"{did}_")]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return ""
    return ""


def _study_window(start: date, num_days: int, today: date) -> tuple[int, int, bool]:
    """First offset from start, how many days to emit, and whether NumDays was clamped.

    A corrupt NumDays must not allocate one date per day of that span.
    """
    if num_days <= MAX_SPAN_DAYS:
        return 0, num_days, False
    elapsed = (today - start).days
    if elapsed < 0:
        return 0, MAX_SPAN_DAYS, True
    offset0 = min(max(elapsed - MAX_SPAN_DAYS + 8, 0), num_days - MAX_SPAN_DAYS)
    return offset0, MAX_SPAN_DAYS, True


def _study_dates(
    start: date | None, num_days: int, today: date, admin_dates: list[date]
) -> tuple[list[date], bool]:
    last7 = [today - timedelta(days=6 - offset) for offset in range(7)]
    bounds: list[date] = []
    truncated = False
    if start is not None and num_days > 0:
        offset0, count, clamped = _study_window(start, num_days, today)
        if clamped:
            truncated = True
        bounds = [start + timedelta(days=offset0 + offset) for offset in range(count)]
    found = set(last7) | set(bounds) | set(admin_dates)
    ordered = sorted(found)
    if ordered and (ordered[-1] - ordered[0]).days > MAX_SPAN_DAYS:
        cutoff = ordered[-1] - timedelta(days=MAX_SPAN_DAYS)
        keep = set(last7)
        ordered = [item for item in ordered if item >= cutoff or item in keep]
        truncated = True
    return ordered, truncated


def _outside_study(day: date, start: date | None, num_days: int) -> bool:
    if start is None or num_days <= 0:
        return False
    if day < start:
        return True
    try:
        end = start + timedelta(days=num_days - 1)
    except OverflowError:
        # The study end is past the largest date Python can name, so this day is inside it.
        return False
    return day > end


@dataclass
class _Admin:
    distribution_id: str
    send: datetime
    expire: datetime | None


def _match_contact(
    admins: list[_Admin], completions: list[tuple[ParsedResponse, str | None]]
) -> tuple[dict[int, ParsedResponse], int, int, int]:
    """Return assigned admin index → response, plus ambiguous, unmatched, duplicate counts."""
    assigned: dict[int, ParsedResponse] = {}
    by_id = {admin.distribution_id: index for index, admin in enumerate(admins) if admin.distribution_id}
    ambiguous = 0
    unmatched = 0
    duplicates = 0
    pending: list[ParsedResponse] = []
    for fact, dist_id in completions:
        if dist_id is not None:
            if dist_id == "" or dist_id not in by_id:
                unmatched += 1
                continue
            index = by_id[dist_id]
            if index in assigned:
                duplicates += 1
            else:
                assigned[index] = fact
            continue
        pending.append(fact)

    open_indexes = [index for index in range(len(admins)) if index not in assigned]
    for fact in sorted(pending, key=lambda item: item.completed_at or datetime.min.replace(tzinfo=UTC)):
        when = fact.completed_at
        if when is None:
            unmatched += 1
            continue
        in_window = []
        for index in open_indexes:
            admin = admins[index]
            if admin.send <= when and (admin.expire is None or when <= admin.expire):
                in_window.append(index)
        if len(in_window) == 1:
            assigned[in_window[0]] = fact
            open_indexes.remove(in_window[0])
            continue
        if len(in_window) > 1:
            ambiguous += 1
            continue
        late = [index for index in open_indexes if admins[index].send <= when]
        if len(late) == 1:
            assigned[late[0]] = fact
            open_indexes.remove(late[0])
            continue
        unmatched += 1
    return assigned, ambiguous, unmatched, duplicates


def aggregate(
    participants: list[Participant],
    invitations: list[Invitation],
    responses: list[ParsedResponse],
    *,
    now: datetime,
    profile_timezone: str,
    export_mode: ExportMode = "columns",
) -> AcquisitionReport:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)

    excluded = ExcludedCounts()
    limitations = [DENOMINATOR_NOTE]
    usable: list[ParsedResponse] = []
    seen_ids: set[str] = set()
    for fact in responses:
        if fact.response_id in seen_ids:
            excluded.duplicateIds += 1
            continue
        seen_ids.add(fact.response_id)
        bucket = _classify(fact)
        if bucket == "preview":
            excluded.preview += 1
        elif bucket == "test":
            excluded.test += 1
        elif bucket == "synthetic":
            excluded.synthetic += 1
        elif bucket == "spam":
            excluded.spam += 1
        elif bucket == "unfinished":
            excluded.unfinished += 1
        elif bucket == "other":
            excluded.otherStatus += 1
        elif bucket == "anonymous":
            excluded.anonymous += 1
        else:
            usable.append(fact)

    by_contact: dict[str, int] = {}
    by_lookup: dict[str, int] = {}
    for index, person in enumerate(participants):
        if person.contact_id:
            by_contact[person.contact_id] = index
        if person.lookup_id:
            by_lookup[person.lookup_id] = index

    attached: dict[int, list[_Admin]] = {index: [] for index in range(len(participants))}
    unplaceable: dict[int, int] = {index: 0 for index in range(len(participants))}
    known_ids: set[str] = set()
    dist_owner: dict[str, int] = {}
    for invite in invitations:
        if not invite.distribution_id:
            excluded.unjoinedInvitations += 1
            continue
        owner = by_lookup.get(invite.lookup_id)
        if owner is None:
            excluded.unjoinedInvitations += 1
            continue
        known_ids.add(invite.distribution_id)
        dist_owner[invite.distribution_id] = owner
        if invite.send is None:
            unplaceable[owner] += 1
            continue
        attached[owner].append(
            _Admin(invite.distribution_id, invite.send, invite.expire)
        )

    grouped: dict[int, list[tuple[ParsedResponse, str | None]]] = {
        index: [] for index in range(len(participants))
    }
    for fact in usable:
        recipient = fact.recipient_id or ""
        owner = by_contact.get(recipient)
        if owner is None:
            owner = by_lookup.get(recipient)
        if owner is None:
            excluded.unmatchedRecipient += 1
            continue
        dist_id = _link_distribution(fact.distribution_token, fact.q_dl, known_ids)
        if dist_id:
            other = dist_owner.get(dist_id)
            if other is not None and other != owner:
                excluded.conflict += 1
                grouped[owner].append((fact, ""))  # counted as unmatched for this person
                continue
        grouped[owner].append((fact, dist_id))

    if excluded.anonymous:
        limitations.append(
            f"{excluded.anonymous} finished response(s) had no recipient id and were not "
            "applied to any row. Matched counts can be low. "
            + PREREQUISITE
        )
    if excluded.unmatchedRecipient:
        limitations.append(
            f"{excluded.unmatchedRecipient} finished response(s) named a recipient id that "
            "is not on this mailing list. They were not applied to a row."
        )
    if excluded.conflict:
        limitations.append(
            f"{excluded.conflict} response(s) named both a participant and a different "
            "participant's invitation. They were not applied to either row."
        )
    if excluded.unjoinedInvitations:
        limitations.append(
            f"{excluded.unjoinedInvitations} listed invitation(s) had no participant id "
            "this profile could resolve. They were not placed on a row, and expected "
            "counts were not guessed."
        )

    rows: list[AcquisitionRow] = []
    truncated = False
    scheduled_without_invites = False
    bad_start = False
    unreadable_send = False
    for index, person in enumerate(participants):
        zone, source = _resolve_zone(person.timezone_name, profile_timezone)
        monitor = normalize_monitor(person.monitor)
        force_unknown = False
        if source in {"invalid", "missing"}:
            force_unknown = True
        if not person.lookup_id and excluded.unjoinedInvitations:
            force_unknown = True
        if unplaceable[index]:
            force_unknown = True
            unreadable_send = True

        if zone is None:
            today = now.astimezone(UTC).date()
            dates = [today - timedelta(days=6 - offset) for offset in range(7)]
            days = [
                DayCell(date=item.isoformat(), kind="unknown")
                for item in dates
            ]
            row_definitive = False
            ambiguous = unmatched = duplicates = 0
        else:
            today = now.astimezone(zone).date()
            admins = sorted(attached[index], key=lambda item: (item.send, item.distribution_id))
            assigned, ambiguous, unmatched, duplicates = _match_contact(
                admins, grouped[index]
            )
            admin_dates = [item.send.astimezone(zone).date() for item in admins]
            start = _parse_start(person.start_date)
            if person.start_date.strip() and start is None:
                bad_start = True
            dates, row_truncated = _study_dates(start, person.num_days, today, admin_dates)
            truncated = truncated or row_truncated
            by_day: dict[date, list[int]] = {item: [] for item in dates}
            for admin_index, admin in enumerate(admins):
                local = admin.send.astimezone(zone).date()
                by_day.setdefault(local, []).append(admin_index)
                if local not in dates:
                    dates.append(local)
            dates = sorted(set(dates))
            days = []
            to_completed = 0
            to_expected = 0
            for day in dates:
                indexes = by_day.get(day, [])
                if force_unknown:
                    days.append(DayCell(date=day.isoformat(), kind="unknown"))
                    continue
                due = 0
                later = 0
                completed = 0
                for admin_index in indexes:
                    admin = admins[admin_index]
                    matched = admin_index in assigned
                    if admin.send <= now or matched:
                        due += 1
                        if matched:
                            completed += 1
                    else:
                        later += 1
                if due == 0 and later > 0:
                    days.append(DayCell(date=day.isoformat(), kind="future", later=later))
                elif due == 0 and later == 0:
                    kind: DayKind = "nonStudy" if _outside_study(day, start, person.num_days) else "none"
                    days.append(DayCell(date=day.isoformat(), kind=kind))
                else:
                    days.append(
                        DayCell(
                            date=day.isoformat(),
                            kind="ratio",
                            completed=completed,
                            expected=due,
                            later=later,
                        )
                    )
                    if day <= today:
                        to_completed += completed
                        to_expected += due
            row_definitive = (
                not force_unknown
                and ambiguous == 0
                and unmatched == 0
                and excluded.anonymous == 0
                and excluded.conflict == 0
                and excluded.unjoinedInvitations == 0
            )
            if (
                person.surveys_scheduled
                and not admins
                and not unplaceable[index]
                and person.lookup_id
                and not force_unknown
            ):
                scheduled_without_invites = True
            if force_unknown:
                to_date = ToDate(completed=None, expected=None, provisional=True)
                row_definitive = False
            else:
                to_date = ToDate(
                    completed=to_completed,
                    expected=to_expected,
                    provisional=not row_definitive,
                )
        if zone is None:
            to_date = ToDate(completed=None, expected=None, provisional=True)
            ambiguous = unmatched = duplicates = 0
        rows.append(
            AcquisitionRow(
                contactId=person.contact_id,
                displayName=person.display_name,
                monitor=monitor,  # type: ignore[arg-type]
                timezone="" if zone is None else str(zone),
                timezoneSource=source,  # type: ignore[arg-type]
                today=today.isoformat(),
                definitive=row_definitive,
                ambiguous=ambiguous,
                unmatchedCompletions=unmatched,
                duplicateCompletions=duplicates,
                days=days,
                toDate=to_date,
            )
        )

    if unreadable_send:
        limitations.append(
            "An invitation had no readable send time, so that participant's expected total is unknown."
        )
    if truncated:
        limitations.append(
            f"A study window longer than {MAX_SPAN_DAYS} days was shortened to the most recent days."
        )
    if scheduled_without_invites:
        limitations.append(
            "Some participants have SurveysScheduled set but no invitations still listed. "
            "Their expected counts stay at the listed invitations rather than a redrawn schedule."
        )
    if bad_start:
        limitations.append(
            "A StartDate could not be read, so days outside the study were not marked for that participant."
        )
    if any(row.ambiguous or row.unmatchedCompletions for row in rows):
        limitations.append(
            "Some finished responses matched a participant but not a single invitation "
            "(more than one open prompt, a late response with several unmatched prompts, "
            "or an invitation id this profile does not list). Those responses were not "
            "added to a day."
        )

    # The anonymous / unjoined messages above are added even when zero. Guard:
    limitations = [item for item in limitations if item]
    definitive = all(row.definitive for row in rows) if rows else (
        excluded.anonymous == 0 and excluded.unjoinedInvitations == 0 and excluded.conflict == 0
    )
    return AcquisitionReport(
        generatedAt=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        definitive=definitive,
        prerequisite=PREREQUISITE,
        limitations=limitations,
        exportMode=export_mode,
        excluded=excluded,
        rows=rows,
    )


# One browser request cannot outlive the 60s proxy in front of the web app.
# Qualtrics exports are asynchronous, so the web route polls once per request.
# These caps bound a single survey and the whole profile, including leftover copies.
EXPORT_BYTE_LIMIT = 32 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 40.0
POLL_LIMIT_PER_SURVEY = 160
POLL_LIMIT_TOTAL = 240
EXPORT_DEADLINE_S = 8 * 60

_EXPORT_DETAILS = frozenset(
    {"timeout", "export status failed", "file too large", "could not be read", "superseded"}
)
_JOBS: dict[tuple[int, str, str], _ExportJob] = {}
_JOB_LOCK = threading.Lock()
_NEXT_GENERATION = 0
_SUPERSEDED: set[tuple[tuple[int, str, str], str]] = set()


def reset_acquisition_jobs() -> None:
    global _NEXT_GENERATION
    with _JOB_LOCK:
        _JOBS.clear()
        _SUPERSEDED.clear()
        _NEXT_GENERATION = 0


def export_failure(
    stage: str,
    *,
    status: int | None = None,
    code: str | None = None,
    detail: str | None = None,
) -> QualtricsError:
    """Stage, HTTP status, and a machine error code. Never a Qualtrics sentence."""
    if stage not in {"start", "poll", "download", "parse", "timeout"}:
        stage = "start"
    safe = machine_code(code)
    note = None
    if isinstance(status, int):
        note = f"HTTP {status}"
    elif detail in _EXPORT_DETAILS:
        note = detail
    message = f"Qualtrics response export failed at {stage}"
    if note:
        message += f" ({note})"
    if safe:
        message += f" [{safe}]"
    message += "."
    http = 502
    if isinstance(status, int) and status >= 400:
        http = status
    elif detail == "timeout" or stage == "timeout":
        http = 504
    elif detail == "superseded":
        http = 409
    return QualtricsError(http, "Api", message, code=safe)


def _tagged(exc: QualtricsError, stage: str) -> QualtricsError:
    if exc.status in (401, 403):
        return QualtricsError(401, "Unauthorized", "Qualtrics rejected the API token.")
    if exc.status == 429:
        return QualtricsError(
            429, "RateLimited", "Qualtrics rate-limited the request.", retryable=True
        )
    if exc.message.startswith("Qualtrics response export failed at "):
        return exc
    return export_failure(stage, status=exc.status, code=exc.code)


def _start_export(client: QualtricsClient, survey_id: str) -> tuple[str, ExportMode]:
    last_status = 502
    last_code: str | None = None
    for mode, body in export_request_bodies():
        try:
            resp = client.post(f"surveys/{survey_id}/export-responses", body, timeout=20)
        except httpx.TimeoutException:
            raise export_failure("start", detail="timeout") from None
        except QualtricsError as exc:
            if exc.status in (401, 403, 429, 404):
                raise _tagged(exc, "start") from None
            last_status = exc.status
            last_code = exc.code
            continue
        result = resp.get("result") if isinstance(resp, dict) else None
        progress = result.get("progressId") if isinstance(result, dict) else None
        if isinstance(progress, str) and progress:
            return progress, mode
        last_status = 502
        last_code = None
    raise export_failure("start", status=last_status, code=last_code)


def progress_view(body: Any) -> tuple[str, str | None]:
    """One Get Response Export Progress body.

    Returns ``("ready", file_id)``, ``("pending", None)``, or raises on
    ``failed``. ``percentComplete`` is not a download signal: Qualtrics
    documents that the file exists only once ``status`` is ``complete``.
    """
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict):
        raise export_failure("poll", status=502)
    status = str(result.get("status") or "").lower()
    if status == "failed":
        err = result.get("error") if isinstance(result.get("error"), dict) else {}
        code = machine_code(err.get("code")) if isinstance(err, dict) else None
        meta = body.get("meta") if isinstance(body, dict) else None
        if code is None and isinstance(meta, dict):
            meta_err = meta.get("error") if isinstance(meta.get("error"), dict) else {}
            if isinstance(meta_err, dict):
                code = machine_code(meta_err.get("errorCode"))
        raise export_failure("poll", detail="export status failed", code=code)
    file_id = result.get("fileId")
    if status == "complete" and isinstance(file_id, str) and file_id:
        return "ready", file_id
    return "pending", None


def _poll_once(client: QualtricsClient, survey_id: str, progress_id: str) -> str | None:
    try:
        body = client.get(f"surveys/{survey_id}/export-responses/{progress_id}", timeout=20)
    except httpx.TimeoutException:
        raise export_failure("poll", detail="timeout") from None
    except QualtricsError as exc:
        raise _tagged(exc, "poll") from None
    kind, file_id = progress_view(body)
    if kind == "ready":
        return file_id
    return None


def _read_export(client: QualtricsClient, survey_id: str, file_id: str) -> bytearray:
    path = f"surveys/{survey_id}/export-responses/{file_id}/file"
    limited = getattr(client, "get_bytes_limited", None)
    try:
        if limited is not None:
            blob = limited(path, EXPORT_BYTE_LIMIT, DOWNLOAD_TIMEOUT_S)
        else:
            blob = client.get_bytes(path)
    except QualtricsError as exc:
        raise _tagged(exc, "download") from None
    if len(blob) > EXPORT_BYTE_LIMIT:
        _wipe(blob)
        raise export_failure("download", detail="file too large")
    return blob


def _expiration(element: dict[str, Any]) -> datetime | None:
    for key in ("surveyLinkExpirationDate", "expirationDate"):
        raw = element.get(key)
        if isinstance(raw, str):
            return parse_send_date(raw)
    link = element.get("surveyLink")
    if isinstance(link, dict):
        raw = link.get("expirationDate")
        if isinstance(raw, str):
            return parse_send_date(raw)
    return None


def _lookup_of(element: dict[str, Any]) -> str:
    recipients = element.get("recipients")
    if isinstance(recipients, dict):
        raw = recipients.get("contactId")
        if isinstance(raw, str):
            return raw.strip()
    return ""


def _int_field(embedded: dict[str, str], key: str) -> int:
    raw = embedded.get(key, "").strip()
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        try:
            return int(float(raw))
        except ValueError:
            return 0


_MODE_RANK = {"columns": 0, "metadata": 1, "no-answers": 2, "full": 3}


@dataclass
class PendingExport:
    stage: str


@dataclass
class _ExportJob:
    attempt: str
    primary: str
    survey_ids: list[str]
    participants: list[Participant]
    invitations: list[Invitation]
    sms_missing: bool
    moment: datetime
    profile_timezone: str
    deadline: float
    index: int = 0
    phase: str = "create"
    progress_id: str | None = None
    mode: ExportMode = "columns"
    responses: list[ParsedResponse] | None = None
    copy_failed: bool = False
    polls: int = 0
    polls_survey: int = 0
    poll_limit_survey: int = POLL_LIMIT_PER_SURVEY
    poll_limit_total: int = POLL_LIMIT_TOTAL
    file_id: str | None = None
    generation: int = 0

    def __post_init__(self) -> None:
        if self.responses is None:
            self.responses = []


def _advance_survey(job: _ExportJob) -> bool:
    job.index += 1
    job.phase = "create"
    job.progress_id = None
    job.polls_survey = 0
    return job.index < len(job.survey_ids)


def _report_from_job(job: _ExportJob) -> AcquisitionReport:
    responses = job.responses or []
    report = aggregate(
        job.participants,
        job.invitations,
        responses,
        now=job.moment,
        profile_timezone=job.profile_timezone,
        export_mode=job.mode,
    )
    if job.mode != "columns":
        report.limitations.append(
            "Qualtrics rejected a filtered response export, so a broader file was "
            "read in memory and reduced to completion fields before counting. Survey "
            "answers were not kept, and names, email, IP, and location were not requested."
        )
    if job.copy_failed:
        report.limitations.append(
            "A leftover survey copy could not be exported. Completions recorded "
            "only on that copy are not in these counts."
        )
    if job.sms_missing:
        report.limitations.append(
            "SMS invitations could not be listed because Qualtrics returned not found. "
            "Expected counts include only the invitation lists that responded."
        )
    return report


def _skip_copy_or_raise(job: _ExportJob, primary: bool, exc: QualtricsError | None = None) -> AcquisitionReport | None:
    if primary:
        if exc is not None:
            raise exc
        return None
    job.copy_failed = True
    if _advance_survey(job):
        return None
    return _report_from_job(job)


def _download_ready(job: _ExportJob, client: QualtricsClient, survey_id: str, primary: bool):
    """Download one finished export. Returns a report when this was the last survey."""
    try:
        blob = _read_export(client, survey_id, job.file_id or "")
        try:
            found = parse_export_bytes(blob)
        except AcquisitionParseError:
            raise export_failure("parse", detail="could not be read") from None
        finally:
            _wipe(blob)
    except QualtricsError as exc:
        done = _skip_copy_or_raise(job, primary, exc)
        if done is not None:
            return done
        return PendingExport("start")
    assert job.responses is not None
    job.responses.extend(found)
    job.file_id = None
    if not _advance_survey(job):
        return _report_from_job(job)
    return PendingExport("start")


def _step_export(job: _ExportJob, client: QualtricsClient, clock) -> AcquisitionReport | PendingExport:
    """One slice: create, a single poll, or one download.

    A request that sees ``complete`` does not also download, and a download
    does not start the next survey. Each of those is its own request so the
    60 second proxy is not holding the file transfer plus another export.
    """
    if clock() > job.deadline:
        if job.phase == "download" and job.file_id and job.index == 0:
            outcome = _download_ready(job, client, job.survey_ids[0], True)
            if isinstance(outcome, PendingExport):
                job.copy_failed = True
                return _report_from_job(job)
            return outcome
        if job.index > 0:
            job.copy_failed = True
            return _report_from_job(job)
        raise export_failure("poll", detail="timeout")
    survey_id = job.survey_ids[job.index]
    primary = survey_id == job.primary
    if job.phase == "download":
        return _download_ready(job, client, survey_id, primary)
    if job.phase == "create":
        try:
            progress, used = _start_export(client, survey_id)
        except QualtricsError as exc:
            done = _skip_copy_or_raise(job, primary, exc)
            if done is not None:
                return done
            return PendingExport("start")
        job.progress_id = progress
        if _MODE_RANK[used] > _MODE_RANK[job.mode]:
            job.mode = used
        job.phase = "poll"
    try:
        file_id = _poll_once(client, survey_id, job.progress_id or "")
    except QualtricsError as exc:
        done = _skip_copy_or_raise(job, primary, exc)
        if done is not None:
            return done
        return PendingExport("start")
    if file_id is None:
        job.polls += 1
        job.polls_survey += 1
        if (
            job.polls_survey > job.poll_limit_survey
            or job.polls > job.poll_limit_total
            or clock() > job.deadline
        ):
            if not primary:
                job.copy_failed = True
                if not _advance_survey(job):
                    return _report_from_job(job)
                return PendingExport("start")
            raise export_failure("poll", detail="timeout")
        return PendingExport("poll")
    job.file_id = file_id
    job.phase = "download"
    return PendingExport("download")


def _new_job(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    *,
    attempt: str,
    moment: datetime,
    clock,
    poll_limit_survey: int,
    poll_limit_total: int,
) -> _ExportJob:
    directory = account.default_directory
    mailing_list = profile.mailing_list_id
    raw_contacts = list_raw(client, directory, mailing_list)
    participants: list[Participant] = []
    for raw in raw_contacts:
        contact_id = contact_id_of(raw) or ""
        if not contact_id:
            continue
        try:
            lookup = resolve_contact_lookup_id(client, directory, mailing_list, raw)
        except HTTPException:
            lookup = ""
        embedded = embedded_of(raw)
        name = f"{str_field(raw, 'firstName')} {str_field(raw, 'lastName')}".strip()
        if not name:
            name = display_name(raw)
        participants.append(
            Participant(
                contact_id=contact_id,
                lookup_id=lookup,
                display_name=name,
                timezone_name=embedded.get("TimeZone", ""),
                start_date=embedded.get("StartDate", ""),
                num_days=_int_field(embedded, "NumDays"),
                monitor=embedded.get(MONITOR_FIELD, ""),
                surveys_scheduled=_int_field(embedded, "SurveysScheduled"),
            )
        )

    invitations: list[Invitation] = []
    sms_missing = False
    primary = profile.survey_id.strip()
    for survey in survey_rotation(profile):
        paths = (
            (
                f"distributions?mailingListId={mailing_list}&surveyId={survey.id}"
                "&distributionRequestType=Invite&useNewPaginationScheme=true"
            ),
            f"distributions/sms?surveyId={survey.id}",
        )
        for path in paths:
            # An email-only survey can 404 the SMS collection. That must not hide
            # the email invitations. A missing primary survey still fails the email list.
            sms = path.startswith("distributions/sms")
            try:
                elements = client.get_elements(path)
            except QualtricsError as exc:
                if exc.status == 404 and (survey.id != primary or sms):
                    if sms:
                        sms_missing = True
                    continue
                raise
            for element in elements:
                if not isinstance(element, dict):
                    continue
                dist_id = element.get("id")
                send_raw = element.get("sendDate")
                invitations.append(
                    Invitation(
                        distribution_id=dist_id.strip() if isinstance(dist_id, str) else "",
                        lookup_id=_lookup_of(element),
                        send=parse_send_date(send_raw) if isinstance(send_raw, str) else None,
                        expire=_expiration(element),
                    )
                )
    return _ExportJob(
        attempt=attempt,
        primary=primary,
        survey_ids=[survey.id for survey in survey_rotation(profile)],
        participants=participants,
        invitations=invitations,
        sms_missing=sms_missing,
        moment=moment,
        profile_timezone=profile.timezone or "",
        deadline=clock() + EXPORT_DEADLINE_S,
        poll_limit_survey=poll_limit_survey,
        poll_limit_total=poll_limit_total,
    )


def acquisition_step(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    *,
    user_id: int,
    attempt: str,
    now: datetime | None = None,
    clock=time.monotonic,
    poll_limit_survey: int = POLL_LIMIT_PER_SURVEY,
    poll_limit_total: int = POLL_LIMIT_TOTAL,
) -> AcquisitionReport | PendingExport:
    """One slice of an acquisition load.

    The web route calls this once per browser request. A Qualtrics export that
    is still ``inProgress`` is remembered in this process only, keyed by the
    user and profile, and the next request with the same attempt continues it.
    A new attempt drops that memory. Nothing is written to disk.
    """
    key = (user_id, account.id, profile.id)
    moment = now or datetime.now(UTC)
    global _NEXT_GENERATION
    with _JOB_LOCK:
        current = _JOBS.get(key)
        if (key, attempt) in _SUPERSEDED:
            raise export_failure("poll", detail="superseded")
        if current is not None and current.attempt == attempt and current.phase != "prepare":
            if clock() > current.deadline and not (
                current.phase == "download" and current.file_id and current.index == 0
            ):
                _JOBS.pop(key, None)
                if current.index > 0:
                    current.copy_failed = True
                    return _report_from_job(current)
                raise export_failure("poll", detail="timeout")
            job = current
            claim = None
        else:
            # A new attempt claims the slot before the slow contact listing, so an
            # older request cannot store its job back over this one when it finishes.
            if current is not None and current.attempt != attempt:
                _SUPERSEDED.add((key, current.attempt))
            _NEXT_GENERATION += 1
            claim = _ExportJob(
                attempt=attempt,
                primary="",
                survey_ids=[""],
                participants=[],
                invitations=[],
                sms_missing=False,
                moment=moment,
                profile_timezone="",
                deadline=clock() + EXPORT_DEADLINE_S,
                phase="prepare",
                generation=_NEXT_GENERATION,
            )
            _JOBS[key] = claim
            job = None
    if job is None:
        assert claim is not None
        try:
            built = _new_job(
                client,
                account,
                profile,
                attempt=attempt,
                moment=moment,
                clock=clock,
                poll_limit_survey=poll_limit_survey,
                poll_limit_total=poll_limit_total,
            )
        except Exception:
            with _JOB_LOCK:
                if _JOBS.get(key) is claim:
                    _JOBS.pop(key, None)
            raise
        built.generation = claim.generation
        with _JOB_LOCK:
            if _JOBS.get(key) is not claim:
                raise export_failure("poll", detail="superseded")
            _JOBS[key] = built
        job = built
    try:
        outcome = _step_export(job, client, clock)
    except Exception:
        with _JOB_LOCK:
            if _JOBS.get(key) is job:
                _JOBS.pop(key, None)
        raise
    with _JOB_LOCK:
        if _JOBS.get(key) is not job:
            if isinstance(outcome, PendingExport):
                raise export_failure("poll", detail="superseded")
            return outcome
        if isinstance(outcome, PendingExport):
            _JOBS[key] = job
        else:
            _JOBS.pop(key, None)
    return outcome


def load_report(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    *,
    now: datetime | None = None,
    sleep=time.sleep,
    user_id: int = 0,
    attempt: str | None = None,
    clock=time.monotonic,
    poll_limit_survey: int = POLL_LIMIT_PER_SURVEY,
    poll_limit_total: int = POLL_LIMIT_TOTAL,
) -> AcquisitionReport:
    """Fetch contacts, listed invitations, and response exports. Nothing is written."""
    token = attempt or f"direct-{time.monotonic_ns()}"
    while True:
        outcome = acquisition_step(
            client,
            account,
            profile,
            user_id=user_id,
            attempt=token,
            now=now,
            clock=clock,
            poll_limit_survey=poll_limit_survey,
            poll_limit_total=poll_limit_total,
        )
        if isinstance(outcome, PendingExport):
            sleep(2)
            continue
        return outcome


def set_monitor_status(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    contact_id: str,
    status: str,
) -> MonitorUpdate:
    """Write only ``QsMonitor``. Does not seed defaults, cancel invitations, or change eligibility."""
    monitor = status.strip().lower()
    if monitor not in {"active", "inactive"}:
        raise app_error(400, "Invalid", "status must be active or inactive")
    raw_list = list_raw(client, account.default_directory, profile.mailing_list_id)
    contact = find_in_list(raw_list, contact_id)
    before = embedded_of(contact).get("SurveysScheduled")
    updated = update_contact(
        client,
        account.default_directory,
        profile.mailing_list_id,
        contact,
        {},
        [],
        {MONITOR_FIELD: monitor},
        {"action": "qs_monitor", "value": monitor},
    )
    after = embedded_of(updated)
    if after.get("SurveysScheduled") != before:
        raise app_error(
            502,
            "Api",
            "Qualtrics changed SurveysScheduled while updating monitor status. No invitations were cancelled.",
        )
    return MonitorUpdate(contactId=contact_id, monitor=normalize_monitor(after.get(MONITOR_FIELD)))
