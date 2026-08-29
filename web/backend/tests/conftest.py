"""Test bootstrap: in-memory SQLite, Fernet key, no Google client (dev-login on).

SQLite here is the CI/test fixture only. Production and local compose use
MariaDB; Alembic revision 0001 is what entrypoint.sh applies on MariaDB 11.
See tests/test_alembic_mariadb.py.
"""

import os

from cryptography.fernet import Fernet

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("SUPERADMIN_EMAILS", "dev@umn.edu")
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import User
from app.security import get_current_user


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=True)

    s = Session()
    user = User(email="dev@umn.edu", name="Dev", is_superuser=True)
    s.add(user)
    s.commit()
    uid = user.id
    s.close()

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: Session().get(User, uid)

    client = TestClient(app)
    yield client, Session, uid
    app.dependency_overrides.clear()


@pytest.fixture()
def anon():
    """No auth override — used for /health, /auth/status, /auth/dev-login."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=True)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
