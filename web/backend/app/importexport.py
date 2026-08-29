"""Import / export of config_qualtrics YAML. Tokens are never written into the file."""

from __future__ import annotations

import re
import uuid
from typing import Any

import yaml

from app.errors import app_error
from app.schemas import (
    Account,
    EmailHeader,
    EmbeddedDefaults,
    ImportPreview,
    Project,
)

DEFAULT_TZ = "America/Chicago"
DEFAULT_EXPIRE = 60


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _int(section: dict | None, key: str, default: int = 0) -> int:
    if not section or key not in section:
        return default
    try:
        return int(section[key])
    except (TypeError, ValueError):
        return default


def _str(section: dict | None, key: str, default: str = "") -> str:
    if not section or key not in section:
        return default
    return _scalar(section[key])


def _bool(section: dict | None, key: str, default: bool = True) -> bool:
    if not section or key not in section:
        return default
    v = section[key]
    if isinstance(v, bool):
        return v
    return _scalar(v).lower() in ("1", "true", "yes", "on")


def _stem(source_name: str) -> str:
    name = source_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"\.ya?ml$", "", name, flags=re.I)
    name = re.sub(r"^config_qualtrics[_-]?", "", name, flags=re.I)
    return name.strip("_- ")


def parse_token_file(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == "QUALTRICS_APITOKEN":
            token = v.strip().strip("\"'")
            return token or None
    return None


def parse_config(yaml_text: str, source_name: str) -> ImportPreview:
    warnings: list[str] = []
    try:
        root = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise app_error(400, "Import", f"{source_name} is not valid YAML: {exc}") from exc
    if not isinstance(root, dict):
        raise app_error(400, "Import", f"{source_name} is not a YAML mapping")

    account_section = root.get("account") if isinstance(root.get("account"), dict) else None
    project_section = root.get("project") if isinstance(root.get("project"), dict) else None
    if account_section is None and project_section is None:
        raise app_error(
            400,
            "Import",
            f"{source_name} has neither an 'account' nor a 'project' section — is it a "
            "qualtrics_util config?",
        )

    data_center = _str(account_section, "DATA_CENTER")
    if not data_center:
        warnings.append("No DATA_CENTER in the file; set it before connecting.")
    verify_tls = _bool(account_section, "VERIFY", True)
    if not verify_tls:
        warnings.append(
            "VERIFY was false, so TLS certificate checking is off for this account. That "
            "matches the VA/gov1 setup, which sits behind TLS interception."
        )

    minutes_expire = _int(project_section, "MINUTES_EXPIRE", 0) or _int(
        project_section, "MINUTES_EXP", DEFAULT_EXPIRE
    )
    if project_section and "MINUTES_EXP" in project_section and "MINUTES_EXPIRE" not in project_section:
        warnings.append("Found MINUTES_EXP (the CLI's misspelling); imported as MINUTES_EXPIRE.")

    timezone = _str(project_section, "TIMEZONE")
    if not timezone:
        warnings.append(f"No project TIMEZONE in the file; defaulted to {DEFAULT_TZ}.")
        timezone = DEFAULT_TZ

    message_id_email = _str(project_section, "MESSAGE_ID_EMAIL")
    email_section = root.get("email_header") if isinstance(root.get("email_header"), dict) else None
    header = EmailHeader()
    if email_section:
        header = EmailHeader(
            fromEmail=_str(email_section, "FROM_EMAIL", header.fromEmail),
            fromName=_str(email_section, "FROM_NAME", header.fromName),
            replyToEmail=_str(email_section, "REPLY_TO_EMAIL", header.replyToEmail),
            subject=_str(email_section, "SUBJECT", header.subject),
        )
    else:
        warnings.append(
            "Email sender details (from address, name, subject) were hardcoded in the CLI. "
            "Review them in the project editor before sending email."
        )

    if not message_id_email:
        warnings.append(
            "No MESSAGE_ID_EMAIL in the file. Email invitations need their own template — "
            "an SMS template will not render as an email."
        )

    embedded = root.get("embedded_data") if isinstance(root.get("embedded_data"), dict) else {}
    defaults = EmbeddedDefaults(
        startDate=_str(embedded, "StartDate").strip("'"),
        surveysScheduled=_int(embedded, "SurveysScheduled", 0),
        timeSlots=_str(embedded, "TimeSlots", "800,1200,1600,2000"),
        contactMethod=_str(embedded, "ContactMethod", "sms") or "sms",
        deleteUnsent=_int(embedded, "DeleteUnsent", 0),
        numDays=_int(embedded, "NumDays", 0),
        expireMinutes=_int(embedded, "ExpireMinutes", minutes_expire),
        logData=_str(embedded, "LogData", "[]") or "[]",
        timeZone=_str(embedded, "TimeZone", timezone) or timezone,
    )
    if embedded and "ContactMethod" not in embedded and "UseSMS" in embedded:
        defaults.contactMethod = "sms" if _int(embedded, "UseSMS", 1) else "email"
        warnings.append(
            f"No ContactMethod in embedded_data; derived '{defaults.contactMethod}' from UseSMS."
        )

    stem = _stem(source_name)
    account_name = stem.upper() if stem else (data_center or "Imported account")
    project_name = _str(project_section, "NAME") or (
        stem.replace("_", " ").replace("-", " ") if stem else "Imported project"
    )

    account = Account(
        id=str(uuid.uuid4()),
        name=account_name,
        dataCenter=data_center,
        verifyTls=verify_tls,
        defaultDirectory=_str(account_section, "DEFAULT_DIRECTORY"),
        libraryId=_str(account_section, "LIBRARY_ID"),
        projects=[],
    )
    project = Project(
        id=str(uuid.uuid4()),
        name=project_name,
        surveyId=_str(project_section, "SURVEY_ID"),
        messageId=_str(project_section, "MESSAGE_ID"),
        messageIdEmail=message_id_email,
        mailingListId=_str(project_section, "MAILING_LIST_ID"),
        timezone=timezone,
        minutesExpire=minutes_expire or DEFAULT_EXPIRE,
        emailHeader=header,
        embeddedDefaults=defaults,
    )
    return ImportPreview(account=account, project=project, warnings=warnings, tokenFound=False)


def build_legacy_yaml(account: Account, project: Project) -> str:
    e = project.embeddedDefaults
    payload = {
        "account": {
            "DATA_CENTER": account.dataCenter,
            "DEFAULT_DIRECTORY": account.defaultDirectory,
            "LIBRARY_ID": account.libraryId,
            "VERIFY": account.verifyTls,
        },
        "project": {
            "NAME": project.name,
            "SURVEY_ID": project.surveyId,
            "MESSAGE_ID": project.messageId,
            "MESSAGE_ID_EMAIL": project.messageIdEmail,
            "MAILING_LIST_ID": project.mailingListId,
            "TIMEZONE": project.timezone,
            "MINUTES_EXPIRE": project.minutesExpire,
        },
        "embedded_data": {
            "StartDate": e.startDate,
            "SurveysScheduled": e.surveysScheduled,
            "TimeSlots": e.timeSlots,
            "ContactMethod": e.contactMethod,
            "DeleteUnsent": e.deleteUnsent,
            "NumDays": e.numDays,
            "ExpireMinutes": e.expireMinutes,
            "LogData": e.logData,
            "TimeZone": e.timeZone,
        },
        "email_header": {
            "FROM_EMAIL": project.emailHeader.fromEmail,
            "FROM_NAME": project.emailHeader.fromName,
            "REPLY_TO_EMAIL": project.emailHeader.replyToEmail,
            "SUBJECT": project.emailHeader.subject,
        },
    }
    yaml_text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return (
        "# Exported by QualSched Web. Readable by Import Config and by the qualtrics_util CLI.\n"
        "# The API token is not in this file; it stays encrypted on the server it was entered on.\n"
        f"{yaml_text}"
    )
