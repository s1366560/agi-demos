"""Runtime for one signed optional-business package.

The host owns grants, scope, and storage. A plugin cannot pass an authority
object, import host modules, or choose another tenant.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import jsonschema

from src.infrastructure.plugins.sdk_path import ensure_plugin_sdk_path
from src.infrastructure.plugins.v2.plugin_namespace_store_v2 import (
    MemoryPluginNamespaceStoreV2,
    NamespaceKeyV2,
    NamespaceRecordV2,
    PluginNamespaceStoreV2,
    PluginStorageError,
    assert_supported_schema_v2,
)
from src.infrastructure.plugins.wasm_host import WasmHostError, WasmToolHost

ensure_plugin_sdk_path()

from memstack_plugin_sdk.contract import (
    ContributionDocument,
    ContractError,
    ToolContribution,
    parse_contribution,
    parse_slot_ui,
    sha256_digest,
)

HIGH_RISK_PERMISSIONS = frozenset({"tools.execute", "storage.write"})
DEFAULT_CAPABILITY_LEASE = timedelta(minutes=15)


class OptionalBusinessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class ScopeBindingV2:
    tenant_id: str
    project_id: str


@dataclass(frozen=True, kw_only=True)
class SignedPackageBytesV2:
    """Verified bytes already admitted by the host. This object does not re-sign."""

    plugin_id: str
    version: str
    digest: str
    wasm: bytes
    contribution: ContributionDocument
    ui_files: dict[str, bytes]
    approved_permissions: frozenset[str]


@dataclass
class LifecycleProjectionV2:
    plugin_id: str
    version: str
    source: str
    package_recorded: bool
    desired_enabled: bool
    runtime_phase: str
    ui_mounted: bool
    sync: str
    desired_revision: int
    actual_generation: int
    desired_digest: str | None
    actual_digest: str | None
    failure: str | None
    retention: str


@dataclass
class _ActiveGeneration:
    package: SignedPackageBytesV2
    host: WasmToolHost
    grant: frozenset[str]
    lease_expires_at: datetime


@dataclass
class OptionalBusinessSessionV2:
    """One scope's view of a package. Grants are fixed at enable time."""

    plugin_id: str
    scope: ScopeBindingV2
    _runtime: SignedOptionalBusinessRuntimeV2 = field(repr=False)

    def invoke(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.invoke(self.plugin_id, self.scope, tool_name, payload)

    def storage_put(self, item_key: str, document: dict[str, Any]) -> None:
        self._runtime.storage_put(self.plugin_id, self.scope, item_key, document)

    def storage_get(self, item_key: str) -> dict[str, Any] | None:
        return self._runtime.storage_get(self.plugin_id, self.scope, item_key)

    def skills(self) -> tuple[str, ...]:
        return self._runtime.skills(self.plugin_id)

    def mount_ui(self, slot: str, target: str) -> dict[str, Any]:
        return self._runtime.mount_ui(self.plugin_id, slot, target)

    def dispose_ui(self) -> None:
        self._runtime.dispose_ui(self.plugin_id)


class SignedOptionalBusinessRuntimeV2:
    def __init__(
        self,
        store: PluginNamespaceStoreV2 | None = None,
        *,
        source: str = "signed-package",
        lease: timedelta = DEFAULT_CAPABILITY_LEASE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store or MemoryPluginNamespaceStoreV2()
        self.source = source
        self.lease = lease
        self._clock = clock or (lambda: datetime.now(UTC))
        self._recorded: dict[str, SignedPackageBytesV2] = {}
        self._previous: dict[str, SignedPackageBytesV2] = {}
        self._active: dict[str, _ActiveGeneration] = {}
        self._desired_enabled: dict[str, bool] = {}
        self._revision: dict[str, int] = {}
        self._generation: dict[str, int] = {}
        self._phase: dict[str, str] = {}
        self._sync: dict[str, str] = {}
        self._failure: dict[str, str | None] = {}
        self._ui_mounted: dict[str, bool] = {}
        self._retention: dict[str, str] = {}
        self._revoked: set[str] = set()

    def record(self, package: SignedPackageBytesV2) -> None:
        self._require_grant_subset(package)
        self._recorded[package.plugin_id] = package
        self._desired_enabled.setdefault(package.plugin_id, False)
        self._revision.setdefault(package.plugin_id, 0)
        self._generation.setdefault(package.plugin_id, 0)
        self._phase.setdefault(package.plugin_id, "inactive")
        self._sync.setdefault(package.plugin_id, "current")
        self._failure.setdefault(package.plugin_id, None)
        self._ui_mounted.setdefault(package.plugin_id, False)
        self._retention.setdefault(package.plugin_id, "retained")

    def enable(self, plugin_id: str) -> None:
        package = self._require_recorded(plugin_id)
        if plugin_id in self._revoked:
            raise OptionalBusinessError("revoked", "revoked package cannot be enabled")
        self._desired_enabled[plugin_id] = True
        self._revision[plugin_id] += 1
        self._apply(package)

    def stage_update(self, package: SignedPackageBytesV2) -> None:
        """Apply a new verified digest or keep the previous generation on failure."""
        current = self._active.get(package.plugin_id)
        self._require_grant_subset(package)
        if current is not None:
            added = package.approved_permissions - current.grant
            if added:
                raise OptionalBusinessError(
                    "permission_upgrade_required",
                    f"new permissions require approval: {', '.join(sorted(added))}",
                )
        self._phase[package.plugin_id] = "loading"
        try:
            host = self._compile(package)
        except (OptionalBusinessError, WasmHostError, ContractError) as exc:
            self._phase[package.plugin_id] = "active" if current is not None else "failed"
            self._sync[package.plugin_id] = "degraded"
            self._failure[package.plugin_id] = str(exc)
            raise OptionalBusinessError("apply_failed", str(exc)) from exc
        if current is not None:
            self._previous[package.plugin_id] = current.package
            current.host.close()
        self._recorded[package.plugin_id] = package
        self._commit(package, host)

    def rollback(self, plugin_id: str) -> LifecycleProjectionV2:
        previous = self._previous.get(plugin_id)
        if previous is None:
            raise OptionalBusinessError("rollback_unavailable", "no previous verified digest")
        self._revision[plugin_id] += 1
        self._apply(previous)
        return self.projection(plugin_id)

    def disable(self, plugin_id: str) -> None:
        self._desired_enabled[plugin_id] = False
        self._stop_runtime(plugin_id)
        self._retention[plugin_id] = "retained"

    def uninstall(self, plugin_id: str) -> None:
        self.disable(plugin_id)
        self._recorded.pop(plugin_id, None)
        self._retention[plugin_id] = "retained"

    def purge(self, plugin_id: str, scope: ScopeBindingV2) -> int:
        self.uninstall(plugin_id)
        self._retention[plugin_id] = "purged"
        return self.store.purge(
            plugin_id=plugin_id, tenant_id=scope.tenant_id, project_id=scope.project_id
        )

    def revoke(self, plugin_id: str) -> None:
        self._revoked.add(plugin_id)
        self._stop_runtime(plugin_id)
        self._sync[plugin_id] = "degraded"
        self._failure[plugin_id] = "revoked"

    def mark_sync(self, plugin_id: str, status: str) -> None:
        if status not in {"current", "stale", "degraded"}:
            raise OptionalBusinessError("sync_status", "unknown sync status")
        self._sync[plugin_id] = status

    def projection(self, plugin_id: str) -> LifecycleProjectionV2:
        package = self._active.get(plugin_id)
        recorded = self._recorded.get(plugin_id)
        shown = package.package if package is not None else recorded
        return LifecycleProjectionV2(
            plugin_id=plugin_id,
            version="" if shown is None else shown.version,
            source=self.source,
            package_recorded=recorded is not None or package is not None,
            desired_enabled=self._desired_enabled.get(plugin_id, False),
            runtime_phase=self._phase.get(plugin_id, "inactive"),
            ui_mounted=self._ui_mounted.get(plugin_id, False),
            sync=self._sync.get(plugin_id, "current"),
            desired_revision=self._revision.get(plugin_id, 0),
            actual_generation=self._generation.get(plugin_id, 0),
            desired_digest=None if recorded is None else recorded.digest,
            actual_digest=None if package is None else package.package.digest,
            failure=self._failure.get(plugin_id),
            retention=self._retention.get(plugin_id, "retained"),
        )

    def session(self, plugin_id: str, scope: ScopeBindingV2) -> OptionalBusinessSessionV2:
        return OptionalBusinessSessionV2(plugin_id=plugin_id, scope=scope, _runtime=self)

    def invoke(
        self,
        plugin_id: str,
        scope: ScopeBindingV2,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_not_revoked(plugin_id)
        active = self._require_active(plugin_id)
        tool = self._tool(active.package, tool_name)
        self._require_permissions(active, tool.permissions)
        self._require_lease(active, tool.permissions)
        if not self._desired_enabled.get(plugin_id, False):
            raise OptionalBusinessError("not_enabled", "disabled package cannot execute")
        try:
            jsonschema.validate(payload, tool.input_schema)
        except jsonschema.ValidationError as exc:
            raise OptionalBusinessError("input_schema", exc.message) from exc
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        try:
            if tool.abi == "invoke":
                produced = active.host.invoke_json(tool_name, raw, tenant_id=scope.tenant_id)
            else:
                outcome = active.host.call(tool_name, raw, tenant_id=scope.tenant_id)
                produced = json.dumps({"abi": "score", "score": outcome.score})
            decoded = json.loads(produced)
        except (WasmHostError, json.JSONDecodeError) as exc:
            raise OptionalBusinessError("invoke_failed", str(exc)) from exc
        try:
            jsonschema.validate(decoded, tool.output_schema)
        except jsonschema.ValidationError as exc:
            raise OptionalBusinessError("output_schema", exc.message) from exc
        if not isinstance(decoded, dict):
            raise OptionalBusinessError("output_schema", "tool output must be an object")
        return decoded

    def storage_put(
        self, plugin_id: str, scope: ScopeBindingV2, item_key: str, document: dict[str, Any]
    ) -> None:
        self._require_not_revoked(plugin_id)
        active = self._require_active(plugin_id)
        self._require_permissions(active, frozenset({"storage.write"}))
        self._require_lease(active, frozenset({"storage.write"}))
        record = NamespaceRecordV2(schema_version=1, document=document)
        assert_supported_schema_v2(record)
        self.store.put(self._key(plugin_id, scope, item_key), record)

    def storage_get(
        self, plugin_id: str, scope: ScopeBindingV2, item_key: str
    ) -> dict[str, Any] | None:
        self._require_not_revoked(plugin_id)
        active = self._require_active(plugin_id)
        self._require_permissions(active, frozenset({"storage.read"}))
        found = self.store.get(self._key(plugin_id, scope, item_key))
        if found is None:
            return None
        try:
            assert_supported_schema_v2(found)
        except PluginStorageError as exc:
            raise OptionalBusinessError(exc.code, str(exc)) from exc
        return dict(found.document)

    def skills(self, plugin_id: str) -> tuple[str, ...]:
        active = self._require_active(plugin_id)
        self._require_not_revoked(plugin_id)
        self._require_permissions(active, frozenset({"skills.register"}))
        return tuple(skill.skill_id for skill in active.package.contribution.skills)

    def mount_ui(self, plugin_id: str, slot: str, target: str) -> dict[str, Any]:
        active = self._require_active(plugin_id)
        self._require_not_revoked(plugin_id)
        matches = [
            item
            for item in active.package.contribution.ui
            if item.slot == slot and target in item.targets
        ]
        if len(matches) != 1:
            raise OptionalBusinessError("ui_conflict", "slot contribution must resolve to one ui")
        ui = matches[0]
        self._require_permissions(active, ui.permissions)
        content = active.package.ui_files.get(ui.path)
        if content is None or sha256_digest(content) != ui.digest:
            raise OptionalBusinessError("ui_digest", "ui bytes do not match the signed digest")
        try:
            document = parse_slot_ui(json.loads(content.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError, ContractError) as exc:
            raise OptionalBusinessError("ui_document", str(exc)) from exc
        self._ui_mounted[plugin_id] = True
        return {
            "slot": slot,
            "target": target,
            "title": document.title,
            "actions": [{"id": action_id, "label": label} for action_id, label in document.actions],
            "digest": ui.digest,
        }

    def dispose_ui(self, plugin_id: str) -> None:
        self._ui_mounted[plugin_id] = False

    def dispatch_command(
        self, plugin_id: str, scope: ScopeBindingV2, command_id: str
    ) -> dict[str, Any]:
        active = self._require_active(plugin_id)
        self._require_not_revoked(plugin_id)
        matches = [
            command
            for command in active.package.contribution.commands
            if command.command_id == command_id
        ]
        if len(matches) != 1:
            raise OptionalBusinessError("command_conflict", "command must resolve to one contribution")
        command = matches[0]
        self._require_permissions(active, command.permissions)
        return self.invoke(plugin_id, scope, command.tool, dict(command.payload))

    def _apply(self, package: SignedPackageBytesV2) -> None:
        self._phase[package.plugin_id] = "loading"
        try:
            host = self._compile(package)
        except Exception as exc:
            active = package.plugin_id in self._active
            self._phase[package.plugin_id] = "active" if active else "failed"
            self._sync[package.plugin_id] = "degraded"
            self._failure[package.plugin_id] = str(exc)
            if active:
                raise OptionalBusinessError("apply_failed", str(exc)) from exc
            raise
        previous = self._active.get(package.plugin_id)
        if previous is not None:
            self._previous[package.plugin_id] = previous.package
            previous.host.close()
        self._recorded[package.plugin_id] = package
        self._commit(package, host)

    def _commit(self, package: SignedPackageBytesV2, host: WasmToolHost) -> None:
        now = self._clock()
        self._active[package.plugin_id] = _ActiveGeneration(
            package=package,
            host=host,
            grant=package.approved_permissions,
            lease_expires_at=now + self.lease,
        )
        self._generation[package.plugin_id] = self._generation.get(package.plugin_id, 0) + 1
        self._phase[package.plugin_id] = "active"
        self._sync[package.plugin_id] = "current"
        self._failure[package.plugin_id] = None
        self._desired_enabled[package.plugin_id] = True

    def _compile(self, package: SignedPackageBytesV2) -> WasmToolHost:
        if not package.wasm.startswith(b"\x00asm") and b"(module" not in package.wasm:
            raise OptionalBusinessError("wasm_invalid", "wasm artifact is not a module")
        return WasmToolHost(package.plugin_id, package.wasm, tenant_id="unscoped")

    def _stop_runtime(self, plugin_id: str) -> None:
        active = self._active.pop(plugin_id, None)
        if active is not None:
            active.host.close()
        self._phase[plugin_id] = "inactive"
        self._ui_mounted[plugin_id] = False
        self._desired_enabled[plugin_id] = False

    def _require_recorded(self, plugin_id: str) -> SignedPackageBytesV2:
        package = self._recorded.get(plugin_id)
        if package is None:
            raise OptionalBusinessError("not_recorded", "package is not recorded")
        return package

    def _require_active(self, plugin_id: str) -> _ActiveGeneration:
        if not self._desired_enabled.get(plugin_id, False):
            raise OptionalBusinessError("not_enabled", "package is not enabled")
        active = self._active.get(plugin_id)
        if active is None or self._phase.get(plugin_id) != "active":
            raise OptionalBusinessError("not_active", "package runtime is not active")
        return active

    def _require_not_revoked(self, plugin_id: str) -> None:
        if plugin_id in self._revoked:
            raise OptionalBusinessError("revoked", "revoked package cannot read or write")

    def _require_permissions(self, active: _ActiveGeneration, required: frozenset[str]) -> None:
        missing = sorted(required - active.grant)
        if missing:
            raise OptionalBusinessError(
                "permission_denied", f"missing approved permissions: {', '.join(missing)}"
            )

    def _require_lease(self, active: _ActiveGeneration, permissions: frozenset[str]) -> None:
        if permissions.isdisjoint(HIGH_RISK_PERMISSIONS):
            return
        if self._clock() >= active.lease_expires_at:
            raise OptionalBusinessError(
                "lease_expired", "high-risk plugin capability lease has expired"
            )

    def _require_grant_subset(self, package: SignedPackageBytesV2) -> None:
        declared = _declared_permissions(package.contribution)
        if not declared <= package.approved_permissions:
            missing = ", ".join(sorted(declared - package.approved_permissions))
            raise OptionalBusinessError(
                "permission_not_approved", f"package lacks approval for {missing}"
            )

    @staticmethod
    def _tool(package: SignedPackageBytesV2, tool_name: str) -> ToolContribution:
        matches = [tool for tool in package.contribution.tools if tool.name == tool_name]
        if len(matches) != 1:
            raise OptionalBusinessError("tool_conflict", "tool name must resolve to one contribution")
        return matches[0]

    @staticmethod
    def _key(plugin_id: str, scope: ScopeBindingV2, item_key: str) -> NamespaceKeyV2:
        if not item_key or "/" in item_key or len(item_key) > 128:
            raise OptionalBusinessError("storage_key", "storage key is invalid")
        return NamespaceKeyV2(
            plugin_id=plugin_id,
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            item_key=item_key,
        )


def load_contribution_v2(payload: dict[str, Any]) -> ContributionDocument:
    try:
        return parse_contribution(payload)
    except ContractError as exc:
        raise OptionalBusinessError(exc.code, str(exc)) from exc


def _declared_permissions(contribution: ContributionDocument) -> frozenset[str]:
    declared: set[str] = set()
    for tool in contribution.tools:
        declared |= tool.permissions
    for skill in contribution.skills:
        declared |= skill.permissions
    for ui in contribution.ui:
        declared |= ui.permissions
    for command in contribution.commands:
        declared |= command.permissions
    if contribution.storage is not None:
        declared |= contribution.storage.permissions
    return frozenset(declared)
