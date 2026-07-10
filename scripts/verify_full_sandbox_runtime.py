"""Verify the complete Desktop/Terminal Sandbox image and isolation boundary."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import secrets
import shutil
import socket
import stat
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

import docker

if TYPE_CHECKING:
    from docker.client import DockerClient
    from docker.models.containers import Container
    from docker.models.networks import Network

DEFAULT_IMAGE = "sandbox-mcp-server:full-ci"
INTERNAL_PORTS = (8765, 6080, 7681)
ISOLATED_NETWORK_OPTIONS = {"com.docker.network.bridge.enable_icc": "false"}
SERVICE_AUTH_USERNAME = "sandbox"


class _WebSocket(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...


class _DockerModule(Protocol):
    def from_env(self) -> DockerClient: ...


_DOCKER_MODULE = cast("_DockerModule", docker)


def _require_mapping(value: object, description: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Full Sandbox runtime did not expose {description}")
    return cast("Mapping[str, object]", value)


def _environment_map(raw_environment: object) -> dict[str, str]:
    if not isinstance(raw_environment, Sequence) or isinstance(raw_environment, str | bytes):
        return {}
    environment: dict[str, str] = {}
    for entry in cast("Sequence[object]", raw_environment):
        if isinstance(entry, str):
            name, separator, value = entry.partition("=")
            if separator:
                environment[name] = value
    return environment


def _verify_process_metadata(
    config: Mapping[str, object],
    host_config: Mapping[str, object],
    expected_image: str,
    expected_network: str,
) -> None:
    if config.get("Image") != expected_image:
        raise RuntimeError("Full Sandbox runtime used an unexpected image")
    user = config.get("User")
    if not isinstance(user, str) or user.strip().lower() in {"", "0", "root"}:
        raise RuntimeError("Full Sandbox runtime must use a non-root user")
    if host_config.get("Privileged") is not False:
        raise RuntimeError("Full Sandbox runtime must not be privileged")
    if host_config.get("NetworkMode") != expected_network:
        raise RuntimeError("Full Sandbox runtime must use its dedicated network")

    binds = host_config.get("Binds")
    if isinstance(binds, list) and any(
        isinstance(bind, str) and "/var/run/docker.sock" in bind
        for bind in cast("list[object]", binds)
    ):
        raise RuntimeError("Full Sandbox runtime must not mount the Docker socket")


def _verify_port_metadata(host_config: Mapping[str, object]) -> None:
    port_bindings = _require_mapping(host_config.get("PortBindings"), "port bindings")
    if set(port_bindings) != {f"{port}/tcp" for port in INTERNAL_PORTS}:
        raise RuntimeError("Full Sandbox runtime did not publish the complete service set")
    for raw_bindings in port_bindings.values():
        if not isinstance(raw_bindings, list) or not raw_bindings:
            raise RuntimeError("Full Sandbox runtime has an invalid port binding")
        for raw_binding in cast("list[object]", raw_bindings):
            binding = _require_mapping(raw_binding, "a port binding")
            if binding.get("HostIp") != "127.0.0.1":
                raise RuntimeError("Full Sandbox runtime ports must bind to loopback")


def _verify_auth_metadata(config: Mapping[str, object]) -> None:
    environment = _environment_map(config.get("Env"))
    required_environment = {
        "MCP_AUTH_ENABLED": "true",
        "MCP_ALLOW_LOCALHOST": "false",
        "DESKTOP_ENABLED": "true",
        "TERMINAL_ENABLED": "true",
    }
    if any(environment.get(name) != value for name, value in required_environment.items()):
        raise RuntimeError("Full Sandbox runtime service or authentication settings drifted")
    if not environment.get("MCP_STATIC_TOKEN"):
        raise RuntimeError("Full Sandbox runtime capability is missing")

    labels = _require_mapping(config.get("Labels"), "container labels")
    if any(
        "token" in str(name).lower() or "token" in str(value).lower()
        for name, value in labels.items()
    ):
        raise RuntimeError("Full Sandbox runtime leaked a capability into Docker labels")


def verify_runtime_metadata(
    attrs: Mapping[str, object],
    *,
    expected_image: str,
    expected_network: str,
) -> None:
    """Fail unless Docker metadata proves the full-image security contract."""
    config = _require_mapping(attrs.get("Config"), "container configuration")
    host_config = _require_mapping(attrs.get("HostConfig"), "host configuration")
    _verify_process_metadata(config, host_config, expected_image, expected_network)
    _verify_port_metadata(host_config)
    _verify_auth_metadata(config)


def _verify_network_metadata(network: Network) -> None:
    network.reload()
    attrs = _require_mapping(cast("object", network.attrs), "network metadata")
    options = _require_mapping(attrs.get("Options"), "network options")
    if options.get("com.docker.network.bridge.enable_icc") != "false":
        raise RuntimeError("Full Sandbox network allows inter-container communication")


def _create_isolated_network(client: DockerClient, name: str) -> Network:
    network = client.networks.create(
        name,
        driver="bridge",
        options=ISOLATED_NETWORK_OPTIONS,
        labels={"memstack.full-runtime": "true"},
    )
    _verify_network_metadata(network)
    return network


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return cast("int", listener.getsockname()[1])


def _runtime_service_urls(ports: Mapping[str, tuple[str, int]]) -> tuple[str, str, str]:
    mcp_port = ports["8765/tcp"][1]
    desktop_port = ports["6080/tcp"][1]
    terminal_port = ports["7681/tcp"][1]
    return (
        f"ws://127.0.0.1:{mcp_port}/",
        f"https://127.0.0.1:{desktop_port}/",
        f"http://127.0.0.1:{terminal_port}/",
    )


def _basic_auth_headers(token: str) -> dict[str, str]:
    credentials = f"{SERVICE_AUTH_USERNAME}:{token}".encode()
    encoded = base64.b64encode(credentials).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _wait_http(
    url: str,
    *,
    timeout_seconds: float = 90.0,
    verify_tls: bool = True,
    headers: Mapping[str, str] | None = None,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    with httpx.Client(timeout=5.0, follow_redirects=True, verify=verify_tls) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(url, headers=headers) if headers else client.get(url)
                if response.status_code < 400:
                    return response.text
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Full Sandbox service did not become ready: {url}") from last_error


def _verify_http_service_auth(
    url: str,
    token: str,
    *,
    verify_tls: bool,
) -> None:
    with httpx.Client(timeout=5.0, follow_redirects=False, verify=verify_tls) as client:
        unauthenticated = client.get(url)
        wrong_credential = client.get(url, headers=_basic_auth_headers("wrong-capability"))
        authenticated = client.get(url, headers=_basic_auth_headers(token))

    for response in (unauthenticated, wrong_credential):
        if response.status_code not in {401, 403}:
            raise RuntimeError("Full Sandbox interactive service accepted invalid credentials")
    if authenticated.status_code >= 400:
        raise RuntimeError("Full Sandbox interactive service rejected its runtime capability")


async def _expect_websocket_rejected(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> None:
    async with websockets.connect(url, additional_headers=headers, open_timeout=10.0) as websocket:
        try:
            _ = await websocket.recv()
        except ConnectionClosed as exc:
            if exc.code == 4001:
                return
            raise RuntimeError(f"Full Sandbox rejected MCP with close code {exc.code}") from exc
    raise RuntimeError("Full Sandbox accepted an invalid MCP capability")


async def _rpc(websocket: _WebSocket, request_id: int, method: str, params: object) -> object:
    await websocket.send(
        json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    )
    response = json.loads(await websocket.recv())
    payload = _require_mapping(cast("object", response), "an MCP response")
    if "error" in payload:
        raise RuntimeError(f"Full Sandbox MCP method failed: {method}")
    return payload.get("result")


async def _verify_mcp(websocket_url: str, token: str) -> None:
    await _expect_websocket_rejected(websocket_url)
    await _expect_websocket_rejected(
        websocket_url,
        headers={"Authorization": "Bearer wrong-capability"},
    )
    await _expect_websocket_rejected(f"{websocket_url}?token=query-only-capability")

    async with websockets.connect(
        websocket_url,
        additional_headers={"Authorization": f"Bearer {token}"},
        open_timeout=10.0,
    ) as websocket:
        initialized = _require_mapping(
            await _rpc(
                websocket,
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "full-runtime-gate", "version": "1.0"},
                },
            ),
            "initialize result",
        )
        if not initialized.get("serverInfo"):
            raise RuntimeError("Full Sandbox MCP initialize result is incomplete")
        tools = _require_mapping(await _rpc(websocket, 2, "tools/list", {}), "tool list")
        if not tools.get("tools"):
            raise RuntimeError("Full Sandbox MCP tool list is empty")
        write_result = _require_mapping(
            await _rpc(
                websocket,
                3,
                "tools/call",
                {
                    "name": "write",
                    "arguments": {"file_path": "full-runtime.txt", "content": "FULL_RUNTIME_OK"},
                },
            ),
            "write result",
        )
        if write_result.get("isError") is True:
            raise RuntimeError("Full Sandbox MCP write failed")
        read_result = await _rpc(
            websocket,
            4,
            "tools/call",
            {"name": "read", "arguments": {"file_path": "full-runtime.txt"}},
        )
        if "FULL_RUNTIME_OK" not in json.dumps(read_result, ensure_ascii=False):
            raise RuntimeError("Full Sandbox MCP read did not preserve written content")


def _assert_exec(container: Container, command: list[str], description: str) -> str:
    result = container.exec_run(command)
    raw_output = cast("bytes | str", result.output)
    output = (
        raw_output.decode("utf-8", errors="replace")
        if isinstance(raw_output, bytes)
        else raw_output
    )
    if result.exit_code != 0:
        raise RuntimeError(f"Full Sandbox {description} check failed: {output[-500:]}")
    return output


def _run_container(
    client: DockerClient,
    *,
    image: str,
    name: str,
    network: Network,
    workspace: Path,
    token: str,
    full_services: bool,
    ports: Mapping[str, tuple[str, int]] | None = None,
) -> Container:
    return client.containers.run(
        image=image,
        name=name,
        hostname=name,
        detach=True,
        network=network.name,
        extra_hosts={name: "127.0.0.1"},
        environment={
            "SANDBOX_ID": name,
            "MCP_AUTH_ENABLED": "true",
            "MCP_ALLOW_LOCALHOST": "false",
            "MCP_STATIC_TOKEN": token,
            "MCP_WORKSPACE": "/workspace",
            "DESKTOP_ENABLED": str(full_services).lower(),
            "TERMINAL_ENABLED": str(full_services).lower(),
        },
        labels={
            "memstack.full-runtime": "true",
            "memstack.sandbox": "true",
            "memstack.sandbox.network": "true",
        },
        ports=dict(ports or {}),
        volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
        mem_limit="4g",
        nano_cpus=2_000_000_000,
    )


def _wait_attacker(container: Container) -> None:
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        result = container.exec_run(
            ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8765), 1)"]
        )
        if result.exit_code == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("Full Sandbox isolation probe container did not become ready")


def _cross_network_probe_commands(
    *,
    victim_ip: str,
    attacker_token: str,
) -> list[list[str]]:
    http_probe = "\n".join(
        [
            "import base64",
            "import http.client",
            "import ssl",
            "import sys",
            "host, port, scheme, token = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]",
            "headers = {}",
            "if token:",
            "    credential = base64.b64encode(f'sandbox:{token}'.encode()).decode()",
            "    headers['Authorization'] = f'Basic {credential}'",
            "if scheme == 'https':",
            "    connection = http.client.HTTPSConnection(",
            "        host, port, timeout=5, context=ssl._create_unverified_context()",
            "    )",
            "else:",
            "    connection = http.client.HTTPConnection(host, port, timeout=5)",
            "connection.request('GET', '/', headers=headers)",
            "response = connection.getresponse()",
            "raise SystemExit(0 if response.status in {401, 403} else 1)",
        ]
    )
    websocket_probe = "\n".join(
        [
            "import base64",
            "import os",
            "import socket",
            "import struct",
            "import sys",
            "host, port, token = sys.argv[1], int(sys.argv[2]), sys.argv[3]",
            "key = base64.b64encode(os.urandom(16)).decode()",
            "headers = [",
            "    'GET / HTTP/1.1',",
            "    f'Host: {host}:{port}',",
            "    'Connection: Upgrade',",
            "    'Upgrade: websocket',",
            "    'Sec-WebSocket-Version: 13',",
            "    f'Sec-WebSocket-Key: {key}',",
            "]",
            "if token:",
            "    headers.append(f'Authorization: Bearer {token}')",
            "request = ('\\r\\n'.join([*headers, '', ''])).encode()",
            "connection = socket.create_connection((host, port), timeout=5)",
            "connection.sendall(request)",
            "response = b''",
            "while b'\\r\\n\\r\\n' not in response:",
            "    response += connection.recv(4096)",
            "response_headers, frame = response.split(b'\\r\\n\\r\\n', 1)",
            "if b' 101 ' not in response_headers.split(b'\\r\\n', 1)[0]:",
            "    raise SystemExit(2)",
            "while len(frame) < 2:",
            "    frame += connection.recv(4096)",
            "opcode, payload_length = frame[0] & 0x0F, frame[1] & 0x7F",
            "offset = 2",
            "if payload_length == 126:",
            "    while len(frame) < 4:",
            "        frame += connection.recv(4096)",
            "    payload_length, offset = struct.unpack('!H', frame[2:4])[0], 4",
            "elif payload_length == 127:",
            "    while len(frame) < 10:",
            "        frame += connection.recv(4096)",
            "    payload_length, offset = struct.unpack('!Q', frame[2:10])[0], 10",
            "while len(frame) < offset + payload_length:",
            "    frame += connection.recv(4096)",
            "payload = frame[offset:offset + payload_length]",
            "close_code = struct.unpack('!H', payload[:2])[0] if len(payload) >= 2 else 0",
            "raise SystemExit(0 if opcode == 8 and close_code == 4001 else 1)",
        ]
    )
    commands = [
        ["python", "-c", websocket_probe, victim_ip, "8765", ""],
        [
            "python",
            "-c",
            websocket_probe,
            victim_ip,
            "8765",
            attacker_token,
        ],
    ]
    for port, scheme in ((6080, "https"), (7681, "http")):
        commands.extend(
            [
                ["python", "-c", http_probe, victim_ip, str(port), scheme, ""],
                [
                    "python",
                    "-c",
                    http_probe,
                    victim_ip,
                    str(port),
                    scheme,
                    attacker_token,
                ],
            ]
        )
    return commands


def _assert_cross_network_authentication(
    attacker: Container,
    victim: Container,
    network_name: str,
    attacker_token: str,
) -> None:
    victim.reload()
    network_settings = _require_mapping(victim.attrs.get("NetworkSettings"), "network settings")
    networks = _require_mapping(network_settings.get("Networks"), "attached networks")
    victim_network = _require_mapping(networks.get(network_name), "victim network")
    victim_ip = victim_network.get("IPAddress")
    if not isinstance(victim_ip, str) or not victim_ip:
        raise RuntimeError("Full Sandbox victim did not receive an isolated network address")

    for probe_index, command in enumerate(
        _cross_network_probe_commands(
            victim_ip=victim_ip,
            attacker_token=attacker_token,
        ),
        start=1,
    ):
        result = attacker.exec_run(command)
        if result.exit_code != 0:
            raw_output = cast("bytes | str", result.output)
            output = (
                raw_output.decode("utf-8", errors="replace")
                if isinstance(raw_output, bytes)
                else raw_output
            )
            raise RuntimeError(
                "Full Sandbox cross-network authentication probe failed "
                f"at check {probe_index}: {output[-500:]}"
            )


def _remove_container(container: Container | None) -> None:
    if container is not None:
        with contextlib.suppress(Exception):
            container.remove(force=True)


def _remove_network(network: Network | None) -> None:
    if network is not None:
        with contextlib.suppress(Exception):
            network.remove()


def _create_workspace_root() -> tuple[Path, Path, Path]:
    workspace_root = Path(tempfile.mkdtemp(prefix="memstack-full-runtime-"))
    workspace_root.chmod(stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    victim_workspace = workspace_root / "victim"
    attacker_workspace = workspace_root / "attacker"
    victim_workspace.mkdir(mode=0o777)
    attacker_workspace.mkdir(mode=0o777)
    return workspace_root, victim_workspace, attacker_workspace


def _runtime_probe_command() -> list[str]:
    required_commands = "python node java go rustc cargo bun firefox playwright ttyd Xvnc"
    probe = "\n".join(
        [
            "set -eu",
            '[ "$(id -u)" != 0 ] || { echo "runtime user is root"; exit 1; }',
            f"for command in {required_commands}; do",
            '  command -v "$command" >/dev/null || { '
            + 'echo "missing command: $command"; exit 1; }',
            "done",
            '[ -x "$CHROME_BIN" ] || { echo "Chrome binary is not executable"; exit 1; }',
            'pgrep -x ttyd >/dev/null || { echo "ttyd process is not running"; exit 1; }',
            "pgrep -x Xvnc >/dev/null || { " + 'echo "Xvnc process is not running"; exit 1; }',
        ]
    )
    return ["bash", "-lc", probe]


def _verify_interactive_services(desktop_url: str, terminal_url: str, token: str) -> None:
    _ = _wait_http(
        desktop_url,
        verify_tls=False,
        headers=_basic_auth_headers(token),
    )
    _ = _wait_http(terminal_url, headers=_basic_auth_headers(token))
    _verify_http_service_auth(desktop_url, token, verify_tls=False)
    _verify_http_service_auth(terminal_url, token, verify_tls=True)


def verify_full_runtime(image: str = DEFAULT_IMAGE) -> None:
    """Launch two sandboxes and prove services, auth, restart, and tenant isolation."""
    client = _DOCKER_MODULE.from_env()
    suffix = uuid.uuid4().hex[:10]
    victim_name = f"memstack-full-victim-{suffix}"
    attacker_name = f"memstack-full-attacker-{suffix}"
    victim_network_name = f"memstack-full-runtime-victim-{suffix}"
    attacker_network_name = f"memstack-full-runtime-attacker-{suffix}"
    workspace_root, victim_workspace, attacker_workspace = _create_workspace_root()
    victim_network: Network | None = None
    attacker_network: Network | None = None
    victim: Container | None = None
    attacker: Container | None = None
    token = secrets.token_urlsafe(32)
    attacker_token = secrets.token_urlsafe(32)

    ports = {f"{port}/tcp": ("127.0.0.1", _reserve_port()) for port in INTERNAL_PORTS}
    try:
        victim_network = _create_isolated_network(client, victim_network_name)
        attacker_network = _create_isolated_network(client, attacker_network_name)
        victim = _run_container(
            client,
            image=image,
            name=victim_name,
            network=victim_network,
            workspace=victim_workspace,
            token=token,
            full_services=True,
            ports=ports,
        )
        mcp_url, desktop_url, terminal_url = _runtime_service_urls(ports)
        health = _wait_http(f"{mcp_url.replace('ws://', 'http://')}health")
        if '"auth_enabled": true' not in health:
            raise RuntimeError("Full Sandbox health endpoint did not confirm authentication")
        _verify_interactive_services(desktop_url, terminal_url, token)

        victim.reload()
        verify_runtime_metadata(
            cast("Mapping[str, object]", victim.attrs),
            expected_image=image,
            expected_network=victim_network_name,
        )
        runtime = _assert_exec(
            victim,
            _runtime_probe_command(),
            "runtime process",
        )
        if runtime.strip():
            raise RuntimeError("Full Sandbox runtime process check returned unexpected output")
        asyncio.run(_verify_mcp(mcp_url, token))

        attacker = _run_container(
            client,
            image=image,
            name=attacker_name,
            network=attacker_network,
            workspace=attacker_workspace,
            token=attacker_token,
            full_services=False,
        )
        _wait_attacker(attacker)
        _assert_cross_network_authentication(
            attacker,
            victim,
            victim_network_name,
            attacker_token,
        )

        victim.restart(timeout=10)
        _ = _wait_http(f"{mcp_url.replace('ws://', 'http://')}health")
        _verify_interactive_services(desktop_url, terminal_url, token)
        asyncio.run(_verify_mcp(mcp_url, token))
        logs = victim.logs(tail=500).decode("utf-8", errors="replace")
        if token in logs:
            raise RuntimeError("Full Sandbox capability leaked into container logs")
    finally:
        _remove_container(attacker)
        _remove_container(victim)
        _remove_network(attacker_network)
        _remove_network(victim_network)
        shutil.rmtree(workspace_root, ignore_errors=True)


if __name__ == "__main__":
    verify_full_runtime(os.getenv("SANDBOX_FULL_IMAGE", DEFAULT_IMAGE))
    print("Complete Sandbox runtime, authentication, restart, and isolation verified")
