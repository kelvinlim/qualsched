"""Per-call timeouts go on the httpx request. Client.send() rejects timeout=."""

import httpx

from app.qualtrics import QualtricsClient


def test_post_and_get_put_timeout_on_the_request():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions.get("timeout")
        assert isinstance(timeout, dict)
        seen.append(timeout)
        return httpx.Response(
            200,
            json={"meta": {"httpStatus": "200"}, "result": {"ok": True}},
        )

    client = QualtricsClient("yul1", "token")
    try:
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        posted = client.post(
            "surveys/SV_example/export-responses",
            {"format": "json"},
            timeout=20,
        )
        got = client.get("surveys/SV_example", timeout=15)
    finally:
        client.close()

    assert posted["result"]["ok"] is True
    assert got["result"]["ok"] is True
    assert [item["read"] for item in seen] == [20, 15]
    assert [item["connect"] for item in seen] == [20, 15]
