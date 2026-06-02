"""Unit tests for the local GitHub plugin."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.agent.plugins.discovery import discover_plugins
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry, PluginToolBuildContext
from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi
from src.infrastructure.agent.plugins.state_store import PluginStateStore
from src.infrastructure.agent.tools.result import ToolResult

_REPO_ROOT = Path(__file__).resolve().parents[6]
_PLUGIN_DIR = _REPO_ROOT / ".memstack" / "plugins" / "github"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_github_plugin_manifest_is_discoverable() -> None:
    discovered, diagnostics = discover_plugins(
        state_store=PluginStateStore(base_path=_REPO_ROOT),
        include_builtins=False,
        include_entrypoints=False,
    )

    plugin = next(item for item in discovered if item.name == "github-plugin")
    assert plugin.source == "local"
    assert plugin.kind == "runtime_tool"
    assert plugin.manifest_id == "github-plugin"
    assert plugin.providers == ("github",)
    assert plugin.skills == ("github",)
    assert plugin.contracts == {
        "tools": ("github",),
        "skills": ("github",),
        "commands": ("github",),
        "services": ("github:defaults", "github:secret_paths"),
    }
    assert not [item for item in diagnostics if item.plugin_name == "github"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_github_plugin_registers_configured_tool_factory() -> None:
    plugin_module = _load_module("test_github_plugin_entry", _PLUGIN_DIR / "plugin.py")
    registry = AgentPluginRegistry()

    plugin_module.plugin.setup(PluginRuntimeApi("github-plugin", registry=registry))

    assert registry.list_config_schemas()["github-plugin"].defaults["token_env"] == "GITHUB_TOKEN"
    factories = registry.list_tool_factories()
    assert "github-plugin" in factories

    tools = await factories["github-plugin"](
        PluginToolBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            base_tools={},
            session_factory=None,
        )
    )
    assert set(tools) == {"github"}
    assert tools["github"]._plugin_origin == "github-plugin"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_github_tool_builds_read_request_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools_module = _load_module("test_github_tools_read", _PLUGIN_DIR / "tools.py")
    captured: dict[str, Any] = {}

    def fake_request_json(request: Any, *, timeout_seconds: int) -> tuple[int, Any]:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["method"] = request.get_method()
        captured["timeout_seconds"] = timeout_seconds
        return 200, {"full_name": "octocat/Hello-World"}

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(tools_module, "_request_json", fake_request_json)

    result: ToolResult = await tools_module.github_tool.execute(
        SimpleNamespace(),
        operation="get_repo",
        owner="octocat",
        repo="Hello-World",
        timeout_seconds=7,
    )

    assert result.is_error is False
    assert captured["method"] == "GET"
    assert captured["url"] == "https://api.github.com/repos/octocat/Hello-World"
    assert "Authorization" not in captured["headers"]
    assert captured["timeout_seconds"] == 7
    assert result.metadata["data"] == {"full_name": "octocat/Hello-World"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_github_tool_requires_write_confirmation() -> None:
    tools_module = _load_module("test_github_tools_write_guard", _PLUGIN_DIR / "tools.py")

    result: ToolResult = await tools_module.github_tool.execute(
        SimpleNamespace(),
        operation="create_issue",
        owner="octocat",
        repo="Hello-World",
        title="Bug",
    )

    payload = json.loads(result.output)
    assert result.is_error is True
    assert payload["code"] == "github_write_confirmation_required"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_github_tool_sends_write_request_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    tools_module = _load_module("test_github_tools_write", _PLUGIN_DIR / "tools.py")
    captured: dict[str, Any] = {}

    def fake_request_json(request: Any, *, timeout_seconds: int) -> tuple[int, Any]:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return 201, {"number": 42}

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setattr(tools_module, "_request_json", fake_request_json)

    result: ToolResult = await tools_module.github_tool.execute(
        SimpleNamespace(),
        operation="create_issue",
        owner="octocat",
        repo="Hello-World",
        title="Bug",
        body="Details",
        confirm_write=True,
    )

    assert result.is_error is False
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.github.com/repos/octocat/Hello-World/issues"
    assert captured["headers"]["Authorization"] == "Bearer ghp_secret"
    assert captured["body"] == {"title": "Bug", "body": "Details"}
    assert result.metadata["status"] == 201
