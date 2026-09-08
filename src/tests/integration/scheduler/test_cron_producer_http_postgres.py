"""A real responding worker serves authorized V2 HTTP inspection and closure."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from apscheduler import AsyncScheduler
from apscheduler.datastores.memory import MemoryDataStore
from apscheduler.eventbrokers.local import LocalEventBroker
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.cron.cutover import CronDeploymentManifest
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
    SqlCronCutoverRepository,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_cron_http_routes import cron_route_definitions_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.scheduler import scheduler_service
from src.tests.unit.domain.model.cron.test_cutover import manifest_wire

pytestmark = pytest.mark.integration
PATH = "/api/v1/admin/cron-producer"


def close_body(**patch):
    return {
        "deployment_id": "deployment-1",
        "source_generation": "python-old",
        "producer_id": "python-api-1",
        "expected_revision": 1,
        "schedule_ids": ["job"],
    } | patch


@asynccontextmanager
async def live_http(database, monkeypatch):
    from src.infrastructure.adapters.secondary.persistence import database as database_module

    _, sessions = database
    monkeypatch.setattr(database_module, "async_session_factory", sessions)
    monkeypatch.setattr(scheduler_service, "_scheduler_lock", asyncio.Lock())
    monkeypatch.setattr(scheduler_service, "_cron_registration_seal", None)
    async with AsyncScheduler(
        identity="python-api-1", data_store=MemoryDataStore(), event_broker=LocalEventBroker()
    ) as scheduler:
        monkeypatch.setattr(scheduler_service, "_scheduler", scheduler)
        monkeypatch.setattr(scheduler_service, "start_scheduler", AsyncMock(return_value=scheduler))
        monkeypatch.setattr(scheduler_service, "sync_all_jobs", AsyncMock())
        monkeypatch.setattr(scheduler_service, "stop_scheduler", AsyncMock())
        await scheduler_service.register_job(
            job_id="job", schedule_type="every", schedule_config={"interval_seconds": 3600}
        )

        async def admin():
            return SimpleNamespace(id="admin", is_superuser=True)

        graph = build_builtin_route_graph_v2(
            workspace_core_settings=get_workspace_core_settings(),
            route_definitions=cron_route_definitions_v2(),
            dependency_overrides={get_current_user: admin},
        )
        host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
        try:
            publication = await host.bootstrap(
                profile_path="config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
                generation=601,
                version=601,
            )
            assert publication.accepted
            distribution = host.current_distribution
            registry = RouteTableRegistryV2()
            await registry.publish(distribution.descriptor, graph.table)
            app = FastAPI()
            app.state.platform_plugin_route_registry_v2 = registry
            mount_generation_http_dispatcher_v2(app)
            async with (
                pin_operation_context_v2(
                    host, operation_id="producer-http", scope=ScopeV2(kind=ScopeKindV2.ROOT)
                ),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client,
            ):
                yield client, sessions, scheduler, app
        finally:
            await host.close()


async def test_http_inspect_prepare_close_preserves_hitl_and_fences_restart(database, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from time import monotonic

    from apscheduler.triggers.date import DateTrigger

    from src.infrastructure.adapters.secondary.persistence.models import (
        AgentSessionSnapshot,
        CronSchedulerOwnerModel,
        HITLRequest,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
        SqlLegacyCronAdmissionRepository,
    )
    from src.tests.integration.scheduler.test_legacy_cron_admission import admit

    async with live_http(database, monkeypatch) as (client, sessions, scheduler, _app):
        await scheduler.add_schedule(
            monotonic, DateTrigger(datetime.now(UTC) + timedelta(days=1)), id="unrelated"
        )
        before = (await client.get(PATH)).json()
        assert before["responding_producer_id"] == "python-api-1"
        assert before["datastore_view"]["scope"] == "shared_scheduler_datastore"
        assert before["datastore_view"]["canonical_cron_schedule_ids"] == ["job"]
        assert before["discovery_complete"] is False
        rejected = await client.post(f"{PATH}/close", json=close_body())
        assert rejected.json()["observation"] == "unresolved"
        assert await scheduler.get_schedule("job")
        async with sessions() as session:
            identity = await admit(session)
            admissions = SqlLegacyCronAdmissionRepository(session)
            ticket = await admissions.claim_execution(identity)
            assert await admissions.park_for_hitl(ticket)
            session.add(
                HITLRequest(
                    id="request",
                    request_type="decision",
                    conversation_id="conversation",
                    tenant_id="tenant",
                    project_id="project",
                    question="Continue?",
                    status="pending",
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            session.add(
                AgentSessionSnapshot(
                    id="snapshot",
                    tenant_id="tenant",
                    project_id="project",
                    agent_mode="default",
                    request_id="request",
                    snapshot_type="hitl",
                    snapshot_data={"retain": True},
                )
            )
            await SqlCronCutoverRepository(session).prepare(
                CronDeploymentManifest.from_wire(manifest_wire()), 0
            )
            await session.commit()
            owner = await session.get(CronSchedulerOwnerModel, "global")
            expected = owner.owner_epoch, owner.cutover_revision, owner.cutover_evidence
        for patch in (
            {"producer_id": "wrong-worker"},
            {"expected_revision": 2},
            {"deployment_id": "other"},
            {"source_generation": "other"},
        ):
            response = await client.post(f"{PATH}/close", json=close_body(**patch))
            assert response.json()["observation"] == "unresolved"
            assert await scheduler.get_schedule("job")
        response = await client.post(f"{PATH}/close", json=close_body())
        assert response.status_code == 200
        assert response.json()["observation"] == "closed"
        assert response.json()["verified"] is False
        recovered = (await client.get(PATH)).json()
        assert recovered["local_registration_sealed"] is True
        assert recovered["datastore_view"]["canonical_cron_schedule_ids"] == []
        assert {item.id for item in await scheduler.get_schedules()} == {"unrelated"}
        async with sessions() as session:
            owner = await session.get(CronSchedulerOwnerModel, "global")
            assert (owner.owner_epoch, owner.cutover_revision, owner.cutover_evidence) == expected
            assert (await session.get(HITLRequest, "request")).status == "pending"
            assert (await session.get(AgentSessionSnapshot, "snapshot")).snapshot_data == {
                "retain": True
            }
            admissions = SqlLegacyCronAdmissionRepository(session)
            resumed = await admissions.claim_execution(identity, resume=True)
            assert await admissions.complete(resumed, "success")
            await session.commit()
        monkeypatch.setattr(scheduler_service, "_cron_registration_seal", None)
        with pytest.raises(scheduler_service.CronProducerRegistrationClosed):
            await scheduler_service.register_job(
                job_id="job", schedule_type="every", schedule_config={"interval_seconds": 60}
            )


async def test_cancelled_close_can_recover_current_state_without_receipt_claim(
    database, monkeypatch
):
    async with live_http(database, monkeypatch) as (client, sessions, scheduler, app):
        async with sessions() as session:
            await SqlCronCutoverRepository(session).prepare(
                CronDeploymentManifest.from_wire(manifest_wire()), 0
            )
            await session.commit()
        removing = asyncio.Event()
        original_remove = AsyncScheduler.remove_schedule

        async def blocked_remove(_self, _identity):
            removing.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(AsyncScheduler, "remove_schedule", blocked_remove)
        task = asyncio.create_task(client.post(f"{PATH}/close", json=close_body()))
        await asyncio.wait_for(removing.wait(), 3)
        task.cancel()
        try:
            response = await task
        except asyncio.CancelledError:
            pass  # A disconnected caller need not receive the adapter's unresolved observation.
        else:
            assert response.json()["observation"] == "unresolved"
        recovered = await client.get(PATH)
        assert recovered.status_code == 200
        assert recovered.json()["local_registration_sealed"] is True
        assert recovered.json()["verified"] is False
        assert recovered.json()["datastore_view"]["canonical_cron_schedule_ids"] == ["job"]
        assert await scheduler.get_schedule("job")
        monkeypatch.setattr(AsyncScheduler, "remove_schedule", original_remove)

        async def disconnected_app(scope, receive, _send):
            async def lost_response(_message):
                raise asyncio.CancelledError("client connection lost before response delivery")

            await app(scope, receive, lost_response)

        # The close can settle even if transport cannot deliver its result.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=disconnected_app), base_url="http://test"
        ) as disconnected:
            with pytest.raises(asyncio.CancelledError):
                await disconnected.post(f"{PATH}/close", json=close_body())
        inspected = (await client.get(PATH)).json()
        assert inspected["local_registration_sealed"] is True
        assert inspected["datastore_view"]["canonical_cron_schedule_ids"] == []
        assert inspected["verified"] is False
