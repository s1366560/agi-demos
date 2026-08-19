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
# Requirements may pin the owning plugin (`contract@plugin-id`) so a
# required provider is unique even when several plugins share a contract.
_REQUIREMENT_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9._:-]{0,191}(?:@[a-z0-9][a-z0-9._-]{0,63})?$"
)
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
class PluginResourceQuota:
    """Resource limits embedded in a signed plugin manifest."""

    max_wasm_fuel: int | None = None
    max_wasm_memory_bytes: int | None = None
    max_wall_time_ms: int | None = None
    max_concurrent_calls: int | None = None
    max_output_bytes: int | None = None
    max_network_requests_per_minute: int | None = None
    max_storage_bytes: int | None = None
    max_monthly_usd: float | None = None

    def to_payload(self) -> dict[str, int | float]:
        """Return only explicitly declared limits to preserve manifest stability."""
        values: dict[str, int | float] = {}
        if self.max_wasm_fuel is not None:
            values["max_wasm_fuel"] = self.max_wasm_fuel
        if self.max_wasm_memory_bytes is not None:
            values["max_wasm_memory_bytes"] = self.max_wasm_memory_bytes
        if self.max_wall_time_ms is not None:
            values["max_wall_time_ms"] = self.max_wall_time_ms
        if self.max_concurrent_calls is not None:
            values["max_concurrent_calls"] = self.max_concurrent_calls
        if self.max_output_bytes is not None:
            values["max_output_bytes"] = self.max_output_bytes
        if self.max_network_requests_per_minute is not None:
            values["max_network_requests_per_minute"] = self.max_network_requests_per_minute
        if self.max_storage_bytes is not None:
            values["max_storage_bytes"] = self.max_storage_bytes
        if self.max_monthly_usd is not None:
            values["max_monthly_usd"] = self.max_monthly_usd
        return values


@dataclass(frozen=True)
class PluginActivation:
    """Activation and generation policy declared by a plugin."""

    default_scope: PluginScope = PluginScope.TENANT
    restart_policy: PluginRestartPolicy = PluginRestartPolicy.PROCESS_BOUNDARY
    quotas: PluginResourceQuota = field(default_factory=PluginResourceQuota)


@dataclass(frozen=True)
class PluginBilling:
    """Signed pricing facts used by host-side spend quotas."""

    usd_micros_per_call: int = 0

    def to_payload(self) -> dict[str, int]:
        """Return the canonical billing payload."""
        return {"usd_micros_per_call": self.usd_micros_per_call}


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
    billing: PluginBilling = field(default_factory=PluginBilling)

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
                **(
                    {"quotas": self.activation.quotas.to_payload()}
                    if self.activation.quotas.to_payload()
                    else {}
                ),
            },
            **({"billing": self.billing.to_payload()} if self.billing.usd_micros_per_call else {}),
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
    billing = _parse_billing(payload.get("billing"), errors)

    if runtime == PluginRuntimeKind.PYTHON_TRUSTED and trust not in {
        PluginTrust.BUILTIN,
        PluginTrust.SIGNED,
    }:
        errors.append("runtime python-trusted requires builtin or signed trust")

    if any(item.kind == CapabilityKind.CREDENTIAL_SOURCE for item in provides) and (
        trust != PluginTrust.BUILTIN
    ):
        errors.append("credential_source capabilities must be builtin")
    if any(item.kind == CapabilityKind.AGENT_LOOP for item in provides):
        if trust not in {PluginTrust.BUILTIN, PluginTrust.SIGNED}:
            errors.append("agent_loop capabilities require builtin or signed trust")
        if runtime != PluginRuntimeKind.PYTHON_TRUSTED:
            errors.append("agent_loop capabilities require the python-trusted runtime")

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
        billing=billing,
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
        if not isinstance(capability, str) or not _REQUIREMENT_PATTERN.fullmatch(capability):
            errors.append(
                f"requires[{index}].capability must match {_REQUIREMENT_PATTERN.pattern}"
            )
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
    raw_quotas = value.get("quotas")
    quotas = (
        _parse_resource_quota(raw_quotas, errors)
        if raw_quotas is not None
        else PluginResourceQuota()
    )
    return PluginActivation(
        default_scope=default_scope,
        restart_policy=restart_policy,
        quotas=quotas,
    )


def _parse_billing(value: object, errors: list[str]) -> PluginBilling:
    if value is None:
        return PluginBilling()
    if not isinstance(value, dict):
        errors.append("billing must be an object")
        return PluginBilling()

    raw_rate = value.get("usdMicrosPerCall", value.get("usd_micros_per_call"))
    if (
        raw_rate is None
        or isinstance(raw_rate, bool)
        or not isinstance(raw_rate, int)
        or raw_rate < 0
    ):
        errors.append("billing.usdMicrosPerCall must be an integer >= 0")
        raw_rate = None
    known = {"usdMicrosPerCall", "usd_micros_per_call"}
    unknown = sorted(set(value) - known)
    if unknown:
        errors.append(f"billing has unknown fields: {', '.join(unknown)}")
    return PluginBilling(usd_micros_per_call=raw_rate or 0)


def _parse_resource_quota(value: object, errors: list[str]) -> PluginResourceQuota:
    if not isinstance(value, dict):
        errors.append("activation.quotas must be an object")
        return PluginResourceQuota()

    integer_fields = {
        "max_wasm_fuel": 1,
        "max_wasm_memory_bytes": 64 * 1024,
        "max_wall_time_ms": 1,
        "max_concurrent_calls": 1,
        "max_output_bytes": 1,
        "max_network_requests_per_minute": 1,
        "max_storage_bytes": 1,
    }
    parsed_integers: dict[str, int] = {}
    for field_name, minimum in integer_fields.items():
        raw_value = value.get(field_name)
        if raw_value is None:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < minimum:
            errors.append(f"activation.quotas.{field_name} must be an integer >= {minimum}")
            continue
        parsed_integers[field_name] = raw_value

    raw_monthly_usd = value.get("max_monthly_usd")
    monthly_usd: float | None = None
    if raw_monthly_usd is not None:
        if (
            isinstance(raw_monthly_usd, bool)
            or not isinstance(raw_monthly_usd, (int, float))
            or raw_monthly_usd <= 0
        ):
            errors.append("activation.quotas.max_monthly_usd must be a number > 0")
        else:
            monthly_usd = float(raw_monthly_usd)

    known = {*integer_fields, "max_monthly_usd"}
    unknown = sorted(set(value) - known)
    if unknown:
        errors.append(f"activation.quotas has unknown fields: {', '.join(unknown)}")
    return PluginResourceQuota(
        max_wasm_fuel=parsed_integers.get("max_wasm_fuel"),
        max_wasm_memory_bytes=parsed_integers.get("max_wasm_memory_bytes"),
        max_wall_time_ms=parsed_integers.get("max_wall_time_ms"),
        max_concurrent_calls=parsed_integers.get("max_concurrent_calls"),
        max_output_bytes=parsed_integers.get("max_output_bytes"),
        max_network_requests_per_minute=parsed_integers.get("max_network_requests_per_minute"),
        max_storage_bytes=parsed_integers.get("max_storage_bytes"),
        max_monthly_usd=monthly_usd,
    )
