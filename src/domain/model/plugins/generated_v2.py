# Generated from shared/schemas/plugins/platform-plugin-protocol.v2.schema.json.
# Schema SHA-256: 5754a10a8e17beb69de1f7d93f3efb610a1b22d0a8c11dac101c5b064022bead
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
class PluginModuleV2:
    module_ref: str
    entrypoint: str
    artifact: ArtifactReferenceV2


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
    "ControlPlaneEnvelopeV2",
    "PluginManifestV2",
    "PluginModuleV2",
    "ProfileEntryV2",
    "ProfileSnapshotV2",
    "QuotaV2",
    "RestartPolicyV2",
    "RuntimeKindV2",
    "ScopeKindV2",
    "ScopeV2",
    "SnapshotApplyReceiptV2",
    "TrustKindV2",
]
