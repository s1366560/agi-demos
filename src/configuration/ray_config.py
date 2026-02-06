"""Ray configuration settings for Actor runtime."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RaySettings(BaseSettings):
    """Ray connection settings."""

    ray_address: str = Field(default="ray://ray-head:10001", alias="RAY_ADDRESS")
    ray_namespace: str = Field(default="memstack", alias="RAY_NAMESPACE")
    ray_log_to_driver: bool = Field(default=False, alias="RAY_LOG_TO_DRIVER")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_ray_settings() -> RaySettings:
    """Get cached Ray settings instance."""
    return RaySettings()
