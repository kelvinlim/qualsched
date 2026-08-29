"""Qualtrics mailing-list contacts. PHI is proxied live and never written to the DB.

Mirrors desktop QualSched (`qualtrics/contacts.rs` + `commands/contact_cmds.rs`):
list/create/update/delete against
`directories/{directoryId}/mailinglists/{mailingListId}/contacts`.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.eligibility import EligibilityDefaults, contact_eligibility, delivery_method
from app.errors import app_error
from app.models import QualtricsAccount, SurveyProfile
from app.qualtrics import QualtricsClient
from app.schemas import ContactView, EmbeddedDefaults, RemovedContact
from app.serialize import profile_to_project

# Identity fields Qualtrics accepts on a mailing-list contact. Anything else is embedded.
CORE_FIELDS = ("firstName", "lastName", "email", "phone", "extRef")

# Cap on retained LogData entries. Qualtrics limits embedded-data field size.
LOG_DATA_MAX = 50

# Qualtrics throttles bursts; a small gap between writes keeps large batches under the limit.
WRITE_PACING_SECONDS = 0.12


def embedded_defaults_pairs(defaults: EmbeddedDefaults) -> list[tuple[str, str]]:
    """The embedded-data key/value pairs this default set contributes to a contact."""
    return [
        ("StartDate", defaults.startDate),
        ("SurveysScheduled", str(defaults.surveysScheduled)),
        ("TimeSlots", defaults.timeSlots),
        ("ContactMethod", defaults.contactMethod),
        ("DeleteUnsent", str(defaults.deleteUnsent)),
        ("NumDays", str(defaults.numDays)),
        ("ExpireMinutes", str(defaults.expireMinutes)),
        ("LogData", defaults.logData),
        ("TimeZone", defaults.timeZone),
    ]


def value_to_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, separators=(",", ":"))


def contact_id_of(raw: dict[str, Any]) -> str | None:
    cid = raw.get("contactId")
    return cid if isinstance(cid, str) and cid else None


def str_field(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if isinstance(value, str) and value:
        return value
    return ""


def embedded_of(raw: dict[str, Any]) -> dict[str, str]:
    data = raw.get("embeddedData")
    if not isinstance(data, dict):
        return {}
    return {str(k): value_to_string(v) for k, v in data.items()}


def display_name(raw: dict[str, Any]) -> str:
    name = f"{str_field(raw, 'firstName')} {str_field(raw, 'lastName')}".strip()
    if name:
        return name
    return (
        str_field(raw, "email")
        or str_field(raw, "phone")
        or contact_id_of(raw)
        or "(unnamed)"
    )


def to_view(raw: dict[str, Any], profile: SurveyProfile) -> ContactView:
    """Project a raw Qualtrics contact into the table row the UI renders."""
    embedded = embedded_of(raw)
    defaults = EligibilityDefaults(
        timezone=profile.timezone or "America/Chicago",
        minutes_expire=profile.minutes_expire,
    )
    result = contact_eligibility(embedded, defaults)
    if isinstance(result, str):
        eligible, skip_reason = False, result
    else:
        eligible, skip_reason = True, None
    try:
        method = delivery_method(embedded)
    except ValueError:
        method = None
    return ContactView(
        contactId=contact_id_of(raw) or "",
        firstName=str_field(raw, "firstName"),
        lastName=str_field(raw, "lastName"),
        email=str_field(raw, "email"),
        phone=str_field(raw, "phone"),
        extRef=str_field(raw, "extRef"),
        embedded=embedded,
        eligible=eligible,
        skipReason=skip_reason,
        method=method,
    )


def append_log_data(existing: Any, entry: dict[str, Any]) -> str:
    """LogData is a JSON array of audit entries. A legacy bare object is promoted."""
    items: list[Any]
    if isinstance(existing, str) and existing.strip():
        try:
            parsed = json.loads(existing)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            items = [parsed]
        else:
            items = []
    elif isinstance(existing, list):
        items = list(existing)
    else:
        items = []
    items.append(entry)
    if len(items) > LOG_DATA_MAX:
        items = items[-LOG_DATA_MAX:]
    return json.dumps(items, separators=(",", ":"))


def list_raw(
    client: QualtricsClient, directory_id: str, mailing_list_id: str
) -> list[dict[str, Any]]:
    return client.get_elements(
        f"directories/{directory_id}/mailinglists/{mailing_list_id}/contacts"
        "?includeEmbedded=true"
    )


def fetch_raw(
    client: QualtricsClient,
    directory_id: str,
    mailing_list_id: str,
    contact_id: str,
) -> dict[str, Any]:
    body = client.get(
        f"directories/{directory_id}/mailinglists/{mailing_list_id}/contacts/{contact_id}"
    )
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict):
        raise app_error(404, "NotFound", f"contact {contact_id} could not be read back")
    return result


def find_in_list(contacts: list[dict[str, Any]], contact_id: str) -> dict[str, Any]:
    for raw in contacts:
        if contact_id_of(raw) == contact_id:
            return raw
    raise app_error(404, "NotFound", f"contact {contact_id} is not in this list")


def resolve_contact_lookup_id(
    client: QualtricsClient,
    directory_id: str,
    mailing_list_id: str,
    contact: dict[str, Any],
) -> str:
    """The `CGC_…` id Qualtrics wants as a distribution recipient.

    The mailing-list response usually carries `contactLookupId` already; falling
    back to a directory-level GET only when it doesn't.
    """
    existing = contact.get("contactLookupId")
    if isinstance(existing, str) and existing.strip():
        return existing
    contact_id = contact_id_of(contact)
    if not contact_id:
        raise app_error(400, "Invalid", "contact has no contactId")
    body = client.get(f"directories/{directory_id}/contacts/{contact_id}")
    result = body.get("result") if isinstance(body, dict) else None
    membership = result.get("mailingListMembership") if isinstance(result, dict) else None
    entry = membership.get(mailing_list_id) if isinstance(membership, dict) else None
    lookup = entry.get("contactLookupId") if isinstance(entry, dict) else None
    if isinstance(lookup, str) and lookup:
        return lookup
    raise app_error(
        404,
        "NotFound",
        f"contact {contact_id} has no membership in mailing list {mailing_list_id}",
    )


def create_contact(
    client: QualtricsClient,
    directory_id: str,
    mailing_list_id: str,
    core: dict[str, str],
    embedded: dict[str, str],
    seed: list[tuple[str, str]],
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in CORE_FIELDS:
        value = core.get(key, "").strip()
        if value:
            fields[key] = value
    if not fields:
        raise app_error(
            400,
            "Invalid",
            "a new participant needs at least a name, email address or phone number",
        )
    fields["language"] = "en"

    embedded_map: dict[str, Any] = {key: value for key, value in seed}
    embedded_map.update(embedded)
    embedded_map["LogData"] = append_log_data(None, {"action": "created"})
    fields["embeddedData"] = embedded_map

    resp = client.post(
        f"directories/{directory_id}/mailinglists/{mailing_list_id}/contacts",
        fields,
    )
    result = resp.get("result") if isinstance(resp, dict) else None
    new_id = None
    if isinstance(result, dict):
        for key in ("id", "contactId"):
            value = result.get(key)
            if isinstance(value, str) and value:
                new_id = value
                break
    if not new_id:
        raise app_error(
            502, "Api", "Qualtrics did not return an id for the new participant"
        )
    return fetch_raw(client, directory_id, mailing_list_id, new_id)


def update_contact(
    client: QualtricsClient,
    directory_id: str,
    mailing_list_id: str,
    contact: dict[str, Any],
    core: dict[str, str],
    seed: list[tuple[str, str]],
    updates: dict[str, str],
    log_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    contact_id = contact_id_of(contact)
    if not contact_id:
        raise app_error(400, "Invalid", "contact has no contactId")
    if not isinstance(contact, dict):
        raise app_error(400, "Invalid", "contact is not a JSON object")

    data = dict(contact)
    for key, value in core.items():
        if key not in CORE_FIELDS:
            raise app_error(400, "Invalid", f"{key} is not an editable field")
        value = value.strip()
        if value:
            data[key] = value
        else:
            data.pop(key, None)

    embedded = data.get("embeddedData")
    embedded_map: dict[str, Any] = dict(embedded) if isinstance(embedded, dict) else {}
    for key, value in seed:
        embedded_map.setdefault(key, value)
    for key, value in updates.items():
        embedded_map[key] = value
    if log_entry is not None:
        embedded_map["LogData"] = append_log_data(embedded_map.get("LogData"), log_entry)
    data["embeddedData"] = embedded_map

    # Qualtrics rejects these on the way back in even though it sends them out.
    data.pop("contactId", None)
    data.pop("contactLookupId", None)
    data.pop("mailingListUnsubscribed", None)
    if data.get("email") is None:
        data.pop("email", None)
    if data.get("language") is None:
        data["language"] = "en"

    client.put(
        f"directories/{directory_id}/mailinglists/{mailing_list_id}/contacts/{contact_id}",
        data,
    )
    return fetch_raw(client, directory_id, mailing_list_id, contact_id)


def remove_from_mailing_list(
    client: QualtricsClient,
    directory_id: str,
    mailing_list_id: str,
    contact_id: str,
) -> None:
    client.delete(
        f"directories/{directory_id}/mailinglists/{mailing_list_id}/contacts/{contact_id}"
    )


def list_views(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
) -> list[ContactView]:
    raw = list_raw(client, account.default_directory, profile.mailing_list_id)
    return [to_view(c, profile) for c in raw]


def create_view(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    core: dict[str, str],
    embedded: dict[str, str],
) -> ContactView:
    project = profile_to_project(profile)
    created = create_contact(
        client,
        account.default_directory,
        profile.mailing_list_id,
        core,
        embedded,
        embedded_defaults_pairs(project.embeddedDefaults),
    )
    return to_view(created, profile)


def update_view(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    contact_id: str,
    core: dict[str, str],
    fields: dict[str, str],
) -> ContactView:
    raw = list_raw(client, account.default_directory, profile.mailing_list_id)
    contact = find_in_list(raw, contact_id)
    changed = sorted(list(core.keys()) + list(fields.keys()))
    updated = update_contact(
        client,
        account.default_directory,
        profile.mailing_list_id,
        contact,
        core,
        [],
        fields,
        {"action": "edit", "fields": changed},
    )
    return to_view(updated, profile)


def delete_view(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    contact_id: str,
) -> RemovedContact:
    raw = list_raw(client, account.default_directory, profile.mailing_list_id)
    contact = find_in_list(raw, contact_id)
    name = display_name(contact)
    # Late import: distributions talks to this module for mailing-list lookups.
    from app.distributions import cancel_pending_for_contact, require_distribution_ids

    require_distribution_ids(account, profile)
    report = cancel_pending_for_contact(client, account, profile, contact)
    if report.failed:
        raise app_error(
            502,
            "Api",
            f"{name} still has {len(report.failed)} invitation(s) that could not be "
            f"cancelled ({report.failed[0].error}). They were left in the mailing list "
            "so you can retry — removing them now would leave those invitations booked "
            "with no way to trace them.",
        )
    remove_from_mailing_list(
        client, account.default_directory, profile.mailing_list_id, contact_id
    )
    return RemovedContact(contactName=name, cancelled=report.deleted)


def apply_defaults(
    client: QualtricsClient,
    account: QualtricsAccount,
    profile: SurveyProfile,
    contact_ids: list[str],
) -> list[ContactView]:
    raw = list_raw(client, account.default_directory, profile.mailing_list_id)
    wanted = set(contact_ids)
    seed = embedded_defaults_pairs(profile_to_project(profile).embeddedDefaults)
    selected = [c for c in raw if contact_id_of(c) in wanted]
    out: list[ContactView] = []
    for i, contact in enumerate(selected):
        updated = update_contact(
            client,
            account.default_directory,
            profile.mailing_list_id,
            contact,
            {},
            seed,
            {},
            {"action": "init"},
        )
        out.append(to_view(updated, profile))
        if i + 1 < len(selected) and WRITE_PACING_SECONDS > 0:
            time.sleep(WRITE_PACING_SECONDS)
    return out
