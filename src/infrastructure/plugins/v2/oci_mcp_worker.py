"""Launch an admitted immutable OCI release in a dedicated restricted MCP container."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol, Self
from urllib.parse import urlsplit

from docker.client import from_env
from docker.errors import DockerException, ImageNotFound
from docker.types import LogConfig
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry

from src.domain.model.plugins.generated_v2 import RuntimeKindV2, ScopeKindV2, ScopeV2
from src.host.runtime.oci_mcp_lease import remove_worker_container, worker_ownership
from src.infrastructure.mcp.protocol import LATEST_PROTOCOL_VERSION, accept_server_protocol
from src.infrastructure.plugins.package_registry import (
    normalize_digest,
    normalize_registry,
    normalize_repository,
)
from src.infrastructure.plugins.v2.bundle_archive import require_signed_archive_verification_v2
from src.infrastructure.plugins.v2.oci_mcp_wire import OciMcpWire

if TYPE_CHECKING:
    from docker.client import DockerClient
    from docker.models.containers import Container

    from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
    from src.infrastructure.plugins.v2.oci_mcp_records import RecordCall
    from src.infrastructure.plugins.v2.signed_optional_business_v2 import ScopeBindingV2


WORKER_MEDIA_TYPE = "application/vnd.memstack.mcp-oci-worker.v1+json"


class OciWorkerError(ValueError):
    """A signed worker could not be admitted or complete its bounded operation."""


class WorkerTool(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def input_schema(self) -> dict[str, Any]: ...
    @property
    def output_schema(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class OciWorkerSpec:
    image: str
    entrypoint: str
    _admission: tuple[str, str, str] | None = field(default=None, init=False, repr=False)

    @classmethod
    def parse(cls, raw: bytes) -> Self:
        if len(raw) > 4096:
            raise OciWorkerError("OCI worker descriptor exceeds limit")
        descriptor = json.loads(raw)
        if not isinstance(descriptor, dict) or set(descriptor) != {"schema", "image", "entrypoint"}:
            raise OciWorkerError("invalid OCI worker descriptor")
        image, entrypoint = descriptor["image"], descriptor["entrypoint"]
        if descriptor["schema"] != "memstack.mcp-oci-worker/1" or not isinstance(image, str):
            raise OciWorkerError("unsupported OCI worker schema")
        location, sep, digest = image.partition("@sha256:")
        authority, slash, repository = location.partition("/")
        if (
            not sep
            or not slash
            or not authority
            or (authority != "localhost" and "." not in authority and ":" not in authority)
        ):
            raise OciWorkerError("worker image requires an explicit registry and immutable digest")
        normalize_registry("https://" + authority)
        normalize_repository(repository)
        normalize_digest(digest)
        if not isinstance(entrypoint, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", entrypoint):
            raise OciWorkerError("expected an absolute worker executable path")
        path = PurePosixPath(entrypoint)
        if path.as_posix() != entrypoint or ".." in path.parts or entrypoint.startswith("//"):
            raise OciWorkerError("invalid worker executable path")
        return cls(image=image, entrypoint=entrypoint)

    @classmethod
    def from_archive(
        cls, archive: VerifiedBundleArchiveV2, *, raw: bytes, scope: ScopeBindingV2 | None
    ) -> Self:
        approved = require_signed_archive_verification_v2(archive)
        manifest = archive.manifest
        if (
            scope is None
            or not scope.tenant_id
            or not scope.project_id
            or "tools.execute" not in approved
        ):
            raise OciWorkerError("OCI worker requires approved project execution")
        if len(manifest.manifests) != 1 or len(manifest.layers) != 1:
            raise OciWorkerError("expected a single project worker release")
        plugin, layer = manifest.manifests[0], manifest.layers[0]
        if (
            plugin.runtime != RuntimeKindV2.MCP
            or len(plugin.modules) != 1
            or len(layer.entries) != 1
        ):
            raise OciWorkerError("expected a signed MCP worker module and entry")
        module, entry = plugin.modules[0], layer.entries[0]
        permitted = {
            ScopeV2(kind=ScopeKindV2.ROOT),
            ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=scope.tenant_id),
            ScopeV2(
                kind=ScopeKindV2.PROJECT, tenant_id=scope.tenant_id, project_id=scope.project_id
            ),
        }
        if layer.scope not in permitted or entry.scope not in permitted or not entry.enabled:
            raise OciWorkerError("worker release does not cover this project")
        if module.entrypoint != "mcp.stdio" or "tools.execute" not in set(entry.permissions) & set(
            plugin.permissions
        ):
            raise OciWorkerError("MCP worker module has no approved tool entry")
        verified = [
            a
            for a in manifest.artifacts
            if a.media_type == WORKER_MEDIA_TYPE
            and a.digest == module.artifact.digest
            and module.artifact.source == f"bundle://{plugin.plugin_id}/{a.path}"
        ]
        if len(verified) != 1 or archive.artifacts[verified[0].artifact_id] != raw:
            raise OciWorkerError("worker descriptor differs from the signed module")
        spec = cls.parse(raw)
        object.__setattr__(spec, "_admission", (scope.tenant_id, scope.project_id, manifest.digest))
        return spec

    def authorize(
        self, scope: ScopeBindingV2, release_digest: str, registries: frozenset[str]
    ) -> None:
        if self._admission != (scope.tenant_id, scope.project_id, release_digest):
            raise OciWorkerError("OCI worker release was not admitted for this project and digest")
        allowed = {urlsplit(normalize_registry(registry)).netloc for registry in registries}
        if self.image.partition("/")[0] not in allowed:
            raise OciWorkerError("worker registry is not approved")


def missing_worker_images(required: set[str]) -> set[str]:
    """Check this replica's execution daemon for the exact images previously prepared."""
    client = from_env(timeout=2)
    try:
        missing = set()
        for name in required:
            try:
                details = client.api.inspect_image(name)
            except ImageNotFound:
                missing.add(name)
            else:
                if name not in (details.get("RepoDigests") or []):
                    missing.add(name)
        return missing
    finally:
        client.close()


class OciWorkerSession:
    def __init__(
        self,
        client: DockerClient,
        container: Container,
        wire: OciMcpWire,
        wall_time_ms: int,
        max_output_bytes: int,
    ) -> None:
        self._client = client
        self._container = container
        self._wire = wire
        self._timeout = min(wall_time_ms, 30_000) / 1000
        self._max_output = min(max_output_bytes, 65536)
        self._tools: dict[str, WorkerTool] = {}

    @classmethod
    @contextlib.asynccontextmanager
    async def open(
        cls,
        spec: OciWorkerSpec,
        *,
        scope: ScopeBindingV2,
        release_digest: str,
        allowed_registries: frozenset[str],
        wall_time_ms: int,
        max_output_bytes: int,
    ) -> AsyncIterator[Self]:
        spec.authorize(scope, release_digest, allowed_registries)
        if wall_time_ms <= 0 or max_output_bytes <= 0:
            raise OciWorkerError("invalid OCI worker quotas")
        pending = asyncio.create_task(
            asyncio.to_thread(
                cls._start, spec, scope, release_digest, wall_time_ms, max_output_bytes
            )
        )
        try:
            worker = await asyncio.shield(pending)
        except asyncio.CancelledError:
            result = await asyncio.gather(pending, return_exceptions=True)
            if isinstance(result[0], cls):
                await asyncio.to_thread(result[0]._stop)
            raise
        try:
            yield worker
        finally:
            await asyncio.to_thread(worker._stop)

    @classmethod
    def _start(
        cls,
        spec: OciWorkerSpec,
        scope: ScopeBindingV2,
        digest: str,
        wall_time_ms: int,
        max_output_bytes: int,
    ) -> Self:
        try:
            client = from_env(timeout=20)
        except DockerException as exc:
            raise OciWorkerError("worker provisioner unavailable") from exc
        container = None
        try:
            try:
                image = client.images.get(spec.image)
            except ImageNotFound:
                repository, _, pinned = spec.image.partition("@")
                image = client.images.pull(repository, tag=pinned)
            if not image.id or spec.image not in (image.attrs.get("RepoDigests") or []):
                raise OciWorkerError("Docker image differs from approved registry digest")
            if image.attrs.get("Config", {}).get("Volumes"):
                raise OciWorkerError("worker images cannot declare data volumes")
            name, ownership = worker_ownership(
                client.info()["ID"], scope.tenant_id, scope.project_id, digest
            )
            container = client.containers.create(
                image.id,
                name=name,
                entrypoint=[spec.entrypoint],
                command=[],
                stdin_open=True,
                tty=False,
                working_dir="/",
                user="65532:65532",
                read_only=True,
                network_mode="none",
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
                pids_limit=32,
                mem_limit="128m",
                memswap_limit="128m",
                nano_cpus=500_000_000,
                ipc_mode="none",
                init=True,
                auto_remove=True,
                healthcheck={"Test": ["NONE"]},
                log_config=LogConfig(type="none"),
                labels={
                    **ownership,
                    "memstack.oci-worker": "1",
                    "memstack.project": scope.project_id,
                    "memstack.tenant": scope.tenant_id,
                    "memstack.release": digest,
                },
            )
            container.reload()
            if (
                container.attrs["Path"] != spec.entrypoint
                or container.attrs["Args"]
                or container.attrs["Mounts"]
            ):
                raise OciWorkerError("Docker worker entrypoint or mount contract differs")
            raw = container.attach_socket(
                params={"stdin": 1, "stdout": 1, "stderr": 0, "stream": 1}
            )
            wire = OciMcpWire(raw)
            try:
                container.start()
            except BaseException:
                wire.close()
                raise
            return cls(client, container, wire, wall_time_ms, max_output_bytes)
        except BaseException as exc:
            if container is not None:
                remove_worker_container(container)
            client.close()
            if isinstance(exc, DockerException):
                raise OciWorkerError("could not provision the approved worker container") from exc
            raise

    def _stop(self) -> None:
        try:
            self._wire.close()
        finally:
            try:
                remove_worker_container(self._container)
            finally:
                self._client.close()

    async def prepare(self, tools: Sequence[WorkerTool]) -> None:
        try:
            async with asyncio.timeout(10):
                details = await self._wire.request(
                    "initialize",
                    {
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "memstack-worker", "version": "1"},
                    },
                )
                accept_server_protocol(details.get("protocolVersion"))
                await self._wire.notify("notifications/initialized", {})
                listing = await self._wire.request("tools/list", {})
        except TimeoutError as exc:
            raise OciWorkerError("worker initialization exceeded its deadline") from exc
        rows = listing.get("tools")
        if listing.get("nextCursor") or not isinstance(rows, list) or len(rows) != len(tools):
            raise OciWorkerError("worker tool discovery differs from signed release")
        declared = {tool.name: tool for tool in tools}
        seen = set()
        for row in rows:
            name = row.get("name") if isinstance(row, dict) else None
            tool = declared.get(name) if isinstance(name, str) else None
            if (
                tool is None
                or name in seen
                or tool.input_schema != row.get("inputSchema")
                or tool.output_schema != row.get("outputSchema")
            ):
                raise OciWorkerError("worker tool schemas differ from signed release")
            seen.add(name)
        self._tools = declared

    async def invoke(
        self,
        name: str,
        payload: dict[str, Any],
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_record: RecordCall | None = None,
    ) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise OciWorkerError("worker tool is not prepared")
        try:
            Draft202012Validator(tool.input_schema, registry=Registry()).validate(payload)
            async with asyncio.timeout(self._timeout):
                result = await self._wire.request(
                    "tools/call", {"name": name, "arguments": payload}, on_progress, on_record
                )
            structured = result.get("structuredContent")
            if result.get("isError") or not isinstance(structured, dict):
                raise OciWorkerError("MCP worker returned no structured result")
            if (
                len(json.dumps(structured, ensure_ascii=False, allow_nan=False).encode())
                > self._max_output
            ):
                raise OciWorkerError("MCP worker exceeded its output quota")
            Draft202012Validator(tool.output_schema, registry=Registry()).validate(structured)
        except TimeoutError as exc:
            raise OciWorkerError("worker invocation exceeded its deadline") from exc
        except ValidationError as error:
            raise OciWorkerError("MCP worker invocation failed schema validation") from error
        return structured
