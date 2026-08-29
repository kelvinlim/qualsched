"""Hard rule: the app DB must never store participant PHI."""

from sqlalchemy import inspect

from app.db import Base
from app.models import QualtricsAccount, SurveyProfile, User  # noqa: F401


# Participant-shaped names. Researcher `users.email` / `users.name` are allowlist
# identity, not study participants, and are the only exception.
FORBIDDEN = {
    "phone",
    "contact_phone",
    "contact_email",
    "first_name",
    "last_name",
    "ext_ref",
    "contact_id",
    "contact_lookup_id",
    "participant_id",
    "mailing_list_unsubscribed",
}


def test_no_contacts_table():
    assert "contacts" not in Base.metadata.tables
    assert "participants" not in Base.metadata.tables
    assert "schedules" not in Base.metadata.tables
    assert "invitations" not in Base.metadata.tables
    assert "distributions" not in Base.metadata.tables


def test_only_allowed_tables():
    assert set(Base.metadata.tables) == {"users", "qualtrics_accounts", "survey_profiles"}


def test_no_participant_pii_columns():
    inspector_cols = {}
    for table_name, table in Base.metadata.tables.items():
        inspector_cols[table_name] = {c.name for c in table.columns}

    for table_name, cols in inspector_cols.items():
        forbidden = cols & FORBIDDEN
        assert not forbidden, f"{table_name} has participant-shaped columns: {forbidden}"

    # Token lives encrypted; never as plaintext.
    assert "token" not in inspector_cols["qualtrics_accounts"]
    assert "api_token" not in inspector_cols["qualtrics_accounts"]
    assert "token_ciphertext" in inspector_cols["qualtrics_accounts"]

    # Researcher identity only.
    assert "email" in inspector_cols["users"]
    assert "email" not in inspector_cols["qualtrics_accounts"]
    assert "email" not in inspector_cols["survey_profiles"]


def test_inspect_module():
    # Keep the inspect import live so a future alembic-only schema still gets grepped
    # the same way locally (`python -c` against models).
    assert inspect is not None
