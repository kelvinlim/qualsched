"""Acquisition heatmap: completed responses, exact id matching, no PHI retention."""

import builtins
import io
import json
import threading
import time
import zipfile
from datetime import UTC, datetime

import httpx
import pytest

from app.acquisition import (
    DENOMINATOR_NOTE,
    EXPORT_DEADLINE_S,
    MAX_SPAN_DAYS,
    MONITOR_FIELD,
    PREREQUISITE,
    AcquisitionParseError,
    Invitation,
    Participant,
    PendingExport,
    _start_export,
    acquisition_step,
    aggregate,
    export_failure,
    export_request_bodies,
    extract_response,
    load_report,
    parse_export_bytes,
    progress_view,
    reset_acquisition_jobs,
    set_monitor_status,
)
from app.distributions import parse_send_date
from app.eligibility import EligibilityDefaults, contact_eligibility
from app.main import app
from app.models import QualtricsAccount, SurveyProfile, User
from app.qualtrics import QualtricsClient, QualtricsError
from app.security import get_current_user
from tests.test_accounts import ACCOUNT, PROJECT
from tests.test_contacts import _ready_account

AID = ACCOUNT["id"]
PID = PROJECT["id"]
BASE = f"/api/accounts/{AID}/projects/{PID}/acquisition"
SECRET_ANSWER = "secret-symptom"
EMAIL = "ada@example.com"
PHONE = "5550100"
NOW = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_export_jobs():
    reset_acquisition_jobs()
    yield
    reset_acquisition_jobs()


def _person(**overrides) -> Participant:
    base = {
        "contact_id": "CID_ada",
        "lookup_id": "CGC_ada",
        "display_name": "Ada Lovelace",
        "timezone_name": "America/Chicago",
        "start_date": "2026-07-13",
        "num_days": 5,
        "monitor": "active",
        "surveys_scheduled": 0,
    }
    base.update(overrides)
    return Participant(**base)


def _invite(dist: str, send: str, expire: str | None = None, lookup: str = "CGC_ada") -> Invitation:
    return Invitation(
        distribution_id=dist,
        lookup_id=lookup,
        send=parse_send_date(send),
        expire=parse_send_date(expire) if expire else None,
    )


def _values(**extra) -> dict:
    payload = {
        "QID1": SECRET_ANSWER,
        "recipientEmail": EMAIL,
        "recipientFirstName": "Ada",
        "recipientLastName": "Lovelace",
        "ipAddress": "203.0.113.9",
        "locationLatitude": "44.9",
    }
    payload.update(extra)
    return payload


def _response(response_id: str, **values) -> dict:
    return {"responseId": response_id, "values": _values(**values)}


def _zip(objects: list[dict] | str) -> bytes:
    raw = objects if isinstance(objects, str) else "\n".join(json.dumps(obj) for obj in objects)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("responses.ndjson", raw)
    return buf.getvalue()


def _report(responses: list[dict], invites: list[Invitation], **person):
    parsed = [extract_response(obj, f"missing-{i}") for i, obj in enumerate(responses)]
    return aggregate(
        [_person(**person)],
        invites,
        parsed,
        now=NOW,
        profile_timezone="America/Chicago",
    )


def _day(report, iso: str):
    return next(day for day in report.rows[0].days if day.date == iso)


def _embedded(**extra) -> dict[str, str]:
    base = {
        "StartDate": "2026-07-13",
        "NumDays": "5",
        "TimeSlots": "800,1200",
        "TimeZone": "America/Chicago",
        "ContactMethod": "sms",
        "SurveysScheduled": "0",
        "ExpireMinutes": "60",
    }
    base.update(extra)
    return base


# The 17 metadata ids Qualtrics documents for surveyMetadataIds.
OFFICIAL_METADATA = {
    "startDate",
    "endDate",
    "status",
    "ipAddress",
    "progress",
    "duration",
    "finished",
    "recordedDate",
    "_recordId",
    "recipientLastName",
    "recipientFirstName",
    "recipientEmail",
    "externalDataReference",
    "locationLatitude",
    "locationLongitude",
    "distributionChannel",
    "userLanguage",
}
JSON_FORBIDDEN = {
    "includeDisplayOrder",
    "useLabels",
    "formatDecimalAsComma",
    "seenUnansweredRecode",
    "multiselectSeenUnansweredRecode",
    "timeZone",
    "newlineReplacement",
    "breakoutSets",
}


def qualtrics_export_status(body: dict, *, survey_embedded: set[str] | None = None) -> int | None:
    """Documented create-export rejections. None means the body is acceptable.

    Unknown embeddedDataIds are HTTP 400 (invalid columns). JSON/NDJSON reject
    the label/timezone/breakout parameters even when false. Empty questionIds
    is allowed and means no answer columns.
    """
    embedded_fields = set() if survey_embedded is None else survey_embedded
    if body.get("format") in {"json", "ndjson"} and JSON_FORBIDDEN.intersection(body):
        return 400
    if "embeddedDataIds" in body and any(name not in embedded_fields for name in body["embeddedDataIds"]):
        return 400
    if "questionIds" in body:
        for qid in body["questionIds"]:
            if not (isinstance(qid, str) and qid.startswith("QID") and qid[3:].isdigit()):
                return 400
    if "surveyMetadataIds" in body and any(item not in OFFICIAL_METADATA for item in body["surveyMetadataIds"]):
        return 400
    return None


def test_export_request_omits_identity_and_answers():
    bodies = export_request_bodies()
    assert [mode for mode, _ in bodies] == ["columns", "metadata", "no-answers", "full"]
    first = bodies[0][1]
    dumped = json.dumps(first)
    assert "recipientEmail" not in dumped
    assert "RecipientID" not in dumped
    assert "embeddedDataIds" not in first
    assert first["format"] == "json"
    assert first["questionIds"] == []
    assert bodies[-1][1] == {"format": "json", "compress": True}
    for _, body in bodies:
        assert qualtrics_export_status(body, survey_embedded=set()) is None
        assert "recipientEmail" not in json.dumps(body)
        assert JSON_FORBIDDEN.isdisjoint(body)


def test_guessed_embedded_ids_are_the_documented_400():
    """The body this screen used to send is rejected when those names are not fields."""
    previous = {
        "format": "ndjson",
        "compress": True,
        "exportResponsesInProgress": False,
        "surveyMetadataIds": ["finished", "recordedDate", "_recordId"],
        "embeddedDataIds": ["RecipientID", "recipientId", "ContactID", "contactId", "Q_DL"],
        "questionIds": [],
    }
    assert qualtrics_export_status(previous, survey_embedded={"TimeZone", "StartDate"}) == 400


def test_json_export_envelope_is_parsed_and_answers_dropped():
    """format=json is a zip of one JSON object, not ndjson lines."""
    payload = {
        "responses": [
            _response(
                "R_1",
                finished=1,
                status=0,
                RecipientID="CID_ada",
                endDate="2026-07-13T13:30:00Z",
                QID1=SECRET_ANSWER,
            )
        ]
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("EMA.json", json.dumps(payload))
    facts = parse_export_bytes(bytearray(buf.getvalue()))
    assert len(facts) == 1
    assert facts[0].recipient_id == "CID_ada"
    assert facts[0].finished is True
    dumped = json.dumps(facts[0].__dict__, default=str)
    assert SECRET_ANSWER not in dumped
    assert EMAIL not in dumped


def test_parser_keeps_completion_fields_only_and_errors_do_not_echo():
    raw = _zip(
        [
            _response(
                "R_1",
                finished=1,
                status=0,
                endDate="2026-07-13T13:30:00Z",
                RecipientID="CID_ada",
                distributionChannel="email",
            )
        ]
    )
    facts = parse_export_bytes(raw)
    dumped = json.dumps(facts[0].__dict__, default=str)
    assert facts[0].recipient_id == "CID_ada"
    assert facts[0].finished is True
    assert SECRET_ANSWER not in dumped
    assert EMAIL not in dumped
    assert "203.0.113.9" not in dumped
    try:
        parse_export_bytes(f"not-an-export {SECRET_ANSWER}".encode())
    except AcquisitionParseError as exc:
        assert SECRET_ANSWER not in str(exc)
        assert exc.__cause__ is None
    else:
        raise AssertionError("corrupt export should fail")


def test_parser_does_not_touch_the_filesystem(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("acquisition parser opened a file")

    monkeypatch.setattr(builtins, "open", boom)
    facts = parse_export_bytes(
        _zip([_response("R_1", finished=1, status=0, RecipientID="CID_ada", endDate="2026-07-13T13:30:00Z")])
    )
    assert facts[0].response_id == "R_1"


def test_completed_only_excludes_preview_test_synthetic_spam_and_partials():
    invites = [
        _invite("D1", "2026-07-13T13:00:00Z", "2026-07-13T14:00:00Z"),
        _invite("D2", "2026-07-13T15:00:00Z", "2026-07-13T16:00:00Z"),
        _invite("D3", "2026-07-13T17:00:00Z", "2026-07-13T18:00:00Z"),
    ]
    responses = [
        _response("R_ok", finished=1, status=0, RecipientID="CID_ada", endDate="2026-07-13T13:20:00Z", DistributionID="D1"),
        _response("R_preview", finished=1, status=1, RecipientID="CID_ada", endDate="2026-07-13T13:20:00Z", DistributionID="D1"),
        _response("R_test", finished=1, status=2, RecipientID="CID_ada", endDate="2026-07-13T13:20:00Z"),
        _response("R_synthetic", finished=1, status=256, RecipientID="CID_ada", endDate="2026-07-13T13:20:00Z"),
        _response("R_spam", finished=1, status=8, RecipientID="CID_ada", endDate="2026-07-13T13:20:00Z"),
        _response("R_partial", finished=0, status=0, RecipientID="CID_ada", endDate="2026-07-13T13:20:00Z"),
        _response("R_label", finished="True", status="Survey Preview", RecipientID="CID_ada", endDate="2026-07-13T13:20:00Z"),
        _response("R_import", finished=1, status=4, RecipientID="CID_ada", endDate="2026-07-13T15:25:00Z", DistributionID="D2"),
        _response("R_offline", finished=1, status=16, RecipientID="CID_ada", endDate="2026-07-13T17:10:00Z", DistributionID="D3"),
    ]
    report = _report(responses, invites)
    day = _day(report, "2026-07-13")
    assert day.kind == "ratio"
    assert day.completed == 3
    assert day.expected == 3
    assert report.excluded.preview == 2
    assert report.excluded.test == 1
    assert report.excluded.synthetic == 1
    assert report.excluded.spam == 1
    assert report.excluded.unfinished == 1
    assert report.rows[0].duplicateCompletions == 0
    assert SECRET_ANSWER not in report.model_dump_json()
    assert EMAIL not in report.model_dump_json()


def test_does_not_match_email_name_or_external_reference():
    invites = [_invite("D1", "2026-07-13T13:00:00Z", "2026-07-13T16:00:00Z")]
    responses = [
        _response(
            "R_email",
            finished=1,
            status=0,
            endDate="2026-07-13T13:30:00Z",
            externalDataReference="CID_ada",
        ),
        {
            "responseId": "R_named",
            "values": {
                "finished": 1,
                "status": 0,
                "endDate": "2026-07-13T13:40:00Z",
                "recipientEmail": EMAIL,
                "recipientFirstName": "Ada",
                "recipientLastName": "Lovelace",
                "QID1": SECRET_ANSWER,
            },
        },
    ]
    report = _report(responses, invites)
    assert report.excluded.anonymous == 2
    assert _day(report, "2026-07-13").completed == 0
    assert _day(report, "2026-07-13").expected == 1
    assert report.rows[0].definitive is False
    dumped = report.model_dump_json()
    assert SECRET_ANSWER not in dumped
    assert EMAIL not in dumped
    assert PREREQUISITE in report.prerequisite


def test_exact_id_dedup_late_and_explicit_distribution():
    invites = [
        _invite("D1", "2026-07-13T13:00:00Z", "2026-07-13T14:00:00Z"),
        _invite("D2", "2026-07-13T17:00:00Z", "2026-07-13T18:00:00Z"),
        _invite("D3", "2026-07-14T13:00:00Z", "2026-07-14T14:00:00Z"),
        _invite("D4", "2026-07-15T15:00:00Z", "2026-07-15T16:00:00Z"),
        _invite("D5", "2026-07-15T23:00:00Z", "2026-07-15T23:30:00Z"),
        _invite("D6", "2026-07-16T13:00:00Z", "2026-07-16T14:00:00Z"),
    ]
    responses = [
        _response("R1", finished=1, status=0, RecipientID="CID_ada", DistributionID="D1", endDate="2026-07-13T13:30:00Z"),
        _response("R1", finished=1, status=0, RecipientID="CID_ada", DistributionID="D1", endDate="2026-07-13T13:31:00Z"),
        _response("R2", finished=1, status=0, RecipientID="CID_ada", endDate="2026-07-13T17:30:00Z"),
        _response("R3", finished=1, status=0, RecipientID="CID_ada", endDate="2026-07-15T15:40:00Z"),
        _response("R5", finished=1, status=0, RecipientID="CID_ada", DistributionID="D1", endDate="2026-07-13T13:50:00Z"),
        _response("Rlate", finished=1, status=0, RecipientID="CID_ada", endDate="2026-07-14T20:00:00Z"),
        _response("Rother", finished=1, status=0, RecipientID="CID_nobody", endDate="2026-07-14T20:00:00Z"),
    ]
    report = _report(responses, invites)
    assert report.excluded.duplicateIds == 1
    assert report.excluded.unmatchedRecipient == 1
    assert _day(report, "2026-07-13").completed == 2
    assert _day(report, "2026-07-13").expected == 2
    assert _day(report, "2026-07-14").completed == 1
    assert _day(report, "2026-07-15").completed == 1
    assert _day(report, "2026-07-15").expected == 1
    assert _day(report, "2026-07-15").later == 1
    assert _day(report, "2026-07-16").kind == "future"
    assert _day(report, "2026-07-16").later == 1
    assert report.rows[0].duplicateCompletions == 1
    assert report.rows[0].toDate.completed == 4
    assert report.rows[0].toDate.expected == 4
    # Unmatched recipient is not this row's response, so the row stays definitive.
    assert report.rows[0].definitive is True


def test_ambiguous_overlap_is_not_attributed():
    invites = [
        _invite("A", "2026-07-13T15:00:00Z", "2026-07-13T19:00:00Z"),
        _invite("B", "2026-07-13T16:00:00Z", "2026-07-13T20:00:00Z"),
    ]
    responses = [
        _response("R", finished=1, status=0, RecipientID="CID_ada", endDate="2026-07-13T17:00:00Z"),
    ]
    report = _report(responses, invites)
    day = _day(report, "2026-07-13")
    assert day.completed == 0
    assert day.expected == 2
    assert report.rows[0].ambiguous == 1
    assert report.rows[0].definitive is False
    assert report.rows[0].toDate.provisional is True


def test_zero_future_none_and_non_study_are_distinct():
    invites = [_invite("D", "2026-07-14T13:00:00Z", "2026-07-14T14:00:00Z")]
    report = _report([], invites)
    assert _day(report, "2026-07-14").kind == "ratio"
    assert _day(report, "2026-07-14").completed == 0
    assert _day(report, "2026-07-14").expected == 1
    assert _day(report, "2026-07-17").kind == "none"
    assert _day(report, "2026-07-12").kind == "nonStudy"
    future = _report([], [_invite("Later", "2026-07-16T13:00:00Z")])
    assert _day(future, "2026-07-16").kind == "future"
    # An invitation outside the study window is still real.
    outside = _report([], [_invite("Early", "2026-07-12T15:00:00Z", "2026-07-12T16:00:00Z")])
    assert _day(outside, "2026-07-12").kind == "ratio"
    assert _day(outside, "2026-07-12").expected == 1


def test_current_day_denominator_ignores_prompts_not_yet_due():
    report = _report(
        [],
        [
            _invite("Due", "2026-07-15T15:00:00Z", "2026-07-15T16:00:00Z"),
            _invite("Later", "2026-07-15T23:00:00Z", "2026-07-15T23:30:00Z"),
        ],
    )
    day = _day(report, "2026-07-15")
    assert day.kind == "ratio"
    assert day.completed == 0
    assert day.expected == 1
    assert day.later == 1
    assert report.rows[0].toDate.expected == 1


def test_changed_send_time_is_not_redrawn_from_time_slots():
    # 15:17 UTC is 10:17 in Chicago, not one of the profile's 800/1200 slots.
    report = _report([], [_invite("Odd", "2026-07-14T15:17:00Z", "2026-07-14T16:17:00Z")])
    assert _day(report, "2026-07-14").expected == 1
    assert _day(report, "2026-07-14").kind == "ratio"


def test_dst_boundaries_use_the_participant_zone():
    spring = aggregate(
        [_person(start_date="", num_days=0)],
        [
            _invite("Before", "2026-03-08T04:30:00Z"),
            _invite("After", "2026-03-08T07:30:00Z"),
        ],
        [],
        now=datetime(2026, 3, 8, 18, 0, tzinfo=UTC),
        profile_timezone="America/Chicago",
    )
    assert _day(spring, "2026-03-07").kind == "ratio"
    assert _day(spring, "2026-03-08").kind == "ratio"
    fall = aggregate(
        [_person(start_date="", num_days=0)],
        [
            _invite("Eve", "2026-11-01T04:59:00Z"),
            _invite("Morning", "2026-11-01T06:30:00Z"),
        ],
        [],
        now=datetime(2026, 11, 1, 18, 0, tzinfo=UTC),
        profile_timezone="America/Chicago",
    )
    assert _day(fall, "2026-10-31").expected == 1
    assert _day(fall, "2026-11-01").expected == 1


def test_unknown_timezone_and_missing_lookup_do_not_invent_counts():
    bad_zone = _report([], [_invite("D", "2026-07-14T13:00:00Z")], timezone_name="Mars/Olympus")
    assert bad_zone.rows[0].timezoneSource == "invalid"
    assert all(day.kind == "unknown" for day in bad_zone.rows[0].days)
    assert bad_zone.rows[0].toDate.expected is None
    assert bad_zone.rows[0].definitive is False

    missing_lookup = aggregate(
        [_person(lookup_id="")],
        [_invite("D", "2026-07-14T13:00:00Z", lookup="CGC_other")],
        [],
        now=NOW,
        profile_timezone="America/Chicago",
    )
    assert missing_lookup.excluded.unjoinedInvitations == 1
    assert all(day.kind == "unknown" for day in missing_lookup.rows[0].days)
    assert missing_lookup.rows[0].toDate.expected is None

    profile_zone = _report([], [], timezone_name="")
    assert profile_zone.rows[0].timezoneSource == "profile"
    assert profile_zone.rows[0].timezone == "America/Chicago"


def test_listed_empty_schedule_is_not_redrawn_when_surveys_scheduled_is_set():
    report = _report([], [], surveys_scheduled=4)
    assert _day(report, "2026-07-14").kind == "none"
    assert report.rows[0].toDate.expected == 0
    assert any("SurveysScheduled" in item for item in report.limitations)
    assert DENOMINATOR_NOTE in report.limitations


def test_q_dl_links_a_known_distribution_and_ignores_a_foreign_one():
    invites = [
        _invite("EMD_ada", "2026-07-13T13:00:00Z", "2026-07-13T16:00:00Z"),
        _invite("EMD_bob", "2026-07-13T13:00:00Z", "2026-07-13T16:00:00Z", lookup="CGC_bob"),
    ]
    ada = _person()
    bob = _person(
        contact_id="CID_bob",
        lookup_id="CGC_bob",
        display_name="Bob Example",
        start_date="",
        num_days=0,
    )
    responses = [
        extract_response(
            _response(
                "R_ada",
                finished=1,
                status=0,
                RecipientID="CID_ada",
                Q_DL="EMD_ada_CID_ada_CG_list",
                endDate="2026-07-13T14:00:00Z",
            ),
            "x",
        ),
        extract_response(
            _response(
                "R_cross",
                finished=1,
                status=0,
                RecipientID="CID_ada",
                DistributionID="EMD_bob",
                endDate="2026-07-13T14:10:00Z",
            ),
            "y",
        ),
    ]
    report = aggregate([ada, bob], invites, responses, now=NOW, profile_timezone="America/Chicago")
    ada_row = next(row for row in report.rows if row.contactId == "CID_ada")
    bob_row = next(row for row in report.rows if row.contactId == "CID_bob")
    ada_day = next(day for day in ada_row.days if day.date == "2026-07-13")
    bob_day = next(day for day in bob_row.days if day.date == "2026-07-13")
    assert ada_day.completed == 1
    assert ada_day.expected == 1
    assert bob_day.completed == 0
    assert bob_day.expected == 1
    assert report.excluded.conflict == 1


def test_monitor_flag_does_not_change_eligibility():
    defaults = EligibilityDefaults(timezone="America/Chicago", minutes_expire=60)
    embedded = _embedded()
    before = contact_eligibility(embedded, defaults)
    inactive = dict(embedded)
    inactive[MONITOR_FIELD] = "inactive"
    after = contact_eligibility(inactive, defaults)
    assert type(before) is type(after)
    assert getattr(before, "num_days", None) == getattr(after, "num_days", None)
    assert not isinstance(after, str)


class FakeQualtrics:
    def __init__(self, export: bytes):
        self.export = bytearray(export)
        self.contacts: list[dict] = []
        self.distributions: list[dict] = []
        self.calls: list[tuple] = []
        self.sms_error: QualtricsError | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def add(self, raw: dict) -> None:
        self.contacts.append(raw)

    def get_elements(self, path: str, timeout: float | None = None):
        self.calls.append(("get_elements", path))
        if "distributions" in path:
            # Email and SMS are different Qualtrics collections. Returning the same
            # rows for both would double-count invitations.
            if path.startswith("distributions/sms"):
                if self.sms_error is not None:
                    raise self.sms_error
                return []
            return list(self.distributions)
        return list(self.contacts)

    def get(self, path: str, timeout: float | None = None):
        self.calls.append(("get", path))
        if "export-responses/" in path:
            return {
                "result": {"status": "complete", "percentComplete": 100, "fileId": "FILE1"}
            }
        cid = path.rstrip("/").rsplit("/", 1)[-1]
        for contact in self.contacts:
            if contact.get("contactId") == cid:
                if "/mailinglists/" not in path:
                    return {
                        "result": {
                            "mailingListMembership": {
                                "CG_list": {"contactLookupId": contact.get("contactLookupId", "")}
                            }
                        }
                    }
                return {"result": contact}
        raise QualtricsError(404, "NotFound", "missing")

    def post(self, path: str, body: dict, timeout: float | None = None):
        self.calls.append(("post", path, body))
        if path.endswith("export-responses"):
            return {"result": {"progressId": "PROG1"}}
        raise AssertionError(path)

    def get_bytes(self, path: str) -> bytearray:
        self.calls.append(("get_bytes", path))
        return bytearray(self.export)

    def put(self, path: str, body: dict):
        self.calls.append(("put", path, body))
        cid = path.rstrip("/").rsplit("/", 1)[-1]
        for contact in self.contacts:
            if contact.get("contactId") == cid:
                embedded = dict(contact.get("embeddedData") or {})
                embedded.update(body.get("embeddedData") or {})
                contact["embeddedData"] = embedded
                contact["contactId"] = cid
                return {"result": {}}
        raise QualtricsError(404, "NotFound", "missing")

    def delete(self, path: str):
        self.calls.append(("delete", path))
        raise AssertionError(f"acquisition must not delete {path}")


def _contact() -> dict:
    return {
        "contactId": "CID_ada",
        "contactLookupId": "CGC_ada",
        "firstName": "Ada",
        "lastName": "Lovelace",
        "email": EMAIL,
        "phone": PHONE,
        "extRef": "P1",
        "language": "en",
        "embeddedData": _embedded(),
    }


def _install(monkeypatch, fake: FakeQualtrics):
    monkeypatch.setattr("app.routers.acquisition.qualtrics_for", lambda _account: fake)
    monkeypatch.setattr("app.acquisition.time.sleep", lambda _seconds: None)

    def inline(target, args):
        target(*args)

    # Existing cases want the finished body. The background-thread test below
    # leaves the real starter in place.
    monkeypatch.setattr("app.routers.acquisition._start_worker", inline)


def _follow(http, headers: dict | None = None):
    """Walk the short export slices the way the browser does."""
    sent = {"X-Qualsched-Attempt": "attempt-follow"}
    if headers:
        sent.update(headers)
    response = None
    for _ in range(8):
        response = http.get(BASE, headers=sent)
        if response.status_code != 202:
            return response
    raise AssertionError(getattr(response, "text", "export did not finish"))


def test_http_report_strips_answers_and_keeps_ratio(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    export = _zip(
        [
            _response(
                "R1",
                finished=1,
                status=0,
                RecipientID="CID_ada",
                DistributionID="EMD_1",
                endDate="2026-07-14T13:30:00Z",
            )
        ]
    )
    fake = FakeQualtrics(export)
    fake.add(_contact())
    fake.distributions.append(
        {
            "id": "EMD_1",
            "sendDate": "2026-07-14T13:00:00Z",
            "surveyLink": {"expirationDate": "2026-07-14T14:00:00Z"},
            "recipients": {"contactId": "CGC_ada"},
        }
    )
    _install(monkeypatch, fake)
    response = _follow(http)
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    text = response.text
    assert SECRET_ANSWER not in text
    assert EMAIL not in text
    assert PHONE not in text
    assert "203.0.113.9" not in text
    assert body["rows"][0]["displayName"] == "Ada Lovelace"
    assert body["rows"][0]["extRef"] == "P1"
    assert body["rows"][0]["monitor"] == "active"
    day = next(item for item in body["rows"][0]["days"] if item["date"] == "2026-07-14")
    assert day["completed"] == 1
    assert day["expected"] == 1
    posted = [call[2] for call in fake.calls if call[0] == "post"]
    assert posted and "recipientEmail" not in json.dumps(posted[0])
    assert all(call[0] != "delete" for call in fake.calls)


def test_http_error_path_does_not_echo_export_bytes(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics(f"broken {SECRET_ANSWER}".encode())
    fake.add(_contact())
    _install(monkeypatch, fake)
    response = _follow(http)
    assert response.status_code == 502
    assert SECRET_ANSWER not in response.text
    assert EMAIL not in response.text


def test_status_roundtrip_keeps_eligibility_and_does_not_cancel(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics(_zip([]))
    fake.add(_contact())
    _install(monkeypatch, fake)
    updated = http.put(BASE + "/status", json={"contactId": "CID_ada", "status": "inactive"})
    assert updated.status_code == 200, updated.text
    assert updated.json() == {"contactId": "CID_ada", "monitor": "inactive"}
    puts = [call for call in fake.calls if call[0] == "put"]
    assert len(puts) == 1
    embedded = puts[0][2]["embeddedData"]
    assert embedded[MONITOR_FIELD] == "inactive"
    assert embedded["SurveysScheduled"] == "0"
    assert all(call[0] != "delete" for call in fake.calls)
    defaults = EligibilityDefaults(timezone="America/Chicago", minutes_expire=60)
    assert not isinstance(contact_eligibility(
        {k: str(v) for k, v in fake.contacts[0]["embeddedData"].items()},
        defaults,
    ), str)

    again = _follow(http)
    assert again.status_code == 200
    row = again.json()["rows"][0]
    assert row["monitor"] == "inactive"
    assert row["contactId"] == "CID_ada"
    # Inactive stays in the payload. The display filter is client-side and must not
    # drop the person server-side, which would look like their data was removed.
    assert len(again.json()["rows"]) == 1


def test_monitor_status_rejects_unknown_values(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics(_zip([]))
    fake.add(_contact())
    _install(monkeypatch, fake)
    response = http.put(BASE + "/status", json={"contactId": "CID_ada", "status": "deleted"})
    assert response.status_code == 400
    assert all(call[0] != "put" for call in fake.calls)
    assert all(call[0] != "delete" for call in fake.calls)


def test_acquisition_requires_login(anon):
    response = anon.get(BASE)
    assert response.status_code == 401
    assert SECRET_ANSWER not in response.text


def test_other_researcher_cannot_read_or_mark_status(ctx, monkeypatch):
    http, Session, _uid = ctx
    _ready_account(http)
    fake = FakeQualtrics(_zip([]))
    fake.add(_contact())
    _install(monkeypatch, fake)
    session = Session()
    other = User(email="other@example.com", name="Other Researcher", is_superuser=False)
    session.add(other)
    session.commit()
    other_id = other.id
    session.close()

    app.dependency_overrides[get_current_user] = lambda: Session().get(User, other_id)
    listing = http.get(BASE)
    marking = http.put(BASE + "/status", json={"contactId": "CID_ada", "status": "inactive"})
    assert listing.status_code == 404
    assert marking.status_code == 404
    assert fake.calls == []
    assert EMAIL not in listing.text
    assert "CID_ada" not in listing.text


def test_load_report_direct_does_not_open_files(monkeypatch):
    """The in-process fetch path used by the route does not create a temp file."""

    def boom(*_args, **_kwargs):
        raise AssertionError("load_report opened a file")

    account = QualtricsAccount(
        id=AID,
        owner_user_id=1,
        name="UMN",
        data_center="yul1",
        verify_tls=True,
        default_directory="POOL_abc",
        library_id="GR_lib",
    )
    profile = SurveyProfile(
        id=PID,
        account_id=AID,
        name="EMA",
        survey_id="SV_1",
        mailing_list_id="CG_list",
        timezone="America/Chicago",
    )
    fake = FakeQualtrics(
        _zip([_response("R1", finished=1, status=0, RecipientID="CID_ada", endDate="2026-07-14T13:30:00Z")])
    )
    fake.add(_contact())
    monkeypatch.setattr(builtins, "open", boom)
    report = load_report(fake, account, profile, now=NOW, sleep=lambda _s: None)
    assert report.rows[0].displayName == "Ada Lovelace"
    assert SECRET_ANSWER not in report.model_dump_json()


def test_set_monitor_unit_does_not_seed_schedule_fields():
    fake = FakeQualtrics(b"")
    contact = _contact()
    # Missing SurveysScheduled must stay missing — seeding it would change eligibility inputs.
    contact["embeddedData"].pop("SurveysScheduled")
    fake.add(contact)
    account = QualtricsAccount(
        id=AID,
        owner_user_id=1,
        default_directory="POOL_abc",
        data_center="yul1",
    )
    profile = SurveyProfile(id=PID, account_id=AID, mailing_list_id="CG_list", survey_id="SV_1")
    updated = set_monitor_status(fake, account, profile, "CID_ada", "inactive")
    assert updated.monitor == "inactive"
    embedded = fake.contacts[0]["embeddedData"]
    assert embedded[MONITOR_FIELD] == "inactive"
    assert "SurveysScheduled" not in embedded
    assert all(call[0] != "delete" for call in fake.calls)


def test_huge_num_days_stays_bounded():
    report = aggregate(
        [_person(start_date="2020-01-01", num_days=10_000_000)],
        [],
        [],
        now=NOW,
        profile_timezone="America/Chicago",
    )
    assert len(report.rows[0].days) <= MAX_SPAN_DAYS + 14
    assert any("370" in item for item in report.limitations)
    assert any(day.date == "2026-07-15" for day in report.rows[0].days)


def test_sms_not_found_keeps_email_invitations():
    account = QualtricsAccount(
        id=AID,
        owner_user_id=1,
        name="UMN",
        data_center="yul1",
        verify_tls=True,
        default_directory="POOL_abc",
        library_id="GR_lib",
    )
    profile = SurveyProfile(
        id=PID,
        account_id=AID,
        name="EMA",
        survey_id="SV_1",
        mailing_list_id="CG_list",
        timezone="America/Chicago",
    )
    fake = FakeQualtrics(_zip([]))
    fake.add(_contact())
    fake.sms_error = QualtricsError(404, "NotFound", "sms collection missing")
    fake.distributions.append(
        {
            "id": "EMD_1",
            "sendDate": "2026-07-14T13:00:00Z",
            "surveyLink": {"expirationDate": "2026-07-14T14:00:00Z"},
            "recipients": {"contactId": "CGC_ada"},
        }
    )
    report = load_report(fake, account, profile, now=NOW, sleep=lambda _s: None)
    day = next(item for item in report.rows[0].days if item.date == "2026-07-14")
    assert day.expected == 1
    assert any("SMS invitations could not be listed" in item for item in report.limitations)


def test_sms_server_error_still_fails_the_report():
    account = QualtricsAccount(
        id=AID,
        owner_user_id=1,
        data_center="yul1",
        default_directory="POOL_abc",
    )
    profile = SurveyProfile(
        id=PID,
        account_id=AID,
        survey_id="SV_1",
        mailing_list_id="CG_list",
        timezone="America/Chicago",
    )
    fake = FakeQualtrics(_zip([]))
    fake.add(_contact())
    fake.sms_error = QualtricsError(500, "Api", "sms exploded")
    try:
        load_report(fake, account, profile, now=NOW, sleep=lambda _s: None)
    except QualtricsError as exc:
        assert exc.status == 500
    else:
        raise AssertionError("an SMS server error should fail the report")


class _RejectingExport:
    """Create-export double that applies one documented rejection at a time."""

    def __init__(self, reject):
        self.reject = reject
        self.posts: list[dict] = []

    def post(self, path: str, body: dict, timeout: float | None = None):
        self.posts.append(body)
        if path.endswith("export-responses") and self.reject(body):
            raise QualtricsError(400, "Api", "rejected")
        if path.endswith("export-responses"):
            return {"result": {"progressId": "PROG1"}}
        raise AssertionError(path)


def test_fallback_reaches_unfiltered_json_when_every_filter_is_rejected():
    """Production saw HTTP 400 because every previous body shared a rejected field."""

    def reject(body: dict) -> bool:
        if body.get("format") == "ndjson":
            return True
        if "embeddedDataIds" in body:
            return True
        if "surveyMetadataIds" in body:
            return True
        return body.get("questionIds") == []

    client = _RejectingExport(reject)
    progress, mode = _start_export(client, "SV_1")
    assert progress == "PROG1"
    assert mode == "full"
    assert client.posts[-1] == {"format": "json", "compress": True}
    assert len(client.posts) == 4
    assert all("rejected" not in json.dumps(body) for body in client.posts)


def test_filtered_json_is_used_when_only_guessed_embedded_ids_are_rejected():
    def reject(body: dict) -> bool:
        ids = body.get("embeddedDataIds") or []
        return any(name not in {"TimeZone"} for name in ids)

    client = _RejectingExport(reject)
    _, mode = _start_export(client, "SV_1")
    assert mode == "columns"
    assert "embeddedDataIds" not in client.posts[0]
    assert client.posts[0]["questionIds"] == []


def test_copy_survey_http_400_does_not_hide_the_profile_survey():
    account = QualtricsAccount(
        id=AID,
        owner_user_id=1,
        name="UMN",
        data_center="yul1",
        verify_tls=True,
        default_directory="POOL_abc",
        library_id="GR_lib",
    )
    profile = SurveyProfile(
        id=PID,
        account_id=AID,
        name="EMA",
        survey_id="SV_1",
        mailing_list_id="CG_list",
        timezone="America/Chicago",
        survey_copies=[{"id": "SV_copy", "name": "old"}],
    )
    fake = FakeQualtrics(
        _zip(
            [
                _response(
                    "R1",
                    finished=1,
                    status=0,
                    RecipientID="CID_ada",
                    endDate="2026-07-14T13:30:00Z",
                )
            ]
        )
    )
    fake.add(_contact())

    def post(path: str, body: dict, timeout: float | None = None):
        fake.calls.append(("post", path, body))
        if "SV_copy" in path:
            raise QualtricsError(400, "Api", "copy export rejected")
        if path.endswith("export-responses"):
            return {"result": {"progressId": "PROG1"}}
        raise AssertionError(path)

    fake.post = post
    report = load_report(fake, account, profile, now=NOW, sleep=lambda _s: None)
    assert report.rows[0].displayName == "Ada Lovelace"
    assert any("leftover survey copy" in item for item in report.limitations)
    assert "copy export rejected" not in report.model_dump_json()
    assert SECRET_ANSWER not in report.model_dump_json()


def test_progress_complete_is_required_before_a_file_id_is_used():
    pending = progress_view(
        {
            "result": {
                "status": "inProgress",
                "percentComplete": 100,
                "fileId": "FILE1",
                "error": {"message": EMAIL, "code": "not a code"},
            }
        }
    )
    assert pending == ("pending", None)
    ready = progress_view(
        {"result": {"status": "complete", "percentComplete": 100, "fileId": "FILE1"}}
    )
    assert ready == ("ready", "FILE1")
    try:
        progress_view(
            {
                "result": {
                    "status": "failed",
                    "error": {"code": "QE_9", "message": EMAIL, "context": {"column": "RecipientID"}},
                }
            }
        )
    except QualtricsError as exc:
        assert exc.message == "Qualtrics response export failed at poll (export status failed) [QE_9]."
        assert EMAIL not in exc.message
        assert "RecipientID" not in exc.message
    else:
        raise AssertionError("a failed export must surface the stage and the machine code")


def test_start_failure_keeps_stage_status_and_code_only():
    class _Start:
        def post(self, path: str, body: dict, timeout: float | None = None):
            raise QualtricsError(400, "Api", "invalid column RecipientID", code="RTE_2")

    try:
        _start_export(_Start(), "SV_1")
    except QualtricsError as exc:
        assert exc.message == "Qualtrics response export failed at start (HTTP 400) [RTE_2]."
        assert "RecipientID" not in exc.message
    else:
        raise AssertionError("create failure should be raised")


def test_in_progress_export_is_not_a_finished_file(ctx, monkeypatch):
    """An in-progress progress body is polled again. It is not downloaded."""
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics(
        _zip(
            [
                _response(
                    "R1",
                    finished=1,
                    status=0,
                    RecipientID="CID_ada",
                    endDate="2026-07-14T13:30:00Z",
                )
            ]
        )
    )
    fake.add(_contact())
    polls = {"n": 0}

    def get(path: str, timeout: float | None = None):
        fake.calls.append(("get", path))
        if "export-responses/" in path:
            polls["n"] += 1
            if polls["n"] == 1:
                return {
                    "result": {
                        "status": "inProgress",
                        "percentComplete": 5,
                        "error": {"message": EMAIL},
                    }
                }
            return {"result": {"status": "complete", "percentComplete": 100, "fileId": "FILE1"}}
        return FakeQualtrics.get(fake, path, timeout)

    fake.get = get
    _install(monkeypatch, fake)
    response = _follow(http)
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["displayName"] == "Ada Lovelace"
    assert polls["n"] >= 2
    assert EMAIL not in response.text
    assert "FILE1" not in response.text


def test_poll_budget_reports_timeout_without_the_progress_body():
    fake = FakeQualtrics(_zip([]))
    fake.add(_contact())

    def get(path: str, timeout: float | None = None):
        if "export-responses/" in path:
            return {"result": {"status": "inProgress", "error": {"message": EMAIL}}}
        return FakeQualtrics.get(fake, path, timeout)

    fake.get = get
    account = QualtricsAccount(
        id=AID,
        owner_user_id=1,
        name="UMN",
        data_center="yul1",
        verify_tls=True,
        default_directory="POOL_abc",
        library_id="GR_lib",
    )
    profile = SurveyProfile(
        id=PID,
        account_id=AID,
        name="EMA",
        survey_id="SV_1",
        mailing_list_id="CG_list",
        timezone="America/Chicago",
    )
    try:
        load_report(
            fake,
            account,
            profile,
            now=NOW,
            sleep=lambda _s: None,
            poll_limit_survey=1,
            poll_limit_total=4,
            clock=lambda: 0,
        )
    except QualtricsError as exc:
        assert exc.status == 504
        assert exc.message == "Qualtrics response export failed at poll (timeout)."
        assert EMAIL not in exc.message
    else:
        raise AssertionError("an export that stays in progress must time out")


def test_oversized_export_stops_at_download(monkeypatch):
    monkeypatch.setattr("app.acquisition.EXPORT_BYTE_LIMIT", 8)
    fake = FakeQualtrics(b"0123456789abcdef")
    fake.add(_contact())
    account = QualtricsAccount(
        id=AID,
        owner_user_id=1,
        data_center="yul1",
        default_directory="POOL_abc",
    )
    profile = SurveyProfile(
        id=PID,
        account_id=AID,
        survey_id="SV_1",
        mailing_list_id="CG_list",
        timezone="America/Chicago",
    )
    try:
        load_report(fake, account, profile, now=NOW, sleep=lambda _s: None)
    except QualtricsError as exc:
        assert exc.message == "Qualtrics response export failed at download (file too large)."
        assert "0123456789" not in exc.message
    else:
        raise AssertionError("an oversized file must not be parsed")


def test_client_extracts_error_code_without_putting_the_sentence_in_the_stage_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "meta": {
                    "httpStatus": "400 - Bad Request",
                    "error": {
                        "errorCode": "RTE_2",
                        "errorMessage": "invalid column RecipientID",
                    },
                }
            },
        )

    client = QualtricsClient("yul1", "token")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        client.post("surveys/SV_1/export-responses", {"format": "json"})
    except QualtricsError as exc:
        assert exc.status == 400
        assert exc.code == "RTE_2"
        shown = export_failure("start", status=exc.status, code=exc.code)
        assert shown.message == "Qualtrics response export failed at start (HTTP 400) [RTE_2]."
        assert "RecipientID" not in shown.message
    else:
        raise AssertionError("the create call should fail")
    finally:
        client.close()


def test_limited_download_drops_an_oversized_body_without_echoing_it():
    payload = b"SECRET-BYTES-ABCDEF"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    client = QualtricsClient("yul1", "token")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        client.get_bytes_limited("surveys/SV_1/export-responses/FILE/file", 4, 5)
    except QualtricsError as exc:
        assert exc.message == "Qualtrics response export failed at download (file too large)."
        assert b"SECRET" not in exc.message.encode()
    else:
        raise AssertionError("an oversized stream should not be returned")
    finally:
        client.close()


def test_export_failure_rejects_a_code_that_is_not_a_machine_token():
    err = export_failure("start", status=400, code="RecipientID missing")
    assert err.message == "Qualtrics response export failed at start (HTTP 400)."
    assert "RecipientID" not in err.message


def _account_profile():
    account = QualtricsAccount(
        id=AID,
        owner_user_id=1,
        name="UMN",
        data_center="yul1",
        verify_tls=True,
        default_directory="POOL_abc",
        library_id="GR_lib",
    )
    profile = SurveyProfile(
        id=PID,
        account_id=AID,
        name="EMA",
        survey_id="SV_1",
        mailing_list_id="CG_list",
        timezone="America/Chicago",
    )
    return account, profile


def test_older_attempt_cannot_replace_the_export_a_newer_attempt_owns():
    fake = FakeQualtrics(_zip([]))
    fake.add(_contact())
    posts = {"n": 0}

    def post(path: str, body: dict, timeout: float | None = None):
        posts["n"] += 1
        return {"result": {"progressId": f"PROG{posts['n']}"}}

    def get(path: str, timeout: float | None = None):
        if "export-responses/" in path:
            return {"result": {"status": "inProgress", "percentComplete": 1}}
        return FakeQualtrics.get(fake, path, timeout)

    fake.post = post
    fake.get = get
    account, profile = _account_profile()
    first = acquisition_step(fake, account, profile, user_id=1, attempt="attempt-a", now=NOW, clock=lambda: 0)
    assert isinstance(first, PendingExport)
    second = acquisition_step(fake, account, profile, user_id=1, attempt="attempt-b", now=NOW, clock=lambda: 0)
    assert isinstance(second, PendingExport)
    assert posts["n"] == 2
    try:
        acquisition_step(fake, account, profile, user_id=1, attempt="attempt-a", now=NOW, clock=lambda: 0)
    except QualtricsError as exc:
        assert exc.message == "Qualtrics response export failed at poll (superseded)."
        assert exc.status == 409
    else:
        raise AssertionError("the older attempt should stop")
    assert posts["n"] == 2
    continued = acquisition_step(
        fake, account, profile, user_id=1, attempt="attempt-b", now=NOW, clock=lambda: 0
    )
    assert isinstance(continued, PendingExport)
    assert posts["n"] == 2


def test_deadline_still_downloads_a_primary_file_that_is_already_ready():
    fake = FakeQualtrics(
        _zip(
            [
                _response(
                    "R1",
                    finished=1,
                    status=0,
                    RecipientID="CID_ada",
                    endDate="2026-07-14T13:30:00Z",
                )
            ]
        )
    )
    fake.add(_contact())
    account, profile = _account_profile()
    clock = {"t": 0, "slices": 0}

    def pause(_seconds: float) -> None:
        clock["slices"] += 1
        clock["t"] = EXPORT_DEADLINE_S + 1

    report = load_report(
        fake,
        account,
        profile,
        now=NOW,
        sleep=pause,
        clock=lambda: clock["t"],
        attempt="attempt-ready-file",
        user_id=1,
    )
    assert report.rows[0].displayName == "Ada Lovelace"
    assert any(call[0] == "get_bytes" for call in fake.calls)


def test_deadline_keeps_primary_counts_when_a_copy_is_still_running():
    fake = FakeQualtrics(
        _zip(
            [
                _response(
                    "R1",
                    finished=1,
                    status=0,
                    RecipientID="CID_ada",
                    endDate="2026-07-14T13:30:00Z",
                )
            ]
        )
    )
    fake.add(_contact())
    account, profile = _account_profile()
    profile.survey_copies = [{"id": "SV_copy", "name": "old"}]
    clock = {"t": 0, "got": False}

    def post(path: str, body: dict, timeout: float | None = None):
        return {"result": {"progressId": "PROG1"}}

    def get(path: str, timeout: float | None = None):
        if "SV_copy" in path and "export-responses/" in path:
            return {"result": {"status": "inProgress", "percentComplete": 1, "error": {"message": EMAIL}}}
        if "export-responses/" in path:
            return {"result": {"status": "complete", "percentComplete": 100, "fileId": "FILE1"}}
        return FakeQualtrics.get(fake, path, timeout)

    def get_bytes(path: str) -> bytearray:
        clock["got"] = True
        return bytearray(fake.export)

    fake.post = post
    fake.get = get
    fake.get_bytes = get_bytes

    def pause(_seconds: float) -> None:
        if clock["got"]:
            clock["t"] = EXPORT_DEADLINE_S + 1

    report = load_report(
        fake,
        account,
        profile,
        now=NOW,
        sleep=pause,
        clock=lambda: clock["t"],
        attempt="attempt-deadline",
        user_id=1,
    )
    assert report.rows[0].displayName == "Ada Lovelace"
    assert any("leftover survey copy" in item for item in report.limitations)
    assert EMAIL not in report.model_dump_json()


def test_status_text_is_a_fixed_phrase():
    from app.acquisition import status_text

    assert status_text("Loading contacts") == "Loading contacts"
    assert status_text("Exporting survey 2 of 3") == "Exporting survey 2 of 3"
    assert status_text("Waiting for export 1 of 1") == "Waiting for export 1 of 1"
    assert status_text("Downloading export 1 of 12") == "Downloading export 1 of 12"
    assert status_text("Counting completions") == "Counting completions"
    assert status_text("Exporting survey SV_1 of 3") is None
    assert status_text("Loading contacts for ada@example.com") is None
    assert status_text("Exporting survey 0 of 1") is None
    assert status_text("http://example.com") is None


def test_error_type_message_has_no_exception_text():
    exc = export_failure("start", error_type="TypeError")
    assert exc.status == 500
    assert exc.message == "Qualtrics response export failed at start (TypeError)."
    noisy = export_failure(
        "poll",
        error_type="Client.send() got an unexpected keyword argument 'timeout'",
    )
    assert "keyword" not in noisy.message
    assert noisy.message == "Qualtrics response export failed at poll."


def test_unexpected_export_error_is_stage_and_type(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics(_zip([]))
    fake.add(_contact())

    def post(path: str, body: dict, timeout: float | None = None):
        raise TypeError("Client.send() got an unexpected keyword argument 'timeout'")

    fake.post = post
    _install(monkeypatch, fake)
    response = _follow(http)
    assert response.status_code == 500, response.text
    message = response.json()["detail"]["message"]
    assert message == "Qualtrics response export failed at start (TypeError)."
    assert "Client.send" not in response.text
    assert "keyword" not in response.text
    assert EMAIL not in response.text
    assert "SV_" not in response.text


def test_acquisition_get_returns_before_qualtrics_answers(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics(
        _zip(
            [
                _response(
                    "R1",
                    finished=1,
                    status=0,
                    RecipientID="CID_ada",
                    endDate="2026-07-14T13:30:00Z",
                )
            ]
        )
    )
    fake.add(_contact())
    release = threading.Event()
    entered = threading.Event()

    def get_elements(path: str, timeout: float | None = None):
        if "contacts" in path:
            entered.set()
            assert release.wait(5)
        return FakeQualtrics.get_elements(fake, path, timeout)

    fake.get_elements = get_elements
    monkeypatch.setattr("app.routers.acquisition.qualtrics_for", lambda _account: fake)
    monkeypatch.setattr("app.acquisition.time.sleep", lambda _seconds: None)
    headers = {"X-Qualsched-Attempt": "attempt-background"}
    box: dict = {}

    def request():
        box["response"] = http.get(BASE, headers=headers)

    caller = threading.Thread(target=request)
    caller.start()
    try:
        assert entered.wait(2), "worker did not start listing contacts"
        caller.join(1)
        assert not caller.is_alive(), "acquisition GET blocked on the contact list"
        first = box["response"]
        assert first.status_code == 202, first.text
        body = first.json()
        assert body["pending"] is True
        assert body["status"] in {"Connecting to Qualtrics", "Loading contacts"}
        assert EMAIL not in first.text
        assert "CID_" not in first.text
        assert "SV_" not in first.text
        assert not any(call[0] == "get_bytes" for call in fake.calls)
    finally:
        release.set()
        caller.join(5)
    done = None
    for _ in range(50):
        done = http.get(BASE, headers=headers)
        if done.status_code != 202:
            break
        time.sleep(0.02)
    assert done is not None
    assert done.status_code == 200, done.text
    assert done.json()["rows"][0]["displayName"] == "Ada Lovelace"
    assert EMAIL not in done.text


def test_cancelled_listing_does_not_ask_for_invitations_or_an_export():
    fake = FakeQualtrics(_zip([]))
    fake.add(_contact())
    seen: list[str] = []
    stop = {"now": False}

    def get_elements(path: str, timeout: float | None = None):
        seen.append(path)
        if "contacts" in path:
            stop["now"] = True
        return FakeQualtrics.get_elements(fake, path, timeout)

    fake.get_elements = get_elements
    account, profile = _account_profile()
    try:
        load_report(
            fake,
            account,
            profile,
            now=NOW,
            sleep=lambda _seconds: None,
            stop=lambda: stop["now"],
        )
    except QualtricsError as exc:
        assert exc.message == "Qualtrics response export failed at poll (superseded)."
    else:
        raise AssertionError("a cancelled listing must stop")
    assert any("contacts" in path for path in seen)
    assert not any(path.startswith("distributions") for path in seen)
    assert not any(call[0] == "post" for call in fake.calls)
