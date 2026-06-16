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


class BindingContainer:
    def __init__(self, repo: object, agent: object | None) -> None:
        self.repo = repo
        self.agent_registry_stub = SimpleNamespace(get_by_id=AsyncMock(return_value=agent))

    def agent_binding_repository(self) -> object:
        return self.repo

    def agent_registry(self) -> object:
        return self.agent_registry_stub


def _patch_container(monkeypatch: pytest.MonkeyPatch, container: object) -> None:
    monkeypatch.setattr(binding_router, "get_container_with_db", lambda _request, _db: container)


def _patch_admin_access(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allow_admin_access(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(binding_router, "require_tenant_access", _allow_admin_access)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_selected_binding_tenant_defaults_to_authenticated_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_access = AsyncMock()
    monkeypatch.setattr(binding_router, "require_tenant_access", require_access)

    tenant_id = await binding_router._get_selected_binding_tenant_id(
        selected_tenant_id=None,
        fallback_tenant_id="tenant-default",
        current_user=SimpleNamespace(id="user-1"),
        db=SimpleNamespace(),
    )

    assert tenant_id == "tenant-default"
    require_access.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_selected_binding_tenant_validates_explicit_tenant_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_access = AsyncMock()
    monkeypatch.setattr(binding_router, "require_tenant_access", require_access)
    db = SimpleNamespace()
    current_user = SimpleNamespace(id="user-1")

    tenant_id = await binding_router._get_selected_binding_tenant_id(
        selected_tenant_id="tenant-selected",
        fallback_tenant_id="tenant-default",
        current_user=current_user,
        db=db,
    )

    assert tenant_id == "tenant-selected"
    require_access.assert_awaited_once_with(db, current_user, "tenant-selected")


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
    _patch_admin_access(monkeypatch)
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
    _patch_admin_access(monkeypatch)
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
async def test_list_bindings_by_agent_filters_current_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MixedTenantBindingRepository:
        async def list_by_agent(self, **_kwargs: Any) -> list[AgentBinding]:
            return [
                AgentBinding(id="binding-1", tenant_id="tenant-1", agent_id="agent-1"),
                AgentBinding(id="binding-2", tenant_id="tenant-2", agent_id="agent-1"),
            ]

    _patch_admin_access(monkeypatch)
    _patch_container(
        monkeypatch,
        SimpleNamespace(agent_binding_repository=lambda: MixedTenantBindingRepository()),
    )

    response = await binding_router.list_bindings(
        request=SimpleNamespace(),
        agent_id="agent-1",
        enabled_only=False,
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=SimpleNamespace(),
    )

    assert [binding["id"] for binding in response] == ["binding-1"]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("route_name", ["list", "group", "test"])
async def test_binding_read_routes_require_tenant_access(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
) -> None:
    async def _deny_tenant_access(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=403, detail="Tenant access required")

    monkeypatch.setattr(binding_router, "require_tenant_access", _deny_tenant_access)
    request = SimpleNamespace()
    current_user = SimpleNamespace(id="user-1")
    db = SimpleNamespace()

    route_calls: dict[str, Any] = {
        "list": lambda: binding_router.list_bindings(
            request=request,
            agent_id=None,
            enabled_only=False,
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

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Tenant access required"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_binding_accepts_tenant_level_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_admin_access(monkeypatch)
    repo = SimpleNamespace(create=AsyncMock(side_effect=lambda binding: binding))
    container = BindingContainer(repo, SimpleNamespace(id="agent-1", project_id=None))
    _patch_container(monkeypatch, container)
    db = SimpleNamespace(commit=AsyncMock())

    result = await binding_router.create_binding(
        body=binding_router.CreateBindingRequest(agent_id="agent-1", channel_type="slack"),
        request=SimpleNamespace(),
        current_user=SimpleNamespace(id="user-1"),
        tenant_id="tenant-1",
        db=db,
    )

    assert result["agent_id"] == "agent-1"
    container.agent_registry_stub.get_by_id.assert_awaited_once_with(
        "agent-1",
        tenant_id="tenant-1",
    )
    repo.create.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent",
    [
        None,
        SimpleNamespace(id="agent-1", project_id="project-1"),
    ],
)
async def test_create_binding_rejects_unavailable_or_project_scoped_agent(
    monkeypatch: pytest.MonkeyPatch,
    agent: object | None,
) -> None:
    _patch_admin_access(monkeypatch)
    repo = SimpleNamespace(create=AsyncMock())
    container = BindingContainer(repo, agent)
    _patch_container(monkeypatch, container)
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await binding_router.create_binding(
            body=binding_router.CreateBindingRequest(agent_id="agent-1", channel_type="slack"),
            request=SimpleNamespace(),
            current_user=SimpleNamespace(id="user-1"),
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid binding request"
    repo.create.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_binding_enabled_value_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_admin_access(monkeypatch)
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


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("route_name", ["create", "delete", "enabled"])
async def test_binding_mutation_routes_require_admin(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
) -> None:
    async def _deny_admin_access(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=403, detail="Admin access required")

    monkeypatch.setattr(binding_router, "require_tenant_access", _deny_admin_access)
    request = SimpleNamespace()
    current_user = SimpleNamespace(id="user-1")
    db = SimpleNamespace(commit=AsyncMock())

    route_calls: dict[str, Any] = {
        "create": lambda: binding_router.create_binding(
            body=binding_router.CreateBindingRequest(agent_id="agent-1", channel_type="slack"),
            request=request,
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
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin access required"
    db.commit.assert_not_called()
