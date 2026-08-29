"""List and cancel Qualtrics distributions. PHI is proxied live and never written to the DB.

Mirrors desktop QualSched (`qualtrics/distributions.rs` + `commands/distribution_cmds.rs`):
list a profile's own survey and any leftover 0.1.4 clones, resolve recipients from the
mailing list, and DELETE unsent invitations against the survey they were created with.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from app import contacts as contacts_svc
from app.errors import app_error
from app.models import QualtricsAccount, SurveyProfile
from app.qualtrics import QualtricsClient, QualtricsError
from app.scheduler import fmt_qualtrics_time
from app.schemas import DeleteFailure, DeleteReport, DeleteTarget, DistributionRow
from app.serialize import profile_to_project

Method = Literal["sms", "email"]

QUALTRICS_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SurveyRef:
    id: str
    label: str


def require_distribution_ids(account: QualtricsAccount, profile: SurveyProfile) -> None:
    """Missing wiring must be a 400, not an empty table that looks like no invitations."""
    if not account.default_directory.strip():
        raise app_error(
            400,
            "Invalid",
            "Set the account's contact directory first. "
            "Invitations cannot be listed without it.",
        )
    if not profile.mailing_list_id.strip():
        raise app_error(
            400,
            "Invalid",
            "Set this survey profile's mailing list ID first. "
            "An empty result here would look like there are no invitations.",
        )
    if not profile.survey_id.strip():
        raise app_error(400, "Invalid", "this project has no survey selected")


def survey_rotation(profile: SurveyProfile) -> list[SurveyRef]:
    """The profile survey plus leftover 0.1.4 clones, labelled original / c1 / c2.

    Listing and cancel still have to reach a clone; scheduling no longer sends through them.
    """
    refs = [SurveyRef(id=profile.survey_id.strip(), label="original")]
    copies = profile.survey_copies or []
    for index, copy in enumerate(copies):
        if not isinstance(copy, dict):
            continue
        copy_id = str(copy.get("id") or "").strip()
        if copy_id:
            refs.append(SurveyRef(id=copy_id, label=f"c{index + 1}"))
    return refs


def parse_send_date(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, QUALTRICS_TIME_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def local_send_time(send_date: str, timezone_name: str) -> str:
    """Wall-clock time in the recipient's zone. Empty rather than a guess on bad input."""
    try:
        tz = ZoneInfo(timezone_name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return ""
    utc = parse_send_date(send_date)
    if utc is None:
        return ""
    return utc.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")


def _list_path(method: Method, mailing_list_id: str, survey_id: str) -> str:
    if method == "sms":
        return f"distributions/sms?surveyId={survey_id}"
    return (
        f"distributions?mailingListId={mailing_list_id}&surveyId={survey_id}"
        "&distributionRequestType=Invite&useNewPaginationScheme=true"
    )


def _delete_path(method: Method, distribution_id: str, survey_id: str) -> str:
    if method == "sms":
        return f"distributions/sms/{distribution_id}?surveyId={survey_id}"
    return f"distributions/{distribution_id}"


def _contact_id_from_element(element: dict[str, Any]) -> str:
    recipients = element.get("recipients")
    if isinstance(recipients, dict):
        contact_id = recipients.get("contactId")
        if isinstance(contact_id, str):
            return contact_id
    return ""


def list_for_survey(
    client: QualtricsClient,
    mailing_list_id: str,
    survey: SurveyRef,
    method: Method,
    now: datetime,
) -> list[DistributionRow]:
    elements = client.get_elements(_list_path(method, mailing_list_id, survey.id))
    now_str = fmt_qualtrics_time(now)
    rows: list[DistributionRow] = []
    for element in elements:
        ident = element.get("id")
        if not isinstance(ident, str) or not ident:
            continue
        send_date = element.get("sendDate")
        send_date = send_date if isinstance(send_date, str) else ""
        rows.append(
            DistributionRow(
                id=ident,
                contactLookupId=_contact_id_from_element(element),
                contactName="",
                contactPhone="",
                contactEmail="",
                sendDate=send_date,
                sendLocal="",
                method=method,
                unsent=send_date > now_str,
                surveyId=survey.id,
                surveyLabel=survey.label,
            )
        )
    return rows


def list_raw_rows(
    client: QualtricsClient,
    profile: SurveyProfile,
    method: Method,
    now: datetime,
) -> list[DistributionRow]:
    own_id = profile.survey_id.strip()
    rows: list[DistributionRow] = []
    for survey in survey_rotation(profile):
        try:
            rows.extend(
                list_for_survey(client, profile.mailing_list_id, survey, method, now)
            )
        except QualtricsError as exc:
            # A clone the user deleted in Qualtrics 404s. That must not empty the table
            # or break contact removal, which cancels pending rows first. Only a missing
            # clone is tolerated; a missing project survey or any other error still
            # propagates rather than showing a silently short list.
            if exc.status == 404 and survey.id != own_id:
                continue
            raise
    return rows


@dataclass
class Recipient:
    name: str
    zone: str
    phone: str
    email: str


def _recipients(
    client: QualtricsClient, account: QualtricsAccount, profile: SurveyProfile
) -> dict[str, Recipient]:
    project = profile_to_project(profile)
    default_zone = project.embeddedDefaults.timeZone
    raw = contacts_svc.list_raw(client, account.default_directory, profile.mailing_list_id)
    found: dict[str, Recipient] = {}
    for contact in raw:
        try:
            lookup = contacts_svc.resolve_contact_lookup_id(
                client, account.default_directory, profile.mailing_list_id, contact
            )
        except (QualtricsError, HTTPException):
            continue
        embedded = contacts_svc.embedded_of(contact)
        zone = (embedded.get("TimeZone") or "").strip() or default_zone
        found[lookup] = Recipient(
            name=contacts_svc.display_name(contact),
            zone=zone,
            phone=contacts_svc.str_field(contact, "phone"),
            email=contacts_svc.str_field(contact, "email"),
        )
    return found


def list_views(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    method: Method,
    *,
    now: datetime | None = None,
) -> list[DistributionRow]:
    now = now or utcnow()
    rows = list_raw_rows(client, profile, method, now)
    recipients = _recipients(client, account, profile)
    resolved: list[DistributionRow] = []
    for row in rows:
        recipient = recipients.get(row.contactLookupId)
        if recipient is None:
            resolved.append(row)
            continue
        resolved.append(
            row.model_copy(
                update={
                    "contactName": recipient.name,
                    "contactPhone": recipient.phone,
                    "contactEmail": recipient.email,
                    "sendLocal": local_send_time(row.sendDate, recipient.zone),
                }
            )
        )
    resolved.sort(key=lambda r: r.sendDate)
    return resolved


def delete_distribution(
    client: QualtricsClient, survey_id: str, method: Method, distribution_id: str
) -> None:
    client.delete(_delete_path(method, distribution_id, survey_id))


def _pace() -> None:
    delay = contacts_svc.WRITE_PACING_SECONDS
    if delay > 0:
        time.sleep(delay)


def delete_selected(
    client: QualtricsClient, method: Method, targets: list[DeleteTarget]
) -> DeleteReport:
    deleted = 0
    failed: list[DeleteFailure] = []
    for target in targets:
        try:
            delete_distribution(client, target.surveyId, method, target.id)
            deleted += 1
        except QualtricsError as exc:
            failed.append(DeleteFailure(id=target.id, error=exc.message))
        _pace()
    return DeleteReport(deleted=deleted, failed=failed)


def contact_method_of(contact: dict[str, Any]) -> Method:
    """Desktop cancel-pending: email only when ContactMethod is email; otherwise SMS."""
    embedded = contacts_svc.embedded_of(contact)
    return "email" if embedded.get("ContactMethod", "").strip().lower() == "email" else "sms"


def cancel_pending_for_contact(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    contact: dict[str, Any],
    *,
    now: datetime | None = None,
) -> DeleteReport:
    now = now or utcnow()
    method = contact_method_of(contact)
    lookup_id = contacts_svc.resolve_contact_lookup_id(
        client, account.default_directory, profile.mailing_list_id, contact
    )
    rows = list_raw_rows(client, profile, method, now)
    targets = [row for row in rows if row.contactLookupId == lookup_id and row.unsent]
    deleted = 0
    failed: list[DeleteFailure] = []
    for row in targets:
        try:
            delete_distribution(client, row.surveyId, method, row.id)
            deleted += 1
        except QualtricsError as exc:
            failed.append(DeleteFailure(id=row.id, error=exc.message))
        _pace()
    return DeleteReport(deleted=deleted, failed=failed)


def delete_unsent_for_contact(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    contact_id: str,
    *,
    now: datetime | None = None,
) -> DeleteReport:
    raw = contacts_svc.list_raw(client, account.default_directory, profile.mailing_list_id)
    contact = contacts_svc.find_in_list(raw, contact_id)
    report = cancel_pending_for_contact(client, account, profile, contact, now=now)

    updates = {"DeleteUnsent": "0"}
    # Cancelled invitations are no longer scheduled; leaving the counter set would block
    # any future scheduling for this contact.
    if not report.failed:
        updates["SurveysScheduled"] = "0"
    contacts_svc.update_contact(
        client,
        account.default_directory,
        profile.mailing_list_id,
        contact,
        {},
        [],
        updates,
        {
            "action": "delete_unsent",
            "count": report.deleted,
            "ts": utcnow().isoformat(timespec="seconds"),
        },
    )
    return report
