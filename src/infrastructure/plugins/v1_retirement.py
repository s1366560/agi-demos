"""Stable public markers for the breaking plugin protocol V1 retirement."""

from __future__ import annotations

PLUGIN_PROTOCOL_V1_RETIRED_CODE = "plugin_protocol_v1_retired"
PLUGIN_PROTOCOL_V1_INCOMPATIBLE_CODE = "plugin_protocol_v1_incompatible"
PLUGIN_MARKETPLACE_V2_PATH = "/api/v1/plugin-marketplace"

__all__ = [
    "PLUGIN_MARKETPLACE_V2_PATH",
    "PLUGIN_PROTOCOL_V1_INCOMPATIBLE_CODE",
    "PLUGIN_PROTOCOL_V1_RETIRED_CODE",
]
