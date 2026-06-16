"""Unit tests for agent definition router A2A normalization."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.domain.model.agent.agent_definition import Agent, AgentModel
from src.domain.model.agent.tool_policy import ToolPolicyPrecedence
from src.domain.model.agent.workspace_config import WorkspaceConfig
from src.infrastructure.adapters.primary.web.routers.agent.definitions_router import (
    CreateDefinitionBody,
    SetEnabledBody,
    UpdateDefinitionBody,
    create_definition,
    delete_definition,
    get_definition,
    list_definitions,
    set_definition_enabled,
    update_definition,
)


def _make_registry() -> MagicMock:
    registry = MagicMock()
    registry.create = AsyncMock(side_effect=lambda agent: agent)
    registry.get_by_id = AsyncMock()
    registry.update = AsyncMock(side_effect=lambda agent: agent)
    registry.delete = AsyncMock(return_value=True)
    registry.set_enabled = AsyncMock(side_effect=lambda _agent_id, _enabled: _make_agent())
    return registry


def _make_container(registry: MagicMock) -> SimpleNamespace:
    orchestrator = MagicMock()
    orchestrator.create_agent = AsyncMock(side_effect=lambda agent: agent)
    return SimpleNamespace(
        agent_registry=lambda: registry,
        agent_orchestrator=lambda: orchestrator,
    )


def _make_db(
    *,
    project_member: bool = True,
    accessible_project_ids: list[str] | None = None,
) -> MagicMock:
    accessible_ids = accessible_project_ids
    if accessible_ids is None:
        accessible_ids = ["proj-1"] if project_member else []
    db = MagicMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(
            scalar_one_or_none=lambda: "membership" if project_member else None,
            scalars=lambda: SimpleNamespace(all=lambda: accessible_ids),
        )
    )
    return db


def _make_agent(**overrides: object) -> Agent:
    agent = Agent.create(
        tenant_id="tenant-1",
        project_id="proj-1",
        name="worker-agent",
        display_name="Worker Agent",
        system_prompt="Work carefully.",
    )
    agent.id = "agent-1"
    for key, value in overrides.items():
        setattr(agent, key, value)
    return agent


@pytest.mark.unit
class TestDefinitionsRouterA2AConfig:
    @pytest.mark.asyncio
    async def test_create_definition_requires_admin_access(self):
        db = _make_db()
        body = CreateDefinitionBody(
            name="worker-agent",
            display_name="Worker Agent",
            system_prompt="Work carefully.",
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(
                    side_effect=HTTPException(status_code=403, detail="Admin access required")
                ),
            ),
            pytest.raises(HTTPException, match="Admin access required"),
        ):
            await create_definition(
                body,
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

    @pytest.mark.asyncio
    async def test_create_definition_requires_project_access_for_project_scope(self):
        db = _make_db(project_member=False)
        container = _make_container(_make_registry())
        body = CreateDefinitionBody(
            name="worker-agent",
            display_name="Worker Agent",
            system_prompt="Work carefully.",
            project_id="proj-1",
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ) as get_container,
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await create_definition(
                body,
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"
        get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_definitions_requires_project_access_for_project_filter(self):
        db = _make_db(project_member=False)
        container = _make_container(_make_registry())

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ) as get_container,
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await list_definitions(
                request=MagicMock(),
                project_id="proj-1",
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"
        get_container.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_definitions_filters_project_scoped_agents_by_project_access(self):
        db = _make_db(accessible_project_ids=["proj-1"])
        registry = _make_registry()
        registry.list_by_tenant = AsyncMock(
            return_value=[
                _make_agent(id="tenant-agent", project_id=None, name="tenant-agent"),
                _make_agent(id="visible-agent", project_id="proj-1", name="visible-agent"),
                _make_agent(id="hidden-agent", project_id="proj-2", name="hidden-agent"),
            ]
        )
        container = _make_container(registry)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await list_definitions(
                request=MagicMock(),
                project_id=None,
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        assert [agent["id"] for agent in response] == ["tenant-agent", "visible-agent"]
        registry.list_by_tenant.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("route_name", ["get", "update", "delete", "enabled"])
    async def test_raw_definition_routes_require_existing_project_access(
        self,
        route_name: str,
    ) -> None:
        db = _make_db(project_member=False)
        registry = _make_registry()
        registry.get_by_id = AsyncMock(return_value=_make_agent(project_id="proj-1"))
        container = _make_container(registry)
        current_user = SimpleNamespace(id="user-1")

        route_calls = {
            "get": lambda: get_definition(
                "agent-1",
                request=MagicMock(),
                current_user=current_user,
                tenant_id="tenant-1",
                db=db,
            ),
            "update": lambda: update_definition(
                "agent-1",
                UpdateDefinitionBody(display_name="Updated Worker Agent"),
                request=MagicMock(),
                current_user=current_user,
                tenant_id="tenant-1",
                db=db,
            ),
            "delete": lambda: delete_definition(
                "agent-1",
                request=MagicMock(),
                current_user=current_user,
                tenant_id="tenant-1",
                db=db,
            ),
            "enabled": lambda: set_definition_enabled(
                "agent-1",
                SetEnabledBody(enabled=True),
                request=MagicMock(),
                current_user=current_user,
                tenant_id="tenant-1",
                db=db,
            ),
        }

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await route_calls[route_name]()

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"
        registry.update.assert_not_awaited()
        registry.delete.assert_not_awaited()
        registry.set_enabled.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_definition_enabling_a2a_without_allowlist_uses_builtin_default_sender(self):
        registry = _make_registry()
        container = _make_container(registry)
        db = _make_db()
        body = CreateDefinitionBody(
            name="worker-agent",
            display_name="Worker Agent",
            system_prompt="Work carefully.",
            project_id="proj-1",
            agent_to_agent_enabled=True,
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await create_definition(
                body,
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        created_agent = container.agent_orchestrator().create_agent.await_args.args[0]
        assert created_agent.agent_to_agent_allowlist == ["builtin:sisyphus", "sisyphus"]
        assert response["agent_to_agent_allowlist"] == ["builtin:sisyphus", "sisyphus"]

    @pytest.mark.asyncio
    async def test_create_definition_explicit_empty_a2a_allowlist_preserves_deny_all(self):
        registry = _make_registry()
        container = _make_container(registry)
        db = _make_db()
        body = CreateDefinitionBody(
            name="worker-agent",
            display_name="Worker Agent",
            system_prompt="Work carefully.",
            project_id="proj-1",
            agent_to_agent_enabled=True,
            agent_to_agent_allowlist=[],
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await create_definition(
                body,
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        created_agent = container.agent_orchestrator().create_agent.await_args.args[0]
        assert created_agent.agent_to_agent_allowlist == []
        assert response["agent_to_agent_allowlist"] == []

    @pytest.mark.asyncio
    async def test_create_definition_normalizes_explicit_a2a_allowlist_entries(self):
        registry = _make_registry()
        container = _make_container(registry)
        db = _make_db()
        body = CreateDefinitionBody(
            name="worker-agent",
            display_name="Worker Agent",
            system_prompt="Work carefully.",
            project_id="proj-1",
            agent_to_agent_enabled=True,
            agent_to_agent_allowlist=[" sender-1 ", "", "sender-1", "sender-2 "],
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await create_definition(
                body,
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        created_agent = container.agent_orchestrator().create_agent.await_args.args[0]
        assert created_agent.agent_to_agent_allowlist == ["sender-1", "sender-2"]
        assert response["agent_to_agent_allowlist"] == ["sender-1", "sender-2"]

    @pytest.mark.asyncio
    async def test_create_definition_accepts_structured_spawn_and_tool_policy(self):
        registry = _make_registry()
        container = _make_container(registry)
        db = _make_db()
        body = CreateDefinitionBody(
            name="worker-agent",
            display_name="Worker Agent",
            system_prompt="Work carefully.",
            project_id="proj-1",
            spawn_policy={
                "max_depth": 1,
                "max_active_runs": 4,
                "max_children_per_requester": 2,
                "allowed_subagents": ["coder", "reviewer"],
            },
            tool_policy={
                "allow": ["read", "grep"],
                "deny": ["bash"],
                "precedence": "allow_first",
            },
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await create_definition(
                body,
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        created_agent = container.agent_orchestrator().create_agent.await_args.args[0]
        assert created_agent.spawn_policy.max_depth == 1
        assert created_agent.spawn_policy.max_active_runs == 4
        assert created_agent.spawn_policy.max_children_per_requester == 2
        assert created_agent.spawn_policy.allowed_subagents == frozenset({"coder", "reviewer"})
        assert created_agent.tool_policy.allow == ("read", "grep")
        assert created_agent.tool_policy.deny == ("bash",)
        assert created_agent.tool_policy.precedence == ToolPolicyPrecedence.ALLOW_FIRST
        assert response["spawn_policy"]["max_depth"] == 1
        assert response["tool_policy"]["deny"] == ["bash"]

    @pytest.mark.asyncio
    async def test_create_definition_duplicate_name_returns_conflict(self):
        registry = _make_registry()
        container = _make_container(registry)
        container.agent_orchestrator().create_agent = AsyncMock(
            side_effect=ValueError("Agent with name 'worker-agent' already exists (id=agent-1)")
        )
        db = _make_db()
        body = CreateDefinitionBody(
            name="worker-agent",
            display_name="Worker Agent",
            system_prompt="Work carefully.",
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await create_definition(
                body,
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "Definition already exists"
        assert "agent-1" not in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_create_definition_integrity_errors_are_sanitized(self):
        registry = _make_registry()
        container = _make_container(registry)
        container.agent_orchestrator().create_agent = AsyncMock(
            side_effect=IntegrityError("secret statement", "secret params", Exception("secret"))
        )
        db = _make_db()
        body = CreateDefinitionBody(
            name="secret-agent",
            display_name="Worker Agent",
            system_prompt="Work carefully.",
        )

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await create_definition(
                body,
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "Definition already exists"
        assert "secret-agent" not in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_update_definition_requires_project_access_when_moving_to_project(self):
        db = _make_db(project_member=False)
        registry = _make_registry()
        registry.get_by_id = AsyncMock(return_value=_make_agent(project_id=None))
        container = _make_container(registry)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=container,
            ) as get_container,
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await update_definition(
                "agent-1",
                UpdateDefinitionBody(project_id="proj-1"),
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access denied"
        get_container.assert_not_called()
        registry.get_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_definition_enabling_a2a_without_allowlist_uses_builtin_default_sender(self):
        registry = _make_registry()
        db = _make_db()
        existing = _make_agent(agent_to_agent_enabled=False, agent_to_agent_allowlist=None)
        registry.get_by_id = AsyncMock(return_value=existing)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=_make_container(registry),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await update_definition(
                "agent-1",
                UpdateDefinitionBody(agent_to_agent_enabled=True),
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        updated_agent = registry.update.await_args.args[0]
        assert updated_agent.agent_to_agent_allowlist == ["builtin:sisyphus", "sisyphus"]
        assert response["agent_to_agent_allowlist"] == ["builtin:sisyphus", "sisyphus"]

    @pytest.mark.asyncio
    async def test_update_definition_unrelated_change_preserves_legacy_open_policy(self):
        registry = _make_registry()
        db = _make_db()
        existing = _make_agent(agent_to_agent_enabled=True, agent_to_agent_allowlist=None)
        registry.get_by_id = AsyncMock(return_value=existing)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=_make_container(registry),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await update_definition(
                "agent-1",
                UpdateDefinitionBody(display_name="Updated Worker Agent"),
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        updated_agent = registry.update.await_args.args[0]
        assert updated_agent.agent_to_agent_allowlist is None
        assert response["agent_to_agent_allowlist"] is None

    @pytest.mark.asyncio
    async def test_update_definition_idempotent_enabled_flag_preserves_legacy_open_policy(self):
        registry = _make_registry()
        db = _make_db()
        existing = _make_agent(agent_to_agent_enabled=True, agent_to_agent_allowlist=None)
        registry.get_by_id = AsyncMock(return_value=existing)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=_make_container(registry),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await update_definition(
                "agent-1",
                UpdateDefinitionBody(agent_to_agent_enabled=True),
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        updated_agent = registry.update.await_args.args[0]
        assert updated_agent.agent_to_agent_allowlist is None
        assert response["agent_to_agent_allowlist"] is None

    @pytest.mark.asyncio
    async def test_update_definition_revalidates_reserved_names(self):
        registry = _make_registry()
        db = _make_db()
        existing = _make_agent()
        registry.get_by_id = AsyncMock(return_value=existing)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=_make_container(registry),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await update_definition(
                "agent-1",
                UpdateDefinitionBody(name="__system__"),
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid definition request"

    @pytest.mark.asyncio
    async def test_update_definition_coerces_model_and_workspace_defaults(self):
        registry = _make_registry()
        db = _make_db()
        existing = _make_agent()
        registry.get_by_id = AsyncMock(return_value=existing)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=_make_container(registry),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await update_definition(
                "agent-1",
                UpdateDefinitionBody(model="inherit", workspace_config=None),
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        updated_agent = registry.update.await_args.args[0]
        assert updated_agent.model == AgentModel.INHERIT
        assert isinstance(updated_agent.workspace_config, WorkspaceConfig)
        assert response["model"] == AgentModel.INHERIT.value

    @pytest.mark.asyncio
    async def test_update_definition_accepts_structured_spawn_and_tool_policy(self):
        registry = _make_registry()
        db = _make_db()
        existing = _make_agent()
        registry.get_by_id = AsyncMock(return_value=existing)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=_make_container(registry),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
        ):
            response = await update_definition(
                "agent-1",
                UpdateDefinitionBody(
                    spawn_policy={
                        "max_depth": 0,
                        "max_active_runs": 3,
                        "max_children_per_requester": 1,
                        "allowed_subagents": ["planner"],
                    },
                    tool_policy={
                        "allow": ["read"],
                        "deny": ["bash"],
                        "precedence": "deny_first",
                    },
                ),
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        updated_agent = registry.update.await_args.args[0]
        assert updated_agent.spawn_policy.max_depth == 0
        assert updated_agent.spawn_policy.max_active_runs == 3
        assert updated_agent.spawn_policy.max_children_per_requester == 1
        assert updated_agent.spawn_policy.allowed_subagents == frozenset({"planner"})
        assert updated_agent.tool_policy.allow == ("read",)
        assert updated_agent.tool_policy.deny == ("bash",)
        assert updated_agent.tool_policy.precedence == ToolPolicyPrecedence.DENY_FIRST
        assert response["spawn_policy"]["allowed_subagents"] == ["planner"]
        assert response["tool_policy"]["precedence"] == "deny_first"

    @pytest.mark.asyncio
    async def test_set_definition_enabled_value_errors_are_sanitized(self):
        registry = _make_registry()
        db = _make_db()
        existing = _make_agent()
        registry.get_by_id = AsyncMock(return_value=existing)
        registry.set_enabled = AsyncMock(side_effect=ValueError("secret definition state"))

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.get_container_with_db",
                return_value=_make_container(registry),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.definitions_router.require_tenant_access",
                AsyncMock(),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await set_definition_enabled(
                "agent-1",
                SetEnabledBody(enabled=True),
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid definition request"
        assert "secret" not in exc_info.value.detail
