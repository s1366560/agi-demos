"""Shared fail-closed markers for the staged plugin protocol V1 retirement."""

from __future__ import annotations

PLUGIN_PROTOCOL_V1_MUTATION_FROZEN_CODE = "plugin_protocol_v1_mutation_frozen"
PLUGIN_MARKETPLACE_V2_PATH = "/api/v1/plugin-marketplace"

__all__ = [
    "PLUGIN_MARKETPLACE_V2_PATH",
    "PLUGIN_PROTOCOL_V1_MUTATION_FROZEN_CODE",
]
