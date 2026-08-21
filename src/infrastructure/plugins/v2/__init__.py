"""Cordis-semantics plugin runtime v2.

The v2 package is intentionally isolated from the v1 compatibility runtime while
the breaking protocol cutover is under construction.
"""

from .protocol import (
    PLUGIN_PROFILE_TYPE_URL_V2,
    PluginProtocolV2Error,
    build_profile_snapshot_v2,
    canonical_json_v2,
    control_envelope_v2_to_payload,
    parse_control_envelope_v2,
    parse_plugin_manifest_v2,
    parse_profile_snapshot_v2,
    plugin_contract_digest_v2,
    profile_snapshot_v2_to_payload,
)
from .reconciler import PlatformPluginSnapshotReconcilerV2
from .runtime import (
    ContextV2,
    FiberPhaseV2,
    FiberV2,
    GenerationManagerV2,
    LoaderV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeGenerationV2,
    RuntimeV2Error,
)

__all__ = [
    "PLUGIN_PROFILE_TYPE_URL_V2",
    "ContextV2",
    "FiberPhaseV2",
    "FiberV2",
    "GenerationManagerV2",
    "LoaderV2",
    "OperationContextV2",
    "PlatformPluginSnapshotReconcilerV2",
    "PluginDefinitionV2",
    "PluginProtocolV2Error",
    "RuntimeGenerationV2",
    "RuntimeV2Error",
    "build_profile_snapshot_v2",
    "canonical_json_v2",
    "control_envelope_v2_to_payload",
    "parse_control_envelope_v2",
    "parse_plugin_manifest_v2",
    "parse_profile_snapshot_v2",
    "plugin_contract_digest_v2",
    "profile_snapshot_v2_to_payload",
]
