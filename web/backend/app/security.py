"""Researcher session helpers.

Session = a Fernet-encrypted, TTL'd cookie holding the user id (reuses FERNET_KEY).
Google tokens are never stored — the grant is only used to prove identity.
"""

import json

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

COOKIE_NAME = "qs_session"
STATE_COOKIE = "qs_oauth_state"


def _fernet() -> Fernet:
    return Fernet(get_settings().fernet_key.encode())


def make_session(user_id: int) -> str:
    return _fernet().encrypt(json.dumps({"uid": user_id}).encode()).decode()


def _read_session(token: str) -> int | None:
    try:
        raw = _fernet().decrypt(token.encode(), ttl=get_settings().session_ttl_seconds)
        return json.loads(raw).get("uid")
    except (InvalidToken, ValueError):
        return None


def cookie_secure() -> bool:
    """Send the cookie over HTTPS only when the configured callback is HTTPS (so localhost works)."""
    return get_settings().researcher_oauth_redirect_uri.lower().startswith("https")


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    uid = _read_session(token)
    return db.get(User, uid) if uid is not None else None


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"kind": "Unauthorized", "message": "Not authenticated", "retryable": False},
        )
    return user


def require_superuser(user: User = Depends(get_current_user)) -> User:
    if not user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail={"kind": "Forbidden", "message": "Superuser only", "retryable": False},
        )
    return user
