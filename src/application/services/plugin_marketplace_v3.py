"""Scoped, durable Codex marketplace lifecycle backed by native resource registries."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginPackageModel,
    Skill,
)
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.plugins.codex_package import inspect_codex_package
from src.infrastructure.plugins.marketplace_snapshot_cache import (
    MarketplaceSnapshotCache,
    preflight_expiry,
    require_fresh_preflight,
)
from src.infrastructure.plugins.marketplace_sources import list_source_packages, snapshot_source

PUBLIC_TENANT = "__public_marketplace__"


class MarketplaceV3Error(ValueError):
    """Safe, user-readable marketplace failure."""


def _expand_package_root(value: Any, package_root: str) -> Any:  # noqa: ANN401
    if isinstance(value, str):
        return value.replace("${PLUGIN_ROOT}", package_root).replace(
            "${CLAUDE_PLUGIN_ROOT}", package_root
        )
    if isinstance(value, list):
        return [_expand_package_root(item, package_root) for item in value]
    if isinstance(value, dict):
        return {key: _expand_package_root(item, package_root) for key, item in value.items()}
    return value


class PluginMarketplaceV3:
    """Own package snapshots and resources within one authorized scope."""

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: str,
        project_id: str | None = None,
        *,
        mcp: Any = None,  # noqa: ANN401
    ) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.project_id = project_id or ""
        self.mcp = mcp

    async def records(self, kind: str) -> list[MarketplaceRecordV3]:
        result = await self.db.scalars(
            select(MarketplaceRecordV3).where(
                MarketplaceRecordV3.tenant_id == self.tenant_id,
                MarketplaceRecordV3.project_id == self.project_id,
                MarketplaceRecordV3.kind == kind,
            )
        )
        return list(result)

    async def record(self, record_id: str, kind: str, *, lock: bool = False) -> MarketplaceRecordV3:
        query = select(MarketplaceRecordV3).where(
            MarketplaceRecordV3.id == record_id,
            MarketplaceRecordV3.tenant_id == self.tenant_id,
            MarketplaceRecordV3.project_id == self.project_id,
            MarketplaceRecordV3.kind == kind,
        )
        if lock:
            query = query.with_for_update()
        record = await self.db.scalar(query)
        if record is None:
            raise MarketplaceV3Error("Marketplace record not found in this scope")
        return record

    async def add_record(
        self, kind: str, payload: dict[str, Any], *, key: str | None = None
    ) -> MarketplaceRecordV3:
        record_id = str(uuid4())
        existing = None
        if kind == "operation":
            existing = next(
                (row for row in await self.records("operation") if row.record_key == key), None
            )
            if existing:
                record_id = existing.id
            installation = await self.record(payload["installation_id"], "installation")
            stage = payload.get("stage", installation.payload["status"])
            payload = {
                **payload,
                "status": payload.get("status", "failed" if stage == "failed" else "completed"),
                "stage": stage,
                "stages": [
                    *(existing.payload.get("stages", ["requested"]) if existing else ["requested"]),
                    stage,
                ],
                "created_at": existing.payload["created_at"]
                if existing
                else datetime.now(UTC).isoformat(),
                "error": payload.get("error", installation.payload.get("error")),
            }
            installation.payload = {**installation.payload, "job_id": record_id}
        if existing:
            existing.payload = {**existing.payload, **payload, "id": record_id}
            await self.db.flush()
            return existing
        record = MarketplaceRecordV3(
            id=record_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            kind=kind,
            record_key=key or record_id,
            payload={**payload, "id": record_id},
        )
        self.db.add(record)
        await self.db.flush()
        return record

    @staticmethod
    def request_digest(payload: dict[str, Any]) -> str:
        """Bind idempotency to semantic request fields without retaining secret values."""
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    async def start_operation(
        self, installation_id: str, action: str, key: str, digest: str
    ) -> None:
        """Publish a running task without releasing the installation's transaction lock."""
        record_id = str(uuid4())
        record = MarketplaceRecordV3(
            id=record_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            kind="operation",
            record_key=key,
            payload={
                "id": record_id,
                "installation_id": installation_id,
                "action": action,
                "request_digest": digest,
                "status": "running",
                "stage": "applying",
                "stages": ["requested", "applying"],
                "created_at": datetime.now(UTC).isoformat(),
                "error": None,
            },
        )
        bind = self.db.bind
        if isinstance(bind, AsyncEngine) and bind.dialect.name == "postgresql":
            async with async_sessionmaker(bind, expire_on_commit=False)() as independent:
                independent.add(record)
                await independent.commit()
        else:
            # SQLite's single-writer transactions are used only in isolated unit tests.
            self.db.add(record)
            await self.db.flush()

    def public_sources(self) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        local = os.environ.get("PLUGIN_MARKETPLACE_CURATED_DIRECTORY")
        remote = os.environ.get("PLUGIN_MARKETPLACE_CATALOG_URL")
        if local:
            sources.append(
                {
                    "id": "curated",
                    "name": "Curated plugins",
                    "kind": "local",
                    "location": local,
                    "trusted": True,
                }
            )
        if remote:
            sources.append(
                {
                    "id": "public",
                    "name": "Public catalog",
                    "kind": "https",
                    "location": remote,
                    "trusted": True,
                }
            )
        return sources

    async def sources(self) -> list[dict[str, Any]]:
        return [
            *self.public_sources(),
            *(record.payload for record in await self.records("source")),
        ]

    async def add_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload["kind"] not in {"https", "git"}:
            raise MarketplaceV3Error("Server filesystem sources are not allowed")
        from urllib.parse import urlsplit

        parsed = urlsplit(payload["location"])
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise MarketplaceV3Error(
                "Sources require a public HTTPS URL without embedded credentials"
            )
        source = await self.add_record(
            "source", {name: payload[name] for name in ("name", "kind", "location", "trusted")}
        )
        return source.payload

    async def remove_source(self, source_id: str) -> None:
        source = await self.record(source_id, "source", lock=True)
        if any(
            row.payload["source_id"] == source_id and row.payload["status"] != "uninstalled"
            for row in await self.records("installation")
        ):
            raise MarketplaceV3Error("Uninstall this source's plugins before removing it")
        await self.db.delete(source)

    async def source(self, source_id: str) -> dict[str, Any]:
        for source in await self.sources():
            if source["id"] == source_id:
                return source
        raise MarketplaceV3Error("Source not found")

    async def packages(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="memstack-marketplace-") as folder:
            root = await snapshot_source(
                source["kind"], source["location"], Path(folder) / "snapshot"
            )
            packages = []
            for path in list_source_packages(root):
                package = inspect_codex_package(path, source_id=source["id"])
                package["files"] = {
                    file.relative_to(path).as_posix(): base64.b64encode(file.read_bytes()).decode(
                        "ascii"
                    )
                    for file in path.rglob("*")
                    if file.is_file() and ".git" not in file.relative_to(path).parts
                }
                packages.append(package)
            for package in packages:
                descriptor = package["descriptor"]
                reasons = list(descriptor.get("reasons", []))
                if "cloud" not in descriptor["targets"]:
                    reasons.append("This plugin does not support cloud execution")
                descriptor["reasons"] = reasons
                descriptor["compatible"] = not reasons
            return packages

    async def catalog(self, source_id: str | None = None) -> dict[str, Any]:
        items, errors = [], []
        for source in await self.sources():
            if source_id and source["id"] != source_id:
                continue
            try:
                items.extend(package["descriptor"] for package in await self.packages(source))
            except (ValueError, OSError, RuntimeError):
                errors.append(
                    {
                        "source_id": source["id"],
                        "error": "Could not load source; check the source URL and package format",
                    }
                )
        if self.tenant_id != PUBLIC_TENANT and (source_id is None or source_id == "signed-v2"):
            from src.infrastructure.plugins.marketplace_v2_descriptor import describe_v2_package

            signed_packages = await self.db.scalars(
                select(PlatformPluginPackageModel).where(
                    PlatformPluginPackageModel.revoked.is_(False)
                )
            )
            items.extend(describe_v2_package(package) for package in signed_packages)
        return {"items": items, "errors": errors}

    async def preflight(
        self, source_id: str, plugin_id: str, version: str | None = None
    ) -> dict[str, Any]:
        if source_id == "signed-v2":
            raise MarketplaceV3Error(
                "Use the signed V2 package installer; signature verification and tenant approval are required"
            )
        source = await self.source(source_id)
        if not source["trusted"]:
            raise MarketplaceV3Error("Confirm source trust before installing plugins")
        for package in await self.packages(source):
            plugin = package["descriptor"]
            if plugin["id"] != plugin_id or (version and plugin["version"] != version):
                continue
            await MarketplaceSnapshotCache(self.db, self.tenant_id, self.project_id).register(
                package
            )
            row = await self.add_record(
                "preflight",
                {"package": package, "source_id": source_id, "expires_at": preflight_expiry()},
            )
            return {
                "id": row.id,
                "plugin": plugin,
                "permissions": plugin["permissions"],
                "compatible": plugin["compatible"],
                "reasons": plugin["reasons"],
                "digest": package["digest"],
            }
        raise MarketplaceV3Error("Plugin version was not found in the selected source")

    @staticmethod
    def installation_view(payload: dict[str, Any]) -> dict[str, Any]:
        from src.application.services.marketplace_installation_view import (
            present_marketplace_installation,
        )

        return present_marketplace_installation(payload)

    async def install(
        self, preflight_id: str, permissions: list[str], idempotency_key: str
    ) -> dict[str, Any]:
        digest = self.request_digest(
            {
                "action": "install",
                "preflight_id": preflight_id,
                "permissions": sorted(set(permissions)),
            }
        )
        previous = [
            row for row in await self.records("operation") if row.record_key == idempotency_key
        ]
        if previous:
            if previous[0].payload.get("request_digest") != digest:
                raise MarketplaceV3Error("Idempotency key belongs to a different operation")
            return self.installation_view(
                (await self.record(previous[0].payload["installation_id"], "installation")).payload
            )
        preflight = await self.record(preflight_id, "preflight", lock=True)
        try:
            require_fresh_preflight(preflight.payload)
        except ValueError as exc:
            raise MarketplaceV3Error(str(exc)) from exc
        package = copy.deepcopy(preflight.payload["package"])
        plugin = package["descriptor"]
        if not plugin["compatible"]:
            raise MarketplaceV3Error("Plugin is incompatible with this target")
        if not set(plugin["permissions"]).issubset(permissions):
            raise MarketplaceV3Error("All requested permissions must be explicitly approved")
        source = await self.source(plugin["source_id"])
        if not source["trusted"]:
            raise MarketplaceV3Error("Source is no longer trusted")
        for existing in await self.records("installation"):
            if (
                existing.payload["plugin_id"] == plugin["id"]
                and existing.payload["status"] != "uninstalled"
            ):
                raise MarketplaceV3Error("Plugin is already installed; use update")
        row = await self.add_record(
            "installation",
            {
                "plugin_id": plugin["id"],
                "source_id": plugin["source_id"],
                "name": plugin["name"],
                "version": plugin["version"],
                "capabilities": plugin["capabilities"],
                "status": "downloaded",
                "package": package,
                "owned_skills": [],
                "owned_servers": [],
                "approved_permissions": permissions,
            },
            key=plugin["id"],
        )
        await self.add_record(
            "operation",
            {
                "installation_id": row.id,
                "preflight_id": preflight_id,
                "action": "install",
                "request_digest": digest,
            },
            key=idempotency_key,
        )
        return self.installation_view(row.payload)

    async def _set_skills(self, payload: dict[str, Any], enabled: bool) -> None:
        for skill_id in payload.get("owned_skills", []):
            skill = await self.db.scalar(
                select(Skill).where(
                    Skill.id == skill_id,
                    Skill.tenant_id == self.tenant_id,
                    Skill.project_id == (self.project_id or None),
                )
            )
            if skill is not None:
                skill.status = "active" if enabled else "disabled"

    async def _activate(self, payload: dict[str, Any]) -> None:  # noqa: C901, PLR0912
        resources = payload["package"]["resources"]
        servers = dict(resources.get("mcp_servers", {}))
        for name, app in resources.get("apps", {}).items():
            if app.get("mcp_server") in servers:
                continue
            config = app.get("mcp", app.get("server", app))
            if "url" not in config and "command" not in config:
                raise MarketplaceV3Error("App requires a reachable MCP service")
            servers[f"app-{name}"] = config
        if (servers or resources.get("hooks")) and (not self.project_id or self.mcp is None):
            raise MarketplaceV3Error(
                "MCP plugins require a project with an available sandbox runtime"
            )
        if (servers or resources.get("hooks")) and payload["package"].get("files"):
            package_root = await self.mcp.sandbox_manager.stage_marketplace_package(
                self.project_id,
                self.tenant_id,
                payload["id"],
                payload["package"]["digest"],
                payload["package"]["files"],
            )
            payload["runtime_root"] = package_root
            await MarketplaceSnapshotCache(self.db, self.tenant_id, self.project_id).register(
                payload["package"], package_root, owner_id=payload.get("oauth_owner", payload["id"])
            )

            servers = _expand_package_root(servers, package_root)
        from src.application.services.marketplace_oauth import authorize_transports
        from src.infrastructure.plugins.marketplace_credentials import configure_transport

        try:
            servers = configure_transport(servers, payload.get("configuration", {}))
            servers = await authorize_transports(self, payload, servers)
        except ValueError as exc:
            payload["status"] = "needs_configuration"
            payload["error"] = str(exc)
            return
        if not payload.get("owned_skills"):
            for skill in resources.get("skills", []):
                existing = await self.db.scalar(
                    select(Skill).where(
                        Skill.tenant_id == self.tenant_id,
                        Skill.project_id == (self.project_id or None),
                        Skill.name == skill["name"],
                    )
                )
                if existing:
                    raise MarketplaceV3Error(
                        "A skill with this name already exists; user resources are never overwritten"
                    )
            for skill in resources.get("skills", []):
                skill_id = str(uuid4())
                self.db.add(
                    Skill(
                        id=skill_id,
                        tenant_id=self.tenant_id,
                        project_id=self.project_id or None,
                        name=skill["name"],
                        description=skill["description"],
                        tools=[],
                        status="active",
                        scope="project" if self.project_id else "tenant",
                        full_content=skill["content"],
                        metadata_json={
                            "marketplace_installation_id": payload["id"],
                            "plugin_version": payload["version"],
                        },
                    )
                )
                payload["owned_skills"].append(skill_id)
        await self._set_skills(payload, True)
        if self.mcp:
            for index, server_id in enumerate(payload.get("owned_servers", [])):
                config = list(servers.values())[index]
                server = await self.mcp.runtime_service.update_server(
                    server_id=server_id, tenant_id=self.tenant_id, enabled=True,
                    transport_config={k: v for k, v in config.items() if k != "type"},
                )
                if server.runtime_status == "error":
                    raise MarketplaceV3Error(
                        "MCP service failed to start; check the project sandbox"
                    )
            if not payload.get("owned_servers"):
                for name, config in servers.items():
                    transport = config.get("type", "stdio" if "command" in config else "http")
                    server = await self.mcp.runtime_service.create_server(
                        tenant_id=self.tenant_id,
                        project_id=self.project_id,
                        name=f"marketplace-{payload['id'][:8]}-{name}",
                        description=f"Plugin {payload['name']} {payload['version']}",
                        server_type=transport,
                        transport_config={k: v for k, v in config.items() if k != "type"},
                        enabled=True,
                    )
                    payload["owned_servers"].append(server.id)
                    if server.runtime_status == "error":
                        raise MarketplaceV3Error(
                            "MCP service failed to start; check the project sandbox"
                        )
            self.mcp.tool_cache.invalidate(self.tenant_id)
        from src.application.services.marketplace_oauth_runtime import marketplace_activation

        with marketplace_activation(self.tenant_id, self.project_id, payload.get("owned_servers", [])):
            await self._verify_apps(payload)
        payload["status"] = "enabled"
        payload.pop("error", None)

    async def _verify_apps(self, payload: dict[str, Any]) -> None:
        resources = payload["package"]["resources"]
        if resources.get("apps"):
            apps = await self.mcp.app_service.list_apps(self.project_id, include_disabled=True)
            owned_apps = [app for app in apps if app.server_id in payload["owned_servers"]]
            for declaration in resources["apps"].values():
                uri = declaration.get("resource_uri")
                matches = [
                    app for app in owned_apps if not uri or app.ui_metadata.resource_uri == uri
                ]
                if not matches:
                    raise MarketplaceV3Error(
                        "The MCP service did not publish its declared app resource"
                    )
                for app in matches:
                    resolved = await self.mcp.app_service.resolve_resource(app.id, self.project_id)
                    if not resolved.is_ready:
                        raise MarketplaceV3Error("The plugin app resource could not be loaded")

    async def _deactivate(self, payload: dict[str, Any], *, uninstall: bool = False) -> None:
        await self._set_skills(payload, False)
        if payload.get("owned_servers") and self.mcp is None:
            raise MarketplaceV3Error("The MCP runtime is required to stop this plugin")
        for server_id in payload.get("owned_servers", []):
            stopped = await self.mcp.runtime_service.update_server(
                server_id=server_id, tenant_id=self.tenant_id, enabled=False
            )
            if stopped.runtime_status == "error":
                raise MarketplaceV3Error(
                    "MCP service could not finish stopping; resources were retained"
                )
            if uninstall:
                await self.mcp.runtime_service.delete_server(server_id, self.tenant_id)
        if uninstall:
            for skill_id in payload.get("owned_skills", []):
                skill = await self.db.scalar(
                    select(Skill).where(
                        Skill.id == skill_id,
                        Skill.tenant_id == self.tenant_id,
                        Skill.project_id == (self.project_id or None),
                    )
                )
                if skill:
                    await self.db.delete(skill)
            payload["owned_skills"], payload["owned_servers"] = [], []
            payload.pop("configuration", None)
        if self.mcp:
            self.mcp.tool_cache.invalidate(self.tenant_id)
        payload["status"] = "uninstalled" if uninstall else "disabled"
        payload.pop("error", None)

    async def _restore_updated_skill_names(
        self, candidate: dict[str, Any], skill_names: list[str], installation_id: str
    ) -> None:
        for skill_id, name in zip(candidate["owned_skills"], skill_names, strict=True):
            skill = await self.db.get(Skill, skill_id)
            if skill:
                skill.name = name
                skill.metadata_json = {
                    "marketplace_installation_id": installation_id,
                    "plugin_version": candidate["version"],
                }

    async def _update(
        self, row: MarketplaceRecordV3, previous: dict[str, Any], data: dict[str, Any]
    ) -> dict[str, Any]:
        """Stage a new version before touching the current active contributions."""
        if not data.get("preflight_id"):
            raise MarketplaceV3Error("A fresh preflight is required for updates")
        preview = await self.record(data["preflight_id"], "preflight")
        try:
            require_fresh_preflight(preview.payload)
        except ValueError as exc:
            raise MarketplaceV3Error(str(exc)) from exc
        package = copy.deepcopy(preview.payload["package"])
        plugin = package["descriptor"]
        if plugin["id"] != previous["plugin_id"] or plugin["source_id"] != previous["source_id"]:
            raise MarketplaceV3Error("Update preflight belongs to another plugin")
        if not plugin["compatible"] or not set(plugin["permissions"]).issubset(
            data.get("approved_permissions", [])
        ):
            raise MarketplaceV3Error("Update compatibility and permissions must be approved")
        source = await self.source(previous["source_id"])
        if not source["trusted"]:
            raise MarketplaceV3Error("Source is no longer trusted")
        candidate = {
            **copy.deepcopy(previous),
            "oauth_owner": previous["id"],
            "id": str(uuid4()),
            "package": package,
            "version": plugin["version"],
            "capabilities": plugin["capabilities"],
            "owned_skills": [],
            "owned_servers": [],
            "status": "downloaded",
            "approved_permissions": data.get("approved_permissions", []),
        }
        # Temporary resource names permit old and new versions to coexist during verification.
        skill_names = [skill["name"] for skill in package["resources"].get("skills", [])]
        for skill in package["resources"].get("skills", []):
            skill["name"] = f"{skill['name'][:145]}-staging-{candidate['id']}"
        try:
            await self._activate(candidate)
            if candidate["status"] != "enabled":
                raise MarketplaceV3Error("Configure the candidate version before updating")
        except Exception as exc:
            await self._deactivate(candidate, uninstall=True)
            raise MarketplaceV3Error(
                "Candidate verification failed; current version is unchanged"
            ) from exc
        old_snapshot = copy.deepcopy(previous)
        try:
            async with self.db.begin_nested():
                await self._deactivate(previous, uninstall=True)
                await self.db.flush()
                await self._restore_updated_skill_names(candidate, skill_names, row.id)
                for skill, name in zip(
                    package["resources"].get("skills", []), skill_names, strict=True
                ):
                    skill["name"] = name
                candidate["id"] = row.id
                row.payload = candidate
                await self.add_record(
                    "operation",
                    {
                        "installation_id": row.id,
                        "action": "update",
                        "request_digest": data["request_digest"],
                    },
                    key=data["idempotency_key"],
                )
                await self.db.flush()
                return self.installation_view(row.payload)
        except Exception as exc:
            await self._deactivate(candidate, uninstall=True)
            await self._activate(old_snapshot)
            row.payload = old_snapshot
            raise MarketplaceV3Error(
                "Version switch failed; the previous version was restored"
            ) from exc

    async def mutate(  # noqa: C901, PLR0912, PLR0915
        self, installation_id: str, action: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        row = await self.record(installation_id, "installation", lock=True)
        payload = copy.deepcopy(row.payload)
        key = data["idempotency_key"]
        digest = self.request_digest(
            {
                "action": action,
                "installation_id": installation_id,
                "preflight_id": data.get("preflight_id"),
                "permissions": sorted(set(data.get("approved_permissions", []))),
                "credentials": data.get("credentials", {}),
            }
        )
        data = {**data, "request_digest": digest}
        previous = [
            record for record in await self.records("operation") if record.record_key == key
        ]
        if previous:
            operation = previous[0].payload
            if (
                operation.get("installation_id") != installation_id
                or operation.get("action") != action
                or operation.get("request_digest") != digest
            ):
                raise MarketplaceV3Error("Idempotency key belongs to a different operation")
            if operation.get("status") == "running":
                raise MarketplaceV3Error(
                    "The operation has no final result yet; inspect its job before retrying"
                )
            if operation.get("status") == "failed":
                raise MarketplaceV3Error(operation.get("error") or "The previous operation failed")
            return self.installation_view(payload)
        if payload["status"] == "uninstalled":
            raise MarketplaceV3Error("Plugin has been uninstalled")
        if action == "update":
            await self.start_operation(installation_id, action, key, digest)
            try:
                return await self._update(row, payload, data)
            except MarketplaceV3Error as exc:
                await self.add_record(
                    "operation",
                    {
                        "installation_id": installation_id,
                        "action": action,
                        "request_digest": digest,
                        "status": "failed",
                        "stage": "rolled_back",
                        "error": str(exc),
                    },
                    key=key,
                )
                raise
        if action == "configure":
            from src.infrastructure.plugins.marketplace_credentials import seal

            if payload["status"] == "enabled":
                raise MarketplaceV3Error("Disable the plugin before changing credentials")
            try:
                sealed = {name: seal(value) for name, value in data.get("credentials", {}).items()}
                await self.start_operation(installation_id, action, key, digest)
                await self._deactivate(payload, uninstall=True)
                payload["configuration"] = sealed
            except Exception as exc:
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "Credential configuration failed; inspect the project runtime"
                )
                await self.add_record(
                    "operation",
                    {
                        "installation_id": installation_id,
                        "action": action,
                        "request_digest": digest,
                        "status": "failed",
                        "stage": "configuration_failed",
                        "error": message,
                    },
                    key=key,
                )
                raise MarketplaceV3Error(message) from exc
            payload["status"] = "downloaded"
            payload.pop("error", None)
            row.payload = payload
            await self.add_record(
                "operation",
                {"installation_id": installation_id, "action": action, "request_digest": digest},
                key=key,
            )
            return self.installation_view(row.payload)
        await self.start_operation(installation_id, action, key, digest)
        try:
            if action == "enable":
                await self._activate(payload)
            elif action in {"disable", "uninstall"}:
                await self._deactivate(payload, uninstall=action == "uninstall")
            elif action == "verify":
                if payload["status"] != "enabled":
                    raise MarketplaceV3Error("Enable the plugin before verification")
                for server_id in payload.get("owned_servers", []):
                    if self.mcp is None:
                        raise MarketplaceV3Error("MCP runtime is not available")
                    await self.mcp.runtime_service.sync_server(server_id, self.tenant_id)
                for skill_id in payload.get("owned_skills", []):
                    skill = await self.db.get(Skill, skill_id)
                    if skill is None or skill.status != "active":
                        raise MarketplaceV3Error("An installed skill is missing or disabled")
            else:
                raise MarketplaceV3Error("Unknown marketplace action")
        except Exception as exc:
            from src.infrastructure.plugins.marketplace_diagnostics import log_marketplace_failure

            log_marketplace_failure(exc)
            # Stop every successfully registered contribution before recording failure.
            with suppress(Exception):
                await self._deactivate(payload)
            payload["status"] = "failed"
            payload["error"] = (
                "Plugin operation failed; review configuration and project runtime availability"
            )
        row.payload = payload
        if payload["status"] == "uninstalled":
            row.record_key = f"uninstalled:{row.id}"
        await self.add_record(
            "operation",
            {"installation_id": installation_id, "action": action, "request_digest": digest},
            key=key,
        )
        await self.db.flush()
        return self.installation_view(row.payload)
