"""Per-call timeouts go on the httpx request. Client.send() rejects timeout=."""

import json

import httpx

from app.acquisition import _start_export
from app.qualtrics import QualtricsClient, QualtricsError, qualtrics_host

# The sentence Qualtrics publishes with errorCode GRP_1. The host token is synthetic.
_GRP1 = (
    "Cannot download response export file through datacenter proxing, "
    "please retry using the url of the datacenter the API user belongs to: iad1.qualtrics.com"
)


def _client(handler) -> QualtricsClient:
    client = QualtricsClient("yul1", "token")
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


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


def test_grp1_host_is_only_a_datacenter_name():
    published = (
        "Cannot download response export file through datacenter proxing, "
        "please retry using the url of the datacenter the API user belongs to: CO1"
    )
    assert qualtrics_host(published) == "co1.qualtrics.com"
    assert qualtrics_host(_GRP1) == "iad1.qualtrics.com"
    assert (
        qualtrics_host("Request proxied. For faster response times, use this host instead: iad1.qualtrics.com")
        == "iad1.qualtrics.com"
    )
    assert qualtrics_host("datacenter the API user belongs to: ada@example.com") is None
    assert qualtrics_host("datacenter the API user belongs to: SV_example") is None


def test_grp1_retries_export_start_on_the_named_host_and_drops_the_sentence():
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "yul1.qualtrics.com":
            return httpx.Response(
                400,
                json={
                    "meta": {
                        "httpStatus": "400 - Bad Request",
                        "error": {"errorCode": "GRP_1", "errorMessage": _GRP1},
                    }
                },
            )
        body = json.loads(request.content)
        assert body["format"] == "json"
        assert "embeddedDataIds" not in body
        return httpx.Response(
            200,
            json={"meta": {"httpStatus": "200 - OK"}, "result": {"progressId": "ES_test"}},
        )

    client = _client(handler)
    try:
        progress, _mode = _start_export(client, "SV_example")
    finally:
        client.close()
    assert progress == "ES_test"
    assert hosts[:2] == ["yul1.qualtrics.com", "iad1.qualtrics.com"]
    assert _GRP1 not in "".join(hosts)


def test_grp1_without_a_host_does_not_keep_the_sentence():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "meta": {
                    "httpStatus": "400 - Bad Request",
                    "error": {
                        "errorCode": "GRP_1",
                        "errorMessage": "belongs to nobody ada@example.com SV_secret",
                    },
                }
            },
        )

    client = _client(handler)
    try:
        client.post("surveys/SV_example/export-responses", {"format": "json"}, timeout=20)
    except QualtricsError as exc:
        assert exc.code == "GRP_1"
        assert "ada@example.com" not in exc.message
        assert "SV_secret" not in exc.message
        assert exc.datacenter_host is None
    else:
        raise AssertionError("GRP_1 without a datacenter host must still fail")
    finally:
        client.close()


def test_proxy_notice_moves_the_next_call_to_the_named_host():
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(
            200,
            json={
                "meta": {
                    "httpStatus": "200 - OK",
                    "notice": (
                        "Request proxied. For faster response times, "
                        "use this host instead: iad1.qualtrics.com"
                    ),
                },
                "result": {"ok": True},
            },
        )

    client = _client(handler)
    try:
        client.get("directories/POOL_example", timeout=15)
        client.post("surveys/SV_example/export-responses", {"format": "json"}, timeout=20)
    finally:
        client.close()
    assert hosts == ["yul1.qualtrics.com", "iad1.qualtrics.com"]
