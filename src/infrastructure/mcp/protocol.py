"""MCP protocol revisions this process can negotiate.

The current stable specification is 2026-07-28. Older revisions stay
acceptable so an existing server can answer with the revision it implements.
A revision outside this list is rejected. Optional features that this
process does not implement are not added here.
"""

from __future__ import annotations

LATEST_PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_PROTOCOL_VERSIONS = (
    "2026-07-28",
    "2026-01-26",
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)


class UnsupportedProtocolVersionError(ValueError):
    """The peer selected a protocol revision this process does not speak."""

    def __init__(self, requested: str | None) -> None:
        self.requested = requested or "missing"
        supported = ", ".join(SUPPORTED_PROTOCOL_VERSIONS)
        super().__init__(
            "unsupported_protocol_version: "
            f"{self.requested}; supported={supported}"
        )


def negotiate_client_offer(offered: str | None) -> str:
    """Accept a client initialize offer only when it is a supported revision."""

    if offered in SUPPORTED_PROTOCOL_VERSIONS:
        return offered
    raise UnsupportedProtocolVersionError(offered)


def protocol_version_of(result: object) -> str | None:
    """Read a protocol revision from an initialize result or JSON-RPC envelope."""

    if isinstance(result, dict):
        direct = result.get("protocolVersion")
        if isinstance(direct, str):
            return direct
        nested = result.get("result")
        if isinstance(nested, dict):
            nested_version = nested.get("protocolVersion")
            return nested_version if isinstance(nested_version, str) else None
        return None
    version = getattr(result, "protocolVersion", None)
    return version if isinstance(version, str) else None


def accept_server_protocol(version: str | None) -> str:
    """Accept the revision a server selected during initialize."""

    if version in SUPPORTED_PROTOCOL_VERSIONS:
        return version
    raise UnsupportedProtocolVersionError(version)
