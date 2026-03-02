"""Backward compatibility re-export."""

from src.domain.model.sandbox.profiles import (
    SANDBOX_PROFILES,
    SandboxProfile,
    SandboxProfileType,
    get_default_profile,
    get_profile,
    list_profiles,
    register_profile,
)

__all__ = [
    "SANDBOX_PROFILES",
    "SandboxProfile",
    "SandboxProfileType",
    "get_default_profile",
    "get_profile",
    "list_profiles",
    "register_profile",
]
