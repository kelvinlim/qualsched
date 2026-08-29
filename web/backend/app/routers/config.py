"""App-config CRUD + token write/has-token (never returns the raw token)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import accounts as svc
from app.db import get_db
from app.models import User
from app.schemas import Account, AppConfig, Project, TokenIn
from app.security import get_current_user

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=AppConfig)
def get_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc.config_for(db, user)


@router.post("/accounts", response_model=AppConfig)
def save_account(
    body: Account, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return svc.save_account(db, user, body)


@router.delete("/accounts/{account_id}", response_model=AppConfig)
def delete_account(
    account_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return svc.delete_account(db, user, account_id)


@router.put("/accounts/{account_id}/token")
def set_token(
    account_id: str,
    body: TokenIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc.set_token(db, user, account_id, body.token)
    return {"ok": True}


@router.get("/accounts/{account_id}/has-token")
def has_token(
    account_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> bool:
    return svc.has_token(db, user, account_id)


@router.delete("/accounts/{account_id}/token")
def clear_token(
    account_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    svc.clear_token(db, user, account_id)
    return {"ok": True}


@router.post("/accounts/{account_id}/test")
def test_account(
    account_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return svc.test_account(db, user, account_id)


@router.post("/accounts/{account_id}/projects", response_model=AppConfig)
def save_project(
    account_id: str,
    body: Project,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.save_project(db, user, account_id, body)


@router.delete("/accounts/{account_id}/projects/{project_id}", response_model=AppConfig)
def delete_project(
    account_id: str,
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.delete_project(db, user, account_id, project_id)


@router.post("/accounts/{account_id}/projects/{project_id}/forget-copies", response_model=AppConfig)
def forget_copies(
    account_id: str,
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.forget_survey_copies(db, user, account_id, project_id)
