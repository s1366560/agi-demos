"""Public marketplace presentation excludes owned files and credential material."""

from __future__ import annotations

from typing import Any


def present_marketplace_installation(payload: dict[str, Any]) -> dict[str, Any]:
    from src.application.services.marketplace_oauth import oauth_service_views
    from src.infrastructure.plugins.marketplace_credentials import PLACEHOLDER

    def names(value: object) -> set[str]:
        if isinstance(value, str):
            return {match[1] for match in PLACEHOLDER.finditer(value)} - {
                "PLUGIN_ROOT",
                "CLAUDE_PLUGIN_ROOT",
            }
        if isinstance(value, dict):
            return set().union(*(names(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(names(item) for item in value))
        return set()

    return {
        "oauth_services": oauth_service_views(payload),
        "required_credentials": sorted(
            names(payload.get("package", {}).get("resources", {}).get("mcp_servers", {}))
        ),
        **{
            key: payload[key]
            for key in (
                "id",
                "plugin_id",
                "source_id",
                "name",
                "version",
                "status",
                "capabilities",
                "error",
                "job_id",
            )
            if key in payload
        },
    }
