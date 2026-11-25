"""Signed rich page entries shared by cloud and device renderers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .sidebar import parse_sidebar

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
_PAGE_LINK = re.compile(r"[a-z][a-z0-9.-]{0,127}/" + _IDENTIFIER.pattern)
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
    workbench: bool = False
    home: bool = False
    slots: tuple[str, ...] = ()
    anchored_slots: tuple[tuple[str, str], ...] = ()
    contributes_to: str | None = None

    resources: tuple[PageAsset, ...] = ()
    query_params: tuple[str, ...] = ()
    page_links: tuple[str, ...] = ()

    sidebar: dict[str, object] | None = None
    navigation_actions: tuple[str, ...] = ()
    voice_authorization: str | None = None

    @property
    def assets(self) -> tuple[PageAsset, ...]:
        return (self.entry, *((self.style,) if self.style else ()), *self.resources)

    def descriptor(self) -> dict[str, object]:
        return {
            "id": self.id,
            **(
                {"voice_authorization": self.voice_authorization}
                if self.voice_authorization
                else {}
            ),
            **({"sidebar": self.sidebar} if self.sidebar else {}),
            **({"navigation_actions": self.navigation_actions} if self.navigation_actions else {}),
            **({"workbench": True} if self.workbench else {}),
            **({"scope": self.scope} if self.scope == "tenant" else {}),
            "title": self.title,
            "routes": self.routes,
            "targets": sorted(self.targets),
            **({"query_params": self.query_params} if self.query_params else {}),
            **({"page_links": self.page_links} if self.page_links else {}),
            **({"anchored_slots": dict(self.anchored_slots)} if self.anchored_slots else {}),
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
        if route != "/tenant/:tenantId/org-settings/clusters" and (
            parts[1].lower() in _TENANT_HOST_SECTIONS
            or (
                len(parts) >= 3
                and (parts[2].lower() in _TENANT_HOST_SECTIONS or parts[2].startswith(":"))
            )
        ):
            raise ValueError("page route overlaps tenant administration")
        if len(parts) >= 3 and parts[2].lower() == "project":
            if len(parts) < 4 or parts[1] != ":tenantId" or parts[3] != ":projectId":
                raise ValueError("invalid tenant and project binding in page route")
    parameters = [part for part in parts if part.startswith(":")]
    if len(set(parameters)) != len(parameters):
        raise ValueError("duplicate route parameter")


def _anchored_slots(
    anchors: object, slots: tuple[str, ...], routes: tuple[str, ...], scope: object
) -> tuple[tuple[str, str], ...]:
    if (
        not isinstance(anchors, dict)
        or len(anchors) > 8
        or any(
            not isinstance(name, str)
            or not _SLOT.fullmatch(name)
            or name in slots
            or not isinstance(link, str)
            or not _PAGE_LINK.fullmatch(link)
            for name, link in anchors.items()
        )
    ):
        raise ValueError("invalid anchored slots")
    if anchors and (not routes or scope == "tenant"):
        raise ValueError("anchored slots require a routed project page")
    return tuple(anchors.items())


def _page_flag(value: dict[str, object], name: str) -> bool:
    flag = value.get(name, False)
    if not isinstance(flag, bool):
        raise ValueError(f"rich page {name} must be a boolean")
    return flag


def _parse_page(value: object, commands: set[str]) -> RichPage:
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
        "workbench",
        "slots",
        "anchored_slots",
        "query_params",
        "page_links",
        "resources",
        "contributes_to",
        "sidebar",
        "navigation_actions",
        "voice_authorization",
    }:
        raise ValueError("unsupported rich page declaration")
    workbench = _page_flag(value, "workbench")
    home = _page_flag(value, "home")
    page_id, title = value.get("id"), value.get("title")
    if not isinstance(page_id, str) or not _IDENTIFIER.fullmatch(page_id):
        raise ValueError("invalid page identifier")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError("invalid page title")
    routes = _strings(value.get("routes"), _ROUTE)
    targets = frozenset(_strings(value.get("targets"), _IDENTIFIER))
    slots = _strings(value.get("slots", []), _SLOT)
    anchors = _anchored_slots(value.get("anchored_slots", {}), slots, routes, value.get("scope"))
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
    navigation_actions = _strings(value.get("navigation_actions", []), _IDENTIFIER)
    if navigation_actions and (
        not routes or not set(navigation_actions) <= {"primary-create", "group-create"}
    ):
        raise ValueError("unsupported shell navigation action")
    page_commands = _strings(value.get("commands", []), _IDENTIFIER)
    voice = value.get("voice_authorization")
    if voice is not None and (
        not isinstance(voice, str)
        or voice not in commands
        or voice not in page_commands
        or scope != "project"
        or not routes
    ):
        raise ValueError("voice requires a routed project page and an authorized command")
    return RichPage(
        voice_authorization=voice,
        navigation_actions=navigation_actions,
        sidebar=parse_sidebar(value.get("sidebar", {}), commands, routes),
        scope=scope,
        workbench=workbench,
        id=page_id,
        home=home,
        slots=slots,
        anchored_slots=anchors,
        resources=_resources(value.get("resources", [])),
        page_links=_strings(value.get("page_links", []), _PAGE_LINK),
        query_params=_strings(value.get("query_params", []), _IDENTIFIER),
        contributes_to=destination,
        title=title,
        routes=routes,
        targets=targets,
        entry=_asset(value.get("entry"), ".js"),
        style=_asset(value["style"], ".css") if "style" in value else None,
        commands=page_commands,
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
    pages = tuple(_parse_page(item, commands) for item in value)
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
