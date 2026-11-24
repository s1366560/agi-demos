"""Default type initialization coexists with graph writes and fences schema activation."""

import asyncio
from collections import Counter

import pytest
from sqlalchemy import select

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
