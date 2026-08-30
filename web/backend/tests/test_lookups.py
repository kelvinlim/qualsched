"""Lookup proxies (directories, surveys, libraries). Token never leaves the server."""

from tests.test_accounts import ACCOUNT, SECRET

AID = ACCOUNT["id"]


def _ready_account(client, *, token=True):
    assert client.post("/api/accounts", json=ACCOUNT).status_code == 200
    if token:
        assert client.put(f"/api/accounts/{AID}/token", json={"token": SECRET}).status_code == 200


class FakeQualtrics:
    def __init__(self, elements_by_path: dict[str, list[dict]]):
        self.elements_by_path = elements_by_path
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_elements(self, path: str):
        self.calls.append(("get_elements", path))
        return list(self.elements_by_path.get(path, []))


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
