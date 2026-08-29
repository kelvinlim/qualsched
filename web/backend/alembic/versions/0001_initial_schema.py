"""Initial schema: researchers, Qualtrics accounts (encrypted token), survey profiles.

MariaDB 11 types (same dialect as wearable-hub): BOOLEAN → TINYINT(1),
DateTime → DATETIME, JSON → JSON, token_ciphertext → TEXT.
entrypoint.sh applies this revision (`alembic upgrade head`) against MariaDB.
Tests may still create_all on in-memory SQLite.

No contacts table. No participant PII columns.

Revision ID: 0001
Revises:
Create Date: 2026-08-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("google_sub", sa.String(255), unique=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(255)),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "qualtrics_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("data_center", sa.String(64), nullable=False, server_default=""),
        sa.Column("verify_tls", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("default_directory", sa.String(64), nullable=False, server_default=""),
        sa.Column("library_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("token_ciphertext", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_qualtrics_accounts_owner_user_id", "qualtrics_accounts", ["owner_user_id"])

    op.create_table(
        "survey_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("qualtrics_accounts.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("survey_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("message_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("message_id_email", sa.String(64), nullable=False, server_default=""),
        sa.Column("mailing_list_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="America/Chicago"),
        sa.Column("minutes_expire", sa.Integer, nullable=False, server_default=sa.text("60")),
        sa.Column("from_email", sa.String(320), nullable=False, server_default="noreply@qualtrics.com"),
        sa.Column("from_name", sa.String(255), nullable=False, server_default="Qualtrics"),
        sa.Column("reply_to_email", sa.String(320), nullable=False, server_default="noreply@qualtrics.com"),
        sa.Column("subject", sa.String(255), nullable=False, server_default="Survey"),
        sa.Column("default_start_date", sa.String(32), nullable=False, server_default=""),
        sa.Column("default_surveys_scheduled", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("default_time_slots", sa.String(255), nullable=False, server_default="800,1200,1600,2000"),
        sa.Column("default_contact_method", sa.String(16), nullable=False, server_default="sms"),
        sa.Column("default_delete_unsent", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("default_num_days", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("default_expire_minutes", sa.Integer, nullable=False, server_default=sa.text("60")),
        sa.Column("default_log_data", sa.Text, nullable=False, server_default="[]"),
        sa.Column("default_time_zone", sa.String(64), nullable=False, server_default="America/Chicago"),
        sa.Column("survey_copies", sa.JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("copies_source_survey_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_survey_profiles_account_id", "survey_profiles", ["account_id"])


def downgrade() -> None:
    op.drop_table("survey_profiles")
    op.drop_table("qualtrics_accounts")
    op.drop_table("users")
