from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from src.infrastructure.agent.plugins.loader import AgentPluginLoader
from src.infrastructure.agent.plugins.registry import (
    AgentPluginRegistry,
    PluginToolBuildContext,
)

PLUGIN_DIR = Path(".memstack/plugins/docker-compose").resolve()


@pytest.fixture(autouse=True)
def _clear_docker_compose_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "MEMSTACK_DOCKER_COMPOSE_BIN",
        "MEMSTACK_DOCKER_COMPOSE_DOCKER_HOST",
        "MEMSTACK_DOCKER_COMPOSE_CONTEXT",
        "MEMSTACK_DOCKER_COMPOSE_CLIENT_WORKDIR",
        "MEMSTACK_DOCKER_COMPOSE_HOST_WORKDIR",
        "MEMSTACK_DOCKER_COMPOSE_DAEMON_WORKDIR",
        "MEMSTACK_DOCKER_COMPOSE_PATH_MAPPINGS",
        "MEMSTACK_DOCKER_COMPOSE_ALLOW_HOST_SOCKET_FROM_SANDBOX",
        "MEMSTACK_DOCKER_COMPOSE_TIMEOUT_SECONDS",
        "MEMSTACK_DOCKER_COMPOSE_ALLOWED_ROOTS",
        "MEMSTACK_DOCKER_COMPOSE_ALLOWED_CLIENT_ROOTS",
        "MEMSTACK_DOCKER_COMPOSE_OUTPUT_LIMIT_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)


def _load_plugin_module(file_name: str, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN_DIR / file_name)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _tool_context() -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docker_compose_plugin_registers_tool_factory() -> None:
    registry = AgentPluginRegistry()
    plugin_module = _load_plugin_module("plugin.py", "test_docker_compose_plugin_entry")

    diagnostics = await AgentPluginLoader(registry=registry).load_plugins([plugin_module.plugin])
    tools, build_diagnostics = await registry.build_tools(
        PluginToolBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            base_tools={},
        )
    )

    assert diagnostics == []
    assert not any(item.level == "error" for item in build_diagnostics)
    assert set(tools) == {"docker_compose"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docker_compose_plugin_applies_tenant_config_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AgentPluginRegistry()
    plugin_module = _load_plugin_module("plugin.py", "test_docker_compose_plugin_config")

    async def load_config(_context: object) -> dict[str, object]:
        return {
            "docker_host": "tcp://remote-docker.example:2376",
            "client_workdir": str(tmp_path),
            "daemon_workdir": "/srv/remote/project",
            "allowed_project_roots": [str(tmp_path)],
            "allowed_client_roots": [str(tmp_path)],
            "default_timeout_seconds": 77,
        }

    monkeypatch.setattr(plugin_module, "_load_tenant_config", load_config)
    diagnostics = await AgentPluginLoader(registry=registry).load_plugins([plugin_module.plugin])
    tools, build_diagnostics = await registry.build_tools(
        PluginToolBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            base_tools={},
        )
    )

    result = await tools["docker_compose"].execute(
        _tool_context(),
        compose_args=["ps"],
        workdir=str(tmp_path),
        dry_run=True,
    )

    payload = json.loads(result.output)
    assert diagnostics == []
    assert not any(item.level == "error" for item in build_diagnostics)
    assert result.is_error is False
    assert payload["docker_host"] == "tcp://remote-docker.example:2376"
    assert payload["client_workdir"] == str(tmp_path)
    assert payload["daemon_workdir"] == "/srv/remote/project"


@pytest.mark.unit
def test_docker_compose_plugin_schema_exposes_remote_daemon_path_settings() -> None:
    plugin_module = _load_plugin_module("plugin.py", "test_docker_compose_plugin_schema")

    properties = plugin_module.DOCKER_COMPOSE_CONFIG_SCHEMA["properties"]

    assert "client_workdir" in properties
    assert "daemon_workdir" in properties
    assert "allowed_client_roots" in properties
    assert "path_mappings" in properties
    assert "output_limit_chars" in properties


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docker_compose_dry_run_builds_full_compose_command(tmp_path: Path) -> None:
    tools_module = _load_plugin_module("tools.py", "test_docker_compose_tools_dry_run")
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    result = await tools_module.docker_compose_tool.execute(
        _tool_context(),
        compose_args=["up", "-d", "--build"],
        workdir=str(tmp_path),
        compose_files=["compose.yml"],
        project_name="demo",
        profiles=["web"],
        docker_host="tcp://docker:2375",
        dry_run=True,
    )

    payload = json.loads(result.output)
    assert result.is_error is False
    assert payload["command"] == [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "-p",
        "demo",
        "--profile",
        "web",
        "up",
        "-d",
        "--build",
    ]
    assert payload["docker_host"] == "tcp://docker:2375"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docker_compose_blocks_container_host_socket_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools_module = _load_plugin_module("tools.py", "test_docker_compose_tools_guard")
    monkeypatch.setattr(tools_module, "_inside_container", lambda: True)

    result = await tools_module.docker_compose_tool.execute(
        _tool_context(),
        compose_args=["ps"],
        workdir=str(tmp_path),
        docker_host="unix:///var/run/docker.sock",
        dry_run=True,
    )

    payload = json.loads(result.output)
    assert result.is_error is True
    assert payload["code"] == "RuntimeError"
    assert "Refusing to run docker compose" in payload["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docker_compose_allows_configured_remote_context_in_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools_module = _load_plugin_module("tools.py", "test_docker_compose_tools_context")
    monkeypatch.setattr(tools_module, "_inside_container", lambda: True)

    result = await tools_module.docker_compose_tool.execute(
        _tool_context(),
        compose_args=["ps"],
        workdir=str(tmp_path),
        docker_context="sandbox-sidecar",
        dry_run=True,
    )

    payload = json.loads(result.output)
    assert result.is_error is False
    assert payload["command"] == ["docker", "--context", "sandbox-sidecar", "compose", "ps"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docker_compose_allows_remote_docker_host_in_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools_module = _load_plugin_module("tools.py", "test_docker_compose_tools_remote_host")
    monkeypatch.setattr(tools_module, "_inside_container", lambda: True)

    result = await tools_module.docker_compose_tool.execute(
        _tool_context(),
        compose_args=["ps"],
        workdir=str(tmp_path),
        docker_host="ssh://deploy@example.com",
        dry_run=True,
    )

    payload = json.loads(result.output)
    assert result.is_error is False
    assert payload["docker_host"] == "ssh://deploy@example.com"
    assert payload["command"] == ["docker", "compose", "ps"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docker_compose_rewrites_bind_mount_sources_for_host_daemon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools_module = _load_plugin_module("tools.py", "test_docker_compose_tools_rewrite")
    docker_script = tmp_path / "docker"
    compose_model = {
        "services": {
            "app": {
                "image": "docker:cli",
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(tmp_path / "data"),
                        "target": "/data",
                    }
                ],
            }
        }
    }
    docker_script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"model = {json.dumps(compose_model)!r}\n"
        "args = sys.argv[1:]\n"
        "if args[-2:] == ['config', '--format'] or args[-2:] == ['--format', 'json']:\n"
        "    print(json.dumps(json.loads(model)))\n"
        "elif 'up' in args:\n"
        "    compose_file = pathlib.Path(args[args.index('-f') + 1])\n"
        "    payload = json.loads(compose_file.read_text())\n"
        "    print(json.dumps(payload['services']['app']['volumes'][0]))\n"
        "else:\n"
        "    print(json.dumps({'args': args}))\n",
        encoding="utf-8",
    )
    docker_script.chmod(0o755)
    monkeypatch.setenv("MEMSTACK_DOCKER_COMPOSE_BIN", str(docker_script))

    result = await tools_module.docker_compose_tool.execute(
        _tool_context(),
        compose_args=["up"],
        workdir=str(tmp_path),
        host_workdir="/host/project",
        container_workdir=str(tmp_path),
    )

    payload = json.loads(result.output)
    stdout_payload = json.loads(payload["stdout"])
    assert result.is_error is False
    assert payload["rewritten_bind_mounts"] == 1
    assert stdout_payload["source"] == "/host/project/data"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docker_compose_maps_sandbox_client_and_remote_daemon_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools_module = _load_plugin_module("tools.py", "test_docker_compose_tools_remote_paths")
    docker_script = tmp_path / "docker"
    compose_model = {
        "services": {
            "app": {
                "image": "docker:cli",
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/workspace/data",
                        "target": "/data",
                    }
                ],
            }
        }
    }
    docker_script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"model = {json.dumps(compose_model)!r}\n"
        "args = sys.argv[1:]\n"
        "if args[-2:] == ['--format', 'json']:\n"
        "    print(json.dumps(json.loads(model)))\n"
        "elif 'up' in args:\n"
        "    compose_file = pathlib.Path(args[args.index('-f') + 1])\n"
        "    payload = json.loads(compose_file.read_text())\n"
        "    print(json.dumps({'cwd': str(pathlib.Path.cwd()), 'volume': payload['services']['app']['volumes'][0]}))\n"
        "else:\n"
        "    print(json.dumps({'args': args, 'cwd': str(pathlib.Path.cwd())}))\n",
        encoding="utf-8",
    )
    docker_script.chmod(0o755)
    monkeypatch.setenv("MEMSTACK_DOCKER_COMPOSE_BIN", str(docker_script))

    result = await tools_module.docker_compose_tool.execute(
        _tool_context(),
        compose_args=["up"],
        workdir="/workspace",
        client_workdir=str(tmp_path),
        daemon_workdir="/srv/remote/project",
        container_workdir="/workspace",
        docker_host="tcp://remote-docker.example:2376",
    )

    payload = json.loads(result.output)
    stdout_payload = json.loads(payload["stdout"])
    assert result.is_error is False
    assert payload["cwd"] == str(tmp_path)
    assert payload["requested_workdir"] == "/workspace"
    assert payload["client_workdir"] == str(tmp_path)
    assert payload["daemon_workdir"] == "/srv/remote/project"
    assert payload["docker_host"] == "tcp://remote-docker.example:2376"
    assert payload["rewritten_bind_mounts"] == 1
    assert stdout_payload["cwd"] == str(tmp_path)
    assert stdout_payload["volume"]["source"] == "/srv/remote/project/data"
