"""Pure contracts for MemStack's cross-runtime plugin manifest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_CAPABILITY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_PERMISSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,191}$")
_CONTRACT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,191}$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class CapabilityKind(str, Enum):
    """Kinds that can be registered in the platform capability registry."""

    AGENT_LOOP = "agent_loop"
    SYSTEM_PROMPT_SECTION = "system_prompt_section"
    TOOL = "tool"
    SKILL_PROVIDER = "skill_provider"
    SUBAGENT_PROVIDER = "subagent_provider"
    HOOK = "hook"
    POLICY = "policy"
    LLM_PROVIDER = "llm_provider"
    EMBEDDER = "embedder"
    RERANKER = "reranker"
    CHANNEL = "channel"
    HTTP_ROUTE = "http_route"
    CLI_COMMAND = "cli_command"
    UI_SLOT = "ui_slot"
    UI_RENDERER = "ui_renderer"
    STORAGE = "storage"
    GRAPH_BACKEND = "graph_backend"
    RETRIEVAL_BACKEND = "retrieval_backend"
    WORKFLOW_ENGINE = "workflow_engine"
    CREDENTIAL_SOURCE = "credential_source"
    TELEMETRY_EXPORTER = "telemetry_exporter"


class PluginRuntimeKind(str, Enum):
    """Execution boundary enforced for a plugin package."""

    PYTHON_TRUSTED = "python-trusted"
    WASM = "wasm"
    MCP = "mcp"
    SUBPROCESS = "subprocess"
    FRONTEND = "frontend"


class PluginTrust(str, Enum):
    """Trust tier granted to a plugin package."""

    BUILTIN = "builtin"
    SIGNED = "signed"
    TENANT_APPROVED = "tenant-approved"
    UNTRUSTED = "untrusted"


class PluginScope(str, Enum):
    """Default ownership scope for plugin activation."""

    GLOBAL = "global"
    TENANT = "tenant"
    PROJECT = "project"
    SESSION = "session"


class PluginRestartPolicy(str, Enum):
    """When a plugin code/config generation may become active."""

    PROCESS_BOUNDARY = "process-boundary"
    HOT_GENERATION = "hot-generation"


class PluginManifestError(ValueError):
    """Raised when a plugin manifest violates the platform contract."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        message = "; ".join(self.errors) or "invalid plugin manifest"
        super().__init__(message)


@dataclass(frozen=True)
class PluginRequirement:
    """A capability contract required from another enabled plugin."""

    capability: str
    min_version: str | None = None


@dataclass(frozen=True)
class ProvidedCapability:
    """One capability advertised by a plugin manifest."""

    kind: CapabilityKind
    id: str
    contract: str
    config_schema: dict[str, Any] = field(default_factory=dict)
    permissions: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        """Return the stable capability coordinates."""
        return self.kind.value, self.id


@dataclass(frozen=True)
class PluginActivation:
    """Activation and generation policy declared by a plugin."""

    default_scope: PluginScope = PluginScope.TENANT
    restart_policy: PluginRestartPolicy = PluginRestartPolicy.PROCESS_BOUNDARY


@dataclass(frozen=True)
class PluginManifest:
    """Immutable, cross-runtime description of a plugin package."""

    schema_version: int
    id: str
    version: str
    runtime: PluginRuntimeKind
    trust: PluginTrust
    requires: tuple[PluginRequirement, ...] = ()
    provides: tuple[ProvidedCapability, ...] = ()
    activation: PluginActivation = field(default_factory=PluginActivation)

    @property
    def provided_contracts(self) -> frozenset[str]:
        """Return the contract names supplied by this manifest."""
        return frozenset(item.contract for item in self.provides)

    def to_payload(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible manifest representation."""
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "version": self.version,
            "runtime": self.runtime.value,
            "trust": self.trust.value,
            "requires": [
                {
                    "capability": item.capability,
                    **({"min_version": item.min_version} if item.min_version else {}),
                }
                for item in self.requires
            ],
            "provides": [
                {
                    "kind": item.kind.value,
                    "id": item.id,
                    "contract": item.contract,
                    "config_schema": item.config_schema,
                    "permissions": list(item.permissions),
                }
                for item in self.provides
            ],
            "activation": {
                "default_scope": self.activation.default_scope.value,
                "restart_policy": self.activation.restart_policy.value,
            },
        }

    def to_json(self) -> str:
        """Return the canonical JSON encoding used by every runtime."""
        return json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"))


def parse_plugin_manifest(payload: object) -> PluginManifest:
    """Parse and validate a plugin manifest payload.

    Validation is deliberately manifest-first and does not import plugin code.
    A manifest with one invalid field fails with every collected error.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        raise PluginManifestError(["manifest must be a JSON object"])

    schema_version = _parse_integer(
        payload.get("schemaVersion", payload.get("schema_version")),
        "schemaVersion",
        errors,
    )
    if schema_version is not None and schema_version != 1:
        errors.append("schemaVersion must be 1")

    plugin_id = _parse_identifier(payload.get("id"), "id", errors)
    version = _parse_version(payload.get("version"), errors)
    runtime = _parse_enum(payload.get("runtime"), PluginRuntimeKind, "runtime", errors)
    trust = _parse_enum(payload.get("trust"), PluginTrust, "trust", errors)
    requires = _parse_requirements(payload.get("requires"), errors)
    provides = _parse_provides(payload.get("provides"), errors)
    activation = _parse_activation(payload.get("activation"), errors)

    if runtime == PluginRuntimeKind.PYTHON_TRUSTED and trust not in {
        PluginTrust.BUILTIN,
        PluginTrust.SIGNED,
    }:
        errors.append("runtime python-trusted requires builtin or signed trust")

    protected_kinds = {CapabilityKind.AGENT_LOOP, CapabilityKind.CREDENTIAL_SOURCE}
    if any(item.kind in protected_kinds for item in provides) and trust != PluginTrust.BUILTIN:
        errors.append("agent_loop and credential_source capabilities must be builtin")

    if errors:
        raise PluginManifestError(errors)

    return PluginManifest(
        schema_version=schema_version or 1,
        id=plugin_id or "",
        version=version or "",
        runtime=runtime or PluginRuntimeKind.PYTHON_TRUSTED,
        trust=trust or PluginTrust.UNTRUSTED,
        requires=requires,
        provides=provides,
        activation=activation,
    )


def parse_plugin_manifest_json(raw: str) -> PluginManifest:
    """Parse a JSON manifest and preserve JSON error context."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PluginManifestError([f"manifest JSON is invalid: {exc.msg}"]) from exc
    return parse_plugin_manifest(payload)


def _parse_integer(value: object, field_name: str, errors: list[str]) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{field_name} must be an integer")
        return None
    return value


def _parse_identifier(value: object, field_name: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        errors.append(f"{field_name} must match {_IDENTIFIER_PATTERN.pattern}")
        return None
    return value


def _parse_version(value: object, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not _VERSION_PATTERN.fullmatch(value):
        errors.append(f"version must match {_VERSION_PATTERN.pattern}")
        return None
    return value


def _parse_enum[T: Enum](
    value: object,
    enum_type: type[T],
    field_name: str,
    errors: list[str],
) -> T | None:
    if not isinstance(value, str):
        errors.append(f"{field_name} must be one of {[item.value for item in enum_type]}")
        return None
    try:
        return enum_type(value)
    except ValueError:
        errors.append(f"{field_name} must be one of {[item.value for item in enum_type]}")
        return None


def _parse_requirements(value: object, errors: list[str]) -> tuple[PluginRequirement, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        errors.append("requires must be an array")
        return ()

    requirements: list[PluginRequirement] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(value):
        if not isinstance(raw_item, dict):
            errors.append(f"requires[{index}] must be an object")
            continue
        capability = raw_item.get("capability")
        if not isinstance(capability, str) or not _CONTRACT_PATTERN.fullmatch(capability):
            errors.append(f"requires[{index}].capability must match {_CONTRACT_PATTERN.pattern}")
            continue
        if capability in seen:
            errors.append(f"requires[{index}].capability is declared more than once")
            continue
        seen.add(capability)
        min_version = raw_item.get("minVersion", raw_item.get("min_version"))
        if min_version is not None and (
            not isinstance(min_version, str) or not _VERSION_PATTERN.fullmatch(min_version)
        ):
            errors.append(f"requires[{index}].minVersion must match {_VERSION_PATTERN.pattern}")
            continue
        requirements.append(PluginRequirement(capability=capability, min_version=min_version))
    return tuple(requirements)


def _parse_provides(value: object, errors: list[str]) -> tuple[ProvidedCapability, ...]:
    if value is None:
        errors.append("provides is required and must be a non-empty array")
        return ()
    if not isinstance(value, list) or not value:
        errors.append("provides is required and must be a non-empty array")
        return ()

    capabilities: list[ProvidedCapability] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_contracts: set[str] = set()
    for index, raw_item in enumerate(value):
        if not isinstance(raw_item, dict):
            errors.append(f"provides[{index}] must be an object")
            continue
        kind = _parse_enum(raw_item.get("kind"), CapabilityKind, f"provides[{index}].kind", errors)
        capability_id = raw_item.get("id")
        if not isinstance(capability_id, str) or not _CAPABILITY_ID_PATTERN.fullmatch(
            capability_id
        ):
            errors.append(f"provides[{index}].id must match {_CAPABILITY_ID_PATTERN.pattern}")
            continue
        if kind is None:
            continue
        key = kind.value, capability_id
        if key in seen_keys:
            errors.append(f"provides[{index}] duplicates capability {kind.value}:{capability_id}")
            continue
        seen_keys.add(key)

        contract = raw_item.get("contract") or f"{kind.value}:{capability_id}"
        if not isinstance(contract, str) or not _CONTRACT_PATTERN.fullmatch(contract):
            errors.append(f"provides[{index}].contract must match {_CONTRACT_PATTERN.pattern}")
            continue
        if contract in seen_contracts:
            errors.append(f"provides[{index}] duplicates contract {contract}")
            continue
        seen_contracts.add(contract)

        config_schema = raw_item.get("configSchema", raw_item.get("config_schema"))
        if config_schema is None:
            config_schema = {}
        if not isinstance(config_schema, dict):
            errors.append(f"provides[{index}].configSchema must be an object")
            continue

        permissions = _parse_permissions(raw_item.get("permissions"), index, errors)
        capabilities.append(
            ProvidedCapability(
                kind=kind,
                id=capability_id,
                contract=contract,
                config_schema=dict(config_schema),
                permissions=permissions,
            )
        )
    return tuple(capabilities)


def _parse_permissions(value: object, index: int, errors: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        errors.append(f"provides[{index}].permissions must be an array")
        return ()
    permissions: list[str] = []
    seen: set[str] = set()
    for permission_index, raw_permission in enumerate(value):
        if not isinstance(raw_permission, str) or not _PERMISSION_PATTERN.fullmatch(raw_permission):
            errors.append(
                f"provides[{index}].permissions[{permission_index}] must match "
                f"{_PERMISSION_PATTERN.pattern}"
            )
            continue
        if raw_permission in seen:
            errors.append(
                f"provides[{index}].permissions[{permission_index}] is declared more than once"
            )
            continue
        seen.add(raw_permission)
        permissions.append(raw_permission)
    return tuple(permissions)


def _parse_activation(value: object, errors: list[str]) -> PluginActivation:
    if value is None:
        return PluginActivation()
    if not isinstance(value, dict):
        errors.append("activation must be an object")
        return PluginActivation()

    raw_default_scope = value.get("defaultScope", value.get("default_scope"))
    parsed_scope = (
        _parse_enum(raw_default_scope, PluginScope, "activation.defaultScope", errors)
        if raw_default_scope is not None
        else None
    )
    default_scope = parsed_scope or PluginScope.TENANT
    raw_restart_policy = value.get("restartPolicy", value.get("restart_policy"))
    parsed_restart_policy = (
        _parse_enum(
            raw_restart_policy,
            PluginRestartPolicy,
            "activation.restartPolicy",
            errors,
        )
        if raw_restart_policy is not None
        else None
    )
    restart_policy = parsed_restart_policy or PluginRestartPolicy.PROCESS_BOUNDARY
    return PluginActivation(default_scope=default_scope, restart_policy=restart_policy)
