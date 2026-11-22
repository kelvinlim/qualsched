"""Qualtrics API client (httpx). Token stays on the server — the browser never sees it."""

from __future__ import annotations

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


class QualtricsError(Exception):
    def __init__(
        self,
        status: int,
        kind: str,
        message: str,
        *,
        retryable: bool = False,
        code: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.message = message
        self.retryable = retryable
        self.code = machine_code(code)

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

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _send(self, req: httpx.Request, timeout: float | None = None) -> dict[str, Any]:
        resp = self._client.send(req, timeout=timeout) if timeout is not None else self._client.send(req)
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
        else:
            msg = None

        if 200 <= status < 300 and (not http_status or http_status.startswith("200")):
            return body

        message = msg or text[:300]
        if status == 404:
            raise QualtricsError(404, "NotFound", message, code=code)
        raise QualtricsError(status if status >= 400 else 502, "Api", message, code=code)

    def get(self, path: str, timeout: float | None = None) -> dict[str, Any]:
        return self._send(self._client.build_request("GET", self.url(path)), timeout)

    def get_bytes(self, path: str) -> bytearray:
        """Download a binary body into memory.

        Failures do not include the response body. Qualtrics export files can
        contain participant data, and that text must not land in an error string
        or a log line. The returned buffer is a ``bytearray`` so the caller can
        overwrite it after parsing. This does not cover copies the HTTP stack
        already made, or memory the OS has paged out.
        """
        resp = self._client.send(self._client.build_request("GET", self.url(path)))
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
                    raise QualtricsError(
                        status if status >= 400 else 502,
                        "Api",
                        f"Qualtrics response export failed at download (HTTP {status}).",
                    )
                buf = bytearray()
                try:
                    for chunk in resp.iter_bytes():
                        if len(buf) + len(chunk) > limit:
                            raise QualtricsError(
                                502,
                                "Api",
                                "Qualtrics response export failed at download (file too large).",
                            )
                        buf.extend(chunk)
                    kept = buf
                    buf = bytearray()
                    return kept
                finally:
                    for index in range(len(buf)):
                        buf[index] = 0
                    buf.clear()
        except httpx.TimeoutException as exc:
            raise QualtricsError(
                504, "Api", "Qualtrics response export failed at download (timeout)."
            ) from exc

    def get_absolute(self, url: str) -> dict[str, Any]:
        return self._send(self._client.build_request("GET", url))

    def post(self, path: str, body: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        return self._send(self._client.build_request("POST", self.url(path), json=body), timeout)

    def put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._send(self._client.build_request("PUT", self.url(path), json=body))

    def delete(self, path: str) -> dict[str, Any]:
        return self._send(self._client.build_request("DELETE", self.url(path)))

    def get_elements(self, path: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        body = self.get(path)
        while True:
            result = body.get("result") if isinstance(body, dict) else None
            elements = result.get("elements") if isinstance(result, dict) else None
            if isinstance(elements, list):
                out.extend(e for e in elements if isinstance(e, dict))
            next_url = result.get("nextPage") if isinstance(result, dict) else None
            if isinstance(next_url, str) and next_url:
                body = self.get_absolute(next_url)
            else:
                break
        return out
