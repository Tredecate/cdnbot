from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    discord_token: SecretStr = Field(..., min_length=1)
    bucket_secret_access_key: SecretStr = Field(..., min_length=1)
    cdn_cache_token: SecretStr = Field(..., min_length=1)

    bucket_access_key_id: str = Field(..., min_length=1)
    bucket_name: str = Field(..., min_length=1)
    bucket_url: str = Field(..., min_length=1)
    bucket_region: str = Field(default="auto", min_length=1)
    bucket_public_url: str = Field(default="", min_length=0)

    cdn_cache_purge_url: str = Field(default="", min_length=0)
    cdn_state_file: str = Field(default="", min_length=0)

    debug_level: int = Field(default=0, ge=0, le=2)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        cli_parse_args=True,
    )


settings = Settings()