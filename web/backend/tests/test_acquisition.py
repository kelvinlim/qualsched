"""Acquisition heatmap: completed responses, exact id matching, no PHI retention."""

import builtins
import io
import json
import zipfile
from datetime import UTC, datetime

from app.acquisition import (
    DENOMINATOR_NOTE,
    MAX_SPAN_DAYS,
    MONITOR_FIELD,
    PREREQUISITE,
    AcquisitionParseError,
    Invitation,
    Participant,
    aggregate,
    export_request_bodies,
    extract_response,
    load_report,
    parse_export_bytes,
    set_monitor_status,
)
from app.distributions import parse_send_date
from app.eligibility import EligibilityDefaults, contact_eligibility
from app.main import app
from app.models import QualtricsAccount, SurveyProfile, User
from app.qualtrics import QualtricsError
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


def test_export_request_omits_identity_and_answers():
    bodies = export_request_bodies()
    assert [mode for mode, _ in bodies] == ["restricted", "embedded", "metadata"]
    first = json.dumps(bodies[0][1])
    assert "recipientEmail" not in first
    assert "recipientFirstName" not in first
    assert "ipAddress" not in first
    assert "locationLatitude" not in first
    assert "externalDataReference" not in first
    assert bodies[0][1]["questionIds"] == []
    assert bodies[0][1]["exportResponsesInProgress"] is False
    assert "RecipientID" in bodies[0][1]["embeddedDataIds"]
    for _, body in bodies:
        dumped = json.dumps(body)
        assert "recipientEmail" not in dumped
        assert "ipAddress" not in dumped


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

    def get_elements(self, path: str):
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

    def get(self, path: str):
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

    def post(self, path: str, body: dict):
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
    response = http.get(BASE)
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    text = response.text
    assert SECRET_ANSWER not in text
    assert EMAIL not in text
    assert PHONE not in text
    assert "203.0.113.9" not in text
    assert body["rows"][0]["displayName"] == "Ada Lovelace"
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
    response = http.get(BASE)
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

    again = http.get(BASE)
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
