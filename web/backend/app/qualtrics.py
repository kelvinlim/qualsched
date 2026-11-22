"""Qualtrics API client (httpx). Token stays on the server — the browser never sees it."""

from __future__ import annotations

import json
import re
import ssl
from typing import Any, Self

import httpx

from app.errors import app_error

# Qualtrics machine codes such as RTE_2. A sentence, a column name, or an id does not match.
_MACHINE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")


def machine_code(value: Any) -> str | None:
    if isinstance(value, str) and _MACHINE_CODE.fullmatch(value):
        return value
    return None


# GRP_1 is the published code for a response export sent to the wrong host.
# The sentence names the datacenter; only that host token is kept.
_BELONGS_TO = re.compile(
    r"datacenter the API user belongs to:\s*([A-Za-z0-9][A-Za-z0-9.-]{0,80})",
    re.IGNORECASE,
)
_USE_HOST = re.compile(
    r"use this host instead:\s*([A-Za-z0-9][A-Za-z0-9.-]{0,80})",
    re.IGNORECASE,
)
_DC_ID = re.compile(r"[a-z]{1,6}[0-9][a-z0-9]{0,6}")
_DC_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,20}[a-z0-9])?")


def qualtrics_host(text: Any) -> str | None:
    """Host from a proxy notice or a GRP_1 sentence. Anything else is dropped."""
    if not isinstance(text, str) or not text:
        return None
    match = _BELONGS_TO.search(text) or _USE_HOST.search(text)
    if match is None:
        return None
    return _host_token(match.group(1))


def _host_token(token: str) -> str | None:
    token = token.strip().strip(".").lower()
    if not token or "@" in token or "/" in token or ".." in token or "_" in token:
        return None
    if token.endswith(".qualtrics.com"):
        name = token[: -len(".qualtrics.com")]
        if name and all(_DC_LABEL.fullmatch(label) for label in name.split(".")):
            return token
        return None
    if _DC_ID.fullmatch(token):
        return f"{token}.qualtrics.com"
    return None


class QualtricsError(Exception):
    def __init__(
        self,
        status: int,
        kind: str,
        message: str,
        *,
        retryable: bool = False,
        code: str | None = None,
        datacenter_host: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.message = message
        self.retryable = retryable
        self.code = machine_code(code)
        host = datacenter_host if isinstance(datacenter_host, str) else ""
        self.datacenter_host = host if _host_token(host) == host else None

    def as_http(self):
        return app_error(self.status, self.kind, self.message, retryable=self.retryable)


class QualtricsClient:
    def __init__(self, data_center: str, token: str, verify_tls: bool = True):
        self.data_center = data_center.strip()
        self.token = token.strip()
        ctx: ssl.SSLContext | bool
        if verify_tls:
            ctx = True
        else:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self._client = httpx.Client(
            headers={"x-api-token": self.token},
            timeout=60.0,
            verify=ctx,
        )

    def url(self, path: str) -> str:
        return f"https://{self.data_center}.qualtrics.com/API/v3/{path.lstrip('/')}"

    def _retarget(self, host: str | None) -> bool:
        """Point later calls at the host Qualtrics named. Returns whether it changed."""
        if not host or not host.endswith(".qualtrics.com"):
            return False
        data_center = host[: -len(".qualtrics.com")]
        if not data_center or data_center == self.data_center:
            return False
        self.data_center = data_center
        return True

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        timeout: float | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Request:
        # httpx.Client.send() does not accept timeout. The per-call deadline has
        # to be stored on the request, or send() raises TypeError before the
        # bytes leave the process.
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if json is not None:
            kwargs["json"] = json
        return self._client.build_request(method, url, **kwargs)

    def _send(self, req: httpx.Request) -> dict[str, Any]:
        resp = self._client.send(req)
        status = resp.status_code
        text = resp.text
        if status in (401, 403):
            raise QualtricsError(401, "Unauthorized", "Qualtrics rejected the API token.")
        if status == 429:
            raise QualtricsError(429, "RateLimited", "Qualtrics rate-limited the request.", retryable=True)
        try:
            body = resp.json()
        except ValueError as exc:
            raise QualtricsError(
                502, "Api", f"HTTP {status}: response was not JSON: {text[:300]}"
            ) from exc

        http_status = ""
        meta = body.get("meta") if isinstance(body, dict) else None
        code = None
        if isinstance(meta, dict):
            http_status = str(meta.get("httpStatus") or "")
            err = meta.get("error") if isinstance(meta.get("error"), dict) else {}
            msg = err.get("errorMessage") if isinstance(err, dict) else None
            code = machine_code(err.get("errorCode")) if isinstance(err, dict) else None
            notice = meta.get("notice")
        else:
            msg = None
            notice = None

        if 200 <= status < 300 and (not http_status or http_status.startswith("200")):
            self._retarget(qualtrics_host(notice))
            return body

        host = qualtrics_host(msg) if code == "GRP_1" else None
        # GRP_1's sentence names a datacenter. Keep the host for one retry, not the sentence.
        if code == "GRP_1":
            message = "Qualtrics refused the response export for this data center."
        else:
            message = msg or text[:300]
        if status == 404:
            raise QualtricsError(404, "NotFound", message, code=code)
        raise QualtricsError(
            status if status >= 400 else 502,
            "Api",
            message,
            code=code,
            datacenter_host=host,
        )

    def _exchange(
        self,
        method: str,
        path: str,
        *,
        timeout: float | None = None,
        json: dict[str, Any] | None = None,
        retried: bool = False,
    ) -> dict[str, Any]:
        try:
            return self._send(
                self._request(method, self.url(path), timeout=timeout, json=json)
            )
        except QualtricsError as exc:
            if (
                not retried
                and exc.code == "GRP_1"
                and self._retarget(exc.datacenter_host)
            ):
                return self._exchange(
                    method, path, timeout=timeout, json=json, retried=True
                )
            raise

    def get(self, path: str, timeout: float | None = None) -> dict[str, Any]:
        return self._exchange("GET", path, timeout=timeout)

    def get_bytes(self, path: str) -> bytearray:
        """Download a binary body into memory.

        Failures do not include the response body. Qualtrics export files can
        contain participant data, and that text must not land in an error string
        or a log line. The returned buffer is a ``bytearray`` so the caller can
        overwrite it after parsing. This does not cover copies the HTTP stack
        already made, or memory the OS has paged out.
        """
        resp = self._client.send(self._request("GET", self.url(path)))
        status = resp.status_code
        if status in (401, 403):
            raise QualtricsError(401, "Unauthorized", "Qualtrics rejected the API token.")
        if status == 429:
            raise QualtricsError(
                429, "RateLimited", "Qualtrics rate-limited the request.", retryable=True
            )
        if not 200 <= status < 300:
            raise QualtricsError(
                status if status >= 400 else 502,
                "Api",
                f"Qualtrics response export failed (HTTP {status}).",
            )
        return bytearray(resp.content)

    def get_bytes_limited(self, path: str, limit: int, timeout: float) -> bytearray:
        """Read an export file up to ``limit`` bytes. The body is never copied into an error."""
        return self._get_bytes_limited(path, limit, timeout, retried=False)

    def _error_host(self, resp: httpx.Response) -> str | None:
        """GRP_1 names a datacenter. Read at most 4 KiB, then wipe it."""
        raw = bytearray()
        try:
            for chunk in resp.iter_bytes():
                room = 4096 - len(raw)
                if room <= 0:
                    break
                raw.extend(chunk[:room])
            try:
                body = json.loads(bytes(raw))
            except ValueError:
                return None
            meta = body.get("meta") if isinstance(body, dict) else None
            err = meta.get("error") if isinstance(meta, dict) else None
            if not isinstance(err, dict) or machine_code(err.get("errorCode")) != "GRP_1":
                return None
            return qualtrics_host(err.get("errorMessage"))
        finally:
            for index in range(len(raw)):
                raw[index] = 0
            raw.clear()

    def _get_bytes_limited(
        self, path: str, limit: int, timeout: float, *, retried: bool
    ) -> bytearray:
        retry_host: str | None = None
        try:
            with self._client.stream("GET", self.url(path), timeout=timeout) as resp:
                status = resp.status_code
                if status in (401, 403):
                    raise QualtricsError(401, "Unauthorized", "Qualtrics rejected the API token.")
                if status == 429:
                    raise QualtricsError(
                        429, "RateLimited", "Qualtrics rate-limited the request.", retryable=True
                    )
                if not 200 <= status < 300:
                    if not retried:
                        retry_host = self._error_host(resp)
                    if not (retry_host and self._retarget(retry_host)):
                        raise QualtricsError(
                            status if status >= 400 else 502,
                            "Api",
                            f"Qualtrics response export failed at download (HTTP {status}).",
                        )
                else:
                    buf = bytearray()
                    try:
                        for chunk in resp.iter_bytes():
                            if len(buf) + len(chunk) > limit:
                                raise QualtricsError(
                                    502,
                                    "Api",
                                    "Qualtrics response export failed at download "
                                    "(file too large).",
                                )
                            buf.extend(chunk)
                        kept = buf
                        buf = bytearray()
                        return kept
                    finally:
                        for index in range(len(buf)):
                            buf[index] = 0
                        buf.clear()
            if retry_host:
                return self._get_bytes_limited(path, limit, timeout, retried=True)
            raise QualtricsError(
                502, "Api", "Qualtrics response export failed at download (HTTP 400)."
            )
        except httpx.TimeoutException as exc:
            raise QualtricsError(
                504, "Api", "Qualtrics response export failed at download (timeout)."
            ) from exc

    def get_absolute(self, url: str, timeout: float | None = None) -> dict[str, Any]:
        return self._send(self._request("GET", url, timeout=timeout))

    def post(self, path: str, body: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        return self._exchange("POST", path, timeout=timeout, json=body)

    def put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._send(self._request("PUT", self.url(path), json=body))

    def delete(self, path: str) -> dict[str, Any]:
        return self._send(self._request("DELETE", self.url(path)))

    def get_elements(self, path: str, timeout: float | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        body = self.get(path) if timeout is None else self.get(path, timeout=timeout)
        while True:
            result = body.get("result") if isinstance(body, dict) else None
            elements = result.get("elements") if isinstance(result, dict) else None
            if isinstance(elements, list):
                out.extend(e for e in elements if isinstance(e, dict))
            next_url = result.get("nextPage") if isinstance(result, dict) else None
            if isinstance(next_url, str) and next_url:
                body = (
                    self.get_absolute(next_url)
                    if timeout is None
                    else self.get_absolute(next_url, timeout=timeout)
                )
            else:
                break
        return out
