"""Compute a Qualtrics invitation plan and book distributions.

Mirrors desktop QualSched (`commands/schedule_cmds.rs` + `qualtrics/distributions.rs`).
The plan is never stored. PHI stays in Qualtrics; this module only proxies.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from random import Random
from typing import Any

from fastapi import HTTPException

from app import contacts as contacts_svc
from app.eligibility import EligibilityDefaults, contact_eligibility
from app.errors import app_error
from app.models import QualtricsAccount, SurveyProfile
from app.qualtrics import QualtricsClient, QualtricsError
from app.scheduler import (
    SURVEY_LABEL,
    PlanInputs,
    build_contact_plan,
    decorate_message,
    fmt_qualtrics_time,
)
from app.schemas import ItemFailure, PlanItem, SchedulePreview, SendReport, Skipped
from app.serialize import profile_to_project


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_rng() -> Random:
    return Random()


def require_schedule_ids(
    account: QualtricsAccount, profile: SurveyProfile, *, for_execute: bool
) -> None:
    """Missing wiring must be a 400, not an empty plan that looks like nobody to schedule."""
    if not account.default_directory.strip():
        raise app_error(
            400,
            "Invalid",
            "Set the account's contact directory first. "
            "A plan cannot be computed without it.",
        )
    if not profile.mailing_list_id.strip():
        raise app_error(
            400,
            "Invalid",
            "Set this survey profile's mailing list ID first. "
            "An empty result here would look like there is no one to schedule.",
        )
    if not profile.survey_id.strip():
        raise app_error(400, "Invalid", "this project has no survey selected")
    if not profile.message_id.strip():
        raise app_error(400, "Invalid", "this project has no SMS message selected")
    if for_execute and not account.library_id.strip():
        raise app_error(400, "Invalid", "Set the account's message library ID first.")


def _defaults(profile: SurveyProfile) -> EligibilityDefaults:
    return EligibilityDefaults(
        timezone=profile.timezone or "America/Chicago",
        minutes_expire=profile.minutes_expire,
    )


def _to_plan_item(item) -> PlanItem:
    return PlanItem(
        contactId=item.contact_id,
        contactName=item.contact_name,
        destination=item.destination,
        method=item.method,
        dayIndex=item.day_index,
        slotLabel=item.slot_label,
        surveyId=item.survey_id,
        surveyLabel=item.survey_label,
        sendLocal=item.send_local,
        sendUtc=item.send_utc,
        expireUtc=item.expire_utc,
    )


def preview(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    *,
    now: datetime | None = None,
    rng: Random | None = None,
) -> SchedulePreview:
    now = now or utcnow()
    rng = rng or new_rng()
    raw = contacts_svc.list_raw(client, account.default_directory, profile.mailing_list_id)
    defaults = _defaults(profile)
    survey_id = profile.survey_id.strip()

    items: list[PlanItem] = []
    skipped_contacts: list[Skipped] = []
    skipped_slots: list[Skipped] = []

    for contact in raw:
        name = contacts_svc.display_name(contact)
        contact_id = contacts_svc.contact_id_of(contact) or ""
        embedded = contacts_svc.embedded_of(contact)
        result = contact_eligibility(embedded, defaults)
        if isinstance(result, str):
            skipped_contacts.append(
                Skipped(contactId=contact_id, contactName=name, reason=result)
            )
            continue

        destination = (
            contacts_svc.str_field(contact, "phone")
            if result.method == "sms"
            else contacts_svc.str_field(contact, "email")
        )
        if not destination:
            kind = "phone number" if result.method == "sms" else "email address"
            skipped_contacts.append(
                Skipped(
                    contactId=contact_id,
                    contactName=name,
                    reason=f"no {kind} on record",
                )
            )
            continue

        built, dropped = build_contact_plan(
            PlanInputs(
                contact_id=contact_id,
                contact_name=name,
                destination=destination,
                method=result.method,
                slots=result.slots,
                survey_id=survey_id,
                survey_label=SURVEY_LABEL,
                num_days=result.num_days,
                start_date=result.start_date,
                timezone=result.timezone,
                expire_minutes=result.expire_minutes,
            ),
            now,
            rng,
        )
        if not built and dropped:
            skipped_contacts.append(
                Skipped(
                    contactId=contact_id,
                    contactName=name,
                    reason=f"all {len(dropped)} slots dropped ({dropped[0].reason})",
                )
            )
            continue
        items.extend(_to_plan_item(item) for item in built)
        skipped_slots.extend(
            Skipped(contactId=s.contact_id, contactName=s.contact_name, reason=s.reason)
            for s in dropped
        )

    items.sort(key=lambda i: i.sendUtc)
    return SchedulePreview(
        items=items,
        skippedContacts=skipped_contacts,
        skippedSlots=skipped_slots,
        warnings=[],
    )


def get_message_text(client: QualtricsClient, library_id: str, message_id: str) -> str:
    body = client.get(f"libraries/{library_id}/messages/{message_id}")
    result = body.get("result") if isinstance(body, dict) else None
    messages = result.get("messages") if isinstance(result, dict) else None
    text = messages.get("en") if isinstance(messages, dict) else None
    if not isinstance(text, str):
        raise QualtricsError(
            404,
            "NotFound",
            f"message {message_id} in library {library_id} has no 'en' text",
        )
    return text


def send_sms(
    client: QualtricsClient,
    *,
    mailing_list_id: str,
    survey_id: str,
    contact_lookup_id: str,
    message_text: str,
    send_at: datetime,
    expires_at: datetime,
) -> str:
    resp = client.post(
        "distributions/sms",
        {
            "sendDate": fmt_qualtrics_time(send_at),
            "surveyLinkExpirationDate": fmt_qualtrics_time(expires_at),
            "method": "Invite",
            "surveyId": survey_id,
            "name": "SMS message",
            "recipients": {
                "mailingListId": mailing_list_id,
                "contactId": contact_lookup_id,
            },
            "message": {"messageText": message_text},
        },
    )
    return _distribution_id(resp)


def send_email(
    client: QualtricsClient,
    *,
    mailing_list_id: str,
    survey_id: str,
    contact_lookup_id: str,
    message_text: str,
    send_at: datetime,
    expires_at: datetime,
    from_email: str,
    from_name: str,
    reply_to_email: str,
    subject: str,
) -> str:
    resp = client.post(
        "distributions",
        {
            "header": {
                "fromEmail": from_email,
                "fromName": from_name,
                "replyToEmail": reply_to_email,
                "subject": subject,
            },
            "surveyLink": {
                "surveyId": survey_id,
                "type": "Individual",
                "expirationDate": fmt_qualtrics_time(expires_at),
            },
            "sendDate": fmt_qualtrics_time(send_at),
            "recipients": {
                "mailingListId": mailing_list_id,
                "contactId": contact_lookup_id,
            },
            "message": {"messageText": message_text},
        },
    )
    return _distribution_id(resp)


def _distribution_id(resp: dict[str, Any]) -> str:
    result = resp.get("result") if isinstance(resp, dict) else None
    ident = result.get("id") if isinstance(result, dict) else None
    return ident if isinstance(ident, str) else ""


def _exc_message(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, QualtricsError):
        return exc.message, exc.retryable
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "message" in detail:
            return str(detail["message"]), bool(detail.get("retryable", False))
        return str(detail), False
    return str(exc), False


def execute(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    plan: SchedulePreview,
    *,
    now: datetime | None = None,
    rng: Random | None = None,
) -> SendReport:
    now = now or utcnow()
    rng = rng or new_rng()
    survey_id = profile.survey_id.strip()
    project = profile_to_project(profile)

    raw = contacts_svc.list_raw(client, account.default_directory, profile.mailing_list_id)
    by_id = {cid: c for c in raw if (cid := contacts_svc.contact_id_of(c))}

    failed: list[ItemFailure] = []
    bookkeeping_failures: list[ItemFailure] = []
    lookup_cache: dict[str, str] = {}
    message_cache: dict[str, str] = {}
    sent_per_contact: dict[str, int] = {}

    def fail(item: PlanItem, error: str, retryable: bool) -> None:
        failed.append(
            ItemFailure(
                contactName=item.contactName,
                destination=item.destination,
                sendLocal=item.sendLocal,
                error=error,
                retryable=retryable,
            )
        )

    for item in plan.items:
        if item.sendUtc <= now:
            fail(
                item,
                "send time passed while the preview was open; re-run the preview",
                False,
            )
            continue

        contact = by_id.get(item.contactId)
        if contact is None:
            fail(item, "this participant is no longer in the mailing list", False)
            continue

        if item.surveyId != survey_id:
            fail(
                item,
                f"this plan sends through survey {item.surveyId}, but the profile now "
                f"sends through {survey_id}; re-run the preview",
                False,
            )
            continue

        try:
            if item.contactId in lookup_cache:
                lookup_id = lookup_cache[item.contactId]
            else:
                lookup_id = contacts_svc.resolve_contact_lookup_id(
                    client,
                    account.default_directory,
                    profile.mailing_list_id,
                    contact,
                )
                lookup_cache[item.contactId] = lookup_id
        except (QualtricsError, HTTPException) as exc:
            message, retryable = _exc_message(exc)
            fail(item, message, retryable)
            continue

        if item.method == "sms":
            message_id = profile.message_id
        else:
            if not profile.message_id_email.strip():
                fail(item, "this project has no email message selected", False)
                continue
            message_id = profile.message_id_email

        try:
            if message_id in message_cache:
                body = message_cache[message_id]
            else:
                body = get_message_text(client, account.library_id, message_id)
                message_cache[message_id] = body
        except (QualtricsError, HTTPException) as exc:
            message, retryable = _exc_message(exc)
            fail(item, message, retryable)
            continue

        text = decorate_message(body, item.method, rng)
        try:
            if item.method == "sms":
                send_sms(
                    client,
                    mailing_list_id=profile.mailing_list_id,
                    survey_id=item.surveyId,
                    contact_lookup_id=lookup_id,
                    message_text=text,
                    send_at=item.sendUtc,
                    expires_at=item.expireUtc,
                )
            else:
                send_email(
                    client,
                    mailing_list_id=profile.mailing_list_id,
                    survey_id=item.surveyId,
                    contact_lookup_id=lookup_id,
                    message_text=text,
                    send_at=item.sendUtc,
                    expires_at=item.expireUtc,
                    from_email=project.emailHeader.fromEmail,
                    from_name=project.emailHeader.fromName,
                    reply_to_email=project.emailHeader.replyToEmail,
                    subject=project.emailHeader.subject,
                )
        except QualtricsError as exc:
            fail(item, exc.message, exc.retryable)
            _pace()
            continue

        sent_per_contact[item.contactId] = sent_per_contact.get(item.contactId, 0) + 1
        _pace()

    scheduled = 0
    for contact_id, count in sent_per_contact.items():
        scheduled += count
        contact = by_id.get(contact_id)
        if contact is None:
            continue
        log = {
            "action": "send",
            "count": count,
            "ts": utcnow().isoformat(timespec="seconds"),
        }
        try:
            contacts_svc.update_contact(
                client,
                account.default_directory,
                profile.mailing_list_id,
                contact,
                {},
                [],
                {"SurveysScheduled": str(count)},
                log,
            )
        except (QualtricsError, HTTPException) as exc:
            message, _retryable = _exc_message(exc)
            bookkeeping_failures.append(
                ItemFailure(
                    contactName=contacts_svc.display_name(contact),
                    destination="",
                    sendLocal="",
                    error=(
                        f"{count} invitations were scheduled but SurveysScheduled could "
                        f"not be updated ({message}). Set it to {count} manually, or a "
                        "re-run will schedule this contact again."
                    ),
                    retryable=True,
                )
            )
        _pace()

    return SendReport(
        scheduled=scheduled,
        failed=failed,
        bookkeepingFailures=bookkeeping_failures,
    )


def _pace() -> None:
    delay = contacts_svc.WRITE_PACING_SECONDS
    if delay > 0:
        time.sleep(delay)
