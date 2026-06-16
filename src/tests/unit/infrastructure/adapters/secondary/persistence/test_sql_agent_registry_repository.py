"""Unit tests for SqlAgentRegistryRepository built-in agent behavior."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.spawn_policy import SpawnPolicy
from src.domain.model.agent.tool_policy import ToolPolicy, ToolPolicyPrecedence
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentDefinitionModel,
    Project,
    Tenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
    SqlAgentRegistryRepository,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_ALL_ACCESS_ID,
    build_builtin_all_access_agent,
    build_builtin_sisyphus_agent,
    list_builtin_agents,
)


def _build_custom_agent(agent_id: str, name: str, tenant_id: str):
    """Create a mutable custom agent from the builtin template."""
    agent = build_builtin_sisyphus_agent(tenant_id=tenant_id)
    agent.id = agent_id
    agent.name = name
    agent.display_name = name.title()
    agent.source = AgentSource.DATABASE
    return agent


def _make_repo() -> SqlAgentRegistryRepository:
    session = MagicMock()
    session.execute = AsyncMock()
    return SqlAgentRegistryRepository(session)


def _agent_model(
    *,
    agent_id: str,
    tenant_id: str,
    project_id: str | None,
    name: str,
    created_at: datetime | None = None,
) -> AgentDefinitionModel:
    model = AgentDefinitionModel(
        id=agent_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name=name,
        display_name=name.replace("-", " ").title(),
        system_prompt=f"You are {name}.",
        trigger_description=f"{name} trigger",
        allowed_tools=[],
        allowed_skills=[],
        allowed_mcp_servers=[],
        source="database",
        max_iterations=10,
    )
    if created_at is not None:
        model.created_at = created_at
        model.updated_at = created_at
    return model


@pytest.mark.unit
class TestSqlAgentRegistryRepository:
    """Focused tests for built-in ID resolution and pagination behavior."""

    @pytest.mark.asyncio
    async def test_get_by_id_resolves_builtin_for_requested_tenant(self) -> None:
        repo = _make_repo()

        agent = await repo.get_by_id(
            BUILTIN_ALL_ACCESS_ID, tenant_id="tenant-1", project_id="proj-1"
        )

        assert agent is not None
        assert agent.tenant_id == "tenant-1"
        assert agent.project_id == "proj-1"
        assert agent.allowed_tools == ["*"]
        assert agent.allowed_mcp_servers == ["*"]
        assert agent.allowed_skills == []

    def test_all_access_builtin_is_first_listed_default(self) -> None:
        agents = list_builtin_agents(tenant_id="tenant-1", project_id="proj-1")

        assert agents[0].id == BUILTIN_ALL_ACCESS_ID
        assert agents[0].source == AgentSource.BUILTIN
        assert build_builtin_all_access_agent("tenant-1").discoverable is True

    @pytest.mark.asyncio
    async def test_update_rejects_reserved_builtin_name(self) -> None:
        repo = _make_repo()
        agent = _build_custom_agent("custom-agent", "sisyphus", "tenant-1")

        with pytest.raises(ValueError, match="Built-in agents cannot be updated"):
            await repo.update(agent)

    @pytest.mark.asyncio
    async def test_list_by_tenant_includes_builtin_only_on_first_page(self) -> None:
        repo = _make_repo()
        repo._to_domain = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                _build_custom_agent("custom-1", "custom-one", "tenant-1"),
                _build_custom_agent("custom-2", "custom-two", "tenant-1"),
            ]
        )
        builtin_ids = [agent.id for agent in list_builtin_agents(tenant_id="tenant-1")]

        result = MagicMock()
        result.scalars.return_value.all.return_value = ["row-1", "row-2"]
        repo._session.execute.return_value = result

        first_page = await repo.list_by_tenant("tenant-1", limit=2, offset=0)
        database_page = await repo.list_by_tenant("tenant-1", limit=2, offset=len(builtin_ids))

        assert [agent.id for agent in first_page] == builtin_ids[:2]
        assert [agent.id for agent in database_page] == ["custom-1", "custom-2"]

    @pytest.mark.asyncio
    async def test_list_by_project_prefers_builtin_when_legacy_db_name_collides(self) -> None:
        repo = _make_repo()
        repo._to_domain = MagicMock(  # type: ignore[method-assign]
            side_effect=[
                _build_custom_agent("custom-sisyphus", "sisyphus", "tenant-1"),
                _build_custom_agent("custom-1", "custom-one", "tenant-1"),
            ]
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = ["row-1", "row-2"]
        repo._session.execute.return_value = result

        agents = await repo.list_by_project("proj-1", tenant_id="tenant-1")

        builtin_ids = [
            agent.id for agent in list_builtin_agents(tenant_id="tenant-1", project_id="proj-1")
        ]
        assert [agent.id for agent in agents] == [*builtin_ids, "custom-1"]

    @pytest.mark.asyncio
    async def test_count_by_tenant_includes_all_builtin_agents(self) -> None:
        repo = _make_repo()
        result = MagicMock()
        result.scalar.return_value = 2
        repo._session.execute.return_value = result

        count = await repo.count_by_tenant("tenant-1")

        assert count == 2 + len(list_builtin_agents(tenant_id="tenant-1"))

    @pytest.mark.asyncio
    async def test_list_by_tenant_filters_project_scope_before_database_pagination(
        self,
        db_session: AsyncSession,
        test_tenant_db,
        test_project_db,
        test_user,
    ) -> None:
        hidden_project = Project(
            id="hidden-agent-project",
            tenant_id=test_tenant_db.id,
            name="Hidden Agent Project",
            owner_id=test_user.id,
            memory_rules={},
            graph_config={},
        )
        db_session.add(hidden_project)
        await db_session.flush()

        base_time = datetime(2026, 6, 1, tzinfo=UTC)
        db_session.add_all(
            [
                _agent_model(
                    agent_id="hidden-newer-agent",
                    tenant_id=test_tenant_db.id,
                    project_id=hidden_project.id,
                    name="hidden-newer-agent",
                    created_at=base_time + timedelta(minutes=2),
                ),
                _agent_model(
                    agent_id="visible-agent",
                    tenant_id=test_tenant_db.id,
                    project_id=test_project_db.id,
                    name="visible-agent",
                    created_at=base_time + timedelta(minutes=1),
                ),
                _agent_model(
                    agent_id="tenant-agent",
                    tenant_id=test_tenant_db.id,
                    project_id=None,
                    name="tenant-agent",
                    created_at=base_time,
                ),
            ]
        )
        await db_session.commit()

        repo = SqlAgentRegistryRepository(db_session)
        builtin_count = len(list_builtin_agents(tenant_id=test_tenant_db.id))

        agents = await repo.list_by_tenant(
            test_tenant_db.id,
            project_ids={test_project_db.id},
            limit=2,
            offset=builtin_count,
            sort="recent",
        )
        count = await repo.count_by_tenant(
            test_tenant_db.id,
            project_ids={test_project_db.id},
        )

        assert [agent.name for agent in agents] == ["visible-agent", "tenant-agent"]
        assert count == builtin_count + 2

    @pytest.mark.asyncio
    async def test_get_by_id_refreshes_existing_identity_map_rows(
        self,
        db_session: AsyncSession,
        test_tenant_db,
        test_project_db,
    ) -> None:
        agent_id = "agent-refresh-test"
        db_session.add(
            AgentDefinitionModel(
                id=agent_id,
                tenant_id=test_tenant_db.id,
                project_id=test_project_db.id,
                name="refresh-test-agent",
                display_name="Refresh Test Agent",
                system_prompt="You are a refresh test agent.",
                trigger_description="Refresh test trigger",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
                source="database",
                max_iterations=10,
            )
        )
        await db_session.commit()

        repo = SqlAgentRegistryRepository(db_session)
        first = await repo.get_by_id(
            agent_id,
            tenant_id=test_tenant_db.id,
            project_id=test_project_db.id,
        )
        assert first is not None
        assert first.max_iterations == 10

        session_factory = async_sessionmaker(
            db_session.bind,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        async with session_factory() as other_session:
            row = await other_session.get(AgentDefinitionModel, agent_id)
            assert row is not None
            row.max_iterations = 42
            await other_session.commit()

        refreshed = await repo.get_by_id(
            agent_id,
            tenant_id=test_tenant_db.id,
            project_id=test_project_db.id,
        )
        assert refreshed is not None
        assert refreshed.max_iterations == 42

    @pytest.mark.asyncio
    async def test_get_by_id_preserves_explicit_empty_allowed_tools(
        self,
        db_session: AsyncSession,
        test_tenant_db,
        test_project_db,
    ) -> None:
        agent_id = "agent-deny-tools"
        db_session.add(
            AgentDefinitionModel(
                id=agent_id,
                tenant_id=test_tenant_db.id,
                project_id=test_project_db.id,
                name="deny-tools-agent",
                display_name="Deny Tools Agent",
                system_prompt="You cannot use runtime tools.",
                trigger_description="Deny tools trigger",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
                source="database",
                max_iterations=10,
            )
        )
        await db_session.commit()

        repo = SqlAgentRegistryRepository(db_session)
        loaded = await repo.get_by_id(
            agent_id,
            tenant_id=test_tenant_db.id,
            project_id=test_project_db.id,
        )

        assert loaded is not None
        assert loaded.allowed_tools == []
        assert loaded.has_tool_access("terminal") is False

    @pytest.mark.asyncio
    async def test_create_round_trips_structured_policies(
        self,
        db_session: AsyncSession,
        test_tenant_db,
        test_project_db,
    ) -> None:
        repo = SqlAgentRegistryRepository(db_session)
        agent = _build_custom_agent("policy-agent", "policy-agent", test_tenant_db.id)
        agent.project_id = test_project_db.id
        agent.spawn_policy = SpawnPolicy(
            max_depth=1,
            max_active_runs=3,
            max_children_per_requester=2,
            allowed_subagents=frozenset({"coder"}),
        )
        agent.tool_policy = ToolPolicy(
            allow=("read", "grep"),
            deny=("bash",),
            precedence=ToolPolicyPrecedence.ALLOW_FIRST,
        )

        await repo.create(agent)
        await db_session.commit()

        loaded = await repo.get_by_id(
            "policy-agent",
            tenant_id=test_tenant_db.id,
            project_id=test_project_db.id,
        )

        assert loaded is not None
        assert loaded.spawn_policy is not None
        assert loaded.spawn_policy.max_depth == 1
        assert loaded.spawn_policy.max_active_runs == 3
        assert loaded.spawn_policy.max_children_per_requester == 2
        assert loaded.spawn_policy.allowed_subagents == frozenset({"coder"})
        assert loaded.tool_policy is not None
        assert loaded.tool_policy.allow == ("read", "grep")
        assert loaded.tool_policy.deny == ("bash",)
        assert loaded.tool_policy.precedence == ToolPolicyPrecedence.ALLOW_FIRST

    @pytest.mark.asyncio
    async def test_get_by_id_filters_database_agents_by_tenant_and_project(
        self,
        db_session: AsyncSession,
        test_tenant_db,
        test_project_db,
        test_user,
    ) -> None:
        other_tenant = Tenant(
            id="other-agent-tenant",
            name="Other Agent Tenant",
            slug="other-agent-tenant",
            owner_id=test_user.id,
        )
        other_project = Project(
            id="other-agent-project",
            tenant_id=test_tenant_db.id,
            name="Other Agent Project",
            owner_id=test_user.id,
            memory_rules={},
            graph_config={},
        )
        db_session.add_all([other_tenant, other_project])
        await db_session.flush()
        db_session.add_all(
            [
                _agent_model(
                    agent_id="tenant-wide-agent",
                    tenant_id=test_tenant_db.id,
                    project_id=None,
                    name="tenant-wide-agent",
                ),
                _agent_model(
                    agent_id="cross-tenant-agent",
                    tenant_id=other_tenant.id,
                    project_id=None,
                    name="cross-tenant-agent",
                ),
                _agent_model(
                    agent_id="wrong-project-agent",
                    tenant_id=test_tenant_db.id,
                    project_id=other_project.id,
                    name="wrong-project-agent",
                ),
            ]
        )
        await db_session.commit()

        repo = SqlAgentRegistryRepository(db_session)

        assert (
            await repo.get_by_id(
                "tenant-wide-agent",
                tenant_id=test_tenant_db.id,
                project_id=test_project_db.id,
            )
        ) is not None
        assert (
            await repo.get_by_id(
                "cross-tenant-agent",
                tenant_id=test_tenant_db.id,
                project_id=test_project_db.id,
            )
        ) is None
        assert (
            await repo.get_by_id(
                "wrong-project-agent",
                tenant_id=test_tenant_db.id,
                project_id=test_project_db.id,
            )
        ) is None

    @pytest.mark.asyncio
    async def test_list_by_project_filters_database_agents_by_tenant(
        self,
        db_session: AsyncSession,
        test_tenant_db,
        test_project_db,
        test_user,
    ) -> None:
        other_tenant = Tenant(
            id="other-list-tenant",
            name="Other List Tenant",
            slug="other-list-tenant",
            owner_id=test_user.id,
        )
        db_session.add(other_tenant)
        await db_session.flush()
        db_session.add_all(
            [
                _agent_model(
                    agent_id="project-agent",
                    tenant_id=test_tenant_db.id,
                    project_id=test_project_db.id,
                    name="project-agent",
                ),
                _agent_model(
                    agent_id="tenant-agent",
                    tenant_id=test_tenant_db.id,
                    project_id=None,
                    name="tenant-agent",
                ),
                _agent_model(
                    agent_id="cross-project-agent",
                    tenant_id=other_tenant.id,
                    project_id=test_project_db.id,
                    name="cross-project-agent",
                ),
                _agent_model(
                    agent_id="cross-tenant-agent-list",
                    tenant_id=other_tenant.id,
                    project_id=None,
                    name="cross-tenant-agent-list",
                ),
            ]
        )
        await db_session.commit()

        repo = SqlAgentRegistryRepository(db_session)

        agents = await repo.list_by_project(test_project_db.id, tenant_id=test_tenant_db.id)
        names = {agent.name for agent in agents}

        assert "project-agent" in names
        assert "tenant-agent" in names
        assert "cross-project-agent" not in names
        assert "cross-tenant-agent-list" not in names

    @pytest.mark.asyncio
    async def test_list_excludes_legacy_workspace_scoped_auto_team_agents(
        self,
        db_session: AsyncSession,
        test_tenant_db,
        test_project_db,
    ) -> None:
        db_session.add_all(
            [
                AgentDefinitionModel(
                    id="legacy-workspace-team-agent",
                    tenant_id=test_tenant_db.id,
                    project_id=test_project_db.id,
                    name="workspace-abc123-architect",
                    display_name="Workspace Architect",
                    system_prompt="You are a legacy workspace-scoped worker.",
                    trigger_description="Legacy workspace worker",
                    allowed_tools=[],
                    allowed_skills=[],
                    allowed_mcp_servers=[],
                    source="database",
                    max_iterations=80,
                    metadata_json={
                        "created_by": "leader_team_setup",
                        "workspace_id": "workspace-abc123",
                        "workspace_role": "execution_worker",
                    },
                ),
                AgentDefinitionModel(
                    id="project-team-agent",
                    tenant_id=test_tenant_db.id,
                    project_id=test_project_db.id,
                    name="workspace-plan-project123-architect",
                    display_name="Workspace Architect",
                    system_prompt="You are a project-scoped worker.",
                    trigger_description="Project workspace worker",
                    allowed_tools=[],
                    allowed_skills=[],
                    allowed_mcp_servers=[],
                    source="database",
                    max_iterations=80,
                    metadata_json={
                        "created_by": "workspace_plan_team_setup",
                        "project_id": test_project_db.id,
                        "workspace_role": "execution_worker",
                        "team_definition_scope": "project",
                    },
                ),
            ]
        )
        await db_session.commit()

        repo = SqlAgentRegistryRepository(db_session)

        tenant_agents = await repo.list_by_tenant(test_tenant_db.id)
        project_agents = await repo.list_by_project(
            test_project_db.id,
            tenant_id=test_tenant_db.id,
        )

        assert "workspace-abc123-architect" not in {agent.name for agent in tenant_agents}
        assert "workspace-abc123-architect" not in {agent.name for agent in project_agents}
        assert "workspace-plan-project123-architect" in {agent.name for agent in tenant_agents}
        assert "workspace-plan-project123-architect" in {agent.name for agent in project_agents}
