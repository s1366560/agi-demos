# Generated from shared/schemas/plugins/platform-plugin-protocol.v2.schema.json.
# Schema SHA-256: 29d898f99289918dcdae5beb63e091ffb9f85f34470d8c6c191b2ec5e59277a5
# Do not edit by hand; run scripts/generate_plugin_protocol_v2.py.

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ScopeKindV2(StrEnum):
    ROOT = "root"
    TENANT = "tenant"
    PROJECT = "project"
    SESSION = "session"


class RuntimeKindV2(StrEnum):
    PYTHON_TRUSTED = "python-trusted"
    RUST_NATIVE = "rust-native"
    WASM = "wasm"
    MCP = "mcp"
    SUBPROCESS = "subprocess"
    FRONTEND = "frontend"


class TrustKindV2(StrEnum):
    BUILTIN = "builtin"
    SIGNED = "signed"
    TENANT_APPROVED = "tenant-approved"
    UNTRUSTED = "untrusted"


class RestartPolicyV2(StrEnum):
    HOT_GENERATION = "hot-generation"
    PROCESS_BOUNDARY = "process-boundary"


class ApplyStatusV2(StrEnum):
    ACK = "ack"
    NACK = "nack"


class PublicationStatusV2(StrEnum):
    RECONCILING = "reconciling"
    READY = "ready"
    DEGRADED = "degraded"


class DataPlaneTargetV2(StrEnum):
    PYTHON = "python"
    RUST_SERVER = "rust-server"
    DESKTOP_SIDECAR = "desktop-sidecar"
    WEB = "web"
    DESKTOP_RENDERER = "desktop-renderer"


class EventModeV2(StrEnum):
    EMIT = "emit"
    SERIAL = "serial"
    BAIL = "bail"
    WATERFALL = "waterfall"


class ProfileLayerKindV2(StrEnum):
    BUNDLE = "bundle"
    PROFILE = "profile"
    TENANT = "tenant"
    PROJECT = "project"
    SESSION = "session"


@dataclass(frozen=True, kw_only=True)
class ScopeV2:
    kind: ScopeKindV2
    tenant_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class QuotaV2:
    max_wasm_fuel: int | None = None
    max_wasm_memory_bytes: int | None = None
    max_wall_time_ms: int | None = None
    max_concurrent_calls: int | None = None
    max_output_bytes: int | None = None
    max_network_requests_per_minute: int | None = None
    max_storage_bytes: int | None = None
    max_monthly_usd_micros: int | None = None


@dataclass(frozen=True, kw_only=True)
class ArtifactReferenceV2:
    digest: str
    source: str
    signature: str | None = None
    provenance: str | None = None


@dataclass(frozen=True, kw_only=True)
class ServiceProvidedV2:
    service: str
    version: str


@dataclass(frozen=True, kw_only=True)
class ServiceRequiredV2:
    alias: str
    service: str
    version: str


@dataclass(frozen=True, kw_only=True)
class ServiceContractV2:
    provides: tuple[ServiceProvidedV2, ...]
    requires: tuple[ServiceRequiredV2, ...]


JsonSchemaV2 = Mapping[str, Any]


@dataclass(frozen=True, kw_only=True)
class EventContractV2:
    event: str
    mode: EventModeV2
    payload_schema: JsonSchemaV2
    result_schema: JsonSchemaV2


@dataclass(frozen=True, kw_only=True)
class EventContractsV2:
    emits: tuple[EventContractV2, ...]
    handles: tuple[EventContractV2, ...]


@dataclass(frozen=True, kw_only=True)
class PluginContractV2:
    services: ServiceContractV2
    events: EventContractsV2
    config_schema: JsonSchemaV2


@dataclass(frozen=True, kw_only=True)
class PluginModuleV2:
    module_ref: str
    entrypoint: str
    artifact: ArtifactReferenceV2
    targets: tuple[DataPlaneTargetV2, ...]
    contract: PluginContractV2
    contract_digest: str


@dataclass(frozen=True, kw_only=True)
class PluginManifestV2:
    schema_version: int
    plugin_id: str
    version: str
    runtime: RuntimeKindV2
    trust: TrustKindV2
    modules: tuple[PluginModuleV2, ...]
    permissions: tuple[str, ...]
    quotas: QuotaV2


@dataclass(frozen=True, kw_only=True)
class ProfileEntryV2:
    entry_id: str
    parent_entry_id: str | None
    plugin_ref: str
    module_ref: str
    enabled: bool
    config: Mapping[str, Any]
    inject: Mapping[str, str]
    isolate: Mapping[str, str]
    scope: ScopeV2
    permissions: tuple[str, ...]
    quotas: QuotaV2
    restart_policy: RestartPolicyV2


@dataclass(frozen=True, kw_only=True)
class BundleReferenceV2:
    bundle_id: str
    version: str
    digest: str
    source: str


@dataclass(frozen=True, kw_only=True)
class BundleArtifactV2:
    artifact_id: str
    target: DataPlaneTargetV2
    path: str
    digest: str
    size_bytes: int
    media_type: str


@dataclass(frozen=True, kw_only=True)
class ProfileLayerV2:
    layer_id: str
    kind: ProfileLayerKindV2
    scope: ScopeV2
    entries: tuple[ProfileEntryV2, ...]
    replacements: tuple[ProfileEntryV2, ...]
    disabled_entry_ids: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class ProfileSourceV2:
    schema_version: int
    source_id: str
    profile_id: str
    revision: int
    digest: str
    provenance: str | None
    layers: tuple[ProfileLayerV2, ...]


@dataclass(frozen=True, kw_only=True)
class ProfileSourceReferenceV2:
    source_id: str
    revision: int
    digest: str


@dataclass(frozen=True, kw_only=True)
class BundleManifestV2:
    schema_version: int
    bundle_id: str
    version: str
    manifests: tuple[PluginManifestV2, ...]
    layers: tuple[ProfileLayerV2, ...]
    artifacts: tuple[BundleArtifactV2, ...]
    digest: str
    signature: str | None
    provenance: str | None


@dataclass(frozen=True, kw_only=True)
class DesiredBundleSetV2:
    schema_version: int
    desired_set_id: str
    revision: int
    bundles: tuple[BundleReferenceV2, ...]
    profile_source: ProfileSourceReferenceV2
    digest: str


@dataclass(frozen=True, kw_only=True)
class ProfileSnapshotV2:
    schema_version: int
    profile_id: str
    generation: int
    manifests: tuple[PluginManifestV2, ...]
    entries: tuple[ProfileEntryV2, ...]
    digest: str


@dataclass(frozen=True, kw_only=True)
class ControlPlaneEnvelopeV2:
    version: int
    nonce: str
    snapshot_digest: str
    type_url: str


@dataclass(frozen=True, kw_only=True)
class SnapshotApplyReceiptV2:
    status: ApplyStatusV2
    requested_version: int
    requested_digest: str
    applied_version: int | None
    applied_digest: str | None
    error_code: str | None
    error_message: str | None


__all__ = [
    "ApplyStatusV2",
    "ArtifactReferenceV2",
    "BundleArtifactV2",
    "BundleManifestV2",
    "BundleReferenceV2",
    "ControlPlaneEnvelopeV2",
    "DataPlaneTargetV2",
    "DesiredBundleSetV2",
    "EventContractV2",
    "EventContractsV2",
    "EventModeV2",
    "JsonSchemaV2",
    "PluginContractV2",
    "PluginManifestV2",
    "PluginModuleV2",
    "ProfileEntryV2",
    "ProfileLayerKindV2",
    "ProfileLayerV2",
    "ProfileSnapshotV2",
    "ProfileSourceReferenceV2",
    "ProfileSourceV2",
    "PublicationStatusV2",
    "QuotaV2",
    "RestartPolicyV2",
    "RuntimeKindV2",
    "ScopeKindV2",
    "ScopeV2",
    "ServiceContractV2",
    "ServiceProvidedV2",
    "ServiceRequiredV2",
    "SnapshotApplyReceiptV2",
    "TrustKindV2",
]
