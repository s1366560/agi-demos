"""Unit tests for agent definition router A2A normalization."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.domain.model.agent.agent_definition import Agent, AgentModel
from src.domain.model.agent.workspace_config import WorkspaceConfig
from src.infrastructure.adapters.primary.web.routers.agent.definitions_router import (
    CreateDefinitionBody,
    UpdateDefinitionBody,
    create_definition,
    update_definition,
)


def _make_registry() -> MagicMock:
    registry = MagicMock()
    registry.create = AsyncMock(side_effect=lambda agent: agent)
    registry.get_by_id = AsyncMock()
    registry.update = AsyncMock(side_effect=lambda agent: agent)
    return registry


def _make_container(registry: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(agent_registry=lambda: registry)


def _make_db() -> MagicMock:
    db = MagicMock()
    db.commit = AsyncMock()
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
    async def test_create_definition_enabling_a2a_without_allowlist_uses_builtin_default_sender(self):
        registry = _make_registry()
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
                return_value=_make_container(registry),
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

        created_agent = registry.create.await_args.args[0]
        assert created_agent.agent_to_agent_allowlist == ["builtin:sisyphus", "sisyphus"]
        assert response["agent_to_agent_allowlist"] == ["builtin:sisyphus", "sisyphus"]

    @pytest.mark.asyncio
    async def test_create_definition_explicit_empty_a2a_allowlist_preserves_deny_all(self):
        registry = _make_registry()
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
                return_value=_make_container(registry),
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

        created_agent = registry.create.await_args.args[0]
        assert created_agent.agent_to_agent_allowlist == []
        assert response["agent_to_agent_allowlist"] == []

    @pytest.mark.asyncio
    async def test_create_definition_normalizes_explicit_a2a_allowlist_entries(self):
        registry = _make_registry()
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
                return_value=_make_container(registry),
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

        created_agent = registry.create.await_args.args[0]
        assert created_agent.agent_to_agent_allowlist == ["sender-1", "sender-2"]
        assert response["agent_to_agent_allowlist"] == ["sender-1", "sender-2"]

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
            pytest.raises(HTTPException, match="name uses a reserved agent identifier"),
        ):
            await update_definition(
                "agent-1",
                UpdateDefinitionBody(name="__system__"),
                request=MagicMock(),
                current_user=SimpleNamespace(id="user-1"),
                tenant_id="tenant-1",
                db=db,
            )

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
