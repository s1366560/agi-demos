"""V2 repository and application seams for Agent recovery streaming."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2 import (
    agent_recovery_stream_services as recovery_module,
    llm_client_service as llm_module,
)
from src.infrastructure.plugins.v2.agent_recovery_stream_services import (
    AGENT_RECOVERY_STREAM_LLM_CLIENTS_INJECT_V2,
    AGENT_RECOVERY_STREAM_MODULE_V2,
    AGENT_RECOVERY_STREAM_REDIS_INJECT_V2,
    AGENT_RECOVERY_STREAM_REPOSITORIES_INJECT_V2,
    AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_MODULE_V2,
    AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_SERVICE_V2,
    AGENT_RECOVERY_STREAM_SERVICE_V2,
    AgentRecoveryStreamResolverV2,
    AgentRecoveryStreamServiceV2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.llm_client_service import TENANT_LLM_CLIENT_FACTORY_SERVICE_V2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.redis_runtime import REDIS_RUNTIME_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_resolver_builds_recovery_service_from_exact_operation_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = SimpleNamespace(name="generation-redis")
    llm_client = object()
    created_repositories: dict[str, object] = {}

    def repository(name: str):
        def build(db: AsyncSession) -> object:
            value = SimpleNamespace(name=name, db=db)
            created_repositories[name] = value
            return value

        return build

    monkeypatch.setattr(
        recovery_module,
        "SqlConversationRepository",
        repository("conversation"),
    )
    monkeypatch.setattr(
        recovery_module,
        "SqlAgentExecutionRepository",
        repository("execution"),
    )
    monkeypatch.setattr(
        recovery_module,
        "SqlToolExecutionRecordRepository",
        repository("tool-record"),
    )
    monkeypatch.setattr(
        recovery_module,
        "SqlAgentExecutionEventRepository",
        repository("execution-event"),
    )
    create_llm = AsyncMock(return_value=llm_client)
    monkeypatch.setattr(llm_module.TenantLlmClientFactoryV2, "create", create_llm)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_redis_client=redis_client)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=946,
        version=946,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-recovery-stream",
                scope=ScopeV2(
                    kind=ScopeKindV2.SESSION,
                    tenant_id="tenant-a",
                    project_id="project-a",
                    session_id="conversation-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            _ = operation.provide(
                OPERATION_IDENTITY_SERVICE_V2,
                {"tenant_id": "tenant-a", "user_id": "user-a"},
            )
            resolver = operation.require(AGENT_RECOVERY_STREAM_SERVICE_V2)

            assert isinstance(resolver, AgentRecoveryStreamResolverV2)
            service = await resolver.resolve(operation)
            assert isinstance(service, AgentRecoveryStreamServiceV2)
            assert cast(Any, service)._conversation_repo is created_repositories["conversation"]
            assert cast(Any, service)._execution_repo is created_repositories["execution"]
            assert (
                cast(Any, service)._tool_execution_record_repo
                is created_repositories["tool-record"]
            )
            assert (
                cast(Any, service)._agent_execution_event_repo
                is created_repositories["execution-event"]
            )
            assert cast(Any, service)._redis_client is redis_client
            assert cast(Any, service)._llm is llm_client
            create_llm.assert_awaited_once_with(db=db, tenant_id="tenant-a")
            assert {cast(Any, value).db for value in created_repositories.values()} == {db}
    finally:
        await db.close()
        await host.close()


def test_recovery_stream_consumer_uses_only_declared_provider_aliases() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[AGENT_RECOVERY_STREAM_MODULE_V2].inject == {
        AGENT_RECOVERY_STREAM_REPOSITORIES_INJECT_V2: (
            AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_SERVICE_V2
        ),
        AGENT_RECOVERY_STREAM_LLM_CLIENTS_INJECT_V2: TENANT_LLM_CLIENT_FACTORY_SERVICE_V2,
        AGENT_RECOVERY_STREAM_REDIS_INJECT_V2: REDIS_RUNTIME_SERVICE_V2,
    }
    assert ordered_modules.index(
        AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_MODULE_V2
    ) < ordered_modules.index(AGENT_RECOVERY_STREAM_MODULE_V2)


async def test_missing_recovery_repository_provider_is_rejected_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == AGENT_RECOVERY_STREAM_REPOSITORY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=947,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-agent-recovery-stream" in str(error.value)


async def test_recovery_stream_fails_closed_when_generation_redis_is_unavailable() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=948,
        version=948,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-recovery-no-redis",
                scope=ScopeV2(
                    kind=ScopeKindV2.SESSION,
                    tenant_id="tenant-a",
                    project_id="project-a",
                    session_id="conversation-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            _ = operation.provide(
                OPERATION_IDENTITY_SERVICE_V2,
                {"tenant_id": "tenant-a", "user_id": "user-a"},
            )
            resolver = operation.require(AGENT_RECOVERY_STREAM_SERVICE_V2)

            with pytest.raises(RuntimeV2Error) as error:
                await cast(AgentRecoveryStreamResolverV2, resolver).resolve(operation)

            assert error.value.code == "agent_recovery_redis_unavailable"
    finally:
        await db.close()
        await host.close()
