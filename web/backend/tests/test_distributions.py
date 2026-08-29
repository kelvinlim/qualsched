"""Distributions proxy Qualtrics. No live API, no real tokens, no distributions table."""

from datetime import datetime, timezone
from urllib.parse import parse_qs

from app.distributions import local_send_time, survey_rotation
from app.models import SurveyProfile
from app.qualtrics import QualtricsError
from tests.test_accounts import ACCOUNT, PROJECT, SECRET
from tests.test_contacts import FakeQualtrics, _eligible_raw, _ready_account

AID = ACCOUNT["id"]
PID = PROJECT["id"]
BASE = f"/api/accounts/{AID}/projects/{PID}/distributions"
CONTACTS = f"/api/accounts/{AID}/projects/{PID}/contacts"

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
FUTURE = "2026-07-29T13:30:00Z"
PAST = "2026-01-15T13:30:00Z"


def _query(path: str, key: str) -> str:
    _, _, query = path.partition("?")
    return (parse_qs(query).get(key) or [""])[0]


class DistFake(FakeQualtrics):
    """Contacts fake plus Qualtrics distribution list/delete."""

    def __init__(self):
        super().__init__()
        self.distributions: list[dict] = []
        self.missing_surveys: set[str] = set()
        self.fail_delete_ids: set[str] = set()

    def add_distribution(
        self,
        *,
        ident: str,
        method: str,
        survey_id: str,
        contact_lookup_id: str,
        send_date: str,
    ) -> None:
        self.distributions.append(
            {
                "id": ident,
                "method": method,
                "surveyId": survey_id,
                "sendDate": send_date,
                "recipients": {"contactId": contact_lookup_id},
            }
        )

    def get_elements(self, path: str):
        self.calls.append(("get_elements", path))
        if path.startswith("directories/"):
            return [self.contacts[i] for i in self.order if i in self.contacts]
        survey_id = _query(path, "surveyId")
        if survey_id in self.missing_surveys:
            raise QualtricsError(404, "NotFound", f"survey {survey_id} missing")
        method = "sms" if path.startswith("distributions/sms") else "email"
        return [
            {
                "id": row["id"],
                "sendDate": row["sendDate"],
                "recipients": row["recipients"],
            }
            for row in self.distributions
            if row["method"] == method and row["surveyId"] == survey_id
        ]

    def delete(self, path: str):
        self.calls.append(("delete", path))
        if path.startswith("distributions"):
            ident = path.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            if ident in self.fail_delete_ids:
                raise QualtricsError(500, "Api", f"could not cancel {ident}")
            before = len(self.distributions)
            self.distributions = [row for row in self.distributions if row["id"] != ident]
            if len(self.distributions) == before:
                raise QualtricsError(404, "NotFound", f"distribution {ident} missing")
            return {"result": {}}
        return super().delete(path)


def _install(monkeypatch, fake: DistFake):
    monkeypatch.setattr("app.routers.distributions.qualtrics_for", lambda _account: fake)
    monkeypatch.setattr("app.routers.contacts.qualtrics_for", lambda _account: fake)
    monkeypatch.setattr("app.contacts.WRITE_PACING_SECONDS", 0)
    monkeypatch.setattr("app.distributions.utcnow", lambda: NOW)


def test_list_maps_rows_and_filters_method(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = DistFake()
    fake.add(_eligible_raw())
    unknown = _eligible_raw("CID_pat", firstName="Pat", lastName="Lee", email="pat@example.com")
    unknown["contactLookupId"] = "CGC_other"
    fake.add(unknown)
    fake.add_distribution(
        ident="EMD_sms_future",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    fake.add_distribution(
        ident="EMD_sms_past",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=PAST,
    )
    fake.add_distribution(
        ident="EMD_email",
        method="email",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    fake.add_distribution(
        ident="EMD_orphan",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_gone",
        send_date=FUTURE,
    )
    _install(monkeypatch, fake)

    r = http.get(f"{BASE}?method=sms")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [row["id"] for row in rows] == ["EMD_sms_past", "EMD_sms_future", "EMD_orphan"]
    ada = rows[1]
    assert ada["contactLookupId"] == "CGC_secret"
    assert ada["contactName"] == "Ada Lovelace"
    assert ada["contactPhone"] == "16125551234"
    assert ada["contactEmail"] == "ada@example.com"
    assert ada["sendDate"] == FUTURE
    assert ada["sendLocal"] == "2026-07-29 08:30 CDT"
    assert ada["method"] == "sms"
    assert ada["unsent"] is True
    assert ada["surveyId"] == "SV_1"
    assert ada["surveyLabel"] == "original"
    assert rows[0]["unsent"] is False
    assert rows[0]["sendLocal"] == "2026-01-15 07:30 CST"
    orphan = rows[2]
    assert orphan["contactName"] == ""
    assert orphan["contactPhone"] == ""
    assert orphan["contactEmail"] == ""
    assert orphan["sendLocal"] == ""
    assert SECRET not in r.text
    assert "token" not in r.text.lower()

    sms_paths = [c[1] for c in fake.calls if c[0] == "get_elements" and "distributions" in c[1]]
    assert any(p.startswith("distributions/sms?surveyId=SV_1") for p in sms_paths)

    email = http.get(f"{BASE}?method=email")
    assert email.status_code == 200, email.text
    email_rows = email.json()
    assert [row["id"] for row in email_rows] == ["EMD_email"]
    assert email_rows[0]["method"] == "email"
    email_paths = [c[1] for c in fake.calls if c[0] == "get_elements" and c[1].startswith("distributions?")]
    assert any("mailingListId=CG_list" in p for p in email_paths)
    assert any("distributionRequestType=Invite" in p for p in email_paths)


def test_list_includes_survey_copies_and_skips_missing_clones(ctx, monkeypatch):
    http, _, _ = ctx
    project = {
        **PROJECT,
        "surveyCopies": [
            {"id": "SV_c1", "name": "EMA-c1"},
            {"id": "SV_gone", "name": "EMA-c2"},
        ],
        "copiesSourceSurveyId": "SV_1",
    }
    assert http.post("/api/accounts", json=ACCOUNT).status_code == 200
    assert http.post(f"/api/accounts/{AID}/projects", json=project).status_code == 200
    assert http.put(f"/api/accounts/{AID}/token", json={"token": SECRET}).status_code == 200

    fake = DistFake()
    fake.add(_eligible_raw())
    fake.missing_surveys.add("SV_gone")
    fake.add_distribution(
        ident="EMD_orig",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    fake.add_distribution(
        ident="EMD_copy",
        method="sms",
        survey_id="SV_c1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    _install(monkeypatch, fake)

    r = http.get(f"{BASE}?method=sms")
    assert r.status_code == 200, r.text
    rows = {row["id"]: row for row in r.json()}
    assert set(rows) == {"EMD_orig", "EMD_copy"}
    assert rows["EMD_orig"]["surveyLabel"] == "original"
    assert rows["EMD_copy"]["surveyId"] == "SV_c1"
    assert rows["EMD_copy"]["surveyLabel"] == "c1"


def test_list_404_on_missing_profile_survey(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = DistFake()
    fake.missing_surveys.add("SV_1")
    _install(monkeypatch, fake)
    r = http.get(f"{BASE}?method=sms")
    assert r.status_code == 404
    assert r.json()["detail"]["kind"] == "NotFound"


def test_400_when_token_missing(ctx):
    http, _, _ = ctx
    _ready_account(http, token=False)
    r = http.get(f"{BASE}?method=sms")
    assert r.status_code == 400
    assert "token" in r.json()["detail"]["message"].lower()


def test_400_when_directory_missing(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http, directory=False)
    _install(monkeypatch, DistFake())
    r = http.get(f"{BASE}?method=sms")
    assert r.status_code == 400
    assert "directory" in r.json()["detail"]["message"].lower()


def test_400_when_mailing_list_missing(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http, mailing_list=False)
    _install(monkeypatch, DistFake())
    r = http.get(f"{BASE}?method=sms")
    assert r.status_code == 400
    assert "mailing list" in r.json()["detail"]["message"].lower()


def test_400_when_survey_missing(ctx, monkeypatch):
    http, _, _ = ctx
    account = {**ACCOUNT}
    project = {**PROJECT, "surveyId": ""}
    assert http.post("/api/accounts", json=account).status_code == 200
    assert http.post(f"/api/accounts/{AID}/projects", json=project).status_code == 200
    assert http.put(f"/api/accounts/{AID}/token", json={"token": SECRET}).status_code == 200
    _install(monkeypatch, DistFake())
    r = http.get(f"{BASE}?method=sms")
    assert r.status_code == 400, r.text
    assert "survey" in r.json()["detail"]["message"].lower()


def test_delete_selected_partial_failure(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = DistFake()
    fake.add(_eligible_raw())
    fake.add_distribution(
        ident="EMD_ok",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    fake.add_distribution(
        ident="EMD_fail",
        method="sms",
        survey_id="SV_c1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    fake.fail_delete_ids.add("EMD_fail")
    _install(monkeypatch, fake)

    r = http.request(
        "DELETE",
        BASE,
        json={
            "method": "sms",
            "targets": [
                {"id": "EMD_ok", "surveyId": "SV_1"},
                {"id": "EMD_fail", "surveyId": "SV_c1"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["deleted"] == 1
    assert report["failed"] == [{"id": "EMD_fail", "error": "could not cancel EMD_fail"}]
    deletes = [c[1] for c in fake.calls if c[0] == "delete"]
    assert "distributions/sms/EMD_ok?surveyId=SV_1" in deletes
    assert "distributions/sms/EMD_fail?surveyId=SV_c1" in deletes
    assert [row["id"] for row in fake.distributions] == ["EMD_fail"]
    assert SECRET not in r.text


def test_delete_email_uses_email_path(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = DistFake()
    fake.add_distribution(
        ident="EMD_mail",
        method="email",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    _install(monkeypatch, fake)
    r = http.request(
        "DELETE",
        BASE,
        json={"method": "email", "targets": [{"id": "EMD_mail", "surveyId": "SV_1"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1
    assert ("delete", "distributions/EMD_mail") in fake.calls


def test_delete_unsent_for_contact(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = DistFake()
    ada = _eligible_raw()
    ada["embeddedData"]["SurveysScheduled"] = "4"
    ada["embeddedData"]["DeleteUnsent"] = "1"
    fake.add(ada)
    pat = _eligible_raw("CID_pat", firstName="Pat", lastName="Lee")
    pat["contactLookupId"] = "CGC_other"
    fake.add(pat)
    fake.add_distribution(
        ident="EMD_ada_future",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    fake.add_distribution(
        ident="EMD_ada_past",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=PAST,
    )
    fake.add_distribution(
        ident="EMD_pat",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_other",
        send_date=FUTURE,
    )
    _install(monkeypatch, fake)

    r = http.delete(f"{BASE}/unsent/CID_ada")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 1, "failed": []}
    remaining = {row["id"] for row in fake.distributions}
    assert remaining == {"EMD_ada_past", "EMD_pat"}
    put = next(c for c in fake.calls if c[0] == "put")
    assert put[2]["embeddedData"]["DeleteUnsent"] == "0"
    assert put[2]["embeddedData"]["SurveysScheduled"] == "0"
    assert '"action":"delete_unsent"' in put[2]["embeddedData"]["LogData"].replace(" ", "")
    assert "CID_ada" in fake.contacts


def test_contact_delete_cancels_unsent_first(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = DistFake()
    fake.add(_eligible_raw())
    fake.add_distribution(
        ident="EMD_1",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    fake.add_distribution(
        ident="EMD_2",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    _install(monkeypatch, fake)

    r = http.delete(f"{CONTACTS}/CID_ada")
    assert r.status_code == 200, r.text
    assert r.json()["contactName"] == "Ada Lovelace"
    assert r.json()["cancelled"] == 2
    assert fake.distributions == []
    assert "CID_ada" not in fake.contacts
    deletes = [c[1] for c in fake.calls if c[0] == "delete"]
    assert deletes.index("distributions/sms/EMD_1?surveyId=SV_1") < deletes.index(
        "directories/POOL_abc/mailinglists/CG_list/contacts/CID_ada"
    )


def test_contact_delete_aborts_if_cancel_fails(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = DistFake()
    fake.add(_eligible_raw())
    fake.add_distribution(
        ident="EMD_stuck",
        method="sms",
        survey_id="SV_1",
        contact_lookup_id="CGC_secret",
        send_date=FUTURE,
    )
    fake.fail_delete_ids.add("EMD_stuck")
    _install(monkeypatch, fake)

    r = http.delete(f"{CONTACTS}/CID_ada")
    assert r.status_code == 502, r.text
    assert "could not be cancelled" in r.json()["detail"]["message"]
    assert "CID_ada" in fake.contacts
    assert fake.distributions[0]["id"] == "EMD_stuck"


def test_local_send_time_matches_desktop():
    assert local_send_time("2026-07-29T13:30:00Z", "America/Chicago") == "2026-07-29 08:30 CDT"
    assert local_send_time("2026-01-15T13:30:00Z", "America/Chicago") == "2026-01-15 07:30 CST"
    assert local_send_time("2026-07-29T23:30:00Z", "Asia/Tokyo") == "2026-07-30 08:30 JST"
    assert local_send_time("2026-07-29T13:30:00+00:00", "America/Chicago") == "2026-07-29 08:30 CDT"
    assert local_send_time("2026-07-29T13:30:00Z", "Mars/Olympus") == ""
    assert local_send_time("2026-07-29T13:30:00Z", "") == ""
    assert local_send_time("not a date", "America/Chicago") == ""


def test_survey_rotation_spans_profile_and_copies():
    profile = SurveyProfile(
        id="p",
        account_id="a",
        survey_id="SV_orig",
        survey_copies=[
            {"id": "SV_a", "name": "Study-c1"},
            {"id": "SV_b", "name": "Study-c2"},
        ],
    )
    rotation = survey_rotation(profile)
    assert [s.id for s in rotation] == ["SV_orig", "SV_a", "SV_b"]
    assert [s.label for s in rotation] == ["original", "c1", "c2"]
