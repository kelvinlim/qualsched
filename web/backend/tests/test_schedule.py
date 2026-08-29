"""Schedule preview/execute proxy Qualtrics. No live API, no real tokens, no plan table."""

from datetime import datetime, timezone
from random import Random

from app.qualtrics import QualtricsError
from tests.test_accounts import ACCOUNT, PROJECT, SECRET
from tests.test_contacts import FakeQualtrics, _eligible_raw, _ready_account

AID = ACCOUNT["id"]
PID = PROJECT["id"]
PREVIEW = f"/api/accounts/{AID}/projects/{PID}/schedule/preview"
EXECUTE = f"/api/accounts/{AID}/projects/{PID}/schedule/execute"

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


class ScheduleFake(FakeQualtrics):
    """Contacts fake plus message library + distribution create."""

    def __init__(self):
        super().__init__()
        self.messages = {
            "MS_sms": "Time for your survey ${l://SurveyURL}",
            "MS_email": "Please complete your survey",
        }
        self.distributions: list[tuple[str, dict]] = []
        self.fail_put = False

    def get(self, path: str):
        self.calls.append(("get", path))
        if path.startswith("libraries/") and "/messages/" in path:
            message_id = path.rsplit("/", 1)[-1]
            text = self.messages.get(message_id)
            if text is None:
                raise QualtricsError(404, "NotFound", f"message {message_id} missing")
            return {"result": {"messages": {"en": text}}}
        if "/mailinglists/" not in path and "/contacts/" in path:
            cid = path.rsplit("/", 1)[-1]
            raw = self.contacts.get(cid) or {}
            lookup = raw.get("contactLookupId") or f"CGC_{cid}"
            return {
                "result": {
                    "mailingListMembership": {
                        "CG_list": {"contactLookupId": lookup},
                    }
                }
            }
        return super().get(path)

    def post(self, path: str, body: dict):
        if path in ("distributions/sms", "distributions"):
            self.calls.append(("post", path, body))
            self.distributions.append((path, body))
            self._seq += 1
            return {"result": {"id": f"EMD_{self._seq}"}}
        return super().post(path, body)

    def put(self, path: str, body: dict):
        if self.fail_put:
            self.calls.append(("put", path, body))
            raise QualtricsError(500, "Api", "embedded data write failed")
        return super().put(path, body)


def _install(monkeypatch, fake: ScheduleFake):
    monkeypatch.setattr("app.routers.schedule.qualtrics_for", lambda _account: fake)
    monkeypatch.setattr("app.contacts.WRITE_PACING_SECONDS", 0)
    monkeypatch.setattr("app.schedule.utcnow", lambda: NOW)
    monkeypatch.setattr("app.schedule.new_rng", lambda: Random(0xC0FFEE))


def test_preview_maps_eligible_vs_skipped(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = ScheduleFake()
    fake.add(_eligible_raw())
    skipped = _eligible_raw("CID_skip", firstName="Skip", lastName="Me")
    skipped["embeddedData"] = {
        "NumDays": "0",
        "ContactMethod": "sms",
        "SurveysScheduled": "0",
    }
    fake.add(skipped)
    already = _eligible_raw("CID_done", firstName="Done", lastName="Already")
    already["embeddedData"] = {
        **skipped["embeddedData"],
        "NumDays": "7",
        "SurveysScheduled": "12",
        "StartDate": "2026-09-01",
        "TimeSlots": "800",
    }
    fake.add(already)
    _install(monkeypatch, fake)

    r = http.post(PREVIEW)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 14  # 7 days × 2 slots
    assert {i["contactId"] for i in body["items"]} == {"CID_ada"}
    assert all(i["method"] == "sms" for i in body["items"])
    assert all(i["surveyId"] == "SV_1" for i in body["items"])
    assert all(i["surveyLabel"] == "original" for i in body["items"])
    assert body["items"][0]["destination"] == "16125551234"
    assert body["items"][0]["sendLocal"].endswith("CDT") or body["items"][0]["sendLocal"].endswith(
        "CST"
    )
    assert body["items"][0]["sendUtc"].endswith("Z")
    assert body["items"][0]["expireUtc"].endswith("Z")
    reasons = {s["contactId"]: s["reason"] for s in body["skippedContacts"]}
    assert "NumDays" in reasons["CID_skip"]
    assert "already scheduled (SurveysScheduled = 12)" == reasons["CID_done"]
    assert body["warnings"] == []
    assert SECRET not in r.text
    assert "token" not in r.text.lower()
    assert fake.calls[0][0] == "get_elements"
    assert "includeEmbedded=true" in fake.calls[0][1]


def test_preview_timezone_math_matches_desktop(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = ScheduleFake()
    winter = _eligible_raw("CID_w")
    winter["embeddedData"] = {
        "StartDate": "2026-01-15",
        "NumDays": "1",
        "TimeSlots": "800",
        "TimeZone": "America/Chicago",
        "ContactMethod": "sms",
        "SurveysScheduled": "0",
        "ExpireMinutes": "60",
    }
    fake.add(winter)
    _install(monkeypatch, fake)
    monkeypatch.setattr(
        "app.schedule.utcnow", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    r = http.post(PREVIEW)
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    # 08:00 CST is 14:00Z.
    assert item["sendUtc"] == "2026-01-15T14:00:00Z"
    assert item["expireUtc"] == "2026-01-15T15:00:00Z"
    assert item["sendLocal"] == "2026-01-15 08:00 CST"


def test_preview_time_n_fallback(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = ScheduleFake()
    raw = _eligible_raw("CID_n")
    raw["embeddedData"] = {
        "StartDate": "2026-09-01",
        "NumDays": "1",
        "Time1": "800",
        "Time2": "2000",
        "TimeZone": "America/Chicago",
        "ContactMethod": "sms",
        "SurveysScheduled": "0",
    }
    fake.add(raw)
    _install(monkeypatch, fake)

    r = http.post(PREVIEW)
    assert r.status_code == 200, r.text
    assert [i["slotLabel"] for i in r.json()["items"]] == ["0800", "2000"]


def test_preview_skips_missing_phone(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = ScheduleFake()
    raw = _eligible_raw("CID_nophone", phone="")
    raw["phone"] = ""
    fake.add(raw)
    _install(monkeypatch, fake)

    r = http.post(PREVIEW)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert "phone number" in body["skippedContacts"][0]["reason"]


def test_400_when_token_missing(ctx):
    http, _, _ = ctx
    _ready_account(http, token=False)
    r = http.post(PREVIEW)
    assert r.status_code == 400
    assert "token" in r.json()["detail"]["message"].lower()


def test_400_when_directory_missing(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http, directory=False)
    _install(monkeypatch, ScheduleFake())
    r = http.post(PREVIEW)
    assert r.status_code == 400
    assert "directory" in r.json()["detail"]["message"].lower()


def test_400_when_mailing_list_missing(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http, mailing_list=False)
    _install(monkeypatch, ScheduleFake())
    r = http.post(PREVIEW)
    assert r.status_code == 400
    assert "mailing list" in r.json()["detail"]["message"].lower()


def test_400_when_survey_missing(ctx, monkeypatch):
    http, _, _ = ctx
    account = {**ACCOUNT}
    project = {**PROJECT, "surveyId": ""}
    assert http.post("/api/accounts", json=account).status_code == 200
    assert http.post(f"/api/accounts/{AID}/projects", json=project).status_code == 200
    assert http.put(f"/api/accounts/{AID}/token", json={"token": SECRET}).status_code == 200
    _install(monkeypatch, ScheduleFake())
    r = http.post(PREVIEW)
    assert r.status_code == 400, r.text
    assert "survey" in r.json()["detail"]["message"].lower()


def test_400_when_message_missing(ctx, monkeypatch):
    http, _, _ = ctx
    account = {**ACCOUNT}
    project = {**PROJECT, "messageId": ""}
    assert http.post("/api/accounts", json=account).status_code == 200
    assert http.post(f"/api/accounts/{AID}/projects", json=project).status_code == 200
    assert http.put(f"/api/accounts/{AID}/token", json={"token": SECRET}).status_code == 200
    _install(monkeypatch, ScheduleFake())
    r = http.post(PREVIEW)
    assert r.status_code == 400, r.text
    assert "sms message" in r.json()["detail"]["message"].lower()


def test_execute_creates_one_distribution_per_item_and_updates_surveys_scheduled(
    ctx, monkeypatch
):
    http, _, _ = ctx
    _ready_account(http)
    fake = ScheduleFake()
    fake.add(_eligible_raw())
    _install(monkeypatch, fake)

    preview = http.post(PREVIEW)
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert len(plan["items"]) == 14

    sent = http.post(EXECUTE, json=plan)
    assert sent.status_code == 200, sent.text
    report = sent.json()
    assert report["scheduled"] == 14
    assert report["failed"] == []
    assert report["bookkeepingFailures"] == []
    assert SECRET not in sent.text

    sms_posts = [c for c in fake.calls if c[0] == "post" and c[1] == "distributions/sms"]
    assert len(sms_posts) == 14
    first = sms_posts[0][2]
    assert first["surveyId"] == "SV_1"
    assert first["recipients"]["mailingListId"] == "CG_list"
    assert first["recipients"]["contactId"] == "CGC_secret"
    assert first["sendDate"].endswith("Z")
    assert first["method"] == "Invite"
    bodies = [c[2]["message"]["messageText"] for c in sms_posts]
    for body in bodies:
        assert body.find("[") < body.find("${l://SurveyURL}")
        assert "&nbsp;" not in body
    assert len(set(bodies)) == 14

    put = next(c for c in fake.calls if c[0] == "put")
    assert put[2]["embeddedData"]["SurveysScheduled"] == "14"
    log = put[2]["embeddedData"]["LogData"]
    assert '"action":"send"' in log.replace(" ", "") or '"action": "send"' in log


def test_execute_email_uses_message_id_email_and_header(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = ScheduleFake()
    raw = _eligible_raw("CID_mail", email="ada@example.com")
    raw["embeddedData"]["ContactMethod"] = "email"
    fake.add(raw)
    _install(monkeypatch, fake)

    plan = http.post(PREVIEW).json()
    assert plan["items"][0]["method"] == "email"
    sent = http.post(EXECUTE, json=plan)
    assert sent.status_code == 200, sent.text
    email_posts = [c for c in fake.calls if c[0] == "post" and c[1] == "distributions"]
    assert len(email_posts) == 14
    body = email_posts[0][2]
    assert body["header"]["fromEmail"] == "study@umn.edu"
    assert body["header"]["subject"] == "Survey"
    assert body["surveyLink"]["surveyId"] == "SV_1"
    assert body["surveyLink"]["type"] == "Individual"
    assert "Please complete your survey" in body["message"]["messageText"]
    assert "&nbsp;" in body["message"]["messageText"]


def test_execute_partial_failure_and_bookkeeping(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = ScheduleFake()
    fake.add(_eligible_raw())
    _install(monkeypatch, fake)

    plan = http.post(PREVIEW).json()
    original_post = fake.post
    failed_once = {"n": 0}

    def flaky_post(path: str, body: dict):
        if path == "distributions/sms" and failed_once["n"] == 0:
            failed_once["n"] = 1
            fake.calls.append(("post", path, body))
            raise QualtricsError(429, "RateLimited", "slow down", retryable=True)
        return original_post(path, body)

    fake.post = flaky_post
    fake.fail_put = True

    sent = http.post(EXECUTE, json=plan)
    assert sent.status_code == 200, sent.text
    report = sent.json()
    assert report["scheduled"] == 13
    assert len(report["failed"]) == 1
    assert report["failed"][0]["retryable"] is True
    assert len(report["bookkeepingFailures"]) == 1
    assert "SurveysScheduled" in report["bookkeepingFailures"][0]["error"]


def test_execute_rejects_stale_send_time(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = ScheduleFake()
    fake.add(_eligible_raw())
    _install(monkeypatch, fake)

    sent = http.post(
        EXECUTE,
        json={
            "items": [
                {
                    "contactId": "CID_ada",
                    "contactName": "Ada Lovelace",
                    "destination": "16125551234",
                    "method": "sms",
                    "dayIndex": 0,
                    "slotLabel": "0800",
                    "surveyId": "SV_1",
                    "surveyLabel": "original",
                    "sendLocal": "2026-01-01 08:00 CST",
                    "sendUtc": "2026-01-01T14:00:00Z",
                    "expireUtc": "2026-01-01T15:00:00Z",
                }
            ],
            "skippedContacts": [],
            "skippedSlots": [],
            "warnings": [],
        },
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["scheduled"] == 0
    assert "preview" in sent.json()["failed"][0]["error"]
    assert fake.distributions == []


def test_execute_400_when_library_missing(ctx, monkeypatch):
    http, _, _ = ctx
    account = {**ACCOUNT, "libraryId": ""}
    assert http.post("/api/accounts", json=account).status_code == 200
    assert http.post(f"/api/accounts/{AID}/projects", json=PROJECT).status_code == 200
    assert http.put(f"/api/accounts/{AID}/token", json={"token": SECRET}).status_code == 200
    _install(monkeypatch, ScheduleFake())
    r = http.post(EXECUTE, json={"items": [], "skippedContacts": [], "skippedSlots": [], "warnings": []})
    assert r.status_code == 400
    assert "library" in r.json()["detail"]["message"].lower()
