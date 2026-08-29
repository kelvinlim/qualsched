"""Live Qualtrics mailing-list contacts. Results are not stored. Token never leaves the server."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts import account_token, get_account, qualtrics_for
from app.contacts import apply_defaults, create_view, delete_view, list_views, update_view
from app.db import get_db
from app.errors import app_error
from app.models import QualtricsAccount, SurveyProfile, User
from app.qualtrics import QualtricsError
from app.schemas import (
    ContactCreateIn,
    ContactDefaultsIn,
    ContactUpdateIn,
    ContactView,
    RemovedContact,
)
from app.security import get_current_user

router = APIRouter(
    prefix="/api/accounts/{account_id}/projects/{project_id}/contacts",
    tags=["contacts"],
)


def _context(
    db: Session, user: User, account_id: str, project_id: str
) -> tuple[QualtricsAccount, SurveyProfile]:
    account = get_account(db, user, account_id)
    profile = next((p for p in account.profiles if p.id == project_id), None)
    if profile is None:
        raise app_error(404, "NotFound", "that account or project no longer exists")
    # Token / data-center first so a missing token is not reported as an empty list.
    account_token(account)
    if not account.default_directory.strip():
        raise app_error(
            400,
            "Invalid",
            "Set the account's contact directory first. Contacts cannot be loaded without it.",
        )
    if not profile.mailing_list_id.strip():
        raise app_error(
            400,
            "Invalid",
            "Set this survey profile's mailing list ID first. "
            "An empty result here would look like there are no participants.",
        )
    return account, profile


@router.get("", response_model=list[ContactView])
def get_contacts(
    account_id: str,
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, profile = _context(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return list_views(client, account, profile)
    except QualtricsError as exc:
        raise exc.as_http() from exc


@router.post("", response_model=ContactView)
def create_contact(
    account_id: str,
    project_id: str,
    body: ContactCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, profile = _context(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return create_view(client, account, profile, body.core, body.embedded)
    except QualtricsError as exc:
        raise exc.as_http() from exc


@router.post("/defaults", response_model=list[ContactView])
def apply_embedded_defaults(
    account_id: str,
    project_id: str,
    body: ContactDefaultsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, profile = _context(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return apply_defaults(client, account, profile, body.contactIds)
    except QualtricsError as exc:
        raise exc.as_http() from exc


@router.put("/{contact_id}", response_model=ContactView)
def update_contact(
    account_id: str,
    project_id: str,
    contact_id: str,
    body: ContactUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, profile = _context(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return update_view(client, account, profile, contact_id, body.core, body.fields)
    except QualtricsError as exc:
        raise exc.as_http() from exc


@router.delete("/{contact_id}", response_model=RemovedContact)
def delete_contact(
    account_id: str,
    project_id: str,
    contact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, profile = _context(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return delete_view(client, account, profile, contact_id)
    except QualtricsError as exc:
        raise exc.as_http() from exc
