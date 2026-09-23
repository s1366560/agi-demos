"""Sandbox writes must retain the marketplace's outer transaction boundary."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.domain.model.sandbox.project_sandbox import ProjectSandbox, ProjectSandboxStatus
from src.infrastructure.adapters.secondary.persistence.models import ProjectSandbox as SandboxRow
from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
    SqlProjectSandboxRepository,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("action", ["save", "delete", "delete_by_project"])
async def test_sandbox_changes_rollback_with_outer_transaction(action: str) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(SandboxRow.__table__.create)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            original = ProjectSandbox(
                id="marketplace-association",
                project_id="marketplace-project",
                tenant_id="marketplace-tenant",
                sandbox_id="marketplace-sandbox",
                status=ProjectSandboxStatus.RUNNING,
                created_at=datetime.now(UTC),
            )
            await SqlProjectSandboxRepository(session).save(original)
            repository = SqlProjectSandboxRepository(session, commit_on_write=False)
            if action == "save":
                original.status = ProjectSandboxStatus.STOPPED
                await repository.save(original)
            elif action == "delete":
                assert await repository.delete(original.id)
            else:
                assert await repository.delete_by_project(original.project_id)
            assert session.in_transaction()
            await session.rollback()
            restored = await repository.find_by_id(original.id)
            assert restored is not None
            assert restored.status == ProjectSandboxStatus.RUNNING
    finally:
        await engine.dispose()
