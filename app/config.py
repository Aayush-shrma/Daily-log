"""Application settings, loaded from environment / .env via pydantic-settings."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholders that must never sign a production session cookie.
_WEAK_SECRETS = {"", "change-me", "changeme", "secret", "test", "daylog"}
_MIN_SECRET_LEN = 32


class Settings(BaseSettings):
    """All runtime configuration. Values come from env vars (which win) or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "DayLog"
    debug: bool = True
    base_url: str = "http://127.0.0.1:8000"
    secret_key: str = "change-me"
    session_days: int = 7

    database_url: str = "sqlite:///./daylog.db"

    google_client_id: str = ""
    google_client_secret: str = ""

    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 20.0

    default_timezone: str = "Asia/Kolkata"

    # Dev workflow only: extra browser origins allowed to send unsafe requests,
    # e.g. the Vite dev server at http://localhost:5173. Comma-separated.
    # Leave empty in production so only BASE_URL's origin is accepted.
    dev_allowed_origins: str = ""

    # Local smoke-testing only; never used by the app itself.
    smoke_llm_key: str = ""

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def cookie_secure(self) -> bool:
        return self.base_url.startswith("https")

    @property
    def is_production(self) -> bool:
        """Production means DEBUG is off, or the app is served over https."""
        return not self.debug or self.base_url.startswith("https")

    @model_validator(mode="after")
    def _require_strong_secret_key(self) -> "Settings":
        """Refuse to start in production with a default or short SECRET_KEY.

        The key signs session cookies, so a guessable value lets anyone forge a
        login. Fail fast and loudly instead of running insecurely.
        """
        if not self.is_production:
            return self
        if (
            self.secret_key.strip().lower() in _WEAK_SECRETS
            or len(self.secret_key) < _MIN_SECRET_LEN
        ):
            raise ValueError(
                "SECRET_KEY must be a random string of at least "
                f"{_MIN_SECRET_LEN} characters when DEBUG is false or "
                "BASE_URL is https (refusing to start insecurely)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
