"""Thin Qualtrics list proxies. Results are not stored. Token never leaves the server."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts import get_account, qualtrics_for
from app.db import get_db
from app.errors import app_error
from app.models import User
from app.qualtrics import QualtricsError
from app.schemas import IdName, MailingListInfo, MessageInfo
from app.security import get_current_user

router = APIRouter(prefix="/api/accounts/{account_id}", tags=["lookups"])


def _client(db: Session, user: User, account_id: str):
    return qualtrics_for(get_account(db, user, account_id))


@router.get("/directories", response_model=list[IdName])
def list_directories(
    account_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        with _client(db, user, account_id) as client:
            elements = client.get_elements("directories")
    except QualtricsError as exc:
        raise exc.as_http() from exc
    out = []
    for e in elements:
        did = e.get("directoryId")
        if not did:
            continue
        out.append(IdName(id=did, name=e.get("name") or "(unnamed)"))
    return out


@router.get("/surveys", response_model=list[IdName])
def list_surveys(
    account_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        with _client(db, user, account_id) as client:
            elements = client.get_elements("surveys")
    except QualtricsError as exc:
        raise exc.as_http() from exc
    out = []
    for e in elements:
        sid = e.get("id")
        if not sid:
            continue
        out.append(IdName(id=sid, name=e.get("name") or "(unnamed)"))
    return out


@router.get("/mailing-lists", response_model=list[MailingListInfo])
def list_mailing_lists(
    account_id: str,
    directoryId: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = get_account(db, user, account_id)
    directory_id = directoryId or account.default_directory
    if not directory_id:
        raise app_error(400, "Invalid", "Set the account's contact directory first.")
    try:
        with qualtrics_for(account) as client:
            elements = client.get_elements(
                f"directories/{directory_id}/mailinglists?includeCount=true"
            )
    except QualtricsError as exc:
        raise exc.as_http() from exc
    out = []
    for e in elements:
        mid = e.get("mailingListId")
        if not mid:
            continue
        count = e.get("contactCount")
        out.append(
            MailingListInfo(
                id=mid,
                name=e.get("name") or "(unnamed)",
                contactCount=int(count) if isinstance(count, (int, float)) else None,
            )
        )
    return out


@router.get("/messages", response_model=list[MessageInfo])
def list_messages(
    account_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    account = get_account(db, user, account_id)
    if not account.library_id:
        raise app_error(400, "Invalid", "Set the account's message library ID first.")
    try:
        with qualtrics_for(account) as client:
            elements = client.get_elements(f"libraries/{account.library_id}/messages")
    except QualtricsError as exc:
        raise exc.as_http() from exc
    out = []
    for e in elements:
        mid = e.get("id")
        if not mid:
            continue
        out.append(
            MessageInfo(
                id=mid,
                description=e.get("description") or "(no description)",
                category=e.get("category"),
            )
        )
    return out


@router.get("/messages/{message_id}/text")
def get_message_text(
    account_id: str,
    message_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> str:
    account = get_account(db, user, account_id)
    if not account.library_id:
        raise app_error(400, "Invalid", "Set the account's message library ID first.")
    try:
        with qualtrics_for(account) as client:
            body = client.get(f"libraries/{account.library_id}/messages/{message_id}")
    except QualtricsError as exc:
        raise exc.as_http() from exc
    result = body.get("result") if isinstance(body, dict) else None
    messages = result.get("messages") if isinstance(result, dict) else None
    text = messages.get("en") if isinstance(messages, dict) else None
    if not isinstance(text, str):
        raise app_error(
            404,
            "NotFound",
            f"message {message_id} in library {account.library_id} has no 'en' text",
        )
    return text
