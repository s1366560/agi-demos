"""Discover and deliver the renderer assets of the project's active signed release."""

import base64
from typing import TYPE_CHECKING

from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    ProjectPluginInstallation as Installation,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from memstack_plugin_sdk.rich_pages import PageAsset

    from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import SignedPackageBytesV2


def renderer_projection(package: "SignedPackageBytesV2 | None" = None) -> dict[str, object]:
    if package is None or "ui.slot" not in package.approved_permissions:
        return {"pages": [], "has_desktop_ui": False, "has_web_ui": False}
    pages = package.contribution.pages
    targets = {target for page in pages for target in page.targets}
    return {
        "pages": [page.descriptor() for page in pages],
        "has_web_ui": "web" in targets or package.page_slot("web") is not None,
        "has_desktop_ui": "desktop-renderer" in targets
        or package.page_slot("desktop-renderer") is not None,
    }


def rich_page_resource(
    package: "SignedPackageBytesV2", page_id: str, target: str
) -> dict[str, object]:
    from memstack_plugin_sdk.rich_pages import RICH_PAGE_SCHEMA

    if "ui.slot" not in package.approved_permissions:
        raise OptionalBusinessError("forbidden", "page is not approved for this package")
    page = next(
        (p for p in package.contribution.pages if p.id == page_id and target in p.targets), None
    )
    if page is None:
        raise OptionalBusinessError("page_not_found", "page is unavailable for this target")

    def resource(asset: "PageAsset") -> dict[str, str]:
        raw = asset.verify(package.ui_files.get("pages/" + asset.path, b""))
        return {
            "path": asset.path,
            "digest": asset.digest,
            "bytes_base64": base64.b64encode(raw).decode("ascii"),
        }

    return {
        "schema": RICH_PAGE_SCHEMA,
        **page.descriptor(),
        "target": target,
        "release_digest": package.digest,
        "navigation_routes": [
            route
            for sibling in package.contribution.pages
            if target in sibling.targets
            for route in sibling.routes
        ],
        "commands": page.commands,
        "device_tools": page.device_tools,
        "entry": resource(page.entry),
        **({"style": resource(page.style)} if page.style else {}),
    }


async def check_page_routes(
    service: "ProjectPluginInstallationService", candidate: "SignedPackageBytesV2"
) -> None:
    from memstack_plugin_sdk.rich_pages import route_bindings

    routes = route_bindings(candidate.contribution.pages)
    if not routes:
        return
    siblings = await service.db.scalars(
        select(Installation.plugin_id).where(
            Installation.project_id == service.scope.project_id,
            Installation.enabled.is_(True),
            Installation.active.is_not(None),
            Installation.plugin_id != candidate.plugin_id,
        )
    )
    for plugin_id in siblings:
        try:
            active = await service.active_release(plugin_id)
        except (ValueError, OptionalBusinessError) as error:
            raise OptionalBusinessError(
                "conflict", f"cannot verify active page routes of {plugin_id}"
            ) from error
        if routes & route_bindings(active.contribution.pages):
            raise OptionalBusinessError("conflict", f"page route already provided by {plugin_id}")
