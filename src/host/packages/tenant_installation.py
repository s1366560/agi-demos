"""Select tenant releases independently and grant only signed tenant page capabilities."""

import asyncio
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.host.operations.project_package_audit import project_operation
from src.host.packages.project_installation_view import release_projection
from src.host.packages.release_governance import check_catalog_release
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Tenant
from src.infrastructure.adapters.secondary.persistence.tenant_plugin_installation import (
    TenantPluginInstallation as Installation,
    TenantPluginRelease as Release,
)
from src.infrastructure.plugins.v2.bundle_archive import declared_bundle_permissions_v2
from src.infrastructure.plugins.v2.project_package_execution import with_wasm_runtime
from src.infrastructure.plugins.v2.project_plugin_package import admit_package
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    SignedPackageBytesV2,
    TenantBindingV2,
    declared_permissions,
)
from src.infrastructure.plugins.wasm_host import WasmHostError


def tenant_package(
    raw: bytes, keys: tuple[str, ...], tenant: TenantBindingV2
) -> SignedPackageBytesV2:
    # Validate the complete signed envelope before reducing it to the tenant surface.
    pkg = admit_package(raw, keys, declared_bundle_permissions_v2(raw), tenant)
    source = pkg.contribution
    pages = tuple(page for page in source.pages if page.scope == "tenant")
    if not pages:
        raise OptionalBusinessError("invalid_package", "Release has no tenant entry")
    commands = tuple(
        c
        for c in source.commands
        if c.scope != "project" and any(c.command_id in page.commands for page in pages)
    )
    from src.host.operations.agent_package.runtime import is_guest_tool

    tools = tuple(
        t for t in source.tools if any(not c.host_operation and c.tool == t.name for c in commands)
    )
    if pkg.worker and any(not is_guest_tool(tool.name) for tool in tools):
        raise OptionalBusinessError(
            "invalid_package", "Tenant commands cannot start a project worker"
        )
    contribution = replace(
        source,
        pages=pages,
        commands=commands,
        tools=tools,
        storage=None,
        skills=(),
        subagents=(),
        ui=(),
    )
    grants = declared_permissions(contribution)
    if not grants <= pkg.approved_permissions:
        raise OptionalBusinessError("forbidden", "Tenant entry exceeds signed permissions")
    return replace(pkg, contribution=contribution, approved_permissions=grants)


class TenantPackageService:
    def __init__(self, db: AsyncSession, tenant_id: str, keys: tuple[str, ...], actor_id: str):
        self.db = db
        self.scope = TenantBindingV2(tenant_id=tenant_id)
        self.keys = keys
        self.actor_id = actor_id

    async def lock(self) -> None:
        if (
            await self.db.scalar(
                select(Tenant.id).where(Tenant.id == self.scope.tenant_id).with_for_update()
            )
            is None
        ):
            raise OptionalBusinessError("forbidden", "Tenant is unavailable")

    async def state(self, plugin: str) -> Installation | None:
        return await self.db.get(
            Installation, (self.scope.tenant_id, plugin), populate_existing=True
        )

    async def installed_ids(self) -> list[str]:
        return list(
            await self.db.scalars(
                select(Installation.plugin_id)
                .where(
                    Installation.tenant_id == self.scope.tenant_id,
                    Installation.desired.is_not(None),
                )
                .order_by(Installation.plugin_id)
            )
        )

    async def projection(self, plugin: str) -> dict[str, Any]:
        state = await self.state(plugin)
        versions = [v for v in (state.desired, state.active) if v] if state else []
        rows = (
            (
                await self.db.execute(
                    refresh_select_statement(
                        select(Release.version, Release.digest).where(
                            Release.tenant_id == self.scope.tenant_id,
                            Release.plugin_id == plugin,
                            Release.version.in_(versions),
                        )
                    )
                )
            )
            .tuples()
            .all()
        )
        return {
            **await release_projection(
                plugin, state, dict(rows), self.reviewed_release, scope_kind="tenant"
            ),
            "scope": "tenant",
        }

    async def inspect(self, raw: bytes) -> SignedPackageBytesV2:
        pkg = await asyncio.to_thread(tenant_package, raw, self.keys, self.scope)
        await check_catalog_release(self.db, pkg.plugin_id, pkg.version, raw)
        return pkg

    async def reviewed_release(self, plugin: str, version: str) -> SignedPackageBytesV2:
        row = await self.db.get(
            Release, (self.scope.tenant_id, plugin, version), populate_existing=True
        )
        if row is None:
            raise OptionalBusinessError("not_recorded", "Tenant release is unavailable")
        pkg = await self.inspect(row.archive)
        if (pkg.plugin_id, pkg.version, pkg.digest, pkg.approved_permissions) != (
            plugin,
            version,
            row.digest,
            frozenset(row.permissions),
        ):
            raise OptionalBusinessError(
                "forbidden", "Tenant release differs from the approved selection"
            )
        return pkg

    async def active(self, plugin: str, digest: str) -> SignedPackageBytesV2:
        state = await self.state(plugin)
        if state is None or not state.enabled or not state.active:
            raise OptionalBusinessError("not_enabled", "Tenant package is inactive")
        pkg = await self.reviewed_release(plugin, state.active)
        if pkg.digest != digest:
            raise OptionalBusinessError("conflict", "Tenant package selection changed")
        return pkg

    async def activate(self, state: Installation, pkg: SignedPackageBytesV2) -> None:
        from memstack_plugin_sdk.rich_pages import route_bindings

        try:
            routes = route_bindings(pkg.contribution.pages)
            others = await self.db.scalars(
                select(Installation).where(
                    Installation.tenant_id == self.scope.tenant_id,
                    Installation.active.is_not(None),
                    Installation.plugin_id != pkg.plugin_id,
                )
            )
            for sibling in others:
                if sibling.active and routes & route_bindings(
                    (
                        await self.reviewed_release(sibling.plugin_id, sibling.active)
                    ).contribution.pages
                ):
                    raise OptionalBusinessError(
                        "conflict", "Tenant page route is already installed"
                    )
            from src.host.operations.agent_package.runtime import is_guest_tool

            if any(not is_guest_tool(tool.name) for tool in pkg.contribution.tools):
                await with_wasm_runtime(pkg, lambda _: None)
        except (OptionalBusinessError, ValueError, WasmHostError) as error:
            state.failure = str(error)[:512]
            await self.db.commit()
            raise OptionalBusinessError("apply_failed", str(error)) from error
        if state.active != pkg.version:
            state.previous, state.active = state.active, pkg.version
            state.generation += 1
        state.enabled = True
        state.desired = pkg.version
        state.failure = None

    async def record(
        self,
        raw: bytes,
        permissions: frozenset[str],
        revision: int,
        digest: str,
        *,
        identity: tuple[str, str] | None,
        activate: bool,
    ) -> SignedPackageBytesV2:
        with project_operation(
            "install", actor_id=self.actor_id, tenant_id=self.scope.tenant_id
        ) as audit:
            pkg = await self.inspect(raw)
            if pkg.digest != digest or (
                identity is not None and identity != (pkg.plugin_id, pkg.version)
            ):
                raise OptionalBusinessError(
                    "conflict", "Tenant release differs from reviewed archive"
                )
            if permissions != pkg.approved_permissions:
                raise OptionalBusinessError(
                    "forbidden", "Tenant entry permissions require exact approval"
                )
            audit.release(pkg)
            state = await self.state(pkg.plugin_id)
            if revision != (state.revision if state else 0):
                raise OptionalBusinessError("conflict", "Tenant package selection changed")
            release = await self.db.get(Release, (self.scope.tenant_id, pkg.plugin_id, pkg.version))
            if release is not None and release.digest != pkg.digest:
                raise OptionalBusinessError("conflict", "Package versions are immutable")
            if release is None:
                self.db.add(
                    Release(
                        tenant_id=self.scope.tenant_id,
                        plugin_id=pkg.plugin_id,
                        version=pkg.version,
                        digest=pkg.digest,
                        archive=raw,
                        permissions=sorted(permissions),
                        approved_by=self.actor_id,
                    )
                )
            if state is None:
                state = Installation(
                    tenant_id=self.scope.tenant_id,
                    plugin_id=pkg.plugin_id,
                    revision=0,
                    generation=0,
                    enabled=False,
                )
                self.db.add(state)
            if state.desired != pkg.version or (
                activate and (state.active != pkg.version or state.failure)
            ):
                state.revision += 1
            state.desired = pkg.version
            if activate:
                await self.activate(state, pkg)
            await self.db.commit()
            return pkg

    async def mutate(self, plugin: str, action: str, revision: int) -> dict[str, Any]:
        with project_operation(
            action, actor_id=self.actor_id, tenant_id=self.scope.tenant_id
        ) as audit:
            state = await self.state(plugin)
            if state is None or state.revision != revision:
                raise OptionalBusinessError("conflict", "Tenant package selection changed")
            before = (state.active, state.desired, state.enabled, state.failure)
            if action in ("enable", "rollback"):
                version = state.previous if action == "rollback" else state.desired
                if not version:
                    raise OptionalBusinessError(
                        "rollback_unavailable", "Tenant release unavailable"
                    )
                pkg = await self.reviewed_release(plugin, version)
                audit.release(pkg)
                await self.activate(state, pkg)
            else:
                state.enabled = False
                state.active = state.previous = state.failure = None
                if action == "uninstall":
                    state.desired = None
            if before != (state.active, state.desired, state.enabled, state.failure):
                state.revision += 1
            await self.db.commit()
            return await self.projection(plugin)
