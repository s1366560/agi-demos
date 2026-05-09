"""Ray configuration settings for Actor runtime."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RaySettings(BaseSettings):
    """Ray connection settings."""

    ray_address: str = Field(default="ray://ray-head:10001", alias="RAY_ADDRESS")
    ray_namespace: str = Field(default="memstack", alias="RAY_NAMESPACE")
    ray_log_to_driver: bool = Field(default=False, alias="RAY_LOG_TO_DRIVER")
    ray_connect_timeout: float = Field(default=3.0, alias="RAY_CONNECT_TIMEOUT")
    ray_init_timeout_seconds: float = Field(default=5.0, alias="RAY_INIT_TIMEOUT_SECONDS")
    ray_failure_cooldown_seconds: float = Field(
        default=30.0,
        alias="RAY_FAILURE_COOLDOWN_SECONDS",
    )

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
