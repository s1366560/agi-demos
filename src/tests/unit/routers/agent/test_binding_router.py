"""Tests for generation-owned AgentBinding HTTP routes."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.domain.model.agent.agent_binding import AgentBinding
from src.infrastructure.adapters.primary.web.agent_binding_http_application_authority_v2 import (
    AgentBindingHttpApplicationAuthorityV2,
)
from src.infrastructure.adapters.primary.web.routers.agent import binding_router
from src.infrastructure.plugins.v2.agent_binding_services import (
    AgentBindingAgentUnavailableV2,
    AgentBindingMatchV2,
    AgentBindingNotFoundV2,
    AgentBindingScopeMismatchV2,
)

pytestmark = pytest.mark.unit


class FailingBindingService:
    async def create(self, _binding: AgentBinding) -> AgentBinding:
        raise RuntimeError("internal binding create secret")

    async def list_bindings(self, **_kwargs: Any) -> list[AgentBinding]:
        raise RuntimeError("internal binding list secret")

    async def delete(self, _binding_id: str) -> bool:
        raise RuntimeError("internal binding delete secret")

    async def set_enabled(self, _binding_id: str, *, enabled: bool) -> AgentBinding:
        del enabled
        raise RuntimeError("internal binding update secret")

    async def list_group(self, _group_id: str) -> list[AgentBinding]:
        raise RuntimeError("internal binding group secret")

    async def resolve_with_trace(self, **_kwargs: Any) -> AgentBindingMatchV2:
        raise RuntimeError("internal binding match secret")


def _authority(
    service: object,
    *,
    tenant_id: str = "tenant-1",
) -> AgentBindingHttpApplicationAuthorityV2:
    return AgentBindingHttpApplicationAuthorityV2(
        operation=cast(Any, SimpleNamespace()),
        db=cast(Any, SimpleNamespace(commit=AsyncMock())),
        tenant_id=tenant_id,
        service=cast(Any, service),
    )


def _patch_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binding_router, "require_tenant_access", AsyncMock())


def _route_calls(
    service: object,
    *,
    current_user: object,
) -> dict[str, Any]:
    authority = _authority(service)
    return {
        "create": lambda: binding_router.create_binding(
            body=binding_router.CreateBindingRequest(agent_id="agent-1", channel_type="slack"),
            current_user=cast(Any, current_user),
            binding_authority=authority,
        ),
        "list": lambda: binding_router.list_bindings(
            agent_id=None,
            enabled_only=False,
            current_user=cast(Any, current_user),
            binding_authority=authority,
        ),
        "delete": lambda: binding_router.delete_binding(
            binding_id="binding-1",
            current_user=cast(Any, current_user),
            binding_authority=authority,
        ),
        "enabled": lambda: binding_router.set_binding_enabled(
            binding_id="binding-1",
            body=binding_router.SetEnabledRequest(enabled=False),
            current_user=cast(Any, current_user),
            binding_authority=authority,
        ),
        "group": lambda: binding_router.list_group_bindings(
            group_id="group-1",
            current_user=cast(Any, current_user),
            binding_authority=authority,
        ),
        "test": lambda: binding_router.test_binding_match(
            body=binding_router.TestBindingRequest(channel_type="slack"),
            current_user=cast(Any, current_user),
            binding_authority=authority,
        ),
    }


async def test_selected_binding_tenant_defaults_to_authenticated_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_access = AsyncMock()
    monkeypatch.setattr(binding_router, "require_tenant_access", require_access)

    tenant_id = await binding_router._get_selected_binding_tenant_id(
        selected_tenant_id=None,
        fallback_tenant_id="tenant-default",
        current_user=cast(Any, SimpleNamespace(id="user-1")),
        db=cast(Any, SimpleNamespace()),
    )

    assert tenant_id == "tenant-default"
    require_access.assert_not_awaited()


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
        current_user=cast(Any, current_user),
        db=cast(Any, db),
    )

    assert tenant_id == "tenant-selected"
    require_access.assert_awaited_once_with(db, current_user, "tenant-selected")


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
    _patch_access(monkeypatch)
    calls = _route_calls(FailingBindingService(), current_user=SimpleNamespace(id="user-1"))

    with pytest.raises(HTTPException) as exc_info:
        await calls[route_name]()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == expected_detail
    assert "internal" not in exc_info.value.detail


async def test_create_binding_commits_service_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_access(monkeypatch)
    service = SimpleNamespace(create=AsyncMock(side_effect=lambda binding: binding))
    authority = _authority(service)

    result = await binding_router.create_binding(
        body=binding_router.CreateBindingRequest(agent_id="agent-1", channel_type="slack"),
        current_user=cast(Any, SimpleNamespace(id="user-1")),
        binding_authority=authority,
    )

    assert result["agent_id"] == "agent-1"
    created = service.create.await_args.args[0]
    assert created.tenant_id == "tenant-1"
    authority.db.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("invalid binding"),
        AgentBindingAgentUnavailableV2("agent-1"),
        AgentBindingScopeMismatchV2("binding-1"),
    ],
)
async def test_create_binding_sanitizes_invalid_service_input(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    _patch_access(monkeypatch)
    authority = _authority(SimpleNamespace(create=AsyncMock(side_effect=failure)))

    with pytest.raises(HTTPException) as exc_info:
        await binding_router.create_binding(
            body=binding_router.CreateBindingRequest(agent_id="agent-1"),
            current_user=cast(Any, SimpleNamespace(id="user-1")),
            binding_authority=authority,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid binding request"
    authority.db.commit.assert_not_awaited()


async def test_list_and_group_routes_use_tenant_scoped_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_access(monkeypatch)
    binding = AgentBinding(id="binding-1", tenant_id="tenant-1", agent_id="agent-1")
    service = SimpleNamespace(
        list_bindings=AsyncMock(return_value=[binding]),
        list_group=AsyncMock(return_value=[binding]),
    )
    authority = _authority(service)

    listed = await binding_router.list_bindings(
        agent_id="agent-1",
        enabled_only=True,
        current_user=cast(Any, SimpleNamespace(id="user-1")),
        binding_authority=authority,
    )
    grouped = await binding_router.list_group_bindings(
        group_id="group-1",
        current_user=cast(Any, SimpleNamespace(id="user-1")),
        binding_authority=authority,
    )

    assert [item["id"] for item in listed] == ["binding-1"]
    assert [item["id"] for item in grouped] == ["binding-1"]
    service.list_bindings.assert_awaited_once_with(agent_id="agent-1", enabled_only=True)
    service.list_group.assert_awaited_once_with("group-1")


@pytest.mark.parametrize("route_name", ["list", "group", "test"])
async def test_binding_read_routes_require_tenant_access(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
) -> None:
    monkeypatch.setattr(
        binding_router,
        "require_tenant_access",
        AsyncMock(side_effect=HTTPException(status_code=403, detail="Tenant access required")),
    )
    calls = _route_calls(SimpleNamespace(), current_user=SimpleNamespace(id="user-1"))

    with pytest.raises(HTTPException) as exc_info:
        await calls[route_name]()

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Tenant access required"


@pytest.mark.parametrize("route_name", ["create", "delete", "enabled"])
async def test_binding_mutation_routes_require_admin(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
) -> None:
    require_access = AsyncMock(
        side_effect=HTTPException(status_code=403, detail="Admin access required")
    )
    monkeypatch.setattr(binding_router, "require_tenant_access", require_access)
    calls = _route_calls(SimpleNamespace(), current_user=SimpleNamespace(id="user-1"))

    with pytest.raises(HTTPException) as exc_info:
        await calls[route_name]()

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin access required"
    assert require_access.await_args.kwargs["require_admin"] is True


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_detail"),
    [
        (AgentBindingNotFoundV2("binding-1"), 404, "Binding not found"),
        (AgentBindingScopeMismatchV2("binding-1"), 403, "Access denied"),
    ],
)
async def test_binding_mutations_map_service_scope_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    _patch_access(monkeypatch)
    service = SimpleNamespace(
        delete=AsyncMock(side_effect=failure),
        set_enabled=AsyncMock(side_effect=failure),
    )
    current_user = cast(Any, SimpleNamespace(id="user-1"))
    for route in (binding_router.delete_binding, binding_router.set_binding_enabled):
        authority = _authority(service)
        kwargs: dict[str, Any] = {
            "binding_id": "binding-1",
            "current_user": current_user,
            "binding_authority": authority,
        }
        if route is binding_router.set_binding_enabled:
            kwargs["body"] = binding_router.SetEnabledRequest(enabled=False)
        with pytest.raises(HTTPException) as exc_info:
            await route(**kwargs)
        assert exc_info.value.status_code == expected_status
        assert exc_info.value.detail == expected_detail
        authority.db.commit.assert_not_awaited()


async def test_binding_match_projects_service_trace_and_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_access(monkeypatch)
    binding = AgentBinding(
        id="binding-1",
        tenant_id="tenant-1",
        agent_id="agent-1",
        channel_type="slack",
        channel_id="channel-1",
    )
    trace = {
        "binding_id": "binding-1",
        "agent_id": "agent-1",
        "specificity_score": binding.specificity_score,
        "channel_type": "slack",
        "channel_id": "channel-1",
        "account_id": None,
        "peer_id": None,
        "priority": 0,
        "eliminated": False,
        "elimination_reason": None,
        "selected": True,
    }
    service = SimpleNamespace(
        resolve_with_trace=AsyncMock(
            return_value=AgentBindingMatchV2(
                binding=binding,
                agent_name="Agent One",
                trace=(trace,),
            )
        )
    )

    response = await binding_router.test_binding_match(
        body=binding_router.TestBindingRequest(
            channel_type="slack",
            channel_id="channel-1",
        ),
        current_user=cast(Any, SimpleNamespace(id="user-1")),
        binding_authority=_authority(service),
    )

    assert response.matched is True
    assert response.agent_name == "Agent One"
    assert response.binding_id == "binding-1"
    assert response.confidence > 0
    assert response.trace[0].selected is True


def test_binding_routes_have_no_static_repository_or_registry_authority() -> None:
    source = inspect.getsource(binding_router)

    assert "get_container_with_db" not in source
    assert ".agent_binding_repository()" not in source
    assert ".agent_registry()" not in source
