"""Trusted protocol declarations distinguish inspections from side effects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.tools.cron_tool import make_cron_tool
from src.infrastructure.agent.tools.model_availability_tool import list_available_models_tool
from src.infrastructure.agent.tools.permission_metadata_v2 import resolve_tool_permission_v2
from src.infrastructure.agent.tools.sandbox_tool_wrapper import create_sandbox_mcp_tool

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("action", "permission"),
    [
        ("status", "read"),
        ("list", "read"),
        ("runs", "read"),
        ("add", "write"),
        ("update", "write"),
        ("remove", "write"),
        ("run", "system_api"),
        ("read_jobs", None),
        ("LIST", None),
        (None, None),
        ([], None),
    ],
)
def test_cron_generation_bound_metadata_survives_conversion(action, permission):
    tool = make_cron_tool(session_factory=lambda: None)
    definition = convert_tools({tool.name: tool})[0]
    assert resolve_tool_permission_v2(definition, {"action": action}) == permission


@pytest.mark.parametrize(
    ("name", "arguments", "permission"),
    [
        ("ast_parse", {}, "read"),
        ("ast_get_imports", {}, "read"),
        ("ast_find_symbols", {}, "read"),
        ("ast_extract_function", {}, "read"),
        ("list_artifacts", {}, "read"),
        ("export_artifact", {}, "ask"),
        ("batch_export_artifacts", {}, "ask"),
        ("ast_parse_and_execute", {}, "ask"),
        ("deps_install", {}, "ask"),
        ("deps_check", {"package_type": "command"}, "read"),
        ("deps_check", {"package_type": "pip", "venv_path": "/tmp/custom"}, "bash"),
        ("deps_check", {"package_type": "system"}, "bash"),
        ("deps_check", {}, "bash"),
        ("deps_check", {"package_type": "unknown"}, None),
        ("deps_check", {"package_type": []}, None),
    ],
)
def test_sandbox_factory_declares_only_known_protocol_inspections(name, arguments, permission):
    port = SimpleNamespace(call_tool=AsyncMock())
    tool = create_sandbox_mcp_tool("sandbox", name, {"input_schema": {}}, port)
    definition = convert_tools({name: tool})[0]
    assert resolve_tool_permission_v2(definition, arguments) == permission
    port.call_tool.assert_not_called()


def test_list_available_models_is_declared_read():
    assert resolve_tool_permission_v2(list_available_models_tool, {}) == "read"
