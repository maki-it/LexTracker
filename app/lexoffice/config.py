from functools import lru_cache

from pydantic import HttpUrl, Field, field_validator, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiConfig(BaseSettings):
  endpoint: HttpUrl = Field(description="Base url to Lexoffice API Endpoints", default='https://api.lexware.io/v1')
  requests_per_seconds: PositiveInt = Field(description="Max allowed requests per second to Lexoffice API", default=2)
  token: str = Field(description="Auth Bearer Token")

  model_config = SettingsConfigDict(
    env_prefix='LEXOFFICE_API_',
    env_file=".env",
    case_sensitive=False,
    extra="ignore"
  )

  # Convert url to string after validation
  @field_validator('endpoint', mode='after')
  def transform_url_to_str(cls, value: HttpUrl):
    return str(value)


@lru_cache
def get_config():
  return ApiConfig()
