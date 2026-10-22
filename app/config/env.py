"""Typed configuration loaded from environment variables (prefix ``APP_``) or a ``.env`` file."""

from decimal import Decimal
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
    time_zone: str = "Europe/Berlin"
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    # Lexware Office Public API, used from step 2 on.
    lexware_api_key: SecretStr = SecretStr("")
    lexware_base_url: str = "https://api.lexware.io/v1/"
    # VAT rate in percent for invoice line items, e.g. 0 for small businesses (§ 19 UStG).
    invoice_tax_rate: Decimal = Decimal("19")

    @property
    def debug(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_env() -> Env:
    return Env()
