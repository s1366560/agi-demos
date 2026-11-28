"""Backward compatibility re-export."""

from src.infrastructure.adapters.secondary.sandbox.url_service import (
    SandboxInstanceInfo,
    SandboxUrls,
    SandboxUrlService,
)

__all__ = ["SandboxInstanceInfo", "SandboxUrlService", "SandboxUrls"]
