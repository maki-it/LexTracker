from functools import lru_cache
from os import path
from typing import Literal
from typing_extensions import Annotated

from pydantic import Field, AnyHttpUrl, field_validator, AfterValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


HttpUrlString = Annotated[AnyHttpUrl, AfterValidator(lambda v: str(v).rstrip('/'))]

class AppConfig(BaseSettings):
    loglevel: Literal["debug", "info", "warning", "error"] = Field(default="info")
    environment: Literal["development", "production"] = Field(default="production")
    timezone: str = Field(alias="TZ", default="UTC")
    secret_key: str = Field(description="Django secret key")
    allowed_hosts: list[str] = Field(default=('.localhost', '127.0.0.1', '[::1]'))
    domain: HttpUrlString = Field(default="http://localhost:8080")

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        secrets_dir="/run/secrets/" if path.exists("/run/secrets/") else None,
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_app_config() -> AppConfig:
    return AppConfig()

app_config = AppConfig()
