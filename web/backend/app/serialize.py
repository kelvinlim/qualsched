"""Serialize ORM rows to the QualSched AppConfig shape. Never include the API token."""

from app.models import QualtricsAccount, SurveyProfile, User
from app.schemas import (
    Account,
    AppConfig,
    EmailHeader,
    EmbeddedDefaults,
    Project,
    SurveyCopy,
)


def profile_to_project(row: SurveyProfile) -> Project:
    copies = row.survey_copies or []
    return Project(
        id=row.id,
        name=row.name,
        surveyId=row.survey_id,
        messageId=row.message_id,
        messageIdEmail=row.message_id_email,
        mailingListId=row.mailing_list_id,
        timezone=row.timezone,
        minutesExpire=row.minutes_expire,
        emailHeader=EmailHeader(
            fromEmail=row.from_email,
            fromName=row.from_name,
            replyToEmail=row.reply_to_email,
            subject=row.subject,
        ),
        embeddedDefaults=EmbeddedDefaults(
            startDate=row.default_start_date,
            surveysScheduled=row.default_surveys_scheduled,
            timeSlots=row.default_time_slots,
            contactMethod=row.default_contact_method,
            deleteUnsent=row.default_delete_unsent,
            numDays=row.default_num_days,
            expireMinutes=row.default_expire_minutes,
            logData=row.default_log_data,
            timeZone=row.default_time_zone,
        ),
        surveyCopies=[SurveyCopy(id=c["id"], name=c["name"]) for c in copies if "id" in c],
        copiesSourceSurveyId=row.copies_source_survey_id,
    )


def account_to_schema(row: QualtricsAccount) -> Account:
    return Account(
        id=row.id,
        name=row.name,
        dataCenter=row.data_center,
        verifyTls=row.verify_tls,
        defaultDirectory=row.default_directory,
        libraryId=row.library_id,
        projects=[profile_to_project(p) for p in row.profiles],
    )


def app_config_for(user: User, accounts: list[QualtricsAccount]) -> AppConfig:
    return AppConfig(version=1, accounts=[account_to_schema(a) for a in accounts])


def apply_account_fields(row: QualtricsAccount, body: Account) -> None:
    """Update connection metadata. Projects are owned by their own endpoints."""
    row.name = body.name
    row.data_center = body.dataCenter
    row.verify_tls = body.verifyTls
    row.default_directory = body.defaultDirectory
    row.library_id = body.libraryId


def apply_project_fields(row: SurveyProfile, body: Project, *, keep_copies: bool) -> None:
    row.name = body.name
    row.survey_id = body.surveyId
    row.message_id = body.messageId
    row.message_id_email = body.messageIdEmail
    row.mailing_list_id = body.mailingListId
    row.timezone = body.timezone or "America/Chicago"
    row.minutes_expire = body.minutesExpire
    row.from_email = body.emailHeader.fromEmail
    row.from_name = body.emailHeader.fromName
    row.reply_to_email = body.emailHeader.replyToEmail
    row.subject = body.emailHeader.subject
    d = body.embeddedDefaults
    row.default_start_date = d.startDate
    row.default_surveys_scheduled = d.surveysScheduled
    row.default_time_slots = d.timeSlots
    row.default_contact_method = d.contactMethod
    row.default_delete_unsent = d.deleteUnsent
    row.default_num_days = d.numDays
    row.default_expire_minutes = d.expireMinutes
    row.default_log_data = d.logData
    row.default_time_zone = d.timeZone or row.timezone
    if not keep_copies:
        row.survey_copies = [c.model_dump() for c in body.surveyCopies]
        row.copies_source_survey_id = body.copiesSourceSurveyId
