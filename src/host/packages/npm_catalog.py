"""Metadata-only catalog of the configured local registry, with npm SemVer precedence."""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from src.host.packages.npm_source import download_bounded, npm_plugin_id, registry_base
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


def version_key(version: str) -> tuple[int, int, int, bool, tuple[tuple[int, int, str], ...]]:
    npm_plugin_id("package", version)
    core, _, pre = version.partition("+")[0].partition("-")
    major, minor, patch = map(int, core.split("."))
    identifiers = tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part) for part in pre.split(".") if part
    )
    return major, minor, patch, not pre, identifiers


def valid_version(v: object) -> bool:
    if not isinstance(v, str) or len(v) > 128:
        return False
    try:
        npm_plugin_id("package", v)
    except ValueError:
        return False
    return True


def _localized(value: object, limit: int) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: label.strip()[:limit]
        for key, label in value.items()
        if key in ("en", "zh") and isinstance(label, str) and label.strip()
    }


@dataclass
class NpmListing:
    package_name: str
    plugin_id: str
    versions: tuple[str, ...]
    latest_version: str | None
    display_name: dict[str, str] = field(default_factory=dict)
    description: dict[str, str] = field(default_factory=dict)
    icon: str | None = None
    targets: tuple[str, ...] = ()
    tenant_versions: tuple[str, ...] = ()


def _listing(doc: dict[str, Any], name: str) -> NpmListing | None:
    releases = doc.get("versions")
    if doc.get("name") != name or not isinstance(releases, dict):
        return None
    versions = []
    for v, data in releases.items():
        if not valid_version(v) or not isinstance(data, dict):
            continue
        # The publishing format declares its payload even before display metadata was introduced.
        if isinstance(data.get("files"), list) and "plugin.mspkg" in data["files"]:
            versions.append(v)
    if not versions:
        return None
    versions.sort(key=version_key, reverse=True)
    tags = doc.get("dist-tags") or {}
    latest = tags.get("latest") if isinstance(tags, dict) else None
    if latest not in versions:
        latest = None
    data = releases[latest or versions[0]]
    namespace = data.get("memstack")
    display = namespace.get("market") if isinstance(namespace, dict) else {}
    display = display if isinstance(display, dict) else {}
    icon, targets = display.get("icon"), display.get("targets")
    return NpmListing(
        package_name=name,
        plugin_id=npm_plugin_id(name, versions[0]),
        versions=tuple(versions),
        tenant_versions=tuple(
            v
            for v in versions
            if isinstance(ns := releases[v].get("memstack"), dict)
            and isinstance(ns.get("scopes"), list)
            and "tenant" in ns["scopes"]
        ),
        latest_version=latest,
        display_name=_localized(display.get("name"), 120),
        description=_localized(display.get("description"), 512),
        icon=icon
        if isinstance(icon, str)
        and icon.isascii()
        and icon.replace("-", "").isalnum()
        and len(icon) <= 64
        else None,
        targets=tuple(t for t in targets if isinstance(t, str) and len(t) <= 64)
        if isinstance(targets, list)
        else (),
    )


async def _packument(client: httpx.AsyncClient, registry: str, name: str) -> NpmListing | None:
    try:
        raw = await download_bounded(client, f"{registry}/{quote(name, safe='@')}", 2 * 1024 * 1024)
    except OptionalBusinessError as exc:
        if exc.code == "npm_not_found":
            # An index may still reference a concurrently unpublished package.
            return None
        raise
    doc = json.loads(raw)
    return _listing(doc, name) if isinstance(doc, dict) else None


async def _names(client: httpx.AsyncClient, registry: str) -> list[str]:
    # Verdaccio refuses an empty v1 search; its local all-packages index includes legacy
    # archives with no keywords and unscoped names. Other npm registries may not support it.
    try:
        raw = await download_bounded(client, registry + "/-/all", 8 * 1024 * 1024)
    except OptionalBusinessError as exc:
        if exc.code != "npm_not_found":
            raise
    else:
        index = json.loads(raw)
        if not isinstance(index, dict):
            raise ValueError("Invalid npm catalog")
        return [
            name for name, doc in index.items() if isinstance(doc, dict) and doc.get("name") == name
        ]
    found: dict[str, None] = {}
    for text in ("@memstack/", "keywords:memstack-plugin"):
        offset = 0
        while True:
            query = urlencode({"text": text, "size": 100, "from": offset})
            response = json.loads(
                await download_bounded(client, registry + "/-/v1/search?" + query, 2 * 1024 * 1024)
            )
            objects = response.get("objects") if isinstance(response, dict) else None
            if not isinstance(objects, list):
                raise ValueError("Invalid npm search results")
            for result in objects:
                package = result.get("package") if isinstance(result, dict) else None
                if isinstance(package, dict) and isinstance(package.get("name"), str):
                    found[package["name"]] = None
            if len(objects) < 100:
                break
            offset += len(objects)
    return list(found)


async def registry_listings(
    registry: str | None, package_name: str | None = None
) -> list[NpmListing]:
    root = registry_base(registry)
    try:
        async with (
            asyncio.timeout(30),
            httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=6,
            ) as client,
        ):
            names = [package_name] if package_name else await _names(client, root)
            listings: list[NpmListing] = []
            # Bound active requests and queued tasks, including on large private registries.
            for i in range(0, len(names), 8):
                batch: list[str] = []
                for name in names[i : i + 8]:
                    try:
                        npm_plugin_id(name, "0.0.0")
                    except ValueError:
                        continue
                    batch.append(name)
                for item in await asyncio.gather(
                    *(_packument(client, root, name) for name in batch)
                ):
                    if item is not None:
                        listings.append(item)
            return listings
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        raise OptionalBusinessError(
            "runtime_unavailable", "npm plugin catalog is unavailable"
        ) from exc
