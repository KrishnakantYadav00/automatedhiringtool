"""
AHP Sourcing Engine — Application configuration.

Uses ``pydantic-settings`` to load values from environment variables and a
``.env`` file.  Every configurable aspect of the service is represented here
so that call-sites never reach into ``os.environ`` directly.

Usage::

    from app.config import get_settings

    settings = get_settings()
    print(settings.database_url)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Nested connector models
# ---------------------------------------------------------------------------


class CeipalConfig(BaseSettings):
    """Configuration for the CEIPAL ATS integration."""

    model_config = SettingsConfigDict(env_prefix="CEIPAL_")

    api_url: str = Field(
        default="https://api.ceipal.com/v1",
        description="Base URL for the CEIPAL REST API.",
    )
    api_key: SecretStr = Field(
        default=SecretStr(""),
        description="API key issued by CEIPAL.",
    )
    tenant_id: str = Field(
        default="",
        description="CEIPAL tenant / account identifier.",
    )


class ImapConfig(BaseSettings):
    """Configuration for the IMAP email-inbox connector."""

    model_config = SettingsConfigDict(env_prefix="IMAP_")

    host: str = Field(default="imap.gmail.com", description="IMAP server hostname.")
    port: int = Field(default=993, description="IMAP server port.")
    username: str = Field(default="", description="IMAP login username (email address).")
    password: SecretStr = Field(default=SecretStr(""), description="IMAP login password / app-password.")
    folder: str = Field(default="INBOX", description="Mailbox folder to poll.")
    use_ssl: bool = Field(default=True, description="Whether to use SSL/TLS.")


class LinkedInConfig(BaseSettings):
    """Configuration for the LinkedIn connector."""

    model_config = SettingsConfigDict(env_prefix="LINKEDIN_")

    client_id: str = Field(default="", description="LinkedIn OAuth2 client ID.")
    client_secret: SecretStr = Field(default=SecretStr(""), description="LinkedIn OAuth2 client secret.")
    access_token: SecretStr = Field(default=SecretStr(""), description="LinkedIn OAuth2 access token.")


class NaukriConfig(BaseSettings):
    """Configuration for the Naukri job-portal connector."""

    model_config = SettingsConfigDict(env_prefix="NAUKRI_")

    api_url: str = Field(default="https://api.naukri.com/v1", description="Naukri API base URL.")
    api_key: SecretStr = Field(default=SecretStr(""), description="Naukri API key.")
    client_id: str = Field(default="", description="Naukri client identifier.")


class ShineConfig(BaseSettings):
    """Configuration for the Shine job-portal connector."""

    model_config = SettingsConfigDict(env_prefix="SHINE_")

    api_url: str = Field(default="https://api.shine.com/v1", description="Shine API base URL.")
    api_key: SecretStr = Field(default=SecretStr(""), description="Shine API key.")


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """
    Root application settings.

    Values are resolved in order:
    1. Environment variables
    2. ``.env`` file in the working directory
    3. Field defaults declared here
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Database -------------------------------------------------------------
    postgres_user: str = Field(default="ahp_user")
    postgres_password: SecretStr = Field(default=SecretStr("changeme_in_production"))
    postgres_db: str = Field(default="ahp_sourcing")
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    database_url: str = Field(
        default="postgresql+asyncpg://ahp_user:changeme_in_production@postgres:5432/ahp_sourcing",
        description="Full async database URL.  Overrides individual PG fields when set.",
    )

    # -- Redis ----------------------------------------------------------------
    redis_url: str = Field(default="redis://redis:6379/0")

    # -- Scheduler ------------------------------------------------------------
    polling_interval_minutes: int = Field(
        default=15,
        ge=1,
        description="Minutes between automated ingestion runs.",
    )

    # -- App ------------------------------------------------------------------
    app_env: Literal["development", "staging", "production"] = Field(default="development")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    secret_key: SecretStr = Field(default=SecretStr("change_this_to_a_random_secret"))

    # -- Connector sub-configs ------------------------------------------------
    ceipal: CeipalConfig = Field(default_factory=CeipalConfig)
    imap: ImapConfig = Field(default_factory=ImapConfig)
    linkedin: LinkedInConfig = Field(default_factory=LinkedInConfig)
    naukri: NaukriConfig = Field(default_factory=NaukriConfig)
    shine: ShineConfig = Field(default_factory=ShineConfig)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance.

    Using ``lru_cache`` ensures the ``.env`` file is read only once and the
    same object is reused across the application lifetime.
    """
    return Settings()  # type: ignore[call-arg]
