"""Schedule preview and execute. Plans are not stored. Token never leaves the server."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.accounts import account_token, get_account, qualtrics_for
from app.db import get_db
from app.errors import app_error
from app.models import QualtricsAccount, SurveyProfile, User
from app.qualtrics import QualtricsError
from app.schedule import execute, preview, require_schedule_ids
from app.schemas import SchedulePreview, SendReport
from app.security import get_current_user

router = APIRouter(
    prefix="/api/accounts/{account_id}/projects/{project_id}/schedule",
    tags=["schedule"],
)


def _context(
    db: Session, user: User, account_id: str, project_id: str, *, for_execute: bool
) -> tuple[QualtricsAccount, SurveyProfile]:
    account = get_account(db, user, account_id)
    profile = next((p for p in account.profiles if p.id == project_id), None)
    if profile is None:
        raise app_error(404, "NotFound", "that account or project no longer exists")
    # Token / data-center first so a missing token is not reported as an empty plan.
    account_token(account)
    require_schedule_ids(account, profile, for_execute=for_execute)
    return account, profile


@router.post("/preview", response_model=SchedulePreview)
def preview_schedule(
    account_id: str,
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, profile = _context(db, user, account_id, project_id, for_execute=False)
    try:
        with qualtrics_for(account) as client:
            return preview(client, account, profile)
    except QualtricsError as exc:
        raise exc.as_http() from exc


@router.post("/execute", response_model=SendReport)
def execute_schedule(
    account_id: str,
    project_id: str,
    body: SchedulePreview,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account, profile = _context(db, user, account_id, project_id, for_execute=True)
    try:
        with qualtrics_for(account) as client:
            return execute(client, account, profile, body)
    except QualtricsError as exc:
        raise exc.as_http() from exc
