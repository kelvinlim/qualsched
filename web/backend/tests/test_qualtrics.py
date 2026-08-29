"""QualtricsClient pagination and write helpers — no live Qualtrics."""

from app.qualtrics import QualtricsClient


def test_get_elements_follows_next_page(monkeypatch):
    client = QualtricsClient("yul1", "tok")
    calls: list[str] = []

    def fake_get(path: str):
        calls.append(path)
        return {
            "result": {
                "elements": [{"contactId": "CID_1"}],
                "nextPage": "https://yul1.qualtrics.com/API/v3/page2",
            }
        }

    def fake_abs(url: str):
        calls.append(url)
        return {"result": {"elements": [{"contactId": "CID_2"}]}}

    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setattr(client, "get_absolute", fake_abs)

    out = client.get_elements("directories/POOL/mailinglists/CG/contacts?includeEmbedded=true")
    assert [e["contactId"] for e in out] == ["CID_1", "CID_2"]
    assert calls[0].endswith("includeEmbedded=true")
    assert calls[1] == "https://yul1.qualtrics.com/API/v3/page2"


def test_get_elements_stops_on_empty_next_page(monkeypatch):
    client = QualtricsClient("yul1", "tok")

    def fake_get(_path: str):
        return {"result": {"elements": [{"contactId": "only"}], "nextPage": ""}}

    monkeypatch.setattr(client, "get", fake_get)
    assert [e["contactId"] for e in client.get_elements("directories/x/mailinglists/y/contacts")] == [
        "only"
    ]


def test_url_and_write_methods_exist():
    client = QualtricsClient("yul1", "tok")
    assert client.url("directories/x") == "https://yul1.qualtrics.com/API/v3/directories/x"
    assert hasattr(client, "post")
    assert hasattr(client, "put")
    assert hasattr(client, "delete")
    client.close()
