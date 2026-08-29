"""Pydantic request/response models. CamelCase to match the QualSched Svelte types.

Never include Qualtrics API tokens or token_ciphertext here.
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class EmailHeader(BaseModel):
    fromEmail: str = "noreply@qualtrics.com"
    fromName: str = "Qualtrics"
    replyToEmail: str = "noreply@qualtrics.com"
    subject: str = "Survey"


class EmbeddedDefaults(BaseModel):
    startDate: str = ""
    surveysScheduled: int = 0
    timeSlots: str = "800,1200,1600,2000"
    contactMethod: str = "sms"
    deleteUnsent: int = 0
    numDays: int = 0
    expireMinutes: int = 60
    logData: str = "[]"
    timeZone: str = "America/Chicago"


class SurveyCopy(BaseModel):
    id: str
    name: str


class Project(BaseModel):
    id: str
    name: str = "New project"
    surveyId: str = ""
    messageId: str = ""
    messageIdEmail: str = ""
    mailingListId: str = ""
    timezone: str = "America/Chicago"
    minutesExpire: int = 60
    emailHeader: EmailHeader = Field(default_factory=EmailHeader)
    embeddedDefaults: EmbeddedDefaults = Field(default_factory=EmbeddedDefaults)
    surveyCopies: list[SurveyCopy] = Field(default_factory=list)
    copiesSourceSurveyId: str = ""


class Account(BaseModel):
    id: str
    name: str = "New account"
    dataCenter: str = ""
    verifyTls: bool = True
    defaultDirectory: str = ""
    libraryId: str = ""
    projects: list[Project] = Field(default_factory=list)


class AppConfig(BaseModel):
    version: int = 1
    accounts: list[Account] = Field(default_factory=list)


class TokenIn(BaseModel):
    token: str


class TestResult(BaseModel):
    ok: bool
    message: str
    directoryCount: int = 0


class IdName(BaseModel):
    id: str
    name: str


class MailingListInfo(BaseModel):
    id: str
    name: str
    contactCount: int | None = None


class MessageInfo(BaseModel):
    id: str
    description: str
    category: str | None = None


class ImportConfirm(BaseModel):
    account: Account
    project: Project
    token: str | None = None
    targetAccountId: str | None = None


class ImportPreview(BaseModel):
    account: Account
    project: Project
    warnings: list[str] = Field(default_factory=list)
    tokenFound: bool = False


class DevLoginIn(BaseModel):
    email: str


class UpdateInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    currentVersion: str
    latestVersion: str
    updateAvailable: bool
    releaseNotes: str = ""
    releaseUrl: str = ""


class ContactView(BaseModel):
    contactId: str
    firstName: str = ""
    lastName: str = ""
    email: str = ""
    phone: str = ""
    extRef: str = ""
    embedded: dict[str, str] = Field(default_factory=dict)
    eligible: bool
    skipReason: str | None = None
    method: str | None = None


class ContactCreateIn(BaseModel):
    core: dict[str, str] = Field(default_factory=dict)
    embedded: dict[str, str] = Field(default_factory=dict)


class ContactUpdateIn(BaseModel):
    core: dict[str, str] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)


class ContactDefaultsIn(BaseModel):
    contactIds: list[str] = Field(default_factory=list)


class RemovedContact(BaseModel):
    contactName: str
    cancelled: int = 0


class PlanItem(BaseModel):
    contactId: str
    contactName: str
    destination: str
    method: Literal["sms", "email"]
    dayIndex: int
    slotLabel: str
    surveyId: str
    surveyLabel: str
    sendLocal: str
    sendUtc: datetime
    expireUtc: datetime

    @field_validator("sendUtc", "expireUtc", mode="before")
    @classmethod
    def parse_utc(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_serializer("sendUtc", "expireUtc")
    def serialize_utc(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Skipped(BaseModel):
    contactId: str
    contactName: str
    reason: str


class SchedulePreview(BaseModel):
    items: list[PlanItem] = Field(default_factory=list)
    skippedContacts: list[Skipped] = Field(default_factory=list)
    skippedSlots: list[Skipped] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ItemFailure(BaseModel):
    contactName: str
    destination: str
    sendLocal: str
    error: str
    retryable: bool = False


class SendReport(BaseModel):
    scheduled: int
    failed: list[ItemFailure] = Field(default_factory=list)
    bookkeepingFailures: list[ItemFailure] = Field(default_factory=list)


class DistributionRow(BaseModel):
    id: str
    contactLookupId: str = ""
    contactName: str = ""
    contactPhone: str = ""
    contactEmail: str = ""
    sendDate: str = ""
    sendLocal: str = ""
    method: Literal["sms", "email"]
    unsent: bool
    surveyId: str
    surveyLabel: str


class DeleteTarget(BaseModel):
    id: str
    surveyId: str


class DeleteDistributionsIn(BaseModel):
    method: Literal["sms", "email"]
    targets: list[DeleteTarget] = Field(default_factory=list)


class DeleteFailure(BaseModel):
    id: str
    error: str


class DeleteReport(BaseModel):
    deleted: int
    failed: list[DeleteFailure] = Field(default_factory=list)
