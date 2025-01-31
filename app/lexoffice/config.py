from typing import Optional
from functools import lru_cache

from pydantic import HttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiConfig(BaseSettings):
  url: HttpUrl = Field(description="Base url to Lexoffice API Endpoints", default='https://api.lexoffice.io/v1')
  token: str = Field(description="Auth Bearer Token")

  model_config = SettingsConfigDict(
    env_prefix='LEXOFFICE_API_',
    env_file = ".env",
    case_sensitive=False,
    extra="ignore"
  )

  # Convert url to string after validation
  @field_validator('url', mode='after')
  def tranform_url_to_str(cls, value: HttpUrl):
    return str(value)


@lru_cache
def get_config():
  return ApiConfig()
