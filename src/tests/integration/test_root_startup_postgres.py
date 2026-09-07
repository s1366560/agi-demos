"""ROOT startup transaction fences on independently migrated PostgreSQL schemas."""

import importlib.util
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from scripts.verify_scoped_restart_postgres import REVISIONS, ROOT as REPOSITORY_ROOT
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_model_v2 import (
    PlatformPluginV2PublicationSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.protocol import (
    control_envelope_v2,
    control_envelope_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.integration
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


def _migrate(connection):
    with Operations.context(MigrationContext.configure(connection)):
        for revision in REVISIONS:
            path = next((REPOSITORY_ROOT / "alembic/versions").glob(f"{revision}_*.py"))
            spec = importlib.util.spec_from_file_location(revision, path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.upgrade()


@pytest_asyncio.fixture(loop_scope="function")
async def root_sessions():
    url = os.environ.get("PLATFORM_PLUGIN_V2_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("requires the owned PostgreSQL runner")
    schema = f"root_startup_{uuid4().hex}"
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "lock_timeout": "10s",
                "statement_timeout": "30s",
            }
        },
    )
    created = False
    try:
        async with admin.begin() as connection:
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(_migrate)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        try:
            if created:
                async with admin.begin() as connection:
                    await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await admin.dispose()


async def _counts(session):
    return tuple(
        [
            await session.scalar(select(func.count()).select_from(model))
            for model in (
                PlatformPluginV2PublicationModel,
                PlatformPluginV2PublicationSourceModel,
                PlatformPluginV2ApplyStateEventModel,
            )
        ]
    )


async def _competing_request(factory, snapshot):
    async with factory() as other:
        pid = await other.scalar(text("SELECT pg_backend_pid()"))
        repository = PlatformPluginRepositoryV2(other)
        version = await repository.allocate_publication_version()
        envelope = control_envelope_v2(snapshot, version=version)
        await repository.record_requested_distribution(snapshot, envelope)
        await other.commit()
        return pid, envelope


async def test_root_stage_observes_committed_lineage_on_another_backend(root_sessions, monkeypatch):
    app = FastAPI()
    original = PlatformPluginRuntimeHostV2.apply
    observations = []

    async def apply(host, snapshot, envelope, **kwargs):
        stage = kwargs["publication_stager"]

        async def observe(generation):
            # Keep A checked out throughout B's read; pool reuse cannot fake two backends.
            async with root_sessions() as held:
                pid_a = await held.scalar(text("SELECT pg_backend_pid()"))
                async with root_sessions() as other:
                    pid_b = await other.scalar(text("SELECT pg_backend_pid()"))
                    assert pid_a != pid_b
                    assert await _counts(other) == (1, 1, 0)
                    row = (await other.scalars(select(PlatformPluginV2PublicationModel))).one()
                    assert row.nonce == envelope.nonce
                    source = await PlatformPluginPublicationSourceRepositoryV2(other).read(
                        scope=ROOT, publication_id=row.id
                    )
                    assert source is not None
                    observations.append((pid_a, pid_b))
                return await stage(generation)

        return await original(host, snapshot, envelope, **{**kwargs, "publication_stager": observe})

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=root_sessions)
        assert len(observations) == 1
        assert host.current_publication.accepted
        assert app.state.platform_plugin_runtime_v2 is host
        async with root_sessions() as session:
            assert await _counts(session) == (1, 1, 1)
            durable = await PlatformPluginRepositoryV2(session).last_good_distribution(
                "python-api-v2"
            )
            assert durable == host.current_distribution.to_payload()
    finally:
        await shutdown_plugin_runtime_v2(app)


async def test_root_restore_rejects_new_request_committed_during_stage(root_sessions, monkeypatch):
    first = FastAPI()
    try:
        saved_host = await initialize_plugin_runtime_v2(first, session_factory=root_sessions)
        saved = saved_host.current_publication
    finally:
        await shutdown_plugin_runtime_v2(first)
    original = PlatformPluginRuntimeHostV2.apply
    hosts, observations = [], []

    async def apply(host, snapshot, envelope, **kwargs):
        hosts.append(host)
        assert envelope == saved.envelope
        stage = kwargs["publication_stager"]

        async def race(generation):
            async with root_sessions() as held:
                pid_a = await held.scalar(text("SELECT pg_backend_pid()"))
                pid_b, newer = await _competing_request(root_sessions, snapshot)
                assert pid_a != pid_b
                observations.append((pid_a, pid_b, newer))
                return await stage(generation)

        return await original(host, snapshot, envelope, **{**kwargs, "publication_stager": race})

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    restarted = FastAPI()
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await initialize_plugin_runtime_v2(restarted, session_factory=root_sessions)
        assert caught.value.code == "root_recovery_changed"
        assert len(observations) == 1
        assert len(hosts) == 1 and hosts[0].manager.current is None
        assert getattr(restarted.state, "platform_plugin_runtime_v2", None) is None
        async with root_sessions() as session:
            assert await _counts(session) == (2, 1, 1)
            repository = PlatformPluginRepositoryV2(session)
            assert (await repository.latest_requested_distribution())["envelope"] == (
                control_envelope_v2_to_payload(observations[0][2])
            )
            assert (await repository.last_good_distribution("python-api-v2"))["envelope"] == (
                control_envelope_v2_to_payload(saved.envelope)
            )
    finally:
        await shutdown_plugin_runtime_v2(restarted)


async def test_root_first_start_rejects_receipt_after_concurrent_allocator(
    root_sessions, monkeypatch
):
    original = PlatformPluginRuntimeHostV2.apply
    hosts, observations = [], []

    async def apply(host, snapshot, envelope, **kwargs):
        hosts.append(host)
        stage = kwargs["publication_stager"]

        async def race(generation):
            async with root_sessions() as held:
                pid_a = await held.scalar(text("SELECT pg_backend_pid()"))
                pid_b, newer = await _competing_request(root_sessions, snapshot)
                assert pid_a != pid_b
                assert newer.version > envelope.version
                observations.append((pid_a, pid_b, newer))
                return await stage(generation)

        return await original(host, snapshot, envelope, **{**kwargs, "publication_stager": race})

    monkeypatch.setattr(PlatformPluginRuntimeHostV2, "apply", apply)
    app = FastAPI()
    try:
        with pytest.raises(PlatformPluginLedgerV2Error) as caught:
            await initialize_plugin_runtime_v2(app, session_factory=root_sessions)
        assert caught.value.code == "stale_receipt"
        assert len(observations) == 1
        assert len(hosts) == 1 and hosts[0].manager.current is None
        assert getattr(app.state, "platform_plugin_runtime_v2", None) is None
        async with root_sessions() as session:
            assert await _counts(session) == (2, 1, 0)
            repository = PlatformPluginRepositoryV2(session)
            assert await repository.last_good_distribution("python-api-v2") is None
            assert (await repository.latest_requested_distribution())["envelope"] == (
                control_envelope_v2_to_payload(observations[0][2])
            )
    finally:
        await shutdown_plugin_runtime_v2(app)
