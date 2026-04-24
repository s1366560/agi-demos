"""Shared workspace surface contract constants.

This module centralizes the boundary / authority / signal metadata used by
workspace-facing surfaces so routers, services, and tests do not drift.
"""

from __future__ import annotations

from typing import Final

SURFACE_BOUNDARY_KEY: Final[str] = "surface_boundary"
AUTHORITY_CLASS_KEY: Final[str] = "authority_class"
SIGNAL_ROLE_KEY: Final[str] = "signal_role"
SURFACE_OWNER_KEY: Final[str] = "surface_owner"

OWNED: Final[str] = "owned"
HOSTED: Final[str] = "hosted"

AUTHORITATIVE: Final[str] = "authoritative"
NON_AUTHORITATIVE: Final[str] = "non-authoritative"

SENSING_CAPABLE: Final[str] = "sensing-capable"

BLACKBOARD_OWNERSHIP_METADATA: Final[dict[str, str]] = {
    SURFACE_OWNER_KEY: "blackboard",
    SURFACE_BOUNDARY_KEY: OWNED,
    AUTHORITY_CLASS_KEY: AUTHORITATIVE,
    SIGNAL_ROLE_KEY: SENSING_CAPABLE,
}

WORKSPACE_CHAT_EVENT_METADATA: Final[dict[str, str]] = {
    SURFACE_OWNER_KEY: "workspace-chat",
    SURFACE_BOUNDARY_KEY: HOSTED,
    AUTHORITY_CLASS_KEY: NON_AUTHORITATIVE,
    SIGNAL_ROLE_KEY: SENSING_CAPABLE,
}
