"""Persist each project's desired and last usable signed package across API replicas."""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import BigInteger, bindparam, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.chat_adapter_scope import chat_adapter_pin
from src.host.operations.project_package_audit import PackageAudit, project_operation
from src.host.packages.project_installation_view import installation_view, market_installation
from src.host.packages.release_governance import check_catalog_release
from src.host.packages.release_pin import (
    ACTIVE_APPLICATION_PIN,
    AGENT_PACKAGE_PINS,
    AgentPackagePin as AgentPackagePin,
)
from src.host.packages.rich_pages import check_page_routes
from src.host.runtime.package_call import admit_package_call
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Project,
)
from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    AgentRunPackageSelection,
    ProjectPluginInstallation as Installation,
    ProjectPluginRelease as Release,
    agent_driver_conflict,
    select_transition_release,
)
from src.infrastructure.plugins.v2.oci_mcp_records import (
    WorkerRecords,
    bind_worker_records,
    check_storage_quota,
)
from src.infrastructure.plugins.v2.oci_mcp_services import WorkerServices, bind_worker_services
from src.infrastructure.plugins.v2.plugin_namespace_store_v2 import (
    NamespaceKeyV2,
    NamespaceRecordV2,
    SqlPluginNamespaceStoreV2,
    assert_supported_schema_v2,
)
from src.infrastructure.plugins.v2.project_plugin_package import admit_package
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedPackageBytesV2,
)
from src.infrastructure.plugins.wasm_host import WasmHostError


class ProjectPluginInstallationService:
    def __init__(
        self,
        db: AsyncSession,
        scope: ScopeBindingV2,
        keys: tuple[str, ...],
        *,
        actor_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.db = db
        self.scope = scope
        self.keys = keys
        self.actor_id = actor_id
        self.run_id = run_id

    def _audit(
        self, operation: str, actor_id: str | None = None
    ) -> AbstractContextManager[PackageAudit]:
        return project_operation(
            operation,
            actor_id=actor_id or self.actor_id,
            tenant_id=self.scope.tenant_id,
            project_id=self.scope.project_id,
            run_id=self.run_id,
        )

    async def _lock(self) -> None:
        project = await self.db.scalar(
            select(Project.id)
            .where(Project.id == self.scope.project_id, Project.tenant_id == self.scope.tenant_id)
            .with_for_update()
        )
        if project is None:
            raise OptionalBusinessError("forbidden", "project is unavailable")

    async def _state(self, plugin: str) -> Installation | None:
        return await self.db.get(
            Installation, (self.scope.project_id, plugin), populate_existing=True
        )

    async def is_installed(self, plugin: str) -> bool:
        state = await self._state(plugin)
        return bool(state and state.desired)

    async def installed_ids(self) -> list[str]:
        ids = await self.db.scalars(
            select(Installation.plugin_id)
            .where(
                Installation.project_id == self.scope.project_id, Installation.desired.is_not(None)
            )
            .order_by(Installation.plugin_id)
        )
        return list(ids.all())

    async def marketplace_items(self) -> list[dict[str, Any]]:
        return [await self.marketplace_item(plugin) for plugin in await self.installed_ids()]

    async def marketplace_item(self, plugin: str) -> dict[str, Any]:
        view = await self.projection(plugin)
        return market_installation(plugin, view, "project")

    async def _release(self, plugin: str, version: str) -> Release:
        release = await self.db.scalar(
            select(Release).where(
                Release.project_id == self.scope.project_id,
                Release.tenant_id == self.scope.tenant_id,
                Release.plugin_id == plugin,
                Release.version == version,
            )
        )
        if release is None:
            raise OptionalBusinessError("not_recorded", "package version is unavailable")
        return release

    async def inspect(self, raw: bytes) -> SignedPackageBytesV2:
        from src.infrastructure.plugins.v2.bundle_archive import declared_bundle_permissions_v2

        requested = await asyncio.to_thread(declared_bundle_permissions_v2, raw)
        package = await asyncio.to_thread(admit_package, raw, self.keys, requested, self.scope)
        await check_catalog_release(self.db, package.plugin_id, package.version, raw)
        return package

    async def record(
        self, raw: bytes, permissions: frozenset[str], approved_by: str
    ) -> SignedPackageBytesV2:
        package, _ = await self.record_selection(raw, permissions, approved_by)
        return package

    async def record_selection(
        self,
        raw: bytes,
        permissions: frozenset[str],
        approved_by: str,
        *,
        expected_revision: int | None = None,
        expected_digest: str | None = None,
        expected_identity: tuple[str, str] | None = None,
        activate: bool = False,
    ) -> tuple[SignedPackageBytesV2, int]:
        with self._audit("install", approved_by) as audit:
            package = await asyncio.to_thread(
                admit_package, raw, self.keys, permissions, self.scope
            )
            if expected_digest is not None and package.digest != expected_digest:
                raise OptionalBusinessError(
                    "conflict", "signed release differs from the reviewed digest"
                )
            if (
                expected_identity is not None
                and (package.plugin_id, package.version) != expected_identity
            ):
                raise OptionalBusinessError(
                    "invalid_package", "signed identity differs from the npm release"
                )
            audit.release(package)
            await self._lock()
            state = await self._state(package.plugin_id)
            revision = state.revision if state else 0
            if expected_revision is not None and expected_revision != revision:
                raise OptionalBusinessError(
                    "conflict", "package selection changed, reload its state"
                )
            await check_catalog_release(self.db, package.plugin_id, package.version, raw)
            release = await self.db.get(
                Release, (self.scope.project_id, package.plugin_id, package.version)
            )
            if release is not None and release.digest != package.digest:
                raise OptionalBusinessError("conflict", "package versions are immutable")
            if release is None:
                self.db.add(
                    Release(
                        project_id=self.scope.project_id,
                        tenant_id=self.scope.tenant_id,
                        plugin_id=package.plugin_id,
                        version=package.version,
                        digest=package.digest,
                        archive=raw,
                        permissions=sorted(package.approved_permissions),
                        approved_by=approved_by,
                    )
                )
            if state is None:
                state = Installation(
                    project_id=self.scope.project_id, plugin_id=package.plugin_id, revision=0
                )
                self.db.add(state)
            if state.desired != package.version or (
                activate and (state.active != package.version or not state.enabled or state.failure)
            ):
                state.desired = package.version
                state.revision += 1
                state.failure = None
            state.retention = "retained"
            if activate:
                await self.db.flush()
                await self._activate(state, package.version)
            revision = state.revision
            await self.db.commit()
            return package, revision

    async def _verified(
        self, plugin: str, version: str, audit: PackageAudit | None = None
    ) -> SignedPackageBytesV2:
        release = await self._release(plugin, version)
        if audit is not None:
            audit.plugin_id, audit.version, audit.digest = (
                release.plugin_id,
                release.version,
                release.digest,
            )
        await check_catalog_release(self.db, plugin, version, release.archive)
        return await asyncio.to_thread(
            admit_package, release.archive, self.keys, frozenset(release.permissions), self.scope
        )

    async def reviewed_release(self, plugin: str, version: str) -> SignedPackageBytesV2:
        return await self._verified(plugin, version)

    async def _check_service_replacement(
        self, active: str, candidate: SignedPackageBytesV2
    ) -> None:
        previous = await self._release(candidate.plugin_id, active)
        # An independently withdrawn release can still describe the contract being replaced.
        try:
            original = await asyncio.to_thread(
                admit_package,
                previous.archive,
                self.keys,
                frozenset(previous.permissions),
                self.scope,
            )
        except (ValueError, OptionalBusinessError):
            # A release that no longer passes trust/ABI checks cannot supply a live service.
            return
        dropped = {(r.service, r.version) for r in original.services.provides} - {
            (r.service, r.version) for r in candidate.services.provides
        }
        if not dropped:
            return
        rows = await self.db.execute(
            select(Release.archive, Release.permissions)
            .join(
                Installation,
                (Installation.project_id == Release.project_id)
                & (Installation.plugin_id == Release.plugin_id)
                & (Installation.active == Release.version),
            )
            .where(
                Release.project_id == self.scope.project_id,
                Release.tenant_id == self.scope.tenant_id,
                Installation.enabled.is_(True),
                Release.plugin_id != candidate.plugin_id,
            )
            .execution_options(populate_existing=True)
        )
        for raw, permissions in rows:
            try:
                consumer = await asyncio.to_thread(
                    admit_package, raw, self.keys, frozenset(permissions), self.scope
                )
            except (ValueError, OptionalBusinessError):
                continue
            if any((r.service, r.version) in dropped for r in consumer.services.requires):
                raise OptionalBusinessError(
                    "conflict", "an enabled project package requires the previous service contract"
                )

    async def _activate(self, state: Installation, candidate: str) -> None:
        try:
            package = await self._verified(state.plugin_id, candidate)
            from src.infrastructure.plugins.v2.project_package_execution import (
                prepare_project_guest,
            )

            conflict = await agent_driver_conflict(
                self.db,
                self.scope.tenant_id,
                self.scope.project_id,
                package.plugin_id,
                package.approved_permissions,
            )
            if conflict:
                raise OptionalBusinessError("conflict", conflict)
            await check_page_routes(self, package)
            await self.resolve_service_pins(package)
            if state.active and state.active != candidate:
                await self._check_service_replacement(state.active, package)
            await prepare_project_guest(package, self.scope)
        except (ValueError, OptionalBusinessError, WasmHostError) as exc:
            state.failure = str(exc)[:512]
            state.enabled = True
            await self.db.commit()
            raise OptionalBusinessError("apply_failed", str(exc)) from exc
        if state.active != candidate:
            state.previous = state.active
            state.active = candidate
            state.generation += 1
        state.enabled = True
        state.desired = candidate
        state.failure = None

    async def mutate(
        self,
        plugin: str,
        action: str,
        *,
        expected_version: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._audit(action) as audit:
            await self._lock()
            selected = await select_transition_release(
                self.db, self.scope.tenant_id, self.scope.project_id, plugin, action
            )
            if selected is None:
                raise OptionalBusinessError("not_recorded", "package is not recorded")
            state, audit.version, audit.digest = selected
            audit.plugin_id = state.plugin_id
            if expected_revision is not None and state.revision != expected_revision:
                raise OptionalBusinessError(
                    "conflict", "package selection changed, reload its state"
                )
            if expected_version is not None and state.desired != expected_version:
                raise OptionalBusinessError("conflict", "installed version changed")
            before = (state.desired, state.active, state.enabled, state.retention)
            if action in {"enable", "rollback"}:
                candidate = state.desired if action == "enable" else state.previous
                if candidate is None:
                    raise OptionalBusinessError(
                        "rollback_unavailable", "no requested package version"
                    )
                await self._activate(state, candidate)
            elif action in {"disable", "uninstall", "purge"}:
                if state.enabled:
                    state.authorization_epoch += 1
                state.enabled = False
                state.active = None
                state.previous = None
                state.failure = None
                if action != "disable":
                    state.desired = None
                if action == "purge":
                    await self.db.execute(
                        delete(Release).where(
                            Release.project_id == self.scope.project_id,
                            Release.tenant_id == self.scope.tenant_id,
                            Release.plugin_id == plugin,
                        )
                    )
                    await self.db.run_sync(
                        lambda db: SqlPluginNamespaceStoreV2(db).purge(
                            plugin_id=plugin,
                            project_id=self.scope.project_id,
                            tenant_id=self.scope.tenant_id,
                        )
                    )
                    state.retention = "purged"
            else:
                raise OptionalBusinessError("action", "unknown package operation")
            if before != (state.desired, state.active, state.enabled, state.retention):
                state.revision += 1
            await self.db.commit()
            return await self.projection(plugin)

    async def projection(self, plugin: str) -> dict[str, Any]:
        return await installation_view(
            self.db, self.scope, plugin, await self._state(plugin), self._verified
        )

    async def _active(self, plugin: str) -> SignedPackageBytesV2:
        state = await self._state(plugin)
        if not state or not state.enabled or not state.active:
            raise OptionalBusinessError("not_enabled", "package is not enabled")
        return await self._verified(plugin, state.active)

    async def pin_agent_run(self, run_id: str) -> tuple[AgentPackagePin, ...]:
        """A restarted run restores its original set, even if the project installed more packages."""
        run = await self.db.scalar(
            select(AgentRunAuthorityModel.id)
            .where(
                AgentRunAuthorityModel.id == run_id,
                AgentRunAuthorityModel.tenant_id == self.scope.tenant_id,
                AgentRunAuthorityModel.project_id == self.scope.project_id,
                AgentRunAuthorityModel.execution_target == "cloud",
            )
            .with_for_update()
        )
        if run is None:
            raise OptionalBusinessError("forbidden", "package run scope is unavailable")
        selection = await self.db.get(AgentRunPackageSelection, run_id)
        if selection is None:
            rows = await self.db.execute(
                select(
                    Release.plugin_id,
                    Release.version,
                    Release.digest,
                    Release.permissions,
                    Installation.authorization_epoch,
                )
                .join(
                    Installation,
                    (Installation.project_id == Release.project_id)
                    & (Installation.plugin_id == Release.plugin_id)
                    & (Installation.active == Release.version),
                )
                .where(
                    Release.project_id == self.scope.project_id,
                    Release.tenant_id == self.scope.tenant_id,
                    Installation.enabled.is_(True),
                )
                .order_by(Release.plugin_id)
                .execution_options(populate_existing=True)
            )
            selection = AgentRunPackageSelection(
                run_id=run_id,
                releases=[
                    {
                        "tenant_id": self.scope.tenant_id,
                        "project_id": self.scope.project_id,
                        "plugin_id": row.plugin_id,
                        "version": row.version,
                        "digest": row.digest,
                        "authorization_epoch": row.authorization_epoch,
                        "drives_agent_loop": "agent.loop.drive" in row.permissions,
                        **chat_adapter_pin(row.permissions),
                    }
                    for row in rows
                ],
            )
            self.db.add(selection)
            await self.db.commit()
        return AGENT_PACKAGE_PINS.validate_python(selection.releases)

    async def pinned_package(self, pin: AgentPackagePin) -> SignedPackageBytesV2:
        """A regular upgrade keeps a live run's release. Withdrawal ends its admission."""
        state = await self._state(pin.plugin_id)
        if (
            pin.tenant_id != self.scope.tenant_id
            or pin.project_id != self.scope.project_id
            or not state
            or not state.enabled
            or not state.active
            or state.authorization_epoch != pin.authorization_epoch
        ):
            raise OptionalBusinessError("not_enabled", "package run authorization has ended")
        package = await self._verified(pin.plugin_id, pin.version)
        if package.digest != pin.digest:
            raise OptionalBusinessError("conflict", "pinned package release changed")
        return package

    async def resolve_service_pins(
        self, package: SignedPackageBytesV2, run_pins: tuple[AgentPackagePin, ...] | None = None
    ) -> dict[str, AgentPackagePin]:
        requires = package.services.requires
        if not requires:
            return {}
        providers = {service.plugin for service in requires}
        if run_pins is None:
            # Resolve every active dependency in a single database snapshot.
            rows = await self.db.execute(
                select(
                    Release.plugin_id,
                    Release.version,
                    Release.digest,
                    Installation.authorization_epoch,
                )
                .join(
                    Installation,
                    (Installation.project_id == Release.project_id)
                    & (Installation.plugin_id == Release.plugin_id)
                    & (Installation.active == Release.version),
                )
                .where(
                    Release.tenant_id == self.scope.tenant_id,
                    Release.project_id == self.scope.project_id,
                    Release.plugin_id.in_(providers),
                    Installation.enabled.is_(True),
                )
                .execution_options(populate_existing=True)
            )
            run_pins = tuple(
                AgentPackagePin(
                    tenant_id=self.scope.tenant_id,
                    project_id=self.scope.project_id,
                    plugin_id=r.plugin_id,
                    version=r.version,
                    digest=r.digest,
                    authorization_epoch=r.authorization_epoch,
                )
                for r in rows
            )
        pins = {pin.plugin_id: pin for pin in run_pins if pin.plugin_id in providers}
        if providers != pins.keys():
            raise OptionalBusinessError("not_enabled", "a required project service is unavailable")
        releases = {name: await self.pinned_package(pin) for name, pin in pins.items()}
        for service in requires:
            provider = releases[service.plugin]
            if not any(
                (row.service, row.version) == (service.service, service.version)
                for row in provider.services.provides
            ):
                raise OptionalBusinessError(
                    "conflict", "required project service version is unavailable"
                )
        return {service.alias: pins[service.plugin] for service in requires}

    async def invoke_pinned_tool(
        self,
        pin: AgentPackagePin,
        tool: str,
        payload: dict[str, Any],
        *,
        run_pins: tuple[AgentPackagePin, ...] | None = (),
        wait_for_slot: bool = False,
        check_access: Callable[[], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        from src.infrastructure.plugins.v2.project_package_execution import invoke_project_tool

        with self._audit("tool") as audit:
            audit.plugin_id, audit.version, audit.digest = pin.plugin_id, pin.version, pin.digest
            package = await self.pinned_package(pin)
            audit.release(package)
            return await self.run_guest(
                package,
                lambda: invoke_project_tool(package, self.scope, tool, payload),
                recheck=lambda: self.pinned_package(pin),
                run_pins=run_pins,
                wait_for_slot=wait_for_slot,
                check_access=check_access,
            )

    async def active_release(
        self, plugin: str, *, expected_digest: str | None = None
    ) -> SignedPackageBytesV2:
        package = await self._active(plugin)
        if expected_digest is not None and expected_digest != package.digest:
            raise OptionalBusinessError("conflict", "the package was replaced, reload its commands")
        return package

    async def pin_active_release(
        self, plugin: str, expected_digest: str | None, audit: PackageAudit | None = None
    ) -> tuple[AgentPackagePin, SignedPackageBytesV2]:
        state = await self._state(plugin)
        if not state or not state.enabled or not state.active:
            raise OptionalBusinessError("not_enabled", "package is not enabled")
        version, epoch = state.active, state.authorization_epoch
        package = await self._verified(plugin, version, audit)
        if expected_digest is not None and package.digest != expected_digest:
            raise OptionalBusinessError("conflict", "the package was replaced, reload its commands")
        pin = AgentPackagePin(
            tenant_id=self.scope.tenant_id,
            project_id=self.scope.project_id,
            plugin_id=plugin,
            version=version,
            digest=package.digest,
            authorization_epoch=epoch,
        )
        return pin, package

    async def call_active[T](
        self,
        plugin: str,
        operation: Callable[[SignedPackageBytesV2], Awaitable[T]],
        *,
        operation_kind: str = "call",
        expected_digest: str | None = None,
        admitted: AgentPackagePin | None = None,
        application_command: str | None = None,
        check_access: Callable[[], Awaitable[None]] | None = None,
    ) -> T:
        with self._audit(operation_kind) as audit:
            if admitted is None:
                pin, package = await self.pin_active_release(plugin, expected_digest, audit)
            else:
                if (plugin, expected_digest) != (admitted.plugin_id, admitted.digest):
                    raise OptionalBusinessError("conflict", "invalid admitted release")
                pin, package = admitted, await self.pinned_package(admitted)
            audit.release(package)
            if application_command and any(
                c.command_id == application_command and c.host_operation
                for c in package.contribution.commands
            ):
                if check_access:
                    await check_access()
                token = ACTIVE_APPLICATION_PIN.set(pin)
                try:
                    result = await operation(package)
                finally:
                    ACTIVE_APPLICATION_PIN.reset(token)
                if check_access:
                    await check_access()
                await self.pinned_package(pin)
                return result
            return await self.run_guest(
                package,
                lambda: operation(package),
                recheck=lambda: self.pinned_package(pin),
                check_access=check_access,
            )

    async def _acquire_guest_slot(
        self,
        package: SignedPackageBytesV2,
        wait_for_slot: bool,
        recheck: Callable[[], Awaitable[SignedPackageBytesV2]],
        check_access: Callable[[], Awaitable[None]] | None,
    ) -> None:
        # PostgreSQL owns the live call across API replicas. The scoped transaction
        # releases it when the request ends, including during process failure.
        if self.db.get_bind().dialect.name == "postgresql":
            identity = json.dumps(
                [self.scope.tenant_id, self.scope.project_id, package.plugin_id, package.digest]
            )
            lock_id = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], signed=True)
            key = bindparam("lock_id", lock_id, type_=BigInteger)
            if wait_for_slot:
                # Concurrent turns share one signed loop. Queue its pure control step before
                # dispatch so contention cannot duplicate tool effects or abort another turn.
                try:
                    async with asyncio.timeout(30):
                        await self.db.scalar(select(func.pg_advisory_xact_lock(key)))
                except TimeoutError as exc:
                    raise OptionalBusinessError(
                        "busy", "package concurrency limit reached"
                    ) from exc
                if check_access:
                    await check_access()
                await recheck()
            elif not await self.db.scalar(select(func.pg_try_advisory_xact_lock(key))):
                raise OptionalBusinessError("busy", "package concurrency limit reached")

    async def run_guest[T](
        self,
        package: SignedPackageBytesV2,
        operation: Callable[[], Awaitable[T]],
        *,
        recheck: Callable[[], Awaitable[SignedPackageBytesV2]],
        wait_for_slot: bool = False,
        run_pins: tuple[AgentPackagePin, ...] | None = None,
        check_access: Callable[[], Awaitable[None]] | None = None,
    ) -> T:
        await self._acquire_guest_slot(package, wait_for_slot, recheck, check_access)
        pins = await self.resolve_service_pins(package, run_pins)
        tools = {service.alias: service.tool for service in package.services.requires}

        async def invoke_service(alias: str, payload: dict[str, Any]) -> dict[str, Any]:
            if check_access:
                await check_access()
            await recheck()
            pin = pins[alias]
            result = await self.invoke_pinned_tool(pin, tools[alias], payload)
            await self.pinned_package(pin)
            return result

        async def checked_operation() -> T:
            result = await operation()
            if pins:
                if check_access:
                    await check_access()
                await recheck()
                for pin in set(pins.values()):
                    await self.pinned_package(pin)
            return result

        services = (
            WorkerServices(scope=self.scope, package=package, invoke=invoke_service)
            if pins
            else None
        )
        with admit_package_call(self.scope, package), bind_worker_services(services):
            # Keep both admissions until a cancelled worker or bounded Wasm invocation drains.
            if package.worker is None or package.contribution.storage is None:
                return await checked_operation()

            async def authorize_write() -> None:
                await self._lock()
                await recheck()

            records = WorkerRecords(
                db=self.db, scope=self.scope, package=package, authorize_write=authorize_write
            )
            with bind_worker_records(records):
                async with self.db.begin_nested():
                    result = await checked_operation()
            if records.write_attempted:
                await self.db.commit()
            return result

    async def storage(
        self, plugin: str, item_key: str, document: dict[str, Any] | None
    ) -> dict[str, Any]:
        # Hold the same project lock as purge/revoke until this write has committed.
        if document is not None:
            await self._lock()
        package = await self._active(plugin)
        required = "storage.read" if document is None else "storage.write"
        if (
            not package.contribution.storage
            or required not in package.contribution.storage.permissions
            or required not in package.approved_permissions
        ):
            raise OptionalBusinessError("permission_not_approved", "storage access is not approved")
        if not item_key or "/" in item_key or len(item_key) > 128:
            raise OptionalBusinessError("storage_key", "invalid storage key")
        key = NamespaceKeyV2(
            plugin_id=plugin,
            tenant_id=self.scope.tenant_id,
            project_id=self.scope.project_id,
            item_key=item_key,
        )
        if document is None:
            record = await self.db.run_sync(lambda db: SqlPluginNamespaceStoreV2(db).get(key))
            if record:
                assert_supported_schema_v2(record)
            return {"document": record.document if record else None}
        row = NamespaceRecordV2(
            schema_version=package.contribution.storage.schema_version, document=document
        )
        assert_supported_schema_v2(row)

        await check_storage_quota(self.db, key, document, package.storage_limit)
        await self.db.run_sync(lambda db: SqlPluginNamespaceStoreV2(db).put(key, row))
        await self.db.commit()
        return {"status": "stored"}
