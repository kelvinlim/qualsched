"""Lookup proxies (directories, surveys, libraries). Token never leaves the server."""

from app.qualtrics import QualtricsError
from tests.test_accounts import ACCOUNT, SECRET

AID = ACCOUNT["id"]


def _ready_account(client, *, token=True):
    assert client.post("/api/accounts", json=ACCOUNT).status_code == 200
    if token:
        assert client.put(f"/api/accounts/{AID}/token", json={"token": SECRET}).status_code == 200


class FakeQualtrics:
    def __init__(
        self,
        elements_by_path: dict[str, list[dict]],
        *,
        get_by_path: dict[str, dict] | None = None,
        errors_by_path: dict[str, Exception] | None = None,
    ):
        self.elements_by_path = elements_by_path
        self.get_by_path = get_by_path or {}
        self.errors_by_path = errors_by_path or {}
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_elements(self, path: str):
        self.calls.append(("get_elements", path))
        if path in self.errors_by_path:
            raise self.errors_by_path[path]
        return list(self.elements_by_path.get(path, []))

    def get(self, path: str):
        self.calls.append(("get", path))
        if path in self.errors_by_path:
            raise self.errors_by_path[path]
        if path not in self.get_by_path:
            raise QualtricsError(404, "NotFound", f"{path} missing")
        return self.get_by_path[path]


def _install(monkeypatch, fake: FakeQualtrics):
    monkeypatch.setattr("app.routers.lookups.qualtrics_for", lambda _account: fake)


def test_list_libraries_maps_id_and_name(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics(
        {
            "libraries": [
                {"libraryId": "GR_2fXBZYGAqiAoC3Q", "libraryName": "LNPI Group"},
                {"id": "UR_personal", "name": "My Library"},
                {"libraryName": "missing id"},
            ]
        }
    )
    _install(monkeypatch, fake)

    r = http.get(f"/api/accounts/{AID}/libraries")
    assert r.status_code == 200, r.text
    assert r.json() == [
        {"id": "GR_2fXBZYGAqiAoC3Q", "name": "LNPI Group"},
        {"id": "UR_personal", "name": "My Library"},
    ]
    assert fake.calls == [("get_elements", "libraries")]
    assert SECRET not in r.text
    assert "token" not in r.text.lower()


def test_list_libraries_400_when_token_missing(ctx):
    http, _, _ = ctx
    _ready_account(http, token=False)
    r = http.get(f"/api/accounts/{AID}/libraries")
    assert r.status_code == 400
    assert r.json()["detail"]["kind"] == "Invalid"
    assert "token" in r.json()["detail"]["message"].lower()


def test_list_mailing_lists_all_directories_tags_and_skips_inaccessible(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics(
        {
            "directories": [
                {"directoryId": "POOL_1", "name": "Primary Dir"},
                {"directoryId": "POOL_locked", "name": "Locked Dir"},
                {"directoryId": "POOL_2", "name": "Secondary Dir"},
            ],
            "directories/POOL_1/mailinglists?includeCount=true": [
                {"mailingListId": "CG_1", "name": "List One", "contactCount": 12},
            ],
            "directories/POOL_2/mailinglists?includeCount=true": [
                {"mailingListId": "CG_2", "name": "List Two", "contactCount": None},
            ],
        },
        errors_by_path={
            "directories/POOL_locked/mailinglists?includeCount=true": QualtricsError(
                401, "Unauthorized", "forbidden"
            ),
        },
    )
    _install(monkeypatch, fake)

    r = http.get(f"/api/accounts/{AID}/mailing-lists?directoryId=*")
    assert r.status_code == 200, r.text
    assert r.json() == [
        {
            "id": "CG_1",
            "name": "List One",
            "contactCount": 12,
            "directoryId": "POOL_1",
            "directoryName": "Primary Dir",
        },
        {
            "id": "CG_2",
            "name": "List Two",
            "contactCount": None,
            "directoryId": "POOL_2",
            "directoryName": "Secondary Dir",
        },
    ]


def test_list_messages_all_libraries_and_explicit_library(ctx, monkeypatch):
    http, _, _ = ctx
    _ready_account(http)
    fake = FakeQualtrics(
        {
            "libraries": [
                {"libraryId": "GR_1", "libraryName": "Core Lib"},
                {"libraryId": "GR_404", "libraryName": "Missing Lib"},
                {"libraryId": "GR_other", "libraryName": "Other Lib"},
            ],
            "libraries/GR_1/messages": [
                {"id": "MS_1", "description": "Core SMS", "category": "invite"},
            ],
            "libraries/GR_other/messages": [
                {"id": "MS_2", "description": "Other Email", "category": None},
            ],
        },
        errors_by_path={
            "libraries/GR_404/messages": QualtricsError(404, "NotFound", "gone"),
        },
        get_by_path={
            "libraries/GR_other/messages/MS_2": {
                "result": {"messages": {"en": "Hello from Other Lib"}}
            }
        },
    )
    _install(monkeypatch, fake)

    r_all = http.get(f"/api/accounts/{AID}/messages?libraryId=*")
    assert r_all.status_code == 200, r_all.text
    assert r_all.json() == [
        {
            "id": "MS_1",
            "description": "Core SMS",
            "category": "invite",
            "libraryId": "GR_1",
            "libraryName": "Core Lib",
        },
        {
            "id": "MS_2",
            "description": "Other Email",
            "category": None,
            "libraryId": "GR_other",
            "libraryName": "Other Lib",
        },
    ]

    r_one = http.get(f"/api/accounts/{AID}/messages?libraryId=GR_other")
    assert r_one.status_code == 200, r_one.text
    assert r_one.json() == [
        {
            "id": "MS_2",
            "description": "Other Email",
            "category": None,
            "libraryId": "GR_other",
            "libraryName": "",
        },
    ]

    r_text = http.get(f"/api/accounts/{AID}/messages/MS_2/text?libraryId=GR_other")
    assert r_text.status_code == 200, r_text.text
    assert r_text.json() == "Hello from Other Lib"
    assert ("get", "libraries/GR_other/messages/MS_2") in fake.calls
