"""Alembic 0001 is what entrypoint.sh applies on MariaDB 11.

CI still uses in-memory SQLite + create_all (see conftest). This test compiles
the upgrade for the MySQL/MariaDB dialect so a SQLite fixture still guards
MariaDB-incompatible SQL (JSON, DATETIME, BOOLEAN, TEXT ciphertext).
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, Boolean, DateTime, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.config import get_settings
from app.db import Base
from app.models import QualtricsAccount, SurveyProfile, User  # noqa: F401


def test_orm_create_table_sql_compiles_for_mariadb():
    dialect = mysql.dialect()
    compiled = {
        name: str(CreateTable(table).compile(dialect=dialect))
        for name, table in Base.metadata.tables.items()
    }

    assert set(compiled) == {"users", "qualtrics_accounts", "survey_profiles"}
    joined = "\n".join(compiled.values())

    assert "DATETIME" in compiled["users"].upper()
    assert "is_superuser" in compiled["users"]
    assert "token_ciphertext" in compiled["qualtrics_accounts"]
    assert "TEXT" in compiled["qualtrics_accounts"].upper()
    assert "JSON" in compiled["survey_profiles"].upper()
    # MariaDB BOOL is an alias for TINYINT(1); SQLAlchemy emits BOOL.
    assert "BOOL" in joined.upper()


def test_model_column_types_are_mariadb_safe():
    assert isinstance(User.__table__.c.is_superuser.type, Boolean)
    assert isinstance(User.__table__.c.created_at.type, DateTime)
    assert isinstance(QualtricsAccount.__table__.c.token_ciphertext.type, Text)
    assert isinstance(QualtricsAccount.__table__.c.verify_tls.type, Boolean)
    assert isinstance(SurveyProfile.__table__.c.survey_copies.type, JSON)
    assert isinstance(SurveyProfile.__table__.c.default_log_data.type, Text)
    assert isinstance(SurveyProfile.__table__.c.updated_at.type, DateTime)


def test_alembic_upgrade_sql_compiles_for_mysql(monkeypatch):
    """Offline `alembic upgrade head --sql` against a mysql+pymysql URL."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql+pymysql://qualsched:changeme@127.0.0.1:3306/qualsched",
    )
    get_settings.cache_clear()
    try:
        cfg = Config("alembic.ini")
        buf = io.StringIO()
        with redirect_stdout(buf):
            command.upgrade(cfg, "head", sql=True)
        sql = buf.getvalue()
    finally:
        monkeypatch.setenv("DATABASE_URL", "sqlite://")
        get_settings.cache_clear()

    assert "CREATE TABLE" in sql.upper()
    assert "users" in sql
    assert "qualtrics_accounts" in sql
    assert "survey_profiles" in sql
    assert "token_ciphertext" in sql
    assert "survey_copies" in sql
    assert "alembic_version" in sql
