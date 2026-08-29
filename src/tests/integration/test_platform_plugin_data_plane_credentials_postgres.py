"""PostgreSQL fencing for protocol-v2 workload credential rotation."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2DataPlaneCredentialModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    PlatformPluginDataPlaneCredentialRepositoryV2,
    PlatformPluginDataPlaneCredentialV2Error,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture
async def postgres_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.getenv("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL")
    if database_url is None:
        pytest.skip("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL is required")
    engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            assert connection.dialect.name == "postgresql"
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def test_concurrent_rotation_issues_one_successor_and_fences_replay(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    data_plane_id = f"postgres-credential-{uuid.uuid4().hex}"
    async with postgres_session_factory() as session:
        issued = await PlatformPluginDataPlaneCredentialRepositoryV2(session).issue(
            data_plane_id=data_plane_id,
            actor_id="postgres-admin",
        )
        source_id = issued.credential.id
        await session.commit()

    gate = asyncio.Event()

    async def rotate(actor_id: str) -> tuple[str, str]:
        await gate.wait()
        async with postgres_session_factory() as session:
            try:
                successor = await PlatformPluginDataPlaneCredentialRepositoryV2(session).rotate(
                    source_id,
                    actor_id=actor_id,
                )
            except PlatformPluginDataPlaneCredentialV2Error as exc:
                await session.rollback()
                return ("error", exc.code)
            await session.commit()
            return ("issued", successor.credential.id)

    first = asyncio.create_task(rotate("postgres-admin-1"))
    second = asyncio.create_task(rotate("postgres-admin-2"))
    gate.set()
    results = await asyncio.gather(first, second)

    assert sorted(result[0] for result in results) == ["error", "issued"]
    assert next(result[1] for result in results if result[0] == "error") == "credential_revoked"
    async with postgres_session_factory() as session:
        rows = tuple(
            (
                await session.execute(
                    select(PlatformPluginV2DataPlaneCredentialModel).where(
                        PlatformPluginV2DataPlaneCredentialModel.data_plane_id == data_plane_id
                    )
                )
            ).scalars()
        )
        assert len(rows) == 2
        source = next(row for row in rows if row.id == source_id)
        successor = next(row for row in rows if row.id != source_id)
        assert source.revoked_at is not None
        assert successor.rotated_from_id == source.id
        assert successor.revoked_at is None

        await session.execute(
            delete(PlatformPluginV2DataPlaneCredentialModel).where(
                PlatformPluginV2DataPlaneCredentialModel.id == successor.id
            )
        )
        await session.execute(
            delete(PlatformPluginV2DataPlaneCredentialModel).where(
                PlatformPluginV2DataPlaneCredentialModel.id == source.id
            )
        )
        await session.commit()
