"""V2 Provider/Consumer coverage for Cron application operations."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.cron.cron_job import CronJob
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.cron_services import (
    CRON_APPLICATION_MODULE_V2,
    CRON_APPLICATION_SERVICE_V2,
    CRON_PERSISTENCE_PROVIDER_MODULE_V2,
    CRON_SCHEDULER_GATEWAY_MODULE_V2,
    CronApplicationResolverV2,
    CronProjectAccessDeniedV2,
    SqlCronProjectAccessV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_cron_resolver_builds_every_service_from_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=101,
        version=101,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="cron:project-a",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(CRON_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, CronApplicationResolverV2)
            services = resolver.resolve(operation)
            assert getattr(services.cron_jobs._cron_job_repo, "_session", None) is db
            assert getattr(services.cron_jobs._cron_job_run_repo, "_session", None) is db
            assert getattr(services.commands._repository, "_session", None) is db
            assert getattr(services.access, "_session", None) is db
    finally:
        await db.close()
        await host.close()


def test_cron_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    for module_ref in (
        CRON_SCHEDULER_GATEWAY_MODULE_V2,
        CRON_PERSISTENCE_PROVIDER_MODULE_V2,
        CRON_APPLICATION_MODULE_V2,
    ):
        assert module_ref in enabled_modules
    assert enabled_modules.index(CRON_PERSISTENCE_PROVIDER_MODULE_V2) < enabled_modules.index(
        CRON_APPLICATION_MODULE_V2
    )
    application_entry = next(
        entry for entry in document.entries if entry.module_ref == CRON_APPLICATION_MODULE_V2
    )
    assert application_entry.inject == {
        "projects": "service:application.project-tenant-services",
        "provider": "service:persistence.cron-provider",
        "scheduler": "service:runtime.cron-scheduler-gateway",
    }


async def test_cron_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == CRON_PERSISTENCE_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=102)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-cron-services" in str(error.value)


async def test_cron_project_access_uses_operation_owned_membership_reader() -> None:
    result = Mock(scalar_one_or_none=Mock(return_value="membership-a"))
    db = AsyncMock(execute=AsyncMock(return_value=result))
    access = SqlCronProjectAccessV2(_session=cast(AsyncSession, db))

    await access.require_project_access(project_id="project-a", user_id="user-a")

    db.execute.assert_awaited_once()


async def test_cron_project_access_fails_closed_for_non_member() -> None:
    result = Mock(scalar_one_or_none=Mock(return_value=None))
    db = AsyncMock(execute=AsyncMock(return_value=result))
    access = SqlCronProjectAccessV2(_session=cast(AsyncSession, db))

    with pytest.raises(CronProjectAccessDeniedV2):
        await access.require_project_access(project_id="project-a", user_id="user-a")


async def test_cron_scheduler_calls_are_generation_owned_and_best_effort() -> None:
    scheduler = SimpleNamespace(
        register=AsyncMock(side_effect=RuntimeError("scheduler unavailable")),
        unregister=AsyncMock(side_effect=RuntimeError("scheduler unavailable")),
    )
    services = SimpleNamespace(scheduler=scheduler)
    job = CronJob(project_id="project-a", tenant_id="tenant-a", name="job")

    from src.infrastructure.plugins.v2.cron_services import sync_cron_schedule_v2

    await sync_cron_schedule_v2(services, job=job, enabled=True)
    await sync_cron_schedule_v2(services, job=job, enabled=False)

    scheduler.register.assert_awaited_once()
    scheduler.unregister.assert_awaited_once_with(job.id)
