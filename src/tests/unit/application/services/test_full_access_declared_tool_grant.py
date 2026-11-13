"""Explicit full_access grants declared categories and still denies unknown ones."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.application.services.chat_run_tool_permission_v2 import ChatRunToolPermissionV2
from src.infrastructure.agent.canvas.tools import canvas_create
from src.infrastructure.agent.permission.rules import classify_sandbox_tool_permission


def _guard(mode: str) -> ChatRunToolPermissionV2:
    guard = ChatRunToolPermissionV2(
        operation=object(),  # type: ignore[arg-type]
        run_id="run-1",
        identity=("tenant", "project", "conversation", "user"),
        mode=mode,
        sessions=object(),  # type: ignore[arg-type]
    )
    object.__setattr__(guard, "revalidate_current_authority", AsyncMock())
    return guard


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tool_name", "category"),
    [
        ("edit", "edit"),
        ("batch_edit", "edit"),
        ("patch", "patch"),
        ("write", "write"),
        ("bash", "bash"),
        ("run_tests", "bash"),
        ("deps_install", "ask"),
        ("git_log", "read"),
        ("preview_edit", "read"),
        ("unknown_tool", "ask"),
        ("docker_compose", "ask"),
    ],
)
def test_named_sandbox_tools_use_declared_categories(tool_name: str, category: str) -> None:
    assert classify_sandbox_tool_permission(tool_name) == category


@pytest.mark.unit
async def test_full_access_allows_declared_mutation_and_denies_unknown_category() -> None:
    guard = _guard("full_access")

    assert await guard.decision("edit", "edit", {}) == "allow"
    assert await guard.decision("bash", "bash", {}) == "allow"
    assert await guard.decision("ask", "unknown_tool", {}) == "deny"
    assert await guard.decision(None, "ask_clarification", {}) == "deny"


@pytest.mark.unit
async def test_ask_and_automatic_do_not_inherit_full_access() -> None:
    ask = _guard("ask")
    automatic = _guard("automatic")

    assert await ask.decision("edit", "edit", {}) == "ask"
    assert await automatic.decision("edit", "edit", {}) == "deny"
    assert await automatic.decision("workspace_file_write", "write", {}) == "allow"
    assert await ask.decision("read", "read", {}) == "allow"


@pytest.mark.unit
def test_canvas_create_declares_write_permission() -> None:
    assert canvas_create.permission == "write"
