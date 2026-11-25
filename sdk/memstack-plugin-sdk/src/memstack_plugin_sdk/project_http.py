"""Permission names for signed, bodyless project HTTP operations on a desktop device."""

import re

_ROUTE_PERMISSION = re.compile(r"desktop\.http\.(?:get|post)\.[a-z0-9-]+(?:\.[a-z0-9-]+)*")


def is_route_permission(permission: str) -> bool:
    return len(permission) <= 128 and bool(_ROUTE_PERMISSION.fullmatch(permission))


def route_permissions(target: str, routes: object) -> set[str]:
    if routes is None:
        return set()
    if target != "desktop-sidecar" or not isinstance(routes, dict) or not routes:
        raise ValueError("Project HTTP routes require a native Wasm target")
    permissions: set[str] = set()
    for method, paths in routes.items():
        if method not in {"GET", "POST"} or not isinstance(paths, list) or not paths:
            raise ValueError("Invalid project HTTP method or paths")
        for path in paths:
            if not isinstance(path, str) or "." in path:
                raise ValueError("Invalid project HTTP path")
            permission = f"desktop.http.{method.lower()}.{path.replace('/', '.')}"
            if not is_route_permission(permission):
                raise ValueError("Invalid project HTTP path")
            permissions.add(permission)
    return permissions


_WORKSPACE_OPERATIONS = frozenset({"status", "directory", "text", "download"})


def is_workspace_permission(permission: str) -> bool:
    return permission in {f"device.workspace.read.{op}" for op in _WORKSPACE_OPERATIONS}


def workspace_permissions(target: str, operations: object) -> set[str]:
    if operations is None:
        return set()
    if (
        target != "desktop-sidecar"
        or not isinstance(operations, list)
        or not operations
        or not all(isinstance(op, str) and op in _WORKSPACE_OPERATIONS for op in operations)
    ):
        raise ValueError("Invalid native workspace read operation")
    return {f"device.workspace.read.{op}" for op in operations}
