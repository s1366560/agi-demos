"""Docker Compose tools provided by the local Docker Compose plugin."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.context import ToolContext

DOCKER_COMPOSE_TOOL_NAME = "docker_compose"

_DEFAULT_TIMEOUT_SECONDS = 600
_DEFAULT_OUTPUT_LIMIT = 40000
_HOST_SOCKET = "/var/run/docker.sock"

DOCKER_COMPOSE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "compose_args": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "Arguments after 'docker compose', for example "
                "['up', '-d', '--build'], ['ps', '--format', 'json'], or ['logs', '--tail', '100']."
            ),
        },
        "workdir": {
            "type": "string",
            "description": (
                "Agent or sandbox-facing compose project directory. Defaults to the current "
                "process cwd when client_workdir is not supplied."
            ),
        },
        "client_workdir": {
            "type": "string",
            "description": (
                "Directory on the machine running this plugin where compose files are readable. "
                "Use this when the agent/sandbox path differs from the API/plugin host path."
            ),
        },
        "compose_files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional compose file paths passed as repeated -f flags.",
        },
        "project_name": {"type": "string", "description": "Optional compose project name."},
        "profiles": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional compose profiles passed as repeated --profile flags.",
        },
        "env": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Additional environment variables for this compose invocation.",
        },
        "docker_host": {
            "type": "string",
            "description": "Optional DOCKER_HOST override such as tcp://docker:2375.",
        },
        "docker_context": {
            "type": "string",
            "description": "Optional Docker context name passed with --context.",
        },
        "docker_bin": {
            "type": "string",
            "description": "Optional Docker CLI executable or argv prefix. Defaults to docker.",
        },
        "host_workdir": {
            "type": "string",
            "description": (
                "Deprecated alias for daemon_workdir. Path on the Docker daemon machine "
                "corresponding to container_workdir."
            ),
        },
        "daemon_workdir": {
            "type": "string",
            "description": (
                "Project path on the Docker daemon machine. Required for bind mounts when "
                "the Docker daemon runs on a different host than the sandbox/API plugin."
            ),
        },
        "container_workdir": {
            "type": "string",
            "description": (
                "Sandbox/container path prefix to rewrite to daemon_workdir. Defaults to workdir."
            ),
        },
        "path_mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "container_path": {"type": "string"},
                    "daemon_path": {"type": "string"},
                },
                "required": ["container_path", "daemon_path"],
            },
            "description": (
                "Additional container/sandbox path to Docker-daemon-machine path mappings for "
                "bind mount rewrite. Applied before daemon_workdir fallback."
            ),
        },
        "rewrite_bind_mount_paths": {
            "type": "boolean",
            "description": (
                "Rewrite compose bind-mount sources from container paths to host paths before "
                "executing against a host or remote Docker daemon. Defaults to true when "
                "daemon_workdir, host_workdir, or path_mappings is set."
            ),
        },
        "timeout_seconds": {
            "type": "integer",
            "minimum": 1,
            "description": "Command timeout in seconds.",
        },
        "allowed_project_roots": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Allowed agent/sandbox-facing workdir roots for this invocation.",
        },
        "allowed_client_roots": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Allowed plugin-client workdir roots for this invocation.",
        },
        "output_limit_chars": {
            "type": "integer",
            "minimum": 1,
            "description": "Maximum stdout/stderr characters returned in the tool result.",
        },
        "allow_host_socket_from_sandbox": {
            "type": "boolean",
            "default": False,
            "description": (
                "Explicitly allow using a Unix Docker socket while running inside a container. "
                "Default false prevents sandbox containers from accidentally driving the host daemon."
            ),
        },
        "dry_run": {
            "type": "boolean",
            "default": False,
            "description": "Return the resolved command and environment summary without executing.",
        },
    },
    "required": ["compose_args"],
}


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _read_bool_env(name: str, *, default: bool = False) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, *, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


def _read_string_list_env(name: str) -> list[str]:
    raw_value = os.environ.get(name, "")
    return [item for item in raw_value.split(os.pathsep) if item]


def _inside_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    if os.environ.get("MEMSTACK_SANDBOX_ID") or os.environ.get("SANDBOX_ID"):
        return True
    if any(key in os.environ for key in ("container", "CONTAINER")):
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "kubepods", "containerd"))


def _resolve_path(value: str | None, *, default: str | None = None) -> Path:
    raw_path = Path(value or default or os.getcwd()).expanduser()
    return raw_path.resolve()


def _path_is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _path_mappings_from_items(items: list[dict[str, str]] | None) -> list[tuple[Path, Path]]:
    mappings: list[tuple[Path, Path]] = []
    for item in items or []:
        container_path = item.get("container_path")
        daemon_path = item.get("daemon_path")
        if not container_path or not daemon_path:
            raise ValueError("path_mappings entries require container_path and daemon_path")
        mappings.append(
            (
                Path(container_path).expanduser().resolve(),
                Path(daemon_path).expanduser().resolve(),
            )
        )
    return mappings


def _map_path_from_container(path: Path, mappings: list[tuple[Path, Path]]) -> Path | None:
    for container_root, daemon_root in mappings:
        if _path_is_under(path, container_root):
            return daemon_root / path.relative_to(container_root)
    return None


def _resolve_existing_dir(value: str | None, *, label: str, default: str | None = None) -> Path:
    resolved = _resolve_path(value, default=default)
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"{label} must be an existing directory: {resolved}")
    return resolved


def _enforce_allowed_roots(
    workdir: Path,
    *,
    allowed_roots: list[str] | None = None,
    env_name: str = "MEMSTACK_DOCKER_COMPOSE_ALLOWED_ROOTS",
) -> None:
    raw_roots = allowed_roots if allowed_roots is not None else _read_string_list_env(env_name)
    resolved_roots = [Path(item).expanduser().resolve() for item in raw_roots if item]
    if not resolved_roots:
        return
    if any(workdir == root or root in workdir.parents for root in resolved_roots):
        return
    roots = ", ".join(str(root) for root in resolved_roots)
    raise ValueError(f"workdir is outside allowed Docker Compose roots from {env_name}: {roots}")


def _resolve_workdirs(
    *,
    workdir: str | None,
    client_workdir: str | None,
    path_mappings: list[dict[str, str]] | None,
    allowed_project_roots: list[str] | None,
    allowed_client_roots: list[str] | None,
) -> tuple[Path, Path]:
    requested_workdir = _resolve_path(workdir)
    client_mapping_candidates = _path_mappings_from_items(
        path_mappings if path_mappings is not None else _read_path_mappings_env()
    )
    raw_client_workdir = client_workdir or os.environ.get("MEMSTACK_DOCKER_COMPOSE_CLIENT_WORKDIR")
    if raw_client_workdir:
        resolved_client = _resolve_existing_dir(
            raw_client_workdir,
            label="client_workdir",
        )
    else:
        resolved_client = _resolve_path(str(requested_workdir))
        if not resolved_client.exists() or not resolved_client.is_dir():
            mapped_client = _map_path_from_container(requested_workdir, client_mapping_candidates)
            if mapped_client is None or not mapped_client.exists() or not mapped_client.is_dir():
                raise ValueError(f"client_workdir must be an existing directory: {resolved_client}")
            resolved_client = mapped_client
    _enforce_allowed_roots(
        requested_workdir,
        allowed_roots=allowed_project_roots,
    )
    _enforce_allowed_roots(
        resolved_client,
        allowed_roots=allowed_client_roots,
        env_name="MEMSTACK_DOCKER_COMPOSE_ALLOWED_CLIENT_ROOTS",
    )
    return requested_workdir, resolved_client


def _resolve_compose_files(
    workdir: Path,
    compose_files: list[str] | None,
    *,
    path_mappings: list[tuple[Path, Path]],
) -> list[str]:
    resolved: list[str] = []
    for item in compose_files or []:
        file_path = Path(item).expanduser()
        if not file_path.is_absolute():
            file_path = workdir / file_path
        final_path = file_path.resolve()
        if not final_path.exists() or not final_path.is_file():
            mapped_file = _map_path_from_container(final_path, path_mappings)
            if mapped_file is not None:
                final_path = mapped_file.resolve()
        if not final_path.exists() or not final_path.is_file():
            raise ValueError(f"compose file must exist: {final_path}")
        resolved.append(str(final_path))
    return resolved


def _is_unix_socket_host(docker_host: str | None, docker_context: str | None) -> bool:
    if docker_context:
        return False
    if docker_host:
        return docker_host.startswith("unix://") or docker_host == _HOST_SOCKET
    return Path(_HOST_SOCKET).exists()


def _guard_docker_runtime(
    *,
    docker_host: str | None,
    docker_context: str | None,
    allow_host_socket_from_sandbox: bool,
) -> None:
    if allow_host_socket_from_sandbox:
        return
    if not _inside_container():
        return
    if not _is_unix_socket_host(docker_host, docker_context):
        return
    raise RuntimeError(
        "Refusing to run docker compose from a container against a Unix Docker socket. "
        "Configure docker_host to a sandbox-local Docker daemon such as tcp://docker:2375, "
        "set docker_context to a safe remote context, or pass allow_host_socket_from_sandbox=true "
        "only when host-daemon DNS/path behavior is intended."
    )


def _build_environment(
    *,
    env: dict[str, str] | None,
    docker_host: str | None,
    docker_context: str | None,
) -> dict[str, str]:
    merged = dict(os.environ)
    if docker_host:
        merged["DOCKER_HOST"] = docker_host
    if docker_context:
        merged["DOCKER_CONTEXT"] = docker_context
        merged.pop("DOCKER_HOST", None)
    for key, value in (env or {}).items():
        if isinstance(key, str) and isinstance(value, str):
            merged[key] = value
    return merged


def _build_command(
    *,
    compose_args: list[str],
    compose_files: list[str],
    project_name: str | None,
    profiles: list[str] | None,
    docker_context: str | None,
    docker_bin: str | None,
) -> list[str]:
    resolved_docker_bin = (
        docker_bin or os.environ.get("MEMSTACK_DOCKER_COMPOSE_BIN", "docker")
    ).strip() or "docker"
    command = [*shlex.split(resolved_docker_bin)]
    if docker_context:
        command.extend(["--context", docker_context])
    command.append("compose")
    for compose_file in compose_files:
        command.extend(["-f", compose_file])
    if project_name:
        command.extend(["-p", project_name])
    for profile in profiles or []:
        command.extend(["--profile", profile])
    command.extend(str(item) for item in compose_args)
    return command


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... <truncated {len(value) - limit} chars>"


def _rewrite_bind_sources(value: object, *, path_mappings: list[tuple[Path, Path]]) -> int:
    rewrites = 0
    if isinstance(value, dict):
        if value.get("type") == "bind" and isinstance(value.get("source"), str):
            source = Path(value["source"]).resolve()
            for container_root, daemon_root in path_mappings:
                if _path_is_under(source, container_root):
                    relative = source.relative_to(container_root)
                    value["source"] = str(daemon_root / relative)
                    rewrites += 1
                    break
        for child in value.values():
            rewrites += _rewrite_bind_sources(child, path_mappings=path_mappings)
    elif isinstance(value, list):
        for child in value:
            rewrites += _rewrite_bind_sources(child, path_mappings=path_mappings)
    return rewrites


def _read_path_mappings_env() -> list[dict[str, str]]:
    raw_value = os.environ.get("MEMSTACK_DOCKER_COMPOSE_PATH_MAPPINGS")
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError("MEMSTACK_DOCKER_COMPOSE_PATH_MAPPINGS must be JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError("MEMSTACK_DOCKER_COMPOSE_PATH_MAPPINGS must be a JSON array")
    mappings: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("Each Docker Compose path mapping must be an object")
        container_path = item.get("container_path")
        daemon_path = item.get("daemon_path")
        if not isinstance(container_path, str) or not isinstance(daemon_path, str):
            raise ValueError(
                "Each Docker Compose path mapping needs container_path and daemon_path"
            )
        mappings.append({"container_path": container_path, "daemon_path": daemon_path})
    return mappings


def _resolve_path_mappings(
    *,
    path_mappings: list[dict[str, str]] | None,
    daemon_workdir: str | None,
    host_workdir: str | None,
    container_workdir: str | None,
    requested_workdir: Path,
) -> list[tuple[Path, Path]]:
    raw_mappings = path_mappings if path_mappings is not None else _read_path_mappings_env()
    resolved = _path_mappings_from_items(raw_mappings)

    resolved_daemon_workdir = (
        daemon_workdir
        or os.environ.get("MEMSTACK_DOCKER_COMPOSE_DAEMON_WORKDIR")
        or host_workdir
        or os.environ.get("MEMSTACK_DOCKER_COMPOSE_HOST_WORKDIR")
    )
    if resolved_daemon_workdir:
        container_root = Path(container_workdir or str(requested_workdir)).expanduser().resolve()
        daemon_root = Path(resolved_daemon_workdir).expanduser().resolve()
        if not any(container_root == existing for existing, _daemon in resolved):
            resolved.append((container_root, daemon_root))
    return resolved


async def _prepare_daemon_compose_file(
    *,
    config_command: list[str],
    client_workdir: Path,
    execution_env: dict[str, str],
    timeout: int,
    path_mappings: list[tuple[Path, Path]],
    rewrite_bind_mount_paths: bool | None,
) -> tuple[str | None, int]:
    if not path_mappings:
        return None, 0
    should_rewrite = True if rewrite_bind_mount_paths is None else rewrite_bind_mount_paths
    if not should_rewrite:
        return None, 0

    process = await asyncio.create_subprocess_exec(
        *config_command,
        cwd=str(client_workdir),
        env=execution_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
    if process.returncode != 0:
        stderr = stderr_bytes.decode(errors="replace")
        raise RuntimeError(f"docker compose config failed before path rewrite: {stderr}")

    compose_model = json.loads(stdout_bytes.decode(errors="replace"))
    rewrite_count = _rewrite_bind_sources(compose_model, path_mappings=path_mappings)
    if rewrite_count <= 0:
        return None, 0

    fd, rewritten_path = tempfile.mkstemp(prefix="memstack-compose-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(compose_model, handle, ensure_ascii=False)
    except Exception:
        with contextlib.suppress(OSError):
            os.close(fd)
        raise
    return rewritten_path, rewrite_count


@tool_define(
    name=DOCKER_COMPOSE_TOOL_NAME,
    description=(
        "Run any Docker Compose operation through a configured Docker CLI environment. "
        "Use compose_args for the full docker compose subcommand surface. The tool blocks "
        "container-to-host Unix socket usage by default to avoid sandbox DNS/path mismatches."
    ),
    parameters=DOCKER_COMPOSE_PARAMETERS,
    permission=None,
    category="docker",
    tags=frozenset({"docker", "compose", "plugin"}),
)
async def docker_compose_tool(  # noqa: PLR0913
    ctx: ToolContext,
    *,
    compose_args: list[str],
    workdir: str | None = None,
    client_workdir: str | None = None,
    compose_files: list[str] | None = None,
    project_name: str | None = None,
    profiles: list[str] | None = None,
    env: dict[str, str] | None = None,
    docker_host: str | None = None,
    docker_context: str | None = None,
    docker_bin: str | None = None,
    host_workdir: str | None = None,
    daemon_workdir: str | None = None,
    container_workdir: str | None = None,
    path_mappings: list[dict[str, str]] | None = None,
    rewrite_bind_mount_paths: bool | None = None,
    timeout_seconds: int | None = None,
    allowed_project_roots: list[str] | None = None,
    allowed_client_roots: list[str] | None = None,
    output_limit_chars: int | None = None,
    allow_host_socket_from_sandbox: bool | None = None,
    dry_run: bool = False,
) -> ToolResult:
    """Run a Docker Compose command with environment isolation guards."""
    _ = ctx
    try:
        if not compose_args or not all(isinstance(item, str) and item for item in compose_args):
            raise ValueError("compose_args must be a non-empty list of strings")

        requested_workdir, resolved_client_workdir = _resolve_workdirs(
            workdir=workdir,
            client_workdir=client_workdir,
            path_mappings=path_mappings,
            allowed_project_roots=allowed_project_roots,
            allowed_client_roots=allowed_client_roots,
        )
        resolved_path_mappings = _resolve_path_mappings(
            path_mappings=path_mappings,
            daemon_workdir=daemon_workdir,
            host_workdir=host_workdir,
            container_workdir=container_workdir,
            requested_workdir=requested_workdir,
        )
        resolved_files = _resolve_compose_files(
            resolved_client_workdir,
            compose_files,
            path_mappings=resolved_path_mappings,
        )
        resolved_host = docker_host or os.environ.get("MEMSTACK_DOCKER_COMPOSE_DOCKER_HOST")
        resolved_context = docker_context or os.environ.get("MEMSTACK_DOCKER_COMPOSE_CONTEXT")
        allow_host_socket = (
            bool(allow_host_socket_from_sandbox)
            if allow_host_socket_from_sandbox is not None
            else _read_bool_env(
                "MEMSTACK_DOCKER_COMPOSE_ALLOW_HOST_SOCKET_FROM_SANDBOX",
                default=False,
            )
        )
        _guard_docker_runtime(
            docker_host=resolved_host,
            docker_context=resolved_context,
            allow_host_socket_from_sandbox=allow_host_socket,
        )

        command = _build_command(
            compose_args=compose_args,
            compose_files=resolved_files,
            project_name=project_name,
            profiles=profiles,
            docker_context=resolved_context,
            docker_bin=docker_bin,
        )
        execution_env = _build_environment(
            env=env,
            docker_host=resolved_host,
            docker_context=resolved_context,
        )
        timeout = timeout_seconds or _read_int_env(
            "MEMSTACK_DOCKER_COMPOSE_TIMEOUT_SECONDS",
            default=_DEFAULT_TIMEOUT_SECONDS,
        )
        payload: dict[str, Any] = {
            "ok": True,
            "command": command,
            "cwd": str(resolved_client_workdir),
            "requested_workdir": str(requested_workdir),
            "client_workdir": str(resolved_client_workdir),
            "docker_host": resolved_host,
            "docker_context": resolved_context,
            "inside_container": _inside_container(),
            "dry_run": dry_run,
            "host_workdir": host_workdir or os.environ.get("MEMSTACK_DOCKER_COMPOSE_HOST_WORKDIR"),
            "daemon_workdir": daemon_workdir
            or os.environ.get("MEMSTACK_DOCKER_COMPOSE_DAEMON_WORKDIR")
            or host_workdir
            or os.environ.get("MEMSTACK_DOCKER_COMPOSE_HOST_WORKDIR"),
            "container_workdir": container_workdir or str(requested_workdir),
            "path_mappings": [
                {"container_path": str(container), "daemon_path": str(daemon)}
                for container, daemon in resolved_path_mappings
            ],
        }
        if dry_run:
            return ToolResult(
                output=_json(payload), title="Docker Compose dry run", metadata=payload
            )

        rewritten_compose_file: str | None = None
        rewritten_bind_mounts = 0
        try:
            rewritten_compose_file, rewritten_bind_mounts = await _prepare_daemon_compose_file(
                config_command=[
                    *command[: -len(compose_args)],
                    "config",
                    "--format",
                    "json",
                ],
                client_workdir=resolved_client_workdir,
                execution_env=execution_env,
                timeout=timeout,
                path_mappings=resolved_path_mappings,
                rewrite_bind_mount_paths=rewrite_bind_mount_paths,
            )
            if rewritten_compose_file:
                command = _build_command(
                    compose_args=compose_args,
                    compose_files=[rewritten_compose_file],
                    project_name=project_name,
                    profiles=profiles,
                    docker_context=resolved_context,
                    docker_bin=docker_bin,
                )
                payload["command"] = command
                payload["rewritten_compose_file"] = rewritten_compose_file
                payload["rewritten_bind_mounts"] = rewritten_bind_mounts

            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(resolved_client_workdir),
                env=execution_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        finally:
            if rewritten_compose_file:
                with contextlib.suppress(OSError):
                    os.unlink(rewritten_compose_file)

        output_limit = output_limit_chars or _read_int_env(
            "MEMSTACK_DOCKER_COMPOSE_OUTPUT_LIMIT_CHARS", default=_DEFAULT_OUTPUT_LIMIT
        )
        stdout = _truncate(stdout_bytes.decode(errors="replace"), output_limit)
        stderr = _truncate(stderr_bytes.decode(errors="replace"), output_limit)
        payload.update(
            {
                "returncode": process.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        )
        payload["ok"] = process.returncode == 0
        return ToolResult(
            output=_json(payload),
            title="Docker Compose completed"
            if process.returncode == 0
            else "Docker Compose failed",
            metadata=payload,
            is_error=process.returncode != 0,
        )
    except TimeoutError:
        payload = {"ok": False, "error": "docker compose command timed out"}
        return ToolResult(
            output=_json(payload),
            title="Docker Compose timed out",
            metadata=payload,
            is_error=True,
        )
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "code": exc.__class__.__name__}
        return ToolResult(
            output=_json(payload), title="Docker Compose rejected", metadata=payload, is_error=True
        )


__all__ = [
    "DOCKER_COMPOSE_PARAMETERS",
    "DOCKER_COMPOSE_TOOL_NAME",
    "docker_compose_tool",
]
