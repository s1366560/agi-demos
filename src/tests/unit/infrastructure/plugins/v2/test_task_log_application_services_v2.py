"""V2 persistence and application seams for durable task logs."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.task_log_services import (
    TASK_LOG_APPLICATION_MODULE_V2,
    TASK_LOG_APPLICATION_SERVICE_V2,
    TASK_LOG_REPOSITORY_INJECT_V2,
    TASK_LOG_REPOSITORY_PROVIDER_MODULE_V2,
    TASK_LOG_REPOSITORY_PROVIDER_SERVICE_V2,
    TaskLogApplicationResolverV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_resolver_builds_task_log_use_cases_from_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=154,
        version=154,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="http-task-log-application",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(TASK_LOG_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, TaskLogApplicationResolverV2)
            services = resolver.resolve(operation)
            assert services.get_task._task_repo._session is db
            assert services.update_task._task_repo._session is db
    finally:
        await db.close()
        await host.close()


def test_task_log_consumer_uses_an_explicit_repository_alias() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[TASK_LOG_APPLICATION_MODULE_V2].inject == {
        TASK_LOG_REPOSITORY_INJECT_V2: TASK_LOG_REPOSITORY_PROVIDER_SERVICE_V2,
    }
    assert ordered_modules.index(TASK_LOG_REPOSITORY_PROVIDER_MODULE_V2) < ordered_modules.index(
        TASK_LOG_APPLICATION_MODULE_V2
    )


async def test_missing_task_log_repository_provider_is_rejected_without_di_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == TASK_LOG_REPOSITORY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=155,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-task-log-services" in str(error.value)
