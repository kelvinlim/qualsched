"""Acquisition heatmap. Qualtrics calls stay on the server; the browser gets aggregates."""

import logging
import re
import threading
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import acquisition as acquisition_mod
from app.accounts import account_token, get_account, qualtrics_for
from app.acquisition import (
    _STATUS_CB,
    AcquisitionParseError,
    AcquisitionReport,
    MonitorIn,
    MonitorUpdate,
    PendingExport,
    claim_run,
    error_type_name,
    export_failure,
    fail_run,
    finish_run,
    load_report,
    publish_status,
    read_run,
    run_cancelled,
    set_monitor_status,
    status_log_token,
    status_text,
)
from app.db import get_db
from app.errors import app_error
from app.models import User
from app.qualtrics import QualtricsError
from app.security import get_current_user

log = logging.getLogger("qualsched.acquisition")

_ATTEMPT = re.compile(r"^[A-Za-z0-9_-]{8,80}$")

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


class _AccountSnapshot:
    """Fields the worker needs after the request session has closed."""

    def __init__(self, account) -> None:
        self.id = account.id
        self.data_center = account.data_center
        self.token_ciphertext = account.token_ciphertext
        self.verify_tls = account.verify_tls
        self.default_directory = account.default_directory


class _ProfileSnapshot:
    def __init__(self, profile) -> None:
        self.id = profile.id
        self.survey_id = profile.survey_id
        self.mailing_list_id = profile.mailing_list_id
        self.timezone = profile.timezone or ""
        copies = profile.survey_copies or []
        self.survey_copies = [dict(item) for item in copies if isinstance(item, dict)]


def _start_worker(target, args) -> None:
    threading.Thread(target=target, args=args, daemon=True, name="acquisition").start()


def _worker(account, profile, user_id: int, attempt: str) -> None:
    key = (user_id, account.id, profile.id)
    stage = {"name": "start"}
    started = time.monotonic()
    last = {"at": started, "token": "connecting"}

    def on_status(text: str, next_stage: str) -> None:
        now = time.monotonic()
        log.info(
            "acquisition stage=%s duration_ms=%d",
            last["token"],
            int((now - last["at"]) * 1000),
        )
        last["at"] = now
        last["token"] = status_log_token(text)
        if next_stage in {"start", "poll", "download", "parse"}:
            stage["name"] = next_stage
        publish_status(key, attempt, text, next_stage)

    token_ctx = _STATUS_CB.set(on_status)
    try:
        with qualtrics_for(account) as client:
            report = load_report(
                client,
                account,
                profile,
                user_id=user_id,
                attempt=attempt,
                sleep=acquisition_mod.time.sleep,
                stop=lambda: run_cancelled(key, attempt),
            )
        finish_run(key, attempt, report)
        log.info(
            "acquisition stage=%s duration_ms=%d",
            last["token"],
            int((time.monotonic() - last["at"]) * 1000),
        )
    except QualtricsError as exc:
        fail_run(key, attempt, exc)
        log.info(
            "acquisition stage=%s duration_ms=%d error=QualtricsError",
            stage["name"],
            int((time.monotonic() - started) * 1000),
        )
    except AcquisitionParseError:
        fail_run(key, attempt, export_failure("parse", detail="could not be read"))
        log.info(
            "acquisition stage=parse duration_ms=%d error=AcquisitionParseError",
            int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 — unexpected failures become a stage and a type name
        kind = error_type_name(exc)
        failed = stage["name"]
        if failed not in {"start", "poll", "download", "parse"}:
            failed = "start"
        fail_run(key, attempt, export_failure(failed, error_type=kind))
        log.info(
            "acquisition stage=%s duration_ms=%d error=%s",
            failed,
            int((time.monotonic() - started) * 1000),
            kind,
        )
    finally:
        _STATUS_CB.reset(token_ctx)


@router.get("", response_model=AcquisitionReport)
def get_acquisition(
    account_id: str,
    project_id: str,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    attempt: str | None = Header(default=None, alias="X-Qualsched-Attempt"),
):
    # Aggregates include participant names. Do not let the browser store the body.
    response.headers["Cache-Control"] = "no-store"
    account, profile = _profile(db, user, account_id, project_id)
    # Same attempt continues one in-memory export. A new attempt starts over.
    token = attempt if attempt and _ATTEMPT.fullmatch(attempt) else f"once{time.monotonic_ns()}"
    creds = _AccountSnapshot(account)
    view = _ProfileSnapshot(profile)
    try:
        run, start = claim_run(user.id, creds.id, view.id, token)
        if start:
            # The Qualtrics work continues after this response. The browser reads
            # the in-memory status on the next request with the same attempt.
            _start_worker(_worker, (creds, view, user.id, token))
        outcome = read_run(run)
    except HTTPException:
        raise
    except QualtricsError as exc:
        raise exc.as_http() from None
    except AcquisitionParseError:
        raise export_failure("parse", detail="could not be read").as_http() from None
    except Exception as exc:  # noqa: BLE001 — unexpected failures become a stage and a type name
        raise export_failure("start", error_type=error_type_name(exc)).as_http() from None
    if isinstance(outcome, PendingExport):
        stage = outcome.stage if outcome.stage in {"start", "poll", "download", "parse"} else "poll"
        body: dict[str, object] = {"pending": True, "stage": stage}
        shown = status_text(outcome.status)
        if shown:
            body["status"] = shown
        return JSONResponse(body, status_code=202, headers={"Cache-Control": "no-store"})
    return outcome


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
