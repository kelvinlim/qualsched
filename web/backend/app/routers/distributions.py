"""Live Qualtrics distributions. Results are not stored. Token never leaves the server."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts import account_token, get_account, qualtrics_for
from app.db import get_db
from app.distributions import (
    delete_selected,
    delete_unsent_for_contact,
    list_views,
    require_distribution_ids,
)
from app.errors import app_error
from app.models import QualtricsAccount, SurveyProfile, User
from app.qualtrics import QualtricsError
from app.schemas import DeleteDistributionsIn, DeleteReport, DistributionRow
from app.security import get_current_user

router = APIRouter(
    prefix="/api/accounts/{account_id}/projects/{project_id}/distributions",
    tags=["distributions"],
)


def _context(
    db: Session, user: User, account_id: str, project_id: str
) -> tuple[QualtricsAccount, SurveyProfile]:
    account = get_account(db, user, account_id)
    profile = next((p for p in account.profiles if p.id == project_id), None)
    if profile is None:
        raise app_error(404, "NotFound", "that account or project no longer exists")
    # Token / data-center first so a missing token is not reported as an empty table.
    account_token(account)
    require_distribution_ids(account, profile)
    return account, profile


@router.get("", response_model=list[DistributionRow])
def get_distributions(
    account_id: str,
    project_id: str,
    method: Literal["sms", "email"],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, profile = _context(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return list_views(client, account, profile, method)
    except QualtricsError as exc:
        raise exc.as_http() from exc


@router.delete("", response_model=DeleteReport)
def cancel_distributions(
    account_id: str,
    project_id: str,
    body: DeleteDistributionsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, _profile = _context(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return delete_selected(client, body.method, body.targets)
    except QualtricsError as exc:
        raise exc.as_http() from exc


@router.delete("/unsent/{contact_id}", response_model=DeleteReport)
def cancel_unsent_for_contact(
    account_id: str,
    project_id: str,
    contact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, profile = _context(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return delete_unsent_for_contact(client, account, profile, contact_id)
    except QualtricsError as exc:
        raise exc.as_http() from exc
