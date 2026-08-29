"""SQLAlchemy 2.0 engine, session factory, and FastAPI session dependency.

Schema changes go through Alembic (`alembic upgrade head` in entrypoint.sh),
the same way wearable-hub does. Do not `Base.metadata.create_all()` against
MariaDB. Tests may `create_all` on in-memory SQLite only.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(url: str) -> dict:
    # pool_pre_ping avoids stale connections after MariaDB idle timeouts.
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # Tests / escape hatch only. Production and compose use MariaDB.
        kwargs["connect_args"] = {"check_same_thread": False}
    return kwargs


_settings = get_settings()
engine = create_engine(_settings.database_url, **_engine_kwargs(_settings.database_url))

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
