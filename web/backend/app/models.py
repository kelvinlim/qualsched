"""MariaDB-compatible ORM schema for QualSched Web.

Types are chosen for MariaDB 11 (JSON, DATETIME, TINYINT BOOLEAN, TEXT
ciphertext). Tests may instantiate the same models on in-memory SQLite.

HARD RULE: this database must NEVER store participant/contact PHI.
No contacts table. No participant name / phone / email / time-slot / timezone /
LogData columns. Those live in Qualtrics; later routes will proxy them and
discard the payload after the response.

Allowed tables:
- users — researchers (Google allowlist), not study participants
- qualtrics_accounts — connection metadata + Fernet-encrypted API token
- survey_profiles — survey / mailing-list / template / sender / default settings
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    """Researchers / admins. Email is the Google allowlist identity, not a participant."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # Google display name, refreshed from the ID token on login. Not a participant name.
    name: Mapped[str | None] = mapped_column(String(255))
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    accounts: Mapped[list["QualtricsAccount"]] = relationship(back_populates="owner")


class QualtricsAccount(Base):
    """One Qualtrics login: data center, directory/library ids, encrypted API token.

    `token_ciphertext` is Fernet ciphertext. It must never appear in API responses.
    """

    __tablename__ = "qualtrics_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    data_center: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    verify_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Qualtrics XM Directory id (POOL_…), not a list of people.
    default_directory: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Qualtrics message library id (GR_… / UR_…).
    library_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    token_ciphertext: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="accounts")
    profiles: Mapped[list["SurveyProfile"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class SurveyProfile(Base):
    """One study's Qualtrics wiring + default schedule seeds.

    Default time slots / timezone / LogData here are PROFILE SETTINGS that seed
    Qualtrics embedded-data keys a contact is missing. They are not participant
    records. Per-person values stay in Qualtrics.
    """

    __tablename__ = "survey_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("qualtrics_accounts.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    survey_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    message_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    message_id_email: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    mailing_list_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Chicago")
    minutes_expire: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    # Email sender (researcher/org), not a participant address.
    from_email: Mapped[str] = mapped_column(String(320), nullable=False, default="noreply@qualtrics.com")
    from_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Qualtrics")
    reply_to_email: Mapped[str] = mapped_column(String(320), nullable=False, default="noreply@qualtrics.com")
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="Survey")

    # Profile-level embedded-data defaults (seeds only).
    default_start_date: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    default_surveys_scheduled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    default_time_slots: Mapped[str] = mapped_column(String(255), nullable=False, default="800,1200,1600,2000")
    default_contact_method: Mapped[str] = mapped_column(String(16), nullable=False, default="sms")
    default_delete_unsent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    default_num_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    default_expire_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    default_log_data: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    default_time_zone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Chicago")

    # Leftover 0.1.4 clone ids (Qualtrics survey ids), not people.
    # JSON (MariaDB) / JSON affinity (SQLite tests). server_default keeps NOT NULL inserts safe.
    survey_copies: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    copies_source_survey_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    account: Mapped["QualtricsAccount"] = relationship(back_populates="profiles")
