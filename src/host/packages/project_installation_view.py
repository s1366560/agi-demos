"""Read the selected and running releases independently for a project installation."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from src.host.packages.rich_pages import renderer_projection
from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    ProjectPluginRelease as Release,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    LifecycleProjectionV2,
    OptionalBusinessError,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
        ProjectPluginInstallation as Installation,
    )
    from src.infrastructure.adapters.secondary.persistence.tenant_plugin_installation import (
        TenantPluginInstallation,
    )
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
        ScopeBindingV2,
        SignedPackageBytesV2,
    )


async def installation_view(
    db: "AsyncSession",
    scope: "ScopeBindingV2",
    plugin: str,
    state: "Installation | None",
    verified: "Callable[[str, str], Awaitable[SignedPackageBytesV2]]",
) -> dict[str, Any]:
    versions = [v for v in (state.desired, state.active) if v] if state else []
    digests = dict(
        (
            await db.execute(
                select(Release.version, Release.digest)
                .where(
                    Release.project_id == scope.project_id,
                    Release.tenant_id == scope.tenant_id,
                    Release.plugin_id == plugin,
                    Release.version.in_(versions),
                )
                .execution_options(populate_existing=True)
            )
        )
        .tuples()
        .all()
    )
    return await release_projection(plugin, state, digests, verified, scope_kind="project")


async def release_projection(
    plugin: str,
    state: "Installation | TenantPluginInstallation | None",
    digests: dict[str, str],
    verified: "Callable[[str, str], Awaitable[SignedPackageBytesV2]]",
    *,
    scope_kind: str,
) -> dict[str, Any]:
    active = state.active if state else None
    desired = state.desired if state else None
    failure = state.failure if state else None
    view = LifecycleProjectionV2(
        plugin_id=plugin,
        source="signed-package",
        version=active or desired or "",
        package_recorded=bool(desired),
        desired_enabled=bool(state and state.enabled),
        runtime_phase="active" if active else "failed" if failure else "inactive",
        ui_mounted=False,
        sync="degraded" if failure else "current" if active == desired else "staged",
        desired_revision=state.revision if state else 0,
        actual_generation=state.generation if state else 0,
        desired_digest=digests.get(desired) if desired else None,
        actual_digest=digests.get(active) if active else None,
        failure=failure,
        retention=state.retention if state else "retained",
    )
    renderer = renderer_projection()
    commands: list[str] = []
    kind: str | None = None
    targets: tuple[str, ...] = ()
    if desired and desired != active:
        try:
            staged = await verified(plugin, desired)
            kind, targets = staged.kind, staged.targets
        except (ValueError, OptionalBusinessError):
            pass
    if active:
        try:
            live = await verified(plugin, active)
            if desired == active:
                kind, targets = live.kind, live.targets
            renderer = renderer_projection(live, scope=scope_kind)
            commands = [
                c.command_id
                for c in live.contribution.commands
                if c.permissions <= live.approved_permissions
            ]
        except (ValueError, OptionalBusinessError) as error:
            active = None
            view.actual_digest = None
            view.runtime_phase = "unavailable"
            view.sync = "degraded"
            view.failure = str(error)
    return {
        **asdict(view),
        "kind": kind,
        "targets": list(targets),
        "previous_version": state.previous if state else None,
        "installed_version": desired,
        "running_version": active,
        "commands": commands,
        **renderer,
    }


def market_installation(plugin: str, view: dict[str, Any], scope: str) -> dict[str, Any]:
    if not view["package_recorded"]:
        status = "uninstalled"
    elif view["failure"]:
        status = "failed"
    elif view["runtime_phase"] == "active":
        status = "enabled"
    else:
        status = "disabled"
    return {
        "id": f"{scope}-package:{plugin}",
        "source_id": "signed-v2",
        "kind": view["kind"],
        "targets": view["targets"],
        "has_desktop_ui": view["has_desktop_ui"],
        "commands": view["commands"],
        "pages": view["pages"],
        "name": plugin,
        "plugin_id": plugin,
        "version": view["installed_version"] or "",
        "status": status,
        "format": "v2",
        "install_strategy": "signed-v2",
        "capabilities": ["tools"] + (["ui"] if view["has_web_ui"] else []),
        "required_credentials": [],
        "error": view["failure"],
        "running_version": view["running_version"],
        "desired_revision": view["desired_revision"],
        "actual_digest": view["actual_digest"],
        "desired_digest": view["desired_digest"],
        "scope": scope,
    }
