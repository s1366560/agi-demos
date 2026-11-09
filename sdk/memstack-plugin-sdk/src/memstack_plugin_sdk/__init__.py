"""Stable DTOs for signed optional-business plugins.

This package is consumable from the repository without the host application.
It does not import host modules and is not published to an external registry.
"""

from memstack_plugin_sdk.contract import (
    CONTRIBUTION_SCHEMA,
    INVOKE_INPUT_OFFSET,
    INVOKE_OUTPUT_OFFSET,
    MAX_INVOKE_OUTPUT_BYTES,
    PERMISSIONS,
    SLOT_UI_SCHEMA,
    ContributionDocument,
    ScanEvidence,
    SlotUiDocument,
    parse_contribution,
    parse_slot_ui,
)

__all__ = [
    "CONTRIBUTION_SCHEMA",
    "INVOKE_INPUT_OFFSET",
    "INVOKE_OUTPUT_OFFSET",
    "MAX_INVOKE_OUTPUT_BYTES",
    "PERMISSIONS",
    "SLOT_UI_SCHEMA",
    "ContributionDocument",
    "ScanEvidence",
    "SlotUiDocument",
    "parse_contribution",
    "parse_slot_ui",
]
