"""V2 application seam coverage for Agent execution resume."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_execution_resume_services import (
    AGENT_EXECUTION_RESUME_MODULE_V2,
    AGENT_EXECUTION_RESUME_REPOSITORIES_INJECT_V2,
    AGENT_EXECUTION_RESUME_SERVICE_V2,
    AgentExecutionResumeResolverV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/agent/events.py"


async def test_execution_resume_resolver_uses_exact_operation_checkpoint_repository() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1000,
        version=1000,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-execution-resume:root",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(AGENT_EXECUTION_RESUME_SERVICE_V2)

            assert isinstance(resolver, AgentExecutionResumeResolverV2)
            service = resolver.resolve(operation)
            checkpoint_repository = getattr(service, "_checkpoint_repo", None)
            assert getattr(checkpoint_repository, "_session", None) is db
    finally:
        await db.close()
        await host.close()


def test_execution_resume_module_is_an_explicit_ordered_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2 in enabled_modules
    assert AGENT_EXECUTION_RESUME_MODULE_V2 in enabled_modules
    assert enabled_modules.index(CONVERSATION_CRUD_REPOSITORY_PROVIDER_MODULE_V2) < (
        enabled_modules.index(AGENT_EXECUTION_RESUME_MODULE_V2)
    )
    entry = next(
        entry for entry in document.entries if entry.module_ref == AGENT_EXECUTION_RESUME_MODULE_V2
    )
    assert entry.inject == {
        AGENT_EXECUTION_RESUME_REPOSITORIES_INJECT_V2: (
            "service:persistence.conversation-crud-repository-provider"
        )
    }


async def test_execution_resume_rejects_missing_repository_inject_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    invalid = replace(
        document,
        entries=tuple(
            replace(entry, inject={})
            if entry.module_ref == AGENT_EXECUTION_RESUME_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(invalid, {manifest.plugin_id: manifest}, generation=1001)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_required_inject"
    assert "builtin-agent-execution-resume" in str(error.value)


async def test_execution_resume_resolver_rejects_non_session_operation_service() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1002,
        version=1002,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-execution-resume:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(AGENT_EXECUTION_RESUME_SERVICE_V2)
            assert isinstance(resolver, AgentExecutionResumeResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                _ = resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


def test_resume_route_has_no_static_checkpoint_construction() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "_get_resume_service" not in source
    assert "SqlExecutionCheckpointRepository" not in source
