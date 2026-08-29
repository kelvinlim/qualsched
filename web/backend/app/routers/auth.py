"""Researcher Google-login auth (wearable-hub pattern).

Flow: GET /auth/login -> Google consent -> GET /auth/callback -> verify id_token ->
allowlist check (a `users` row, SUPERADMIN_EMAILS, or ALLOWED_EMAIL_DOMAINS) -> set a
session cookie -> redirect to the console. The grant is only used to prove identity;
Google tokens are never stored.

When GOOGLE_CLIENT_ID/SECRET are unset and ENVIRONMENT is not prod, POST /auth/dev-login
provisions the same session so the skeleton runs locally.
"""

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import app_error
from app.models import User
from app.schemas import DevLoginIn
from app.security import (
    COOKIE_NAME,
    STATE_COOKIE,
    cookie_secure,
    get_optional_user,
    make_session,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def _superadmin_emails() -> set[str]:
    return {e.strip().lower() for e in get_settings().superadmin_emails.split(",") if e.strip()}


def _allowed_domains() -> set[str]:
    return {
        d.strip().lower().lstrip("@")
        for d in get_settings().allowed_email_domains.split(",")
        if d.strip()
    }


def _domain_allowed(email: str) -> bool:
    """True if the address is on ALLOWED_EMAIL_DOMAINS (exact domain or subdomain)."""
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].lower()
    for allowed in _allowed_domains():
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False


def _provision_user(db: Session, email: str, sub: str | None, name: str | None) -> User | None:
    """Return the User for a verified identity, or None if not allowlisted.

    Allowlist = an existing `users` row, OR an email in SUPERADMIN_EMAILS (bootstrap —
    created as a superuser on first login), OR an address whose domain is in
    ALLOWED_EMAIL_DOMAINS (created as a regular researcher). Superadmin emails are
    (re)promoted on every login.
    """
    email = email.lower()
    user = db.scalar(select(User).where(User.email == email))
    is_boot_super = email in _superadmin_emails()
    if user is None:
        if not is_boot_super and not _domain_allowed(email):
            return None
        user = User(email=email, google_sub=sub, name=name, is_superuser=is_boot_super)
        db.add(user)
    else:
        if sub:
            user.google_sub = sub
        if name:
            user.name = name
        if is_boot_super:
            user.is_superuser = True
    db.commit()
    db.refresh(user)
    return user


def _session_response(user: User, *, redirect: str | None = None):
    s = get_settings()
    if redirect:
        resp = RedirectResponse(redirect, status_code=303)
    else:
        resp = JSONResponse(
            {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "is_superuser": user.is_superuser,
            }
        )
    resp.set_cookie(
        COOKIE_NAME,
        make_session(user.id),
        max_age=s.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
    )
    return resp


@router.get("/status")
def status() -> dict:
    s = get_settings()
    return {
        "google": s.google_login_configured,
        "devLogin": s.dev_login_allowed,
        "version": s.app_version,
    }


@router.get("/login")
def login() -> RedirectResponse:
    s = get_settings()
    if not s.google_login_configured:
        raise app_error(
            400,
            "Invalid",
            "Google OAuth is not configured. Use the local development sign-in, or set "
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": s.google_client_id,
        "redirect_uri": s.researcher_oauth_redirect_uri,
        "scope": s.researcher_google_scopes,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{AUTH_ENDPOINT}?{urlencode(params)}")
    resp.set_cookie(
        STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=cookie_secure()
    )
    return resp


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    s = get_settings()
    if error:
        raise app_error(400, "Invalid", f"Google sign-in failed: {error}")
    if not code or not state or request.cookies.get(STATE_COOKIE) != state:
        raise app_error(400, "Invalid", "Invalid or missing OAuth state")

    token_resp = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": s.researcher_oauth_redirect_uri,
        },
        timeout=30,
    )
    token_resp.raise_for_status()
    id_token_str = token_resp.json().get("id_token")
    if not id_token_str:
        raise app_error(400, "Invalid", "No id_token from Google")

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_str, google_requests.Request(), s.google_client_id
        )
    except ValueError as exc:
        raise app_error(400, "Invalid", f"id_token verification failed: {exc}") from exc

    if not claims.get("email_verified"):
        raise app_error(403, "Forbidden", "Email not verified by Google")

    user = _provision_user(db, claims["email"], claims.get("sub"), claims.get("name"))
    if user is None:
        raise app_error(403, "Forbidden", "This Google account is not authorized")

    console_base = s.researcher_oauth_redirect_uri.split("/auth/callback")[0] + "/"
    resp = _session_response(user, redirect=console_base)
    resp.delete_cookie(STATE_COOKIE)
    return resp


@router.post("/dev-login")
def dev_login(body: DevLoginIn, db: Session = Depends(get_db)):
    s = get_settings()
    if not s.dev_login_allowed:
        raise app_error(
            403,
            "Forbidden",
            "Development sign-in is disabled. Set Google OAuth, or run with ENVIRONMENT=dev "
            "and empty GOOGLE_CLIENT_ID.",
        )
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise app_error(400, "Invalid", "A valid email is required")
    user = _provision_user(db, email, sub=None, name="Local developer")
    if user is None:
        raise app_error(
            403,
            "Forbidden",
            "This email is not on SUPERADMIN_EMAILS, ALLOWED_EMAIL_DOMAINS, or the users table. "
            "Add it to SUPERADMIN_EMAILS or ALLOWED_EMAIL_DOMAINS in .env.",
        )
    return _session_response(user)


@router.post("/logout")
def logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME)
    return resp


@router.get("/me")
def me(user: User | None = Depends(get_optional_user)) -> dict:
    if user is None:
        raise app_error(401, "Unauthorized", "Not authenticated")
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_superuser": user.is_superuser,
    }
