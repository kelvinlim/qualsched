"""Application settings, loaded from environment / .env via pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "QualSched Web"
    # Keep in sync with backend/pyproject.toml + frontend/package.json.
    app_version: str = "0.1.0"
    environment: str = "dev"  # dev | prod

    # Public URL path prefix the app would be served under on the host (e.g. "/qualsched"
    # on lnpitask). Backend routes stay unprefixed; host nginx strips it. "" = root.
    # Do not use /wearable — that belongs to wearable-hub.
    public_path_prefix: str = ""

    # --- Database ---
    # MariaDB is the intended database. Override per environment via .env.
    # Production / lnpitask: mysql+pymysql://qualsched:<password>@cnc3.med.umn.edu:3306/qualsched
    # Local compose: the backend service overrides this to the sidecar `db`.
    # SQLite is tests-only (and an explicit escape hatch), not the default.
    database_url: str = "mysql+pymysql://qualsched:changeme@localhost:3306/qualsched"

    # --- Token encryption at rest (Fernet) ---
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_key: str = ""

    # --- Researcher auth (Google login + allowlist) ---
    google_client_id: str = ""
    google_client_secret: str = ""
    researcher_oauth_redirect_uri: str = "http://localhost:8040/auth/callback"
    researcher_google_scopes: str = "openid email profile"
    # Bootstrap superadmins: these emails are auto-provisioned as superusers on first login.
    superadmin_emails: str = ""  # comma-separated
    # Comma-separated email domains auto-provisioned as non-superuser researchers on
    # first Google login (e.g. "umn.edu"). Matches the domain and its subdomains.
    # Do not add gmail.com — that would allow any Google account on the internet.
    # Empty = no domain-wide allowlist (SUPERADMIN_EMAILS + existing users rows only).
    allowed_email_domains: str = ""
    # Signed+encrypted session cookie (Fernet, reuses FERNET_KEY) lifetime.
    session_ttl_seconds: int = 60 * 60 * 12  # 12h

    @property
    def google_login_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def dev_login_allowed(self) -> bool:
        """Local bypass when Google client ids are unset. Never in prod."""
        return self.environment != "prod" and not self.google_login_configured


@lru_cache
def get_settings() -> Settings:
    return Settings()
