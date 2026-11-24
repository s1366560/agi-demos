"""Signed rich page entries shared by cloud and device renderers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

RICH_PAGE_SCHEMA = "memstack.rich-page/1"
_RESOURCE_TYPES = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
}
_RENDERERS = {"web", "desktop-renderer"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SLOT = re.compile(r"[a-z][a-z0-9-]{0,63}@[1-9][0-9]{0,3}")
_SLOT_REFERENCE = re.compile(r"[a-z][a-z0-9.-]{0,127}/" + _SLOT.pattern)
_ROUTE = re.compile(r"(?:/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*|:[A-Za-z][A-Za-z0-9_]*))+")
# These URL namespaces belong to the shell even when the project has no packages.
_HOST_ROOTS = frozenset(
    {
        "api",
        "assets",
        "auth",
        "login",
        "logout",
        "device",
        "invite",
        "force-change-password",
        "projects",
        "tenants",
        "plugins",
        "project-packages.html",
        "settings",
        "recovery",
    }
)
_TENANT_HOST_SECTIONS = frozenset(
    {"projects", "users", "profile", "plugins", "org-settings", "settings", "audit-logs"}
)
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")


@dataclass(frozen=True)
class PageAsset:
    path: str
    digest: str

    def verify(self, raw: bytes) -> bytes:
        if not raw or len(raw) > 8 * 1024 * 1024:
            raise ValueError("page asset is empty or exceeds 8 MiB")
        if self.digest != "sha256:" + hashlib.sha256(raw).hexdigest():
            raise ValueError("page asset differs from its signed digest")
        if self.path.endswith((".js", ".css")):
            raw.decode("utf-8")
        return raw


@dataclass(frozen=True)
class RichPage:
    id: str
    title: str
    routes: tuple[str, ...]
    targets: frozenset[str]
    entry: PageAsset
    style: PageAsset | None
    commands: tuple[str, ...]
    device_tools: tuple[str, ...]
    scope: str = "project"
    home: bool = False
    slots: tuple[str, ...] = ()
    contributes_to: str | None = None

    resources: tuple[PageAsset, ...] = ()
    query_params: tuple[str, ...] = ()

    @property
    def assets(self) -> tuple[PageAsset, ...]:
        return (self.entry, *((self.style,) if self.style else ()), *self.resources)

    def descriptor(self) -> dict[str, object]:
        return {
            "id": self.id,
            **({"scope": self.scope} if self.scope == "tenant" else {}),
            "title": self.title,
            "routes": self.routes,
            "targets": sorted(self.targets),
            **({"query_params": self.query_params} if self.query_params else {}),
            **({"slots": self.slots} if self.slots else {}),
            **({"contributes_to": self.contributes_to} if self.contributes_to else {}),
            **({"home": True} if self.home else {}),
        }


def _asset(value: object, suffix: str | None) -> PageAsset:
    if not isinstance(value, dict) or value.keys() != {"path", "digest"}:
        raise ValueError("expected a page asset path and digest")
    path = value["path"]
    digest = value["digest"]
    if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,512}", path):
        raise ValueError("invalid page asset path")
    relative = PurePosixPath(path)
    if (
        relative.is_absolute()
        or relative.as_posix() != path
        or ".." in relative.parts
        or (relative.suffix != suffix if suffix else relative.suffix not in _RESOURCE_TYPES)
    ):
        raise ValueError("invalid page asset path or type")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError("invalid page asset digest")
    return PageAsset(path, digest)


def _resources(value: object) -> tuple[PageAsset, ...]:
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError("expected up to 64 page resources")
    assets = tuple(_asset(item, None) for item in value)
    if len({asset.path for asset in assets}) != len(assets):
        raise ValueError("duplicate page resource")
    return assets


def _strings(value: object, pattern: re.Pattern[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(s, str) or not pattern.fullmatch(s) for s in value
    ):
        raise ValueError("invalid rich page declaration")
    if len(value) != len(set(value)):
        raise ValueError("duplicate rich page declaration")
    return tuple(value)


def _check_route(route: str) -> None:
    parts = route[1:].split("/")
    root = parts[0].lower()
    if root.startswith(":") or root in _HOST_ROOTS:
        raise ValueError("page route overlaps a reserved host namespace")
    if root in {"tenant", "project"}:
        scope_param = ":tenantId" if root == "tenant" else ":projectId"
        if len(parts) == 1 or (parts[1].startswith(":") and parts[1] != scope_param):
            raise ValueError("invalid scope in page route")
        if len(parts) == 2 and parts[1] == scope_param:
            raise ValueError("page route overlaps a host scope selector")
    if root == "tenant":
        if parts[1].lower() in _TENANT_HOST_SECTIONS or (
            len(parts) >= 3
            and (parts[2].lower() in _TENANT_HOST_SECTIONS or parts[2].startswith(":"))
        ):
            raise ValueError("page route overlaps tenant administration")
        if len(parts) >= 3 and parts[2].lower() == "project":
            if len(parts) < 4 or parts[1] != ":tenantId" or parts[3] != ":projectId":
                raise ValueError("invalid tenant and project binding in page route")
    parameters = [part for part in parts if part.startswith(":")]
    if len(set(parameters)) != len(parameters):
        raise ValueError("duplicate route parameter")


def _parse_page(value: object) -> RichPage:
    if not isinstance(value, dict) or value.keys() - {
        "id",
        "title",
        "routes",
        "targets",
        "commands",
        "device_tools",
        "scope",
        "entry",
        "style",
        "home",
        "slots",
        "query_params",
        "resources",
        "contributes_to",
    }:
        raise ValueError("unsupported rich page declaration")
    home = value.get("home", False)
    if not isinstance(home, bool):
        raise ValueError("rich page home must be a boolean")
    page_id, title = value.get("id"), value.get("title")
    if not isinstance(page_id, str) or not _IDENTIFIER.fullmatch(page_id):
        raise ValueError("invalid page identifier")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError("invalid page title")
    routes = _strings(value.get("routes"), _ROUTE)
    targets = frozenset(_strings(value.get("targets"), _IDENTIFIER))
    slots = _strings(value.get("slots", []), _SLOT)
    destination = value.get("contributes_to")
    if destination is not None and (
        not isinstance(destination, str)
        or not _SLOT_REFERENCE.fullmatch(destination)
        or routes
        or slots
        or home
    ):
        raise ValueError("invalid embedded page slot")
    if not (routes or destination) or not targets or not targets <= _RENDERERS:
        raise ValueError("rich pages require routes and supported renderer targets")
    for route in routes:
        _check_route(route)
    scope = value.get("scope", "project")
    if scope not in ("tenant", "project"):
        raise ValueError("unsupported rich page scope")
    if scope == "tenant" and (
        not routes
        or any(
            not route.startswith("/tenant/:tenantId/") or ":projectId" in route.split("/")
            for route in routes
        )
        or value.get("device_tools")
        or slots
        or destination
        or home
    ):
        raise ValueError("tenant pages require tenant routes and cloud commands")
    return RichPage(
        scope=scope,
        id=page_id,
        home=home,
        slots=slots,
        resources=_resources(value.get("resources", [])),
        query_params=_strings(value.get("query_params", []), _IDENTIFIER),
        contributes_to=destination,
        title=title,
        routes=routes,
        targets=targets,
        entry=_asset(value.get("entry"), ".js"),
        style=_asset(value["style"], ".css") if "style" in value else None,
        commands=_strings(value.get("commands", []), _IDENTIFIER),
        device_tools=_strings(value.get("device_tools", []), _IDENTIFIER),
    )


def route_bindings(pages: tuple[RichPage, ...]) -> set[tuple[str, str]]:
    return {
        (target, re.sub(r"/:[^/]+", "/:", route.lower()))
        for page in pages
        for target in page.targets
        for route in page.routes
    }


def parse_rich_pages(value: object, commands: set[str]) -> tuple[RichPage, ...]:
    if not isinstance(value, list):
        raise ValueError("pages must be a list")
    pages = tuple(_parse_page(item) for item in value)
    if any(not set(page.commands) <= commands for page in pages):
        raise ValueError("page refers to an undeclared command")
    ids = [(target, page.id) for page in pages for target in page.targets]
    if len(ids) != len(set(ids)) or sum(len(p.routes) * len(p.targets) for p in pages) != len(
        route_bindings(pages)
    ):
        raise ValueError("conflicting rich page id or route")
    return pages


def validate_device_tools(pages: tuple[RichPage, ...], device_tool: object) -> None:
    if any(tool != device_tool for page in pages for tool in page.device_tools):
        raise ValueError("page refers to an undeclared device tool")
