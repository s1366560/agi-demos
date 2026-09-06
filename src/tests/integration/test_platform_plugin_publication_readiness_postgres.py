"""PostgreSQL transaction fencing for the plugin-v2 publication ledger."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.domain.model.plugins.generated_v2 import PublicationStatusV2
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2DataPlaneCredentialModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    PlatformPluginDataPlaneCredentialRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.protocol import snapshot_apply_receipt_v2_to_payload
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

_ROOT = Path(__file__).resolve().parents[3]
_PROFILE = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFESTS = (_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",)


@dataclass(frozen=True, kw_only=True)
class _PublishedCase:
    publication: PlatformPluginPublicationV2
    publication_id: str
    data_plane_id: str
    requested_at: datetime


@dataclass(kw_only=True)
class _Rendezvous:
    expected: int
    timeout_seconds: float = 0.5
    arrivals: int = 0
    ready: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait(self) -> None:
        self.arrivals += 1
        if self.arrivals >= self.expected:
            self.ready.set()
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=self.timeout_seconds)
        except TimeoutError:
            return


@pytest.fixture
async def postgres_engine() -> AsyncIterator[AsyncEngine]:
    database_url = os.getenv("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL")
    if not database_url:
        pytest.skip("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL must identify an isolated test database")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            assert connection.dialect.name == "postgresql"
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def postgres_session_factory(
    postgres_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(postgres_engine, expire_on_commit=False)


async def _build_publication(*, version: int, nonce: str) -> PlatformPluginPublicationV2:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    try:
        return await host.bootstrap(
            profile_path=_PROFILE,
            manifest_paths=_MANIFESTS,
            generation=version,
            version=version,
            nonce=nonce,
        )
    finally:
        await host.close()


@asynccontextmanager
async def _published_case(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    deadline_seconds: int = 30,
    already_expired: bool = False,
) -> AsyncIterator[_PublishedCase]:
    suffix = uuid.uuid4().hex
    data_plane_id = f"postgres-ack-{suffix}"
    nonce = f"postgres-readiness-{suffix}"
    requested_at = datetime.now(UTC)
    if already_expired:
        requested_at -= timedelta(seconds=deadline_seconds + 1)
    async with session_factory() as session:
        latest_version = await session.scalar(
            select(func.coalesce(func.max(PlatformPluginV2PublicationModel.requested_version), 0))
        )
        version = int(latest_version or 0) + 1
        publication = await _build_publication(version=version, nonce=nonce)
        row = await PlatformPluginRepositoryV2(session).record_publication(
            publication,
            policy=PlatformPluginPublicationPolicyV2(
                required_data_plane_ids=(data_plane_id,),
                ack_deadline_seconds=deadline_seconds,
            ),
            now=requested_at,
        )
        await session.commit()
    case = _PublishedCase(
        publication=publication,
        publication_id=row.id,
        data_plane_id=data_plane_id,
        requested_at=requested_at,
    )
    try:
        yield case
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(PlatformPluginV2DataPlaneCredentialModel).where(
                    PlatformPluginV2DataPlaneCredentialModel.data_plane_id == case.data_plane_id
                )
            )
            await session.execute(
                delete(PlatformPluginV2ApplyStateEventModel).where(
                    PlatformPluginV2ApplyStateEventModel.requested_publication_id
                    == case.publication_id
                )
            )
            await session.execute(
                delete(PlatformPluginV2ApplyStateModel).where(
                    PlatformPluginV2ApplyStateModel.data_plane_id == case.data_plane_id
                )
            )
            await session.execute(
                delete(PlatformPluginV2PublicationModel).where(
                    PlatformPluginV2PublicationModel.id == case.publication_id
                )
            )
            await session.commit()


def _selects_model(statement: object, model: type[object]) -> bool:
    descriptions = getattr(statement, "column_descriptions", ())
    return any(description.get("entity") is model for description in descriptions)


def _pause_after_state_read(
    session: AsyncSession,
    *,
    read_number: int,
    pause: Callable[[], Awaitable[None]],
) -> None:
    original_execute = session.execute
    state_reads = 0

    async def execute_with_pause(statement: object, *args: Any, **kwargs: Any) -> Any:
        nonlocal state_reads
        result = await original_execute(statement, *args, **kwargs)
        if _selects_model(statement, PlatformPluginV2ApplyStateModel):
            state_reads += 1
            if state_reads == read_number:
                await pause()
        return result

    session.execute = execute_with_pause  # type: ignore[method-assign]


async def test_concurrent_duplicate_receipts_are_idempotent_in_postgres(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with _published_case(postgres_session_factory) as case:
        rendezvous = _Rendezvous(expected=2)

        async def record_once() -> str:
            async with postgres_session_factory() as session:
                _pause_after_state_read(session, read_number=2, pause=rendezvous.wait)
                state = await PlatformPluginRepositoryV2(session).record_data_plane_receipt(
                    data_plane_id=case.data_plane_id,
                    nonce=case.publication.envelope.nonce,
                    receipt=case.publication.receipt,
                )
                await session.commit()
                return state.id

        results = await asyncio.gather(record_once(), record_once(), return_exceptions=True)

        assert all(isinstance(result, str) for result in results), results
        assert len(set(results)) == 1
        async with postgres_session_factory() as session:
            event_count = await session.scalar(
                select(func.count())
                .select_from(PlatformPluginV2ApplyStateEventModel)
                .where(
                    PlatformPluginV2ApplyStateEventModel.requested_publication_id
                    == case.publication_id,
                    PlatformPluginV2ApplyStateEventModel.data_plane_id == case.data_plane_id,
                )
            )
        assert event_count == 1


async def test_deadline_refresh_cannot_overwrite_concurrent_ack(
    postgres_engine: AsyncEngine,
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with _published_case(
        postgres_session_factory,
        deadline_seconds=1,
        already_expired=True,
    ) as case:
        readiness_observed_missing_state = asyncio.Event()
        ack_committed = asyncio.Event()

        async def pause_readiness() -> None:
            readiness_observed_missing_state.set()
            try:
                await asyncio.wait_for(ack_committed.wait(), timeout=0.5)
            except TimeoutError:
                return

        async def refresh_deadline() -> None:
            async with AsyncSession(bind=postgres_engine, expire_on_commit=False) as session:
                _pause_after_state_read(session, read_number=1, pause=pause_readiness)
                await PlatformPluginRepositoryV2(session).latest_publication_readiness(
                    now=datetime.now(UTC)
                )
                await session.commit()

        async def acknowledge() -> None:
            await readiness_observed_missing_state.wait()
            async with postgres_session_factory() as session:
                await PlatformPluginRepositoryV2(session).record_data_plane_receipt(
                    data_plane_id=case.data_plane_id,
                    nonce=case.publication.envelope.nonce,
                    receipt=case.publication.receipt,
                    now=datetime.now(UTC),
                )
                await session.commit()
            ack_committed.set()

        await asyncio.gather(refresh_deadline(), acknowledge())

        async with postgres_session_factory() as session:
            row = await session.get(PlatformPluginV2PublicationModel, case.publication_id)
            assert row is not None
            assert row.status == PublicationStatusV2.READY.value


async def test_late_ack_remains_ready_after_sessions_reopen(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with _published_case(
        postgres_session_factory,
        deadline_seconds=1,
        already_expired=True,
    ) as case:
        async with postgres_session_factory() as session:
            timed_out = await PlatformPluginRepositoryV2(session).publication_readiness(
                case.publication.envelope.nonce,
                now=datetime.now(UTC),
            )
            assert timed_out.status is PublicationStatusV2.DEGRADED
            await session.commit()

        async with postgres_session_factory() as session:
            await PlatformPluginRepositoryV2(session).record_data_plane_receipt(
                data_plane_id=case.data_plane_id,
                nonce=case.publication.envelope.nonce,
                receipt=case.publication.receipt,
                now=datetime.now(UTC),
            )
            await session.commit()

        async with postgres_session_factory() as session:
            row = await session.get(PlatformPluginV2PublicationModel, case.publication_id)
            assert row is not None
            assert row.status == PublicationStatusV2.READY.value
            assert row.ready_at is not None
            reopened = await PlatformPluginRepositoryV2(session).publication_readiness(
                case.publication.envelope.nonce,
                now=datetime.now(UTC),
            )
            assert reopened.status is PublicationStatusV2.READY


async def test_deadline_sweep_persists_timeout_without_read_query_in_postgres(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with _published_case(
        postgres_session_factory,
        deadline_seconds=1,
        already_expired=True,
    ) as case:
        async with postgres_session_factory() as session:
            reconciled = await PlatformPluginRepositoryV2(session).reconcile_publication_deadlines(
                now=datetime.now(UTC)
            )
            await session.commit()
        assert reconciled == 1

        async with postgres_session_factory() as session:
            row = await session.get(PlatformPluginV2PublicationModel, case.publication_id)
            assert row is not None
            assert row.status == PublicationStatusV2.DEGRADED.value


async def test_concurrent_receipt_api_replays_are_idempotent_in_postgres(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with _published_case(postgres_session_factory) as case:
        async with postgres_session_factory() as session:
            issued = await PlatformPluginDataPlaneCredentialRepositoryV2(session).issue(
                data_plane_id=case.data_plane_id,
                actor_id="plugin-v2-postgres-user",
            )
            await session.commit()
        app = FastAPI()
        app.include_router(platform_plugins.router)

        async def override_db() -> AsyncIterator[AsyncSession]:
            async with postgres_session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        payload = {
            "schema_version": 2,
            "data_plane_id": case.data_plane_id,
            "nonce": case.publication.envelope.nonce,
            "receipt": snapshot_apply_receipt_v2_to_payload(case.publication.receipt),
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {issued.secret}"},
        ) as client:
            responses = await asyncio.gather(
                client.post("/api/v1/platform-plugins/v2/data-plane-state", json=payload),
                client.post("/api/v1/platform-plugins/v2/data-plane-state", json=payload),
            )

        assert [response.status_code for response in responses] == [200, 200]
        assert [response.json() for response in responses] == [payload, payload]
        async with postgres_session_factory() as session:
            event_count = await session.scalar(
                select(func.count())
                .select_from(PlatformPluginV2ApplyStateEventModel)
                .where(
                    PlatformPluginV2ApplyStateEventModel.requested_publication_id
                    == case.publication_id,
                    PlatformPluginV2ApplyStateEventModel.data_plane_id == case.data_plane_id,
                )
            )
        assert event_count == 1


async def test_receipt_api_rejects_forged_plane_binding_in_postgres(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with _published_case(postgres_session_factory) as case:
        async with postgres_session_factory() as session:
            issued = await PlatformPluginDataPlaneCredentialRepositoryV2(session).issue(
                data_plane_id=case.data_plane_id,
                actor_id="plugin-v2-postgres-user",
            )
            await session.commit()
        app = FastAPI()
        app.include_router(platform_plugins.router)

        async def override_db() -> AsyncIterator[AsyncSession]:
            async with postgres_session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        payload = {
            "schema_version": 2,
            "data_plane_id": f"forged-{uuid.uuid4().hex}",
            "nonce": case.publication.envelope.nonce,
            "receipt": snapshot_apply_receipt_v2_to_payload(case.publication.receipt),
        }

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {issued.secret}"},
        ) as client:
            response = await client.post(
                "/api/v1/platform-plugins/v2/data-plane-state",
                json=payload,
            )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "plugin_data_plane_identity_mismatch"
        async with postgres_session_factory() as session:
            event_count = await session.scalar(
                select(func.count())
                .select_from(PlatformPluginV2ApplyStateEventModel)
                .where(
                    PlatformPluginV2ApplyStateEventModel.requested_publication_id
                    == case.publication_id
                )
            )
        assert event_count == 0
