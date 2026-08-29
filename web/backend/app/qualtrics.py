"""Qualtrics API client (httpx). Token stays on the server — the browser never sees it."""

from __future__ import annotations

import ssl
from typing import Any

import httpx

from app.errors import app_error


class QualtricsError(Exception):
    def __init__(self, status: int, kind: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.message = message
        self.retryable = retryable

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

    def __enter__(self) -> QualtricsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

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
        if isinstance(meta, dict):
            http_status = str(meta.get("httpStatus") or "")
            err = meta.get("error") if isinstance(meta.get("error"), dict) else {}
            msg = err.get("errorMessage") if err else None
        else:
            msg = None

        if 200 <= status < 300 and (not http_status or http_status.startswith("200")):
            return body

        message = msg or text[:300]
        if status == 404:
            raise QualtricsError(404, "NotFound", message)
        raise QualtricsError(status if status >= 400 else 502, "Api", message)

    def get(self, path: str) -> dict[str, Any]:
        return self._send(self._client.build_request("GET", self.url(path)))

    def get_absolute(self, url: str) -> dict[str, Any]:
        return self._send(self._client.build_request("GET", url))

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._send(self._client.build_request("POST", self.url(path), json=body))

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
