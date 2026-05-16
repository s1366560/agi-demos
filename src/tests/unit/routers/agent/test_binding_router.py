"""Tests for agent binding route hardening."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.domain.model.agent.agent_binding import AgentBinding
from src.infrastructure.adapters.primary.web.routers.agent import (
    binding_router,
)


class FailingBindingRepository:
    async def create(self, _binding: AgentBinding) -> AgentBinding:
        raise RuntimeError("internal binding create secret")

    async def list_by_agent(self, **_kwargs: Any) -> list[AgentBinding]:
        raise RuntimeError("internal binding list secret")

    async def list_by_tenant(self, **_kwargs: Any) -> list[AgentBinding]:
        raise RuntimeError("internal binding list secret")

    async def get_by_id(self, _binding_id: str) -> AgentBinding | None:
        raise RuntimeError("internal binding get secret")

    async def find_by_group(self, **_kwargs: Any) -> list[AgentBinding]:
        raise RuntimeError("internal binding group secret")

    async def resolve_binding_with_trace(self, **_kwargs: Any) -> tuple[None, list[dict[str, Any]]]:
        raise RuntimeError("internal binding match secret")


class FailingContainer:
    def agent_binding_repository(self) -> FailingBindingRepository:
        return FailingBindingRepository()

    def agent_registry(self) -> object:
        return object()


class ValueErrorBindingRepository:
    async def get_by_id(self, _binding_id: str) -> AgentBinding:
        return AgentBinding(id="binding-1", tenant_id="tenant-1", agent_id="agent-1")

    async def set_enabled(self, _binding_id: str, _enabled: bool) -> AgentBinding:
        raise ValueError("internal binding update secret")


class ValueErrorContainer:
    def agent_binding_repository(self) -> ValueErrorBindingRepository:
        return ValueErrorBindingRepository()


def _patch_container(monkeypatch: pytest.MonkeyPatch, container: object) -> None:
    monkeypatch.setattr(binding_router, "get_container_with_db", lambda _request, _db: container)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_name", "expected_detail"),
    [
        ("create", "Failed to create binding"),
        ("list", "Failed to list bindings"),
        ("delete", "Failed to delete binding"),
        ("enabled", "Failed to update binding"),
        ("group", "Failed to list group bindings"),
        ("test", "Failed to test binding"),
    ],
)
async def test_binding_routes_sanitize_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
    expected_detail: str,
) -> None:
    _patch_container(monkeypatch, FailingContainer())
    db = SimpleNamespace(commit=AsyncMock())
    request = SimpleNamespace()
    current_user = SimpleNamespace(id="user-1")

    route_calls: dict[str, Any] = {
        "create": lambda: binding_router.create_binding(
            body=binding_router.CreateBindingRequest(agent_id="agent-1", channel_type="slack"),
            request=request,
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "list": lambda: binding_router.list_bindings(
            request=request,
            agent_id=None,
            enabled_only=False,
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "delete": lambda: binding_router.delete_binding(
            binding_id="binding-1",
            request=request,
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "enabled": lambda: binding_router.set_binding_enabled(
            binding_id="binding-1",
            body=binding_router.SetEnabledRequest(enabled=False),
            request=request,
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "group": lambda: binding_router.list_group_bindings(
            group_id="group-1",
            request=request,
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
        "test": lambda: binding_router.test_binding_match(
            body=binding_router.TestBindingRequest(channel_type="slack"),
            request=request,
            current_user=current_user,
            tenant_id="tenant-1",
            db=db,
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == expected_detail
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_binding_value_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_container(
        monkeypatch,
        SimpleNamespace(agent_binding_repository=lambda: object()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await binding_router.create_binding(
            body=binding_router.CreateBindingRequest(agent_id="agent-1", priority=-1),
            request=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid binding request"
    assert "internal" not in exc_info.value.detail
    assert "priority" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_binding_enabled_value_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_container(monkeypatch, ValueErrorContainer())

    with pytest.raises(HTTPException) as exc_info:
        await binding_router.set_binding_enabled(
            binding_id="binding-1",
            body=binding_router.SetEnabledRequest(enabled=False),
            request=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid binding update"
    assert "internal" not in exc_info.value.detail
