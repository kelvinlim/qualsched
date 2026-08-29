"""YAML import/export of survey-profile settings. Tokens are optional on import, never on export."""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app import accounts as svc
from app.db import get_db
from app.importexport import build_legacy_yaml, parse_config, parse_token_file
from app.models import User
from app.schemas import AppConfig, ImportConfirm, ImportPreview
from app.security import get_current_user
from app.serialize import account_to_schema

router = APIRouter(prefix="/api", tags=["import-export"])


@router.post("/import/preview", response_model=ImportPreview)
async def preview_import(
    yaml: UploadFile = File(...),
    tokenFile: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
):
    text = (await yaml.read()).decode("utf-8", errors="replace")
    preview = parse_config(text, yaml.filename or "config.yaml")
    if tokenFile is not None:
        token_text = (await tokenFile.read()).decode("utf-8", errors="replace")
        preview.tokenFound = parse_token_file(token_text) is not None
    return preview


@router.post("/import/preview-text", response_model=ImportPreview)
def preview_import_text(
    yamlText: str = Form(...),
    sourceName: str = Form("config.yaml"),
    tokenText: str = Form(""),
    user: User = Depends(get_current_user),
):
    preview = parse_config(yamlText, sourceName)
    if tokenText.strip():
        preview.tokenFound = parse_token_file(tokenText) is not None or bool(tokenText.strip())
    return preview


@router.post("/import/confirm", response_model=AppConfig)
def confirm_import(
    body: ImportConfirm,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_id = body.targetAccountId
    if target_id:
        # Add the profile only; the existing account's token and connection stay untouched.
        cfg = svc.save_project(db, user, target_id, body.project)
        return cfg

    cfg = svc.save_account(db, user, body.account)
    cfg = svc.save_project(db, user, body.account.id, body.project)
    if body.token and body.token.strip():
        svc.set_token(db, user, body.account.id, body.token)
    return cfg


@router.get("/accounts/{account_id}/projects/{project_id}/export")
def export_project(
    account_id: str,
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = svc.get_account(db, user, account_id)
    profile = svc.get_profile(db, user, account_id, project_id)
    schema = account_to_schema(account)
    project = next(p for p in schema.projects if p.id == profile.id)
    yaml_text = build_legacy_yaml(schema, project)
    if "QUALTRICS_APITOKEN" in yaml_text:
        raise RuntimeError("refusing to export a file that contains QUALTRICS_APITOKEN")
    return PlainTextResponse(yaml_text, media_type="text/yaml")
