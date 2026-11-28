"""Default type initialization coexists with graph writes and fences schema activation."""

import asyncio
from collections import Counter

import pytest
from sqlalchemy import select

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.infrastructure.adapters.secondary.persistence.graph_discovery_session import (
    bind_discovery,
    persist_after_graph_commit,
)
from src.infrastructure.adapters.secondary.persistence.models import EntityType, Project
from src.infrastructure.adapters.secondary.schema import dynamic_schema
from src.infrastructure.adapters.secondary.schema.active_schema_reads import (
    SchemaCommandRequiredV2,
    require_legacy_schema,
)
from src.tests.integration.project_schema_command_support import (
    SCOPE,
    activated,
    schema_command_pg as _schema_command_pg,
    schema_storage_pg as _schema_storage_pg,
)

pytestmark = pytest.mark.integration
schema_storage_pg = _schema_storage_pg
schema_command_pg = _schema_command_pg


async def test_schema_read_inside_graph_lease_and_concurrent_seeding(
    schema_command_pg, monkeypatch
):
    _, sessions = schema_command_pg
    project = "project-b"
    monkeypatch.setattr(dynamic_schema, "async_session_factory", sessions)
    monkeypatch.setattr(dynamic_schema, "_initialized_projects", set())
    async with sessions.begin() as lease:
        await lease.scalar(
            select(Project.id).where(Project.id == project).with_for_update(key_share=True)
        )
        async with asyncio.timeout(5):
            context = await dynamic_schema.get_project_schema_context(
                project, persist_defaults=False
            )
            defaults = {
                row["entity_type_name"] for row in dynamic_schema.DEFAULT_ENTITY_TYPES_CONTEXT
            }
            assert set(context["entity_type_name_to_id"]) == defaults
            assert not list(
                await lease.scalars(select(EntityType.name).where(EntityType.project_id == project))
            )
    async with sessions.begin() as reader:
        async with asyncio.timeout(5):
            await asyncio.gather(
                *(dynamic_schema._ensure_default_types_initialized(project) for _ in range(2))
            )
        names = await reader.scalars(
            select(EntityType.name).where(EntityType.project_id == project)
        )
        assert Counter(names) == Counter(
            row["entity_type_name"] for row in dynamic_schema.DEFAULT_ENTITY_TYPES_CONTEXT
        )


async def test_seed_fences_schema_activation_in_both_orders(schema_command_pg):
    _, sessions = schema_command_pg
    async with sessions.begin() as seed:
        await require_legacy_schema(seed, SCOPE.project_id)
        activating = asyncio.create_task(activated(sessions))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(activating), 0.15)
    await asyncio.wait_for(activating, 5)
    async with sessions.begin() as late_seed:
        with pytest.raises(SchemaCommandRequiredV2):
            await require_legacy_schema(late_seed, SCOPE.project_id)


@pytest.mark.parametrize("commit", [True, False])
async def test_discovered_schema_runs_after_the_graph_transaction(
    schema_command_pg, monkeypatch, commit
):
    _, sessions = schema_command_pg
    project, tenant = SCOPE.project_id, SCOPE.tenant_id
    monkeypatch.setattr(dynamic_schema, "async_session_factory", sessions)
    invalidated = []
    monkeypatch.setattr(dynamic_schema, "clear_schema_context_cache", invalidated.append)
    query = select(EntityType.name).where(EntityType.name == "DiscoveryReceipt")

    async def persist():
        result = await dynamic_schema.save_discovered_types_batch(
            project_id=project,
            tenant_id=tenant,
            entity_types=[{"name": "DiscoveryReceipt", "description": "Receipt"}],
            edge_types=[],
            edge_type_maps=[],
        )
        assert result["entity_types_created"] == 1

    async with asyncio.timeout(5):
        async with sessions() as lease:
            await lease.scalar(
                select(Project.id).where(Project.id == project).with_for_update(key_share=True)
            )
            with bind_discovery(lease, project=project, tenant=tenant) as discovery:
                with pytest.raises(KnowledgeSyncError):
                    await persist_after_graph_commit(project, "another-tenant", persist)
                with pytest.raises(KnowledgeSyncError):
                    await persist_after_graph_commit("another-project", tenant, persist)
                with pytest.raises(KnowledgeSyncError):
                    await asyncio.create_task(persist_after_graph_commit(project, tenant, persist))
                await persist_after_graph_commit(project, tenant, persist)
                async with sessions() as reader:
                    assert await reader.scalar(query) is None
                    # The journal's foreign keys can still coexist with the graph fence.
                    assert (
                        await reader.scalar(
                            select(Project.id)
                            .where(Project.id == project)
                            .with_for_update(read=True, key_share=True)
                        )
                        == project
                    )
                assert invalidated == []
            if commit:
                await lease.commit()
            else:
                await lease.rollback()
        if commit:
            await discovery.persist()
        async with sessions() as reader:
            assert await reader.scalar(query) == ("DiscoveryReceipt" if commit else None)
    assert invalidated == ([project] if commit else [])


@pytest.mark.parametrize("changed", ["enrollment", "tenant"])
async def test_discovery_revalidates_scope_and_schema_after_admission(
    schema_command_pg, monkeypatch, changed
):
    _, sessions = schema_command_pg
    monkeypatch.setattr(dynamic_schema, "async_session_factory", sessions)
    project, tenant = SCOPE.project_id, SCOPE.tenant_id

    async def persist():
        await dynamic_schema.save_discovered_types_batch(
            project_id=project,
            tenant_id=tenant if changed == "enrollment" else "another-tenant",
            entity_types=[{"name": "Disallowed", "description": ""}],
            edge_types=[],
            edge_type_maps=[],
        )

    async with sessions.begin() as lease:
        await lease.scalar(
            select(Project.id).where(Project.id == project).with_for_update(key_share=True)
        )
        with bind_discovery(lease, project=project, tenant=tenant) as discovery:
            await persist_after_graph_commit(project, tenant, persist)
    if changed == "enrollment":
        await activated(sessions)
    async with asyncio.timeout(5):
        with pytest.raises(
            SchemaCommandRequiredV2 if changed == "enrollment" else KnowledgeSyncError
        ):
            await discovery.persist()
    async with sessions() as reader:
        assert not await reader.scalar(select(EntityType.id).where(EntityType.name == "Disallowed"))
