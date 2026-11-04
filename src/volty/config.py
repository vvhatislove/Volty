from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr


class Settings(DatabaseSettings):
    bot_token: SecretStr
    encryption_key: SecretStr
    poll_interval_seconds: int = Field(default=60, ge=20)
    log_level: str = "INFO"
