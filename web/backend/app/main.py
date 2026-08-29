"""FastAPI app entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.routers import auth, config, contacts, distributions, importexport, lookups, schedule

settings = get_settings()

app = FastAPI(title=settings.app_name, version=settings.app_version)

if settings.environment == "dev":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:8040",
            "http://127.0.0.1:8040",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(config.router)
app.include_router(contacts.router)
app.include_router(distributions.router)
app.include_router(schedule.router)
app.include_router(lookups.router)
app.include_router(importexport.router)


@app.get("/health")
def health() -> dict:
    """Liveness + DB connectivity. Never returns secrets."""
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.environment,
        "db": db_ok,
        "google": settings.google_login_configured,
        "devLogin": settings.dev_login_allowed,
    }
