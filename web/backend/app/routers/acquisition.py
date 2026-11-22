"""Acquisition heatmap. Qualtrics calls stay on the server; the browser gets aggregates."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.accounts import account_token, get_account, qualtrics_for
from app.acquisition import (
    AcquisitionParseError,
    AcquisitionReport,
    MonitorIn,
    MonitorUpdate,
    load_report,
    set_monitor_status,
)
from app.db import get_db
from app.errors import app_error
from app.models import User
from app.qualtrics import QualtricsError
from app.security import get_current_user

router = APIRouter(
    prefix="/api/accounts/{account_id}/projects/{project_id}/acquisition",
    tags=["acquisition"],
)


def _profile(db: Session, user: User, account_id: str, project_id: str):
    account = get_account(db, user, account_id)
    profile = next((item for item in account.profiles if item.id == project_id), None)
    if profile is None:
        raise app_error(404, "NotFound", "that account or project no longer exists")
    account_token(account)
    if not account.default_directory.strip() or not profile.mailing_list_id.strip():
        raise app_error(
            400,
            "Invalid",
            "Set the contact directory and mailing list before loading acquisition.",
        )
    if not profile.survey_id.strip():
        raise app_error(400, "Invalid", "this project has no survey selected")
    return account, profile


@router.get("", response_model=AcquisitionReport)
def get_acquisition(
    account_id: str,
    project_id: str,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Aggregates include participant names. Do not let the browser store the body.
    response.headers["Cache-Control"] = "no-store"
    account, profile = _profile(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return load_report(client, account, profile)
    except QualtricsError as exc:
        raise exc.as_http() from None
    except AcquisitionParseError as exc:
        raise app_error(502, "Api", str(exc)) from None


@router.put("/status", response_model=MonitorUpdate)
def put_monitor_status(
    account_id: str,
    project_id: str,
    body: MonitorIn,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    account, profile = _profile(db, user, account_id, project_id)
    try:
        with qualtrics_for(account) as client:
            return set_monitor_status(client, account, profile, body.contactId, body.status)
    except QualtricsError as exc:
        raise exc.as_http() from None
