from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    cliniko_api_key: SecretStr
    cliniko_api_base_url: str
    cliniko_user_agent: str
    cliniko_timeout_seconds: float = 10.0
    retell_api_key: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
