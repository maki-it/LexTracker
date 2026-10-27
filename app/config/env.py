"""Typed configuration loaded from environment variables (prefix ``APP_``) or a ``.env`` file."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, SecretStr
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def _split_commas(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


CommaList = Annotated[list[str], NoDecode, BeforeValidator(_split_commas)]


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=ROOT_DIR / ".env", extra="ignore")

    environment: Literal["development", "production", "test"] = "production"
    secret_key: SecretStr = SecretStr("")
    allowed_hosts: CommaList = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    csrf_trusted_origins: CommaList = Field(default_factory=list)
    data_dir: Path = ROOT_DIR / "data"
    # Send session and CSRF cookies only over HTTPS. Turn off only for plain-HTTP setups.
    secure_cookies: bool = True
    # Seconds browsers must keep using HTTPS for this host (Strict-Transport-Security). 0 sends no header. Only
    # sensible once the app is reachable over HTTPS for good, since browsers refuse plain HTTP for that long.
    hsts_seconds: int = Field(default=0, ge=0)
    time_zone: str = "Europe/Berlin"
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    # Lexware Office Public API, used from step 2 on.
    lexware_api_key: SecretStr = SecretStr("")
    lexware_base_url: str = "https://api.lexware.io/v1/"
    # Single sign-on with OpenID Connect, next to the local login. Active once issuer, client ID and secret are set.
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr = SecretStr("")
    # Name on the login button.
    oidc_name: str = "SSO"
    oidc_scopes: str = "openid email profile"
    # Create an employee account for someone who signs in with SSO and has none. Off: only existing users.
    oidc_create_users: bool = False
    # Only with oidc_create_users: the e-mail domains (comma-separated) that may get an account. Empty: all.
    oidc_allowed_email_domains: CommaList = Field(default_factory=list)
    # Sign in with passkeys (WebAuthn). Active once the domain is set: a passkey belongs to it for good, so it must not
    # change. Just the host name, e.g. zeit.example.de (no scheme, no port). It has to be the host the app is opened
    # under, or a domain above it.
    passkey_rp_id: str = ""
    # The addresses the app is opened under, with scheme (and port, if it is not the standard one). Empty: https://
    # plus the domain above. Needed for a trial over plain HTTP, e.g. http://localhost:8000.
    passkey_origins: CommaList = Field(default_factory=list)
    # Folder for the daily database copies (data_dir/backups if unset). When and how many is set on the settings page.
    backup_dir: Path | None = None
    # Largest file accepted when uploading a backup on the backups page, in MB.
    backup_upload_max_mb: int = Field(default=100, ge=1)
    # Set by the Docker image from the release it was built for (docker/Dockerfile), not meant to be set by hand.
    # Empty when the app runs from source, see core.version.
    version: str = ""
    commit: str = ""
    build_date: str = ""

    @property
    def debug(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_env() -> Env:
    return Env()
