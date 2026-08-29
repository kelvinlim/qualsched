"""Contacts proxy Qualtrics. No live API, no real tokens, no contacts table."""

import json

from app.contacts import WRITE_PACING_SECONDS, append_log_data
from app.qualtrics import QualtricsError
from tests.test_accounts import ACCOUNT, PROJECT, SECRET

AID = ACCOUNT["id"]
PID = PROJECT["id"]
BASE = f"/api/accounts/{AID}/projects/{PID}/contacts"


def _ready_account(client, *, directory=True, mailing_list=True, token=True):
    account = {**ACCOUNT, "defaultDirectory": "POOL_abc" if directory else ""}
    project = {**PROJECT, "mailingListId": "CG_list" if mailing_list else ""}
    assert client.post("/api/accounts", json=account).status_code == 200
    assert client.post(f"/api/accounts/{AID}/projects", json=project).status_code == 200
    if token:
        assert client.put(f"/api/accounts/{AID}/token", json={"token": SECRET}).status_code == 200


class FakeQualtrics:
    """In-memory stand-in for QualtricsClient. Stores mailing-list contacts only."""

    def __init__(self):
        self.contacts: dict[str, dict] = {}
        self.order: list[str] = []
        self.calls: list[tuple] = []
        self._seq = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add(self, raw: dict) -> dict:
        cid = raw["contactId"]
        self.contacts[cid] = raw
        if cid not in self.order:
            self.order.append(cid)
        return raw

    def get_elements(self, path: str):
        self.calls.append(("get_elements", path))
        return [self.contacts[i] for i in self.order if i in self.contacts]

    def get(self, path: str):
        self.calls.append(("get", path))
        cid = path.rsplit("/", 1)[-1]
        if cid not in self.contacts:
            raise QualtricsError(404, "NotFound", f"contact {cid} missing")
        raw = self.contacts[cid]
        # Directory-level GET (used to resolve CGC_… when the list row has none).
        if path.startswith("directories/") and "/mailinglists/" not in path:
            lookup = raw.get("contactLookupId") or f"CGC_{cid}"
            return {
                "result": {
                    **raw,
                    "mailingListMembership": {
                        "CG_list": {"contactLookupId": lookup},
                    },
                }
            }
        return {"result": raw}

    def post(self, path: str, body: dict):
        self.calls.append(("post", path, body))
        self._seq += 1
        cid = f"CID_{self._seq}"
        raw = {k: v for k, v in body.items() if k != "embeddedData"}
        raw["contactId"] = cid
        raw["embeddedData"] = dict(body.get("embeddedData") or {})
        self.add(raw)
        return {"result": {"id": cid}}

    def put(self, path: str, body: dict):
        self.calls.append(("put", path, body))
        cid = path.rsplit("/", 1)[-1]
        existing = dict(self.contacts.get(cid) or {})
        updated = {**existing, **body, "contactId": cid}
        self.contacts[cid] = updated
        return {"result": {}}

    def delete(self, path: str):
        self.calls.append(("delete", path))
        cid = path.rsplit("/", 1)[-1]
        self.contacts.pop(cid, None)
        if cid in self.order:
            self.order.remove(cid)
        return {"result": {}}


def _eligible_raw(contact_id: str = "CID_ada", **overrides) -> dict:
    raw = {
        "contactId": contact_id,
        "firstName": "Ada",
        "lastName": "Lovelace",
        "email": "ada@example.com",
        "phone": "16125551234",
        "extRef": "P1",
        "language": "en",
        "contactLookupId": "CGC_secret",
        "mailingListUnsubscribed": False,
        "embeddedData": {
            "StartDate": "2026-09-01",
            "NumDays": "7",
            "TimeSlots": "800,1200",
            "TimeZone": "America/Chicago",
            "ContactMethod": "sms",
            "SurveysScheduled": "0",
            "ExpireMinutes": "60",
        },
    }
    raw.update(overrides)
    return raw


def _install(monkeypatch, fake: FakeQualtrics):
    monkeypatch.setattr("app.routers.contacts.qualtrics_for", lambda _account: fake)
    monkeypatch.setattr("app.contacts.WRITE_PACING_SECONDS", 0)


def test_list_maps_contacts_and_eligibility(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics()
    fake.add(_eligible_raw())
    skipped = _eligible_raw("CID_skip", firstName="Skip", lastName="Me", email="skip@example.com")
    skipped["embeddedData"] = {"NumDays": "0", "ContactMethod": "email"}
    fake.add(skipped)
    _install(monkeypatch, fake)

    r = http.get(BASE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    ada = body[0]
    assert ada["contactId"] == "CID_ada"
    assert ada["firstName"] == "Ada"
    assert ada["lastName"] == "Lovelace"
    assert ada["email"] == "ada@example.com"
    assert ada["phone"] == "16125551234"
    assert ada["extRef"] == "P1"
    assert ada["embedded"]["StartDate"] == "2026-09-01"
    assert ada["eligible"] is True
    assert ada["skipReason"] is None
    assert ada["method"] == "sms"
    assert body[1]["eligible"] is False
    assert "NumDays" in (body[1]["skipReason"] or "")
    assert "get_elements" == fake.calls[0][0]
    assert "includeEmbedded=true" in fake.calls[0][1]
    assert "directories/POOL_abc/mailinglists/CG_list/contacts" in fake.calls[0][1]
    assert SECRET not in r.text
    assert "token" not in r.text.lower()


def test_list_uses_paginated_elements(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics()
    fake.add(_eligible_raw("CID_1", firstName="One"))
    fake.add(_eligible_raw("CID_2", firstName="Two", email="two@example.com"))
    _install(monkeypatch, fake)

    # Pagination itself is covered on QualtricsClient; list must consume get_elements.
    r = http.get(BASE)
    assert r.status_code == 200
    assert [c["contactId"] for c in r.json()] == ["CID_1", "CID_2"]
    assert fake.calls[0][0] == "get_elements"


def test_400_when_token_missing(ctx):
    http, _, _ = ctx
    _ready_account(http, token=False)
    r = http.get(BASE)
    assert r.status_code == 400
    assert r.json()["detail"]["kind"] == "Invalid"
    assert "token" in r.json()["detail"]["message"].lower()


def test_400_when_directory_missing(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http, directory=False)
    _install(monkeypatch, FakeQualtrics())
    r = http.get(BASE)
    assert r.status_code == 400
    assert "directory" in r.json()["detail"]["message"].lower()
    assert r.json() != []


def test_400_when_mailing_list_missing(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http, mailing_list=False)
    _install(monkeypatch, FakeQualtrics())
    r = http.get(BASE)
    assert r.status_code == 400, r.text
    message = r.json()["detail"]["message"].lower()
    assert "mailing list" in message
    assert r.json()["detail"]["kind"] == "Invalid"


def test_create_update_delete(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics()
    _install(monkeypatch, fake)

    created = http.post(
        BASE,
        json={
            "core": {"firstName": "Grace", "lastName": "Hopper", "email": "grace@example.com"},
            "embedded": {"NumDays": "14", "StartDate": "2026-10-01"},
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["contactId"] == "CID_1"
    assert row["firstName"] == "Grace"
    assert row["embedded"]["NumDays"] == "14"
    assert row["embedded"]["StartDate"] == "2026-10-01"
    # Profile defaults fill the rest; create never overwrites the provided fields.
    assert row["embedded"]["TimeSlots"] == "800,1200"
    assert row["embedded"]["ContactMethod"] == "sms"
    log = json.loads(row["embedded"]["LogData"])
    assert log[-1]["action"] == "created"
    post_path = next(c[1] for c in fake.calls if c[0] == "post")
    assert post_path == "directories/POOL_abc/mailinglists/CG_list/contacts"

    updated = http.put(
        f"{BASE}/CID_1",
        json={"core": {"lastName": "Murray"}, "fields": {"TimeSlots": "900"}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["lastName"] == "Murray"
    assert updated.json()["embedded"]["TimeSlots"] == "900"
    assert updated.json()["embedded"]["NumDays"] == "14"
    put = next(c for c in fake.calls if c[0] == "put")
    assert put[1] == "directories/POOL_abc/mailinglists/CG_list/contacts/CID_1"
    assert "contactId" not in put[2]
    assert "contactLookupId" not in put[2]
    log = json.loads(updated.json()["embedded"]["LogData"])
    assert log[-1]["action"] == "edit"

    removed = http.delete(f"{BASE}/CID_1")
    assert removed.status_code == 200, removed.text
    assert removed.json()["contactName"] == "Grace Murray"
    assert removed.json()["cancelled"] == 0
    delete = next(c for c in fake.calls if c[0] == "delete")
    assert delete[1] == "directories/POOL_abc/mailinglists/CG_list/contacts/CID_1"
    assert http.get(BASE).json() == []


def test_create_rejects_empty_identity(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    _install(monkeypatch, FakeQualtrics())
    r = http.post(BASE, json={"core": {"firstName": "  "}, "embedded": {}})
    assert r.status_code == 400
    assert "name" in r.json()["detail"]["message"]


def test_defaults_fill_only(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics()
    fake.add(
        {
            "contactId": "CID_keep",
            "firstName": "Pat",
            "lastName": "Lee",
            "email": "pat@example.com",
            "embeddedData": {
                "StartDate": "2026-01-15",
                "ContactMethod": "email",
                "LogData": "[]",
            },
        }
    )
    _install(monkeypatch, fake)

    r = http.post(f"{BASE}/defaults", json={"contactIds": ["CID_keep"]})
    assert r.status_code == 200, r.text
    row = r.json()[0]
    # Existing values survive.
    assert row["embedded"]["StartDate"] == "2026-01-15"
    assert row["embedded"]["ContactMethod"] == "email"
    # Missing keys come from the profile.
    assert row["embedded"]["TimeSlots"] == "800,1200"
    assert row["embedded"]["NumDays"] == "7"
    assert row["embedded"]["TimeZone"] == "America/Chicago"
    put = next(c for c in fake.calls if c[0] == "put")
    assert put[2]["embeddedData"]["StartDate"] == "2026-01-15"
    assert put[2]["embeddedData"]["TimeSlots"] == "800,1200"
    log = json.loads(row["embedded"]["LogData"])
    assert log[-1]["action"] == "init"


def test_qualtrics_error_shape(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)

    class Boom(FakeQualtrics):
        def get_elements(self, path: str):
            raise QualtricsError(401, "Unauthorized", "Qualtrics rejected the API token.")

    _install(monkeypatch, Boom())
    r = http.get(BASE)
    assert r.status_code == 401
    detail = r.json()["detail"]
    assert detail["kind"] == "Unauthorized"
    assert "message" in detail
    assert detail["retryable"] is False


def test_append_log_data_promotes_and_caps():
    assert json.loads(append_log_data(None, {"action": "send"})) == [{"action": "send"}]
    promoted = json.loads(append_log_data('{"action":"init"}', {"action": "send"}))
    assert [e["action"] for e in promoted] == ["init", "send"]
    existing = json.dumps([{"n": i} for i in range(60)])
    capped = json.loads(append_log_data(existing, {"n": "last"}))
    assert len(capped) == 50
    assert capped[-1]["n"] == "last"


def test_write_pacing_constant_matches_desktop():
    assert WRITE_PACING_SECONDS == 0.12
