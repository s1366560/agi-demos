"""Exact project service imports and exports for isolated guest packages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contract import ToolContribution

_ALIAS = re.compile(r"[a-z][a-z0-9_]{0,127}")
_SERVICE = re.compile(r"service:package:([a-z0-9][a-z0-9._-]{0,127}):([a-z0-9][a-z0-9_.-]{0,63})")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?")


@dataclass(frozen=True)
class ProjectService:
    service: str
    version: str
    plugin: str
    tool: str
    alias: str = ""


@dataclass(frozen=True)
class ProjectServices:
    provides: tuple[ProjectService, ...] = ()
    requires: tuple[ProjectService, ...] = ()


def _rows(value: object, *, imports: bool) -> tuple[ProjectService, ...]:
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("expected up to eight project services")
    result = []
    for row in value:
        fields = {"service", "version", "alias"} if imports else {"service", "version"}
        if not isinstance(row, dict) or row.keys() != fields:
            raise ValueError("unexpected project service fields")
        service, version, alias = row["service"], row["version"], row.get("alias", "")
        match = _SERVICE.fullmatch(service) if isinstance(service, str) else None
        if match is None or not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise ValueError("unsupported project service or dependency version")
        if imports and (
            not isinstance(alias, str) or not _ALIAS.fullmatch(alias) or alias == "catalog"
        ):
            raise ValueError("invalid project service alias")
        result.append(ProjectService(service, version, match.group(1), match.group(2), alias))
    names = {item.alias if imports else item.service for item in result}
    if len(names) != len(result):
        raise ValueError("duplicate project service binding")
    return tuple(result)


def project_services(
    value: object, *, plugin: str, target: str, worker: bool, tools: tuple[ToolContribution, ...]
) -> ProjectServices:
    if not isinstance(value, dict) or value.keys() - {"provides", "requires"}:
        raise ValueError("invalid project services")
    exports = _rows(value.get("provides", []), imports=False)
    imports = _rows(value.get("requires", []), imports=True)
    if (imports or exports) and target != "python":
        raise ValueError("project services require a cloud module")
    if any(row.plugin != plugin for row in exports) or any(row.plugin == plugin for row in imports):
        raise ValueError("invalid project service owner or self dependency")
    if (exports and worker) or (imports and not worker):
        raise ValueError("project services connect an OCI consumer to a pure Wasm provider")
    providers = {tool.name for tool in tools if "services.provide" in tool.permissions}
    if providers != {row.tool for row in exports} or any(
        tool.permissions != frozenset({"tools.execute", "services.provide"})
        for tool in tools
        if tool.name in providers
    ):
        raise ValueError("service export requires one approved pure computation tool")
    aliases = {alias for tool in tools for alias in tool.service_aliases}
    if aliases != {row.alias for row in imports}:
        raise ValueError("service imports must bind the aliases of signed tools")
    return ProjectServices(exports, imports)
