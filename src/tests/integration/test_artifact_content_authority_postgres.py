"""PostgreSQL syntax and migration barrier for Artifact content authority locks."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.configuration.config import get_settings
from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentScope,
)
from src.infrastructure.adapters.secondary.persistence.sql_artifact_content_authority import (
    SqlArtifactContentAuthorityRepository,
)

pytestmark = pytest.mark.integration


async def test_postgres_executes_scoped_authority_and_skip_locked_gc_queries() -> None:
    """Execute both PostgreSQL lock forms against the migrated integration database."""
    engine = create_async_engine(get_settings().postgres_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            transaction = await session.begin()
            try:
                repository = SqlArtifactContentAuthorityRepository(session)
                missing_scope = ArtifactContentScope(
                    artifact_id=f"artifact-lock-probe-{uuid.uuid4()}",
                    tenant_id=f"tenant-lock-probe-{uuid.uuid4()}",
                    project_id=f"project-lock-probe-{uuid.uuid4()}",
                    conversation_id=None,
                )
                assert (
                    await repository.get_authority(
                        missing_scope,
                        for_update=True,
                    )
                    is None
                )

                historical_now = datetime(2000, 1, 1, tzinfo=UTC)
                claimed = await repository.claim_orphan_gc(
                    lease_owner="artifact-pg-probe",
                    lease_token=uuid.uuid4().hex,
                    now=historical_now,
                    lease_expires_at=historical_now + timedelta(seconds=30),
                    limit=1,
                )
                assert claimed == []
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
