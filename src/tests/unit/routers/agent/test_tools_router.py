"""Tests for agent tools route hardening."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.agent import tools as tools_router
from src.infrastructure.adapters.primary.web.routers.agent.schemas import ToolPolicyDebugRequest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tool_capabilities_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingRuntimeManager:
        ensure_loaded = AsyncMock(side_effect=RuntimeError("internal plugin secret"))

    import src.infrastructure.agent.plugins.manager as plugin_manager

    monkeypatch.setattr(
        plugin_manager,
        "get_plugin_runtime_manager",
        lambda: FailingRuntimeManager(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.get_tool_capabilities(
            current_user=SimpleNamespace(id="user-1", tenant_id="tenant-1")
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get tool capabilities"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_tool_compositions_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCompositionRepository:
        def __init__(self, db: Any) -> None:
            self.db = db

        list_all = AsyncMock(side_effect=RuntimeError("internal composition secret"))

    import src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository as comp_repo

    monkeypatch.setattr(comp_repo, "SqlToolCompositionRepository", FailingCompositionRepository)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.list_tool_compositions(
            request=SimpleNamespace(),
            tools=None,
            limit=100,
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to list tool compositions"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tool_composition_sanitizes_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCompositionRepository:
        def __init__(self, db: Any) -> None:
            self.db = db

        get_by_id = AsyncMock(side_effect=RuntimeError("internal composition secret"))

    import src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository as comp_repo

    monkeypatch.setattr(comp_repo, "SqlToolCompositionRepository", FailingCompositionRepository)

    with pytest.raises(HTTPException) as exc_info:
        await tools_router.get_tool_composition(
            composition_id="composition-1",
            request=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get tool composition"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_debug_tool_policy_sanitizes_invalid_sandbox_scope() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await tools_router.debug_tool_policy(
            body=ToolPolicyDebugRequest(
                tool_names=["bash"],
                sandbox_scope="secret-scope",
            ),
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Invalid sandbox scope"
    assert "secret-scope" not in exc_info.value.detail
