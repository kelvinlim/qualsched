"""Account + token CRUD: token is encrypted at rest and never echoed back."""

from app.crypto import decrypt
from app.models import QualtricsAccount

ACCOUNT = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "UMN",
    "dataCenter": "yul1",
    "verifyTls": True,
    "defaultDirectory": "POOL_abc",
    "libraryId": "GR_lib",
    "projects": [],
}

PROJECT = {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "EMA",
    "surveyId": "SV_1",
    "messageId": "MS_sms",
    "messageIdEmail": "MS_email",
    "mailingListId": "CG_list",
    "timezone": "America/Chicago",
    "minutesExpire": 60,
    "emailHeader": {
        "fromEmail": "study@umn.edu",
        "fromName": "Study",
        "replyToEmail": "study@umn.edu",
        "subject": "Survey",
    },
    "embeddedDefaults": {
        "startDate": "2026-09-01",
        "surveysScheduled": 0,
        "timeSlots": "800,1200",
        "contactMethod": "sms",
        "deleteUnsent": 0,
        "numDays": 7,
        "expireMinutes": 60,
        "logData": "[]",
        "timeZone": "America/Chicago",
    },
    "surveyCopies": [],
    "copiesSourceSurveyId": "",
}

SECRET = "qualtrics-api-token-value"


def _dump(obj) -> str:
    return str(obj).lower()


def test_save_account_and_token_never_echoed(ctx):
    client, Session, uid = ctx

    r = client.post("/api/accounts", json=ACCOUNT)
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["accounts"][0]["name"] == "UMN"
    assert cfg["accounts"][0]["dataCenter"] == "yul1"
    assert "token" not in _dump(cfg)
    assert "ciphertext" not in _dump(cfg)
    assert SECRET not in _dump(cfg)

    put = client.put(f"/api/accounts/{ACCOUNT['id']}/token", json={"token": SECRET})
    assert put.status_code == 200, put.text
    assert SECRET not in _dump(put.json())

    has = client.get(f"/api/accounts/{ACCOUNT['id']}/has-token")
    assert has.status_code == 200
    assert has.json() is True
    assert SECRET not in _dump(has.json())

    cfg2 = client.get("/api/config").json()
    assert SECRET not in _dump(cfg2)
    assert "token_ciphertext" not in _dump(cfg2)

    db = Session()
    row = db.get(QualtricsAccount, ACCOUNT["id"])
    assert row is not None
    assert row.token_ciphertext
    assert SECRET not in row.token_ciphertext
    assert decrypt(row.token_ciphertext) == SECRET
    db.close()


def test_clear_token(ctx):
    client, Session, uid = ctx
    client.post("/api/accounts", json=ACCOUNT)
    client.put(f"/api/accounts/{ACCOUNT['id']}/token", json={"token": SECRET})
    r = client.delete(f"/api/accounts/{ACCOUNT['id']}/token")
    assert r.status_code == 200
    assert client.get(f"/api/accounts/{ACCOUNT['id']}/has-token").json() is False
    db = Session()
    assert db.get(QualtricsAccount, ACCOUNT["id"]).token_ciphertext is None
    db.close()


def test_save_and_delete_profile(ctx):
    client, _, _ = ctx
    client.post("/api/accounts", json=ACCOUNT)
    r = client.post(f"/api/accounts/{ACCOUNT['id']}/projects", json=PROJECT)
    assert r.status_code == 200, r.text
    projects = r.json()["accounts"][0]["projects"]
    assert len(projects) == 1
    assert projects[0]["surveyId"] == "SV_1"
    assert projects[0]["embeddedDefaults"]["timeSlots"] == "800,1200"

    gone = client.delete(f"/api/accounts/{ACCOUNT['id']}/projects/{PROJECT['id']}")
    assert gone.status_code == 200
    assert gone.json()["accounts"][0]["projects"] == []


def test_empty_token_rejected(ctx):
    client, _, _ = ctx
    client.post("/api/accounts", json=ACCOUNT)
    r = client.put(f"/api/accounts/{ACCOUNT['id']}/token", json={"token": "  "})
    assert r.status_code == 400
