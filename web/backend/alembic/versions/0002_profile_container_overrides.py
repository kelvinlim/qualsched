"""Add per-profile directory and SMS/email library overrides to survey_profiles.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "survey_profiles",
        sa.Column("directory_id", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "survey_profiles",
        sa.Column("message_library_id", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "survey_profiles",
        sa.Column("message_email_library_id", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("survey_profiles", "message_email_library_id")
    op.drop_column("survey_profiles", "message_library_id")
    op.drop_column("survey_profiles", "directory_id")
