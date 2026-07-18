from functools import lru_cache
import re

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    cliniko_api_key: SecretStr
    cliniko_shard: str | None = None
    cliniko_api_base_url: str | None = None
    cliniko_user_agent: str
    cliniko_timeout_seconds: float = 10.0
    retell_api_key: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def configure_cliniko_api_base_url(self) -> "Settings":
        if self.cliniko_api_base_url:
            self.cliniko_api_base_url = self.cliniko_api_base_url.rstrip("/")
            return self

        if not self.cliniko_shard or not re.fullmatch(
            r"[a-z]{2}\d+", self.cliniko_shard.lower()
        ):
            raise ValueError(
                "CLINIKO_SHARD must look like 'au5' when "
                "CLINIKO_API_BASE_URL is not set"
            )

        self.cliniko_shard = self.cliniko_shard.lower()
        self.cliniko_api_base_url = (
            f"https://api.{self.cliniko_shard}.cliniko.com/v1"
        )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
