"""Protocol revisions spoken by the sandbox MCP server and its child clients."""

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
    def __init__(self, requested: str | None) -> None:
        self.requested = requested or "missing"
        supported = ", ".join(SUPPORTED_PROTOCOL_VERSIONS)
        super().__init__(
            "unsupported_protocol_version: "
            f"{self.requested}; supported={supported}"
        )


def negotiate_client_offer(offered: str | None) -> str:
    if offered in SUPPORTED_PROTOCOL_VERSIONS:
        return offered
    raise UnsupportedProtocolVersionError(offered)


def accept_server_protocol(version: str | None) -> str:
    if version in SUPPORTED_PROTOCOL_VERSIONS:
        return version
    raise UnsupportedProtocolVersionError(version)
