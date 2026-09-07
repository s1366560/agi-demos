"""Real SQL binding persistence must accept generation-catalog definitions."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import Column, MetaData, String, Table, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.domain.model.agent.agent_binding import AgentBinding
from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.subagent import AgentTrigger
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import AgentBindingModel
from src.infrastructure.adapters.secondary.persistence.sql_binding_repository import (
    SqlAgentBindingRepository,
)
from src.infrastructure.agent.sisyphus.builtin_agent import get_builtin_agent_by_id
from src.infrastructure.plugins.v2.agent_binding_services import (
    AgentBindingAgentUnavailableV2,
    AgentBindingScopeMismatchV2,
    AgentBindingServiceV2,
)
from src.infrastructure.plugins.v2.agent_definition import (
    AgentDefinitionCatalogV2,
    AgentDefinitionResolverV2,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def catalog_binding_service() -> AsyncIterator[AgentBindingServiceV2]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    definitions = Table(
        "agent_definitions",
        MetaData(),
        Column("id", String, primary_key=True),
        Column("tenant_id", String, nullable=False),
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(definitions.create)
            await connection.run_sync(AgentBindingModel.__table__.create)
            await connection.execute(
                insert(definitions),
                [
                    {"id": "persisted-agent", "tenant_id": "tenant-a"},
                    {"id": "foreign-agent", "tenant_id": "tenant-b"},
                ],
            )
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            catalog = AgentDefinitionCatalogV2()
            catalog.register(
                "builtin:sisyphus",
                lambda tenant_id, project_id: get_builtin_agent_by_id(
                    "builtin:sisyphus",
                    tenant_id,
                    project_id=project_id,
                ),
            )

            async def persisted_definition(
                *,
                agent_id: str,
                tenant_id: str,
                project_id: str | None,
            ) -> Agent | None:
                row = (
                    await session.execute(select(definitions).where(definitions.c.id == agent_id))
                ).first()
                if row is None:
                    return None
                return Agent(
                    id=row.id,
                    tenant_id=row.tenant_id,
                    name=row.id,
                    display_name=row.id,
                    system_prompt="QA binding agent",
                    trigger=AgentTrigger(description="QA binding"),
                )

            catalog.register_provider("database", persisted_definition)
            yield AgentBindingServiceV2(
                operation=cast(
                    Any,
                    SimpleNamespace(
                        context=SimpleNamespace(
                            scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
                        )
                    ),
                ),
                binding_repository=SqlAgentBindingRepository(cast(AsyncSession, session)),
                agent_definitions=AgentDefinitionResolverV2(
                    strategy="explicit-id", catalog=catalog
                ),
            )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("agent_id", ["builtin:sisyphus", "persisted-agent"])
@pytest.mark.parametrize("channel_type", ["websocket", None])
async def test_catalog_binding_crud_and_resolution(
    catalog_binding_service: AgentBindingServiceV2,
    agent_id: str,
    channel_type: str | None,
) -> None:
    service = catalog_binding_service
    binding = AgentBinding(
        id="binding-a",
        tenant_id="tenant-a",
        agent_id=agent_id,
        channel_type=channel_type,
        channel_id="qa-channel",
    )
    await service.create(binding)
    listed = await service.list_bindings(agent_id=agent_id, enabled_only=True)
    assert [item.id for item in listed] == [binding.id]
    match = await service.resolve_with_trace(
        channel_type="websocket",
        channel_id="qa-channel",
        account_id=None,
        peer_id=None,
    )
    assert match.binding is not None
    assert match.binding.agent_id == agent_id
    assert match.agent_name
    direct = await service.binding_repository.resolve_binding(
        tenant_id="tenant-a",
        channel_type="websocket",
        channel_id="qa-channel",
    )
    assert direct is not None and direct.agent_id == agent_id
    await service.set_enabled(binding.id, enabled=False)
    assert await service.list_bindings(agent_id=None, enabled_only=True) == []
    await service.set_enabled(binding.id, enabled=True)
    assert await service.delete(binding.id)
    assert await service.list_bindings(agent_id=None, enabled_only=False) == []


@pytest.mark.parametrize("agent_id", ["missing-agent", "foreign-agent"])
async def test_catalog_binding_rejects_unknown_and_foreign_definitions(
    catalog_binding_service: AgentBindingServiceV2,
    agent_id: str,
) -> None:
    service = catalog_binding_service
    with pytest.raises(AgentBindingAgentUnavailableV2):
        await service.create(AgentBinding(id="rejected", tenant_id="tenant-a", agent_id=agent_id))
    assert await service.list_bindings(agent_id=None, enabled_only=False) == []


async def test_catalog_binding_rejects_foreign_binding_scope(
    catalog_binding_service: AgentBindingServiceV2,
) -> None:
    with pytest.raises(AgentBindingScopeMismatchV2):
        await catalog_binding_service.create(
            AgentBinding(
                id="rejected",
                tenant_id="tenant-b",
                agent_id="builtin:sisyphus",
            )
        )
