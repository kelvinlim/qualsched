"""Acquisition heatmap: distribution stats counting, mailing-list filtering, no PHI retention."""

import builtins
import threading
import time
from datetime import UTC, datetime

import httpx
import pytest

from app.acquisition import (
    DENOMINATOR_NOTE,
    MAX_SPAN_DAYS,
    MONITOR_FIELD,
    PREREQUISITE,
    Invitation,
    Participant,
    aggregate,
    export_failure,
    export_request_bodies,
    load_report,
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
        "ext_ref": "P1",
        "timezone_name": "America/Chicago",
        "start_date": "2026-07-13",
        "num_days": 5,
        "monitor": "active",
        "surveys_scheduled": 0,
    }
    base.update(overrides)
    return Participant(**base)


def _invite(
    dist: str,
    send: str,
    expire: str | None = None,
    lookup: str = "CGC_ada",
    *,
    method: str = "sms",
    sent: int = 1,
    started: int = 0,
    finished: int = 0,
    failed: int = 0,
    has_stats: bool = True,
) -> Invitation:
    return Invitation(
        distribution_id=dist,
        lookup_id=lookup,
        send=parse_send_date(send),
        expire=parse_send_date(expire) if expire else None,
        method=method,  # type: ignore[arg-type]
        sent=sent,
        started=started,
        finished=finished,
        failed=failed,
        has_stats=has_stats,
    )


def _report(invites: list[Invitation], **person):
    return aggregate(
        [_person(**person)],
        invites,
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


def test_counts_finished_and_classifies_prompt_statuses():
    invites = [
        _invite("D1", "2026-07-13T13:00:00Z", finished=1, started=1, sent=1, method="sms"),
        _invite("D2", "2026-07-13T15:00:00Z", finished=0, started=1, sent=1, method="email"),
        _invite("D3", "2026-07-13T17:00:00Z", finished=0, started=0, sent=1, method="sms"),
        _invite("D4", "2026-07-13T19:00:00Z", finished=0, started=0, sent=0, failed=1, method="sms"),
        _invite("D5", "2026-07-15T23:00:00Z", finished=0, started=0, sent=0, method="sms"),
    ]
    report = _report(invites)
    assert report.exportMode == "distribution-stats"
    assert report.definitive is True
    assert PREREQUISITE in report.prerequisite

    day13 = _day(report, "2026-07-13")
    assert day13.kind == "ratio"
    assert day13.completed == 1
    assert day13.expected == 4
    assert day13.later == 0
    assert [(p.sendLocal, p.method, p.status) for p in day13.prompts] == [
        ("08:00", "sms", "finished"),
        ("10:00", "email", "started"),
        ("12:00", "sms", "sent"),
        ("14:00", "sms", "failed"),
    ]

    day15 = _day(report, "2026-07-15")
    assert day15.kind == "future"
    assert day15.later == 1
    assert [(p.sendLocal, p.status) for p in day15.prompts] == [("18:00", "scheduled")]

    assert report.rows[0].toDate.completed == 1
    assert report.rows[0].toDate.expected == 4
    assert report.rows[0].toDate.provisional is False


def test_missing_stats_marks_day_unknown_and_provisional():
    invites = [
        _invite("D1", "2026-07-13T13:00:00Z", finished=1, sent=1, has_stats=True),
        _invite("D2", "2026-07-14T13:00:00Z", has_stats=False),
    ]
    report = _report(invites)
    assert _day(report, "2026-07-13").kind == "ratio"
    day14 = _day(report, "2026-07-14")
    assert day14.kind == "unknown"
    assert day14.prompts[0].status == "unknown"
    assert report.rows[0].definitive is False
    assert report.rows[0].toDate.provisional is True
    assert any("did not include completion stats" in note for note in report.limitations)


def test_zero_future_none_and_non_study_are_distinct():
    invites = [_invite("D", "2026-07-14T13:00:00Z", "2026-07-14T14:00:00Z")]
    report = _report(invites)
    assert _day(report, "2026-07-14").kind == "ratio"
    assert _day(report, "2026-07-14").completed == 0
    assert _day(report, "2026-07-14").expected == 1
    assert _day(report, "2026-07-17").kind == "none"
    assert _day(report, "2026-07-12").kind == "nonStudy"
    future = _report([_invite("Later", "2026-07-16T13:00:00Z")])
    assert _day(future, "2026-07-16").kind == "future"
    # An invitation outside the study window is still real.
    outside = _report([_invite("Early", "2026-07-12T15:00:00Z", "2026-07-12T16:00:00Z")])
    assert _day(outside, "2026-07-12").kind == "ratio"
    assert _day(outside, "2026-07-12").expected == 1


def test_current_day_denominator_ignores_prompts_not_yet_due():
    report = _report(
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

    # Early finish before scheduled send time still counts as due & completed.
    early_done = _report(
        [
            _invite("Due", "2026-07-15T15:00:00Z", finished=0),
            _invite("EarlyDone", "2026-07-15T23:00:00Z", finished=1),
        ]
    )
    day_early = _day(early_done, "2026-07-15")
    assert day_early.completed == 1
    assert day_early.expected == 2
    assert day_early.later == 0


def test_changed_send_time_is_not_redrawn_from_time_slots():
    # 15:17 UTC is 10:17 in Chicago, not one of the profile's 800/1200 slots.
    report = _report([_invite("Odd", "2026-07-14T15:17:00Z", "2026-07-14T16:17:00Z")])
    day = _day(report, "2026-07-14")
    assert day.expected == 1
    assert day.kind == "ratio"
    assert day.prompts[0].sendLocal == "10:17"


def test_dst_boundaries_use_the_participant_zone():
    spring = aggregate(
        [_person(start_date="", num_days=0)],
        [
            _invite("Before", "2026-03-08T04:30:00Z"),
            _invite("After", "2026-03-08T07:30:00Z"),
        ],
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
        now=datetime(2026, 11, 1, 18, 0, tzinfo=UTC),
        profile_timezone="America/Chicago",
    )
    assert _day(fall, "2026-10-31").expected == 1
    assert _day(fall, "2026-11-01").expected == 1


def test_unknown_timezone_and_missing_lookup_do_not_invent_counts():
    bad_zone = _report([_invite("D", "2026-07-14T13:00:00Z")], timezone_name="Mars/Olympus")
    assert bad_zone.rows[0].timezoneSource == "invalid"
    assert all(day.kind == "unknown" for day in bad_zone.rows[0].days)
    assert bad_zone.rows[0].toDate.expected is None
    assert bad_zone.rows[0].definitive is False

    missing_lookup = aggregate(
        [_person(lookup_id="")],
        [_invite("D", "2026-07-14T13:00:00Z", lookup="CGC_other")],
        now=NOW,
        profile_timezone="America/Chicago",
    )
    assert missing_lookup.excluded.unjoinedInvitations == 1
    assert all(day.kind == "unknown" for day in missing_lookup.rows[0].days)
    assert missing_lookup.rows[0].toDate.expected is None

    profile_zone = _report([], timezone_name="")
    assert profile_zone.rows[0].timezoneSource == "profile"
    assert profile_zone.rows[0].timezone == "America/Chicago"


def test_removed_contact_invitations_do_not_taint_active_rows():
    report = aggregate(
        [_person()],
        [
            _invite("D1", "2026-07-14T13:00:00Z", lookup="CGC_ada", finished=1),
            _invite("D_removed", "2026-07-14T13:00:00Z", lookup="CGC_gone", finished=0),
        ],
        now=NOW,
        profile_timezone="America/Chicago",
    )
    assert report.rows[0].definitive is True
    assert report.definitive is True
    assert report.excluded.unjoinedInvitations == 1
    assert any("no longer on the list" in note for note in report.limitations)


def test_listed_empty_schedule_is_not_redrawn_when_surveys_scheduled_is_set():
    report = _report([], surveys_scheduled=4)
    assert _day(report, "2026-07-14").kind == "none"
    assert report.rows[0].toDate.expected == 0
    assert any("SurveysScheduled" in item for item in report.limitations)
    assert DENOMINATOR_NOTE in report.limitations


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
    def __init__(self):
        self.contacts: list[dict] = []
        self.distributions: list[dict] = []
        self.sms_distributions: list[dict] = []
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
            if path.startswith("distributions/sms"):
                if self.sms_error is not None:
                    raise self.sms_error
                return list(self.sms_distributions)
            return list(self.distributions)
        return list(self.contacts)

    def get(self, path: str, timeout: float | None = None):
        self.calls.append(("get", path))
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
        raise AssertionError(f"acquisition must not POST {path}")

    def get_bytes(self, path: str) -> bytearray:
        self.calls.append(("get_bytes", path))
        raise AssertionError(f"acquisition must not download {path}")

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

    monkeypatch.setattr("app.routers.acquisition._start_worker", inline)


def _follow(http, headers: dict | None = None):
    """Walk the short slices the way the browser does."""
    sent = {"X-Qualsched-Attempt": "attempt-follow"}
    if headers:
        sent.update(headers)
    response = None
    for _ in range(8):
        response = http.get(BASE, headers=sent)
        if response.status_code != 202:
            return response
    raise AssertionError(getattr(response, "text", "acquisition did not finish"))


def test_http_report_counts_distribution_stats_and_filters_other_mailing_lists(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics()
    fake.add(_contact())
    fake.sms_distributions.extend(
        [
            {
                "id": "SMS_1",
                "sendDate": "2026-07-14T13:00:00Z",
                "surveyLinkExpirationDate": "2026-07-14T14:00:00Z",
                "recipients": {"contactId": "CGC_ada", "mailingListId": "CG_list"},
                "stats": {"sent": 1, "started": 1, "finished": 1, "failed": 0},
            },
            {
                "id": "SMS_2",
                "sendDate": "2026-07-14T17:00:00Z",
                "surveyLinkExpirationDate": "2026-07-14T18:00:00Z",
                "recipients": {"contactId": "CGC_ada", "mailingListId": "CG_list"},
                "stats": {"sent": 1, "started": 1, "finished": 0, "failed": 0},
            },
            # Different mailing list sharing the same survey — must be ignored cleanly.
            {
                "id": "SMS_other_ml",
                "sendDate": "2026-07-14T13:00:00Z",
                "recipients": {"contactId": "CGC_stranger", "mailingListId": "CG_other_study"},
                "stats": {"sent": 1, "started": 0, "finished": 1, "failed": 0},
            },
        ]
    )
    fake.distributions.append(
        {
            "id": "EMD_1",
            "sendDate": "2026-07-13T13:00:00Z",
            "surveyLink": {"expirationDate": "2026-07-13T14:00:00Z"},
            "recipients": {"contactId": "CGC_ada", "mailingListId": "CG_list"},
            "stats": {"sent": 1, "started": 1, "finished": 1, "failed": 0},
        }
    )
    _install(monkeypatch, fake)
    response = _follow(http)
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    text = response.text
    assert EMAIL not in text
    assert PHONE not in text
    assert body["exportMode"] == "distribution-stats"
    assert body["definitive"] is True
    assert body["excluded"]["unjoinedInvitations"] == 0
    assert body["rows"][0]["displayName"] == "Ada Lovelace"
    assert body["rows"][0]["extRef"] == "P1"
    assert body["rows"][0]["monitor"] == "active"

    day13 = next(item for item in body["rows"][0]["days"] if item["date"] == "2026-07-13")
    assert day13["completed"] == 1
    assert day13["expected"] == 1
    assert day13["prompts"] == [{"sendLocal": "08:00", "method": "email", "status": "finished"}]

    day14 = next(item for item in body["rows"][0]["days"] if item["date"] == "2026-07-14")
    assert day14["completed"] == 1
    assert day14["expected"] == 2
    assert day14["prompts"] == [
        {"sendLocal": "08:00", "method": "sms", "status": "finished"},
        {"sendLocal": "12:00", "method": "sms", "status": "started"},
    ]
    assert all(call[0] not in {"post", "get_bytes", "delete"} for call in fake.calls)


def test_status_roundtrip_keeps_eligibility_and_does_not_cancel(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics()
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
    assert not isinstance(
        contact_eligibility(
            {k: str(v) for k, v in fake.contacts[0]["embeddedData"].items()},
            defaults,
        ),
        str,
    )

    again = _follow(http)
    assert again.status_code == 200
    row = again.json()["rows"][0]
    assert row["monitor"] == "inactive"
    assert row["contactId"] == "CID_ada"
    assert len(again.json()["rows"]) == 1


def test_monitor_status_rejects_unknown_values(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics()
    fake.add(_contact())
    _install(monkeypatch, fake)
    response = http.put(BASE + "/status", json={"contactId": "CID_ada", "status": "deleted"})
    assert response.status_code == 400
    assert all(call[0] != "put" for call in fake.calls)
    assert all(call[0] != "delete" for call in fake.calls)


def test_acquisition_requires_login(anon):
    response = anon.get(BASE)
    assert response.status_code == 401


def test_other_researcher_cannot_read_or_mark_status(ctx, monkeypatch):
    http, Session, _uid = ctx
    _ready_account(http)
    fake = FakeQualtrics()
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
    """The in-process fetch path does not create a temp file or download exports."""

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
    fake = FakeQualtrics()
    fake.add(_contact())
    fake.sms_distributions.append(
        {
            "id": "SMS_1",
            "sendDate": "2026-07-14T13:00:00Z",
            "recipients": {"contactId": "CGC_ada", "mailingListId": "CG_list"},
            "stats": {"sent": 1, "started": 1, "finished": 1, "failed": 0},
        }
    )
    monkeypatch.setattr(builtins, "open", boom)
    report = load_report(fake, account, profile, now=NOW, sleep=lambda _s: None)
    assert report.rows[0].displayName == "Ada Lovelace"
    day14 = next(item for item in report.rows[0].days if item.date == "2026-07-14")
    assert day14.completed == 1
    assert day14.expected == 1


def test_set_monitor_unit_does_not_seed_schedule_fields():
    fake = FakeQualtrics()
    contact = _contact()
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
    fake = FakeQualtrics()
    fake.add(_contact())
    fake.sms_error = QualtricsError(404, "NotFound", "sms collection missing")
    fake.distributions.append(
        {
            "id": "EMD_1",
            "sendDate": "2026-07-14T13:00:00Z",
            "surveyLink": {"expirationDate": "2026-07-14T14:00:00Z"},
            "recipients": {"contactId": "CGC_ada", "mailingListId": "CG_list"},
            "stats": {"sent": 1, "started": 1, "finished": 1, "failed": 0},
        }
    )
    report = load_report(fake, account, profile, now=NOW, sleep=lambda _s: None)
    day = next(item for item in report.rows[0].days if item.date == "2026-07-14")
    assert day.completed == 1
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
    fake = FakeQualtrics()
    fake.add(_contact())
    fake.sms_error = QualtricsError(500, "Api", "sms exploded")
    try:
        load_report(fake, account, profile, now=NOW, sleep=lambda _s: None)
    except QualtricsError as exc:
        assert exc.status == 500
    else:
        raise AssertionError("an SMS server error should fail the report")


def test_status_text_is_a_fixed_phrase():
    from app.acquisition import status_text

    assert status_text("Loading contacts") == "Loading contacts"
    assert status_text("Counting completions") == "Counting completions"
    assert status_text("Loading contacts for ada@example.com") is None
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


def test_export_helpers_remain_safe():
    bodies = export_request_bodies()
    assert bodies[0][0] == "columns"
    assert progress_view({"result": {"status": "complete", "fileId": "F1"}}) == ("ready", "F1")


def test_unexpected_error_is_stage_and_type(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics()
    fake.add(_contact())

    def get_elements(_path: str, timeout: float | None = None):
        raise TypeError("Client.send() got an unexpected keyword argument 'timeout'")

    fake.get_elements = get_elements
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
    fake = FakeQualtrics()
    fake.add(_contact())
    fake.sms_distributions.append(
        {
            "id": "SMS_1",
            "sendDate": "2026-07-14T13:00:00Z",
            "recipients": {"contactId": "CGC_ada", "mailingListId": "CG_list"},
            "stats": {"sent": 1, "started": 1, "finished": 1, "failed": 0},
        }
    )
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


def test_cancelled_listing_does_not_ask_for_invitations():
    fake = FakeQualtrics()
    fake.add(_contact())
    seen: list[str] = []
    stop = {"now": False}

    def get_elements(path: str, timeout: float | None = None):
        seen.append(path)
        if "contacts" in path:
            stop["now"] = True
        return FakeQualtrics.get_elements(fake, path, timeout)

    fake.get_elements = get_elements
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
