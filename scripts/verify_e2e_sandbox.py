"""Verify the authenticated MCP-only Sandbox lifecycle against a real container."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import stat
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

import httpx
import websockets
from docker.errors import NotFound
from websockets.exceptions import ConnectionClosed

import docker

E2E_SANDBOX_RESPONSE = "E2E_SANDBOX_OK"
EXPECTED_SANDBOX_IMAGE = "sandbox-mcp-server:lite"


class _Container(Protocol):
    attrs: Mapping[str, object]

    def reload(self) -> None: ...

    def remove(self, *, force: bool) -> None: ...


class _ContainerCollection(Protocol):
    def get(self, container_id: str) -> _Container: ...


class _DockerClient(Protocol):
    containers: _ContainerCollection


class _DockerModule(Protocol):
    def from_env(self) -> _DockerClient: ...


_DOCKER_MODULE = cast("_DockerModule", docker)


def _require_mapping(payload: object, description: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"Sandbox E2E did not return {description}")
    return cast("Mapping[str, object]", payload)


def _require_string(payload: Mapping[str, object], key: str, description: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Sandbox E2E did not return {description}")
    return value


def _environment_map(raw_environment: object) -> dict[str, str]:
    if not isinstance(raw_environment, Sequence) or isinstance(raw_environment, str | bytes):
        return {}
    result: dict[str, str] = {}
    for entry in cast("Sequence[object]", raw_environment):
        if not isinstance(entry, str):
            continue
        name, separator, value = entry.partition("=")
        if separator:
            result[name] = value
    return result


def _verify_container_process(
    config: Mapping[str, object],
    host_config: Mapping[str, object],
    expected_image: str,
) -> None:
    if config.get("Image") != expected_image:
        raise RuntimeError("Sandbox E2E container did not use the selected profile image")

    user = config.get("User")
    if not isinstance(user, str) or user.strip().lower() in {"", "0", "root"}:
        raise RuntimeError("Sandbox E2E container must run as a non-root user")
    if host_config.get("Privileged") is not False:
        raise RuntimeError("Sandbox E2E container must not be privileged")

    binds = host_config.get("Binds")
    if isinstance(binds, list):
        for bind in cast("list[object]", binds):
            if isinstance(bind, str) and "/var/run/docker.sock" in bind:
                raise RuntimeError("Sandbox E2E container must not mount the Docker socket")


def _verify_container_ports(host_config: Mapping[str, object]) -> None:
    port_bindings = _require_mapping(host_config.get("PortBindings"), "container port bindings")
    if "6080/tcp" in port_bindings:
        raise RuntimeError("Sandbox E2E container published a disabled desktop port")
    if "7681/tcp" in port_bindings:
        raise RuntimeError("Sandbox E2E container published a disabled terminal port")
    for raw_bindings in port_bindings.values():
        if not isinstance(raw_bindings, list) or not raw_bindings:
            raise RuntimeError("Sandbox E2E container has an invalid port binding")
        for raw_binding in cast("list[object]", raw_bindings):
            binding = _require_mapping(raw_binding, "a container port binding")
            if binding.get("HostIp") != "127.0.0.1":
                raise RuntimeError("Sandbox E2E ports must bind to loopback")


def _verify_container_auth(config: Mapping[str, object]) -> None:
    environment = _environment_map(config.get("Env"))
    if environment.get("MCP_AUTH_ENABLED") != "true":
        raise RuntimeError("Sandbox E2E MCP authentication is not enabled")
    if environment.get("MCP_ALLOW_LOCALHOST") != "false":
        raise RuntimeError("Sandbox E2E localhost authentication bypass is enabled")
    if not environment.get("MCP_STATIC_TOKEN"):
        raise RuntimeError("Sandbox E2E capability token is missing")
    if environment.get("DESKTOP_ENABLED") != "false":
        raise RuntimeError("Sandbox E2E desktop profile is not disabled")
    if environment.get("TERMINAL_ENABLED") != "false":
        raise RuntimeError("Sandbox E2E terminal profile is not disabled")


def verify_sandbox_container(
    attrs: Mapping[str, object],
    *,
    expected_image: str,
) -> None:
    """Fail unless Docker metadata proves the least-privilege E2E contract."""
    config = _require_mapping(attrs.get("Config"), "container configuration")
    host_config = _require_mapping(attrs.get("HostConfig"), "container host configuration")
    _verify_container_process(config, host_config, expected_image)
    _verify_container_ports(host_config)
    _verify_container_auth(config)


def verify_tool_result(
    payload: object,
    *,
    expected_text: str | None = None,
    expect_error: bool = False,
) -> None:
    """Validate a project Sandbox tool response without depending on tool internals."""
    result = _require_mapping(payload, "a tool response")
    is_error = result.get("is_error") is True
    success = result.get("success") is True
    if expect_error:
        if not is_error or success:
            raise RuntimeError("Sandbox E2E expected the tool call to be rejected")
        return
    if is_error or not success:
        raise RuntimeError("Sandbox E2E tool call failed")
    if expected_text is not None:
        serialized_content = json.dumps(result.get("content"), ensure_ascii=False)
        if expected_text not in serialized_content:
            raise RuntimeError("Sandbox E2E tool response did not contain expected content")


def _authenticate(client: httpx.Client, api_base: str, username: str, password: str) -> str:
    response = client.post(
        f"{api_base}/api/v1/auth/token",
        data={"username": username, "password": password},
    )
    _ = response.raise_for_status()
    payload = _require_mapping(cast("object", response.json()), "an authentication object")
    return _require_string(payload, "access_token", "an access token")


def _create_project(client: httpx.Client, api_base: str, token: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    tenant_response = client.get(f"{api_base}/api/v1/tenants/", headers=headers)
    _ = tenant_response.raise_for_status()
    tenant_payload = cast("object", tenant_response.json())
    if isinstance(tenant_payload, Mapping):
        tenant_payload = cast("Mapping[str, object]", tenant_payload).get("tenants")
    if not isinstance(tenant_payload, list) or not tenant_payload:
        raise RuntimeError("Sandbox E2E did not return a tenant")
    tenant = _require_mapping(cast("object", tenant_payload[0]), "a tenant object")
    tenant_id = _require_string(tenant, "id", "a tenant id")

    project_response = client.post(
        f"{api_base}/api/v1/projects/",
        headers=headers,
        json={
            "name": f"Sandbox E2E {uuid.uuid4().hex[:8]}",
            "description": "Authenticated MCP-only Sandbox E2E fixture",
            "tenant_id": tenant_id,
        },
    )
    _ = project_response.raise_for_status()
    project = _require_mapping(cast("object", project_response.json()), "a project object")
    return _require_string(project, "id", "a project id")


async def _verify_unauthenticated_websocket_rejected(
    websocket_url: str,
    *,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(websocket_url) as websocket:
                try:
                    _ = await websocket.recv()
                except ConnectionClosed as exc:
                    if exc.code == 4001:
                        return
                    raise RuntimeError(
                        f"Sandbox E2E unauthenticated close used code {exc.code}"
                    ) from exc
        except (ConnectionRefusedError, OSError) as exc:
            last_error = exc
            await asyncio.sleep(0.25)
    raise RuntimeError("Sandbox E2E unauthenticated WebSocket was not rejected") from last_error


def _call_tool(
    client: httpx.Client,
    api_base: str,
    project_id: str,
    headers: Mapping[str, str],
    tool_name: str,
    arguments: Mapping[str, object],
) -> object:
    response = client.post(
        f"{api_base}/api/v1/projects/{project_id}/sandbox/execute",
        headers=headers,
        json={"tool_name": tool_name, "arguments": arguments, "timeout": 15.0},
    )
    _ = response.raise_for_status()
    return cast("object", response.json())


def _wait_for_container_removal(
    docker_client: _DockerClient,
    sandbox_id: str,
    *,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            _ = docker_client.containers.get(sandbox_id)
        except NotFound:
            return
        time.sleep(0.25)
    raise RuntimeError("Sandbox E2E container was not removed")


def verify_sandbox(
    api_base: str,
    *,
    expected_image: str = EXPECTED_SANDBOX_IMAGE,
    docker_client: _DockerClient | None = None,
) -> None:
    """Create, exercise, inspect, and destroy one authenticated Sandbox."""
    base = api_base.rstrip("/")
    resolved_docker = docker_client or _DOCKER_MODULE.from_env()

    with httpx.Client(timeout=30.0) as client:
        admin_token = _authenticate(client, base, "admin@memstack.ai", "adminpassword")
        user_token = _authenticate(client, base, "user@memstack.ai", "userpassword")
        headers = {"Authorization": f"Bearer {admin_token}"}
        project_id = _create_project(client, base, admin_token)
        workspace_path = Path(f"/tmp/memstack_{project_id}")
        sandbox_id: str | None = None
        workspace_path.mkdir(parents=True, exist_ok=True)
        workspace_path.chmod(
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IWGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IWOTH
            | stat.S_IXOTH
        )

        try:
            anonymous = client.post(
                f"{base}/api/v1/projects/{project_id}/sandbox",
                json={"profile": "lite"},
            )
            if anonymous.status_code != 401:
                raise RuntimeError("Sandbox E2E anonymous create was not rejected")
            wrong_user = client.post(
                f"{base}/api/v1/projects/{project_id}/sandbox",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"profile": "lite"},
            )
            if wrong_user.status_code != 403:
                raise RuntimeError("Sandbox E2E cross-tenant create was not rejected")

            create_response = client.post(
                f"{base}/api/v1/projects/{project_id}/sandbox",
                headers=headers,
                json={"profile": "lite"},
            )
            _ = create_response.raise_for_status()
            sandbox = _require_mapping(cast("object", create_response.json()), "a Sandbox response")
            sandbox_id = _require_string(sandbox, "sandbox_id", "a Sandbox id")
            websocket_url = _require_string(sandbox, "websocket_url", "an MCP WebSocket URL")
            if sandbox.get("desktop_port") is not None or sandbox.get("desktop_url") is not None:
                raise RuntimeError("Sandbox E2E reported a disabled desktop service")
            if sandbox.get("terminal_port") is not None or sandbox.get("terminal_url") is not None:
                raise RuntimeError("Sandbox E2E reported a disabled terminal service")

            container = resolved_docker.containers.get(sandbox_id)
            container.reload()
            verify_sandbox_container(container.attrs, expected_image=expected_image)
            asyncio.run(_verify_unauthenticated_websocket_rejected(websocket_url))

            verify_tool_result(
                _call_tool(
                    client,
                    base,
                    project_id,
                    headers,
                    "write",
                    {"file_path": "e2e.txt", "content": E2E_SANDBOX_RESPONSE},
                )
            )
            verify_tool_result(
                _call_tool(
                    client,
                    base,
                    project_id,
                    headers,
                    "read",
                    {"file_path": "e2e.txt"},
                ),
                expected_text=E2E_SANDBOX_RESPONSE,
            )
            verify_tool_result(
                _call_tool(
                    client,
                    base,
                    project_id,
                    headers,
                    "bash",
                    {"command": "pwd && id -u"},
                ),
                expected_text="/workspace",
            )
            verify_tool_result(
                _call_tool(
                    client,
                    base,
                    project_id,
                    headers,
                    "write",
                    {"file_path": "/etc/memstack-e2e-forbidden", "content": "blocked"},
                ),
                expect_error=True,
            )

            delete_response = client.delete(
                f"{base}/api/v1/projects/{project_id}/sandbox",
                headers=headers,
            )
            _ = delete_response.raise_for_status()
            _wait_for_container_removal(resolved_docker, sandbox_id)
            sandbox_id = None
        finally:
            with contextlib.suppress(Exception):
                _ = client.delete(
                    f"{base}/api/v1/projects/{project_id}/sandbox",
                    headers=headers,
                )
            if sandbox_id is not None:
                with contextlib.suppress(Exception):
                    resolved_docker.containers.get(sandbox_id).remove(force=True)
            shutil.rmtree(workspace_path, ignore_errors=True)


if __name__ == "__main__":
    verify_sandbox(os.getenv("API_BASE", "http://localhost:8000"))
    print("Authenticated MCP-only Sandbox E2E verified")
