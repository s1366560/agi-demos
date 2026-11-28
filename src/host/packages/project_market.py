"""Join an npm source to the selected project's durable installation state."""

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal, Protocol

from jsonschema.exceptions import SchemaError

from src.host.packages.npm_catalog import NpmListing, registry_listings, valid_version, version_key
from src.host.packages.npm_source import fetch_npm_archive, npm_plugin_id, registry_base
from src.host.packages.rich_pages import renderer_projection
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import SignedPackageBytesV2

View = Literal["all", "installed", "updates"]


class MarketService(Protocol):
    async def projection(self, plugin: str) -> dict[str, Any]: ...
    async def installed_ids(self) -> list[str]: ...
    async def inspect(self, raw: bytes) -> "SignedPackageBytesV2": ...
    async def reviewed_release(self, plugin: str, version: str) -> "SignedPackageBytesV2": ...


def _source_label(registry: str | None) -> str | None:
    try:
        return registry_base(registry)
    except (ValueError, OptionalBusinessError):
        return None


async def _source(
    registry: str | None, name: str | None = None, *, scope: str = "project"
) -> tuple[list[NpmListing], str | None]:
    try:
        listings = await registry_listings(registry, name)
        if scope == "tenant":
            listings = [
                replace(
                    row,
                    versions=row.tenant_versions,
                    latest_version=row.latest_version
                    if row.latest_version in row.tenant_versions
                    else row.tenant_versions[0],
                )
                for row in listings
                if row.tenant_versions
            ]
        return listings, None
    except OptionalBusinessError as exc:
        if exc.code == "npm_not_found":
            return [], None
        return [], str(exc)


def _update(latest: str | None, current: str | None) -> bool:
    return bool(
        latest
        and current
        and valid_version(current)
        and version_key(latest)[3]
        and version_key(latest) > version_key(current)
    )


def _card(
    plugin: str, npm: NpmListing | None, installation: dict[str, Any] | None
) -> dict[str, Any]:
    state = installation or {}
    titles = [p["title"] for p in state.get("pages", [])]
    return {
        "plugin_id": plugin,
        "package_name": npm.package_name if npm else None,
        "display_name": npm.display_name if npm else {},
        "description": (npm.description if npm else {})
        or ({"en": " · ".join(titles)} if titles else {}),
        "icon": npm.icon if npm else None,
        "targets": (npm.targets if npm else ())
        or sorted(
            set(state.get("targets", ())).union(
                target
                for target, flag in (("web", "has_web_ui"), ("desktop-renderer", "has_desktop_ui"))
                if state.get(flag)
            )
        ),
        "latest_version": npm.latest_version if npm else None,
        "update_available": _update(
            npm.latest_version if npm else None,
            state.get("running_version") or state.get("installed_version"),
        ),
        "installation": installation,
    }


async def market_catalog(
    service: MarketService,
    registry: str | None,
    *,
    query: str,
    view: View,
    offset: int,
    limit: int,
    scope: str = "project",
) -> dict[str, Any]:
    source, error = await _source(registry, scope=scope)
    installed = {
        plugin: await service.projection(plugin) for plugin in await service.installed_ids()
    }
    cards = [_card(item.plugin_id, item, installed.get(item.plugin_id)) for item in source]
    source_ids = {item.plugin_id for item in source}
    cards += [
        _card(plugin, None, state)
        for plugin, state in installed.items()
        if plugin not in source_ids
    ]
    text = query.casefold().strip()
    results = []
    for card in cards:
        if (view == "installed" and not card["installation"]) or (
            view == "updates" and not card["update_available"]
        ):
            continue
        labels = [
            card["plugin_id"],
            card["package_name"] or "",
            *card["display_name"].values(),
            *card["description"].values(),
        ]
        if not text or any(text in label.casefold() for label in labels):
            results.append(card)
    results.sort(key=lambda c: c["package_name"] or c["plugin_id"])
    return {
        "source": _source_label(registry),
        "source_error": error,
        "total": len(results),
        "items": results[offset : offset + limit],
    }


def _release(package: "SignedPackageBytesV2", scope: str) -> dict[str, Any]:
    renderer = renderer_projection(package, scope=scope)
    return {
        "version": package.version,
        "digest": package.digest,
        "permissions": sorted(package.approved_permissions),
        "pages": renderer["pages"],
        "commands": [c.command_id for c in package.contribution.commands],
        "targets": sorted(
            set(package.targets).union(
                target
                for target, enabled in [
                    ("web", renderer["has_web_ui"]),
                    ("desktop-renderer", renderer["has_desktop_ui"]),
                ]
                if enabled
            )
        ),
    }


async def _inspect_selection(
    service: MarketService,
    registry: str | None,
    source: NpmListing | None,
    plugin: str,
    version: str,
    recorded: set[str],
    current: "SignedPackageBytesV2 | None",
    scope: str,
) -> dict[str, Any]:
    if source and version in source.versions:
        raw = await fetch_npm_archive(registry, source.package_name, version)
        package = await service.inspect(raw)
        if (package.plugin_id, package.version) != (plugin, version):
            raise ValueError("Signed plugin identity differs from the npm release")
        return _release(package, scope)
    if version not in recorded:
        raise OptionalBusinessError("npm_not_found", "This npm version is unavailable")
    if current and current.version == version:
        return _release(current, scope)
    return _release(await service.reviewed_release(plugin, version), scope)


async def market_detail(
    service: MarketService,
    registry: str | None,
    *,
    plugin: str,
    name: str | None,
    version: str | None,
    scope: str = "project",
) -> dict[str, Any]:
    if name and npm_plugin_id(name, version or "0.0.0") != plugin:
        raise ValueError("The npm name does not match the plugin identity")
    if version and not valid_version(version):
        raise ValueError("An exact npm version is required")
    listings, error = await _source(registry, name, scope=scope)
    source = next((item for item in listings if item.plugin_id == plugin), None)
    view = await service.projection(plugin)
    installed = view if view["package_recorded"] else None
    if not source and not installed:
        if error:
            raise OptionalBusinessError("runtime_unavailable", error)
        raise OptionalBusinessError("npm_not_found", "Plugin was not found")
    local = {
        v
        for v in (view["installed_version"], view["running_version"], view["previous_version"])
        if v
    }
    available = set(source.versions if source else ()) | local
    versions = sorted((v for v in available if valid_version(v)), key=version_key, reverse=True)
    versions.extend(sorted(available - set(versions)))
    selected = (
        version
        or (source.latest_version if source else None)
        or view["running_version"]
        or view["installed_version"]
        or (versions[0] if versions else None)
    )
    current = view["running_version"] or view["installed_version"]
    checked = None
    permissions: list[str] = []
    reason = None
    if current:
        try:
            checked = await service.reviewed_release(plugin, current)
            permissions = sorted(checked.approved_permissions)
        except (ValueError, OptionalBusinessError, SchemaError) as exc:
            reason = str(exc)
    release = None
    try:
        if selected:
            release = await _inspect_selection(
                service, registry, source, plugin, selected, local, checked, scope
            )
    except (ValueError, OptionalBusinessError, SchemaError, TypeError, KeyError) as exc:
        reason = str(exc)
    card = _card(plugin, source, installed)
    if release and not card["description"]:
        titles = [p["title"] for p in release["pages"]]
        if titles:
            card["description"] = {"en": " · ".join(titles)}
    return {
        **card,
        "source": _source_label(registry),
        "source_error": error,
        "versions": versions,
        "release": release,
        "release_error": reason,
        "current_permissions": permissions,
        "desired_revision": view["desired_revision"],
        "previous_version": view["previous_version"],
    }
