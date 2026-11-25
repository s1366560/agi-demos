"""Declarative bindings for the workbench's existing row, tree and action controls."""

from __future__ import annotations

import re

_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,127}")
_KINDS = {"rows", "create", "rename", "delete", "groups", "group", "children"}


def _field(value: object) -> bool:
    return isinstance(value, str) and bool(_FIELD.fullmatch(value)) and value != "constructor"


def _check_destinations(binding: dict[str, object], routes: tuple[str, ...]) -> None:
    row_param = binding.get("row_param")
    for key in ("route", "row_route"):
        if key not in binding:
            continue
        route = binding[key]
        if not isinstance(route, str) or route not in routes:
            raise ValueError("sidebar destination must belong to its page")
        allowed = {"tenantId", "projectId"}
        if key == "row_route":
            if (
                not isinstance(row_param, str)
                or not _field(row_param)
                or ":" + row_param not in route.split("/")
            ):
                raise ValueError("invalid sidebar destination parameter")
            allowed.add(row_param)
        if any(part[1:] not in allowed for part in route.split("/") if part.startswith(":")):
            raise ValueError("sidebar destination requires unbound parameters")


def parse_sidebar(value: object, commands: set[str], routes: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(value, dict) or value.keys() - _KINDS:
        raise ValueError("unknown sidebar slot")
    for binding in value.values():
        if not isinstance(binding, dict) or binding.keys() - {
            "command",
            "inputs",
            "constants",
            "collection",
            "fields",
            "match",
            "route",
            "row_route",
            "row_param",
            "group_query",
        }:
            raise ValueError("invalid sidebar binding")
        command = binding.get("command")
        if not isinstance(command, str) or command not in commands:
            raise ValueError("sidebar command must belong to the release")
        for key in ("inputs", "fields", "match", "constants"):
            mapping = binding.get(key, {})
            if not isinstance(mapping, dict) or any(
                not _field(k)
                or (not _field(v) if key != "constants" else not isinstance(v, (bool, int, str)))
                for k, v in mapping.items()
            ):
                raise ValueError("invalid sidebar field mapping")
        if "collection" in binding and not _field(binding["collection"]):
            raise ValueError("invalid sidebar collection")
        if "group_query" in binding and not _field(binding["group_query"]):
            raise ValueError("invalid sidebar query parameter")
        _check_destinations(binding, routes)
    return value
