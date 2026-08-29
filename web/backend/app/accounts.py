"""Accounts, survey profiles, encrypted Qualtrics tokens. Returns AppConfig like the desktop app."""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.crypto import decrypt, encrypt
from app.errors import app_error
from app.models import QualtricsAccount, SurveyProfile, User
from app.qualtrics import QualtricsClient, QualtricsError
from app.schemas import Account, AppConfig, Project, TestResult
from app.serialize import (
    account_to_schema,
    app_config_for,
    apply_account_fields,
    apply_project_fields,
)


def load_accounts(db: Session, user: User) -> list[QualtricsAccount]:
    return list(
        db.scalars(
            select(QualtricsAccount)
            .where(QualtricsAccount.owner_user_id == user.id)
            .options(selectinload(QualtricsAccount.profiles))
            .order_by(QualtricsAccount.created_at)
        )
    )


def config_for(db: Session, user: User) -> AppConfig:
    return app_config_for(user, load_accounts(db, user))


def get_account(db: Session, user: User, account_id: str) -> QualtricsAccount:
    row = db.scalar(
        select(QualtricsAccount)
        .where(QualtricsAccount.id == account_id, QualtricsAccount.owner_user_id == user.id)
        .options(selectinload(QualtricsAccount.profiles))
    )
    if row is None:
        raise app_error(404, "NotFound", "that account no longer exists")
    return row


def get_profile(db: Session, user: User, account_id: str, project_id: str) -> SurveyProfile:
    account = get_account(db, user, account_id)
    for p in account.profiles:
        if p.id == project_id:
            return p
    raise app_error(404, "NotFound", "that account or project no longer exists")


def account_token(account: QualtricsAccount) -> str:
    token = decrypt(account.token_ciphertext)
    if not token:
        raise app_error(
            400,
            "Invalid",
            "No API token stored for this account. Save one on the Accounts screen.",
        )
    if not account.data_center.strip():
        raise app_error(400, "Invalid", "Set the data center before talking to Qualtrics.")
    return token


def qualtrics_for(account: QualtricsAccount) -> QualtricsClient:
    return QualtricsClient(account.data_center, account_token(account), account.verify_tls)


def save_account(db: Session, user: User, body: Account) -> AppConfig:
    row = db.get(QualtricsAccount, body.id)
    if row is None:
        row = QualtricsAccount(id=body.id, owner_user_id=user.id)
        db.add(row)
    elif row.owner_user_id != user.id:
        raise app_error(403, "Forbidden", "That account belongs to another researcher.")
    apply_account_fields(row, body)
    db.commit()
    db.expire_all()
    return config_for(db, user)


def delete_account(db: Session, user: User, account_id: str) -> AppConfig:
    row = get_account(db, user, account_id)
    db.delete(row)
    db.commit()
    db.expire_all()
    return config_for(db, user)


def save_project(db: Session, user: User, account_id: str, body: Project) -> AppConfig:
    account = get_account(db, user, account_id)
    existing = next((p for p in account.profiles if p.id == body.id), None)
    if existing is None:
        existing = SurveyProfile(id=body.id, account_id=account.id)
        db.add(existing)
        apply_project_fields(existing, body, keep_copies=False)
    else:
        apply_project_fields(existing, body, keep_copies=True)
    db.commit()
    db.expire_all()
    return config_for(db, user)


def delete_project(db: Session, user: User, account_id: str, project_id: str) -> AppConfig:
    profile = get_profile(db, user, account_id, project_id)
    db.delete(profile)
    db.commit()
    db.expire_all()
    return config_for(db, user)


def forget_survey_copies(db: Session, user: User, account_id: str, project_id: str) -> AppConfig:
    profile = get_profile(db, user, account_id, project_id)
    profile.survey_copies = []
    profile.copies_source_survey_id = ""
    db.commit()
    db.expire_all()
    return config_for(db, user)


def set_token(db: Session, user: User, account_id: str, token: str) -> None:
    token = token.strip()
    if not token:
        raise app_error(400, "Invalid", "the API token is empty")
    row = get_account(db, user, account_id)
    row.token_ciphertext = encrypt(token)
    db.commit()


def has_token(db: Session, user: User, account_id: str) -> bool:
    row = get_account(db, user, account_id)
    return bool(row.token_ciphertext)


def clear_token(db: Session, user: User, account_id: str) -> None:
    row = get_account(db, user, account_id)
    row.token_ciphertext = None
    db.commit()


def test_account(db: Session, user: User, account_id: str) -> TestResult:
    account = get_account(db, user, account_id)
    try:
        with qualtrics_for(account) as client:
            elements = client.get_elements("directories")
    except QualtricsError as exc:
        raise exc.as_http() from exc
    n = len(elements)
    noun = "y" if n == 1 else "ies"
    return TestResult(
        ok=True,
        message=f"Connected. {n} director{noun} visible.",
        directoryCount=n,
    )
