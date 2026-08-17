"""HTTP route capability contract."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HttpAuthorizationMode(str, Enum):
    """Kernel-supported authorization boundary for plugin routes."""

    AUTHENTICATED = "authenticated"
    TENANT_MEMBER = "tenant_member"
    PROJECT_MEMBER = "project_member"
    TENANT_ADMIN = "tenant_admin"


@dataclass(frozen=True)
class HttpRouteDefinition:
    """One declaratively owned HTTP route."""

    plugin_id: str
    method: str
    path: str
    permission: str
    authorization: HttpAuthorizationMode
    summary: str = ""
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


HttpRouteHandler = Callable[..., Awaitable[Any]]


def route_definition_is_safe(definition: HttpRouteDefinition) -> bool:
    """Return whether a route can be mounted without bypassing kernel auth."""
    normalized_method = definition.method.upper()
    return (
        normalized_method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        and definition.path.startswith("/")
        and bool(definition.permission.strip())
        and definition.authorization
        in {
            HttpAuthorizationMode.TENANT_MEMBER,
            HttpAuthorizationMode.PROJECT_MEMBER,
            HttpAuthorizationMode.TENANT_ADMIN,
        }
    )
