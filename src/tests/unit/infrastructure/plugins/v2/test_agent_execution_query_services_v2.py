"""V2 Provider/Consumer coverage for Agent execution queries."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.agent.conversation_manager import ConversationManager
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_execution_query_services import (
    AGENT_EXECUTION_QUERY_MODULE_V2,
    AGENT_EXECUTION_QUERY_SERVICE_V2,
    AGENT_EXECUTION_REPOSITORY_PROVIDER_MODULE_V2,
    AgentExecutionQueryApplicationServicesV2,
    AgentExecutionQueryResolverV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_agent_execution_query_resolver_uses_operation_session_without_llm() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=81,
        version=81,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-execution-query:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(AGENT_EXECUTION_QUERY_SERVICE_V2)

            assert isinstance(resolver, AgentExecutionQueryResolverV2)
            services = resolver.resolve(operation)
            conversation_repository = getattr(services.manager, "_conversation_repo", None)
            execution_repository = getattr(services.manager, "_execution_repo", None)
            assert getattr(conversation_repository, "_session", None) is db
            assert getattr(execution_repository, "_session", None) is db
            assert not hasattr(services, "llm")
    finally:
        await db.close()
        await host.close()


def test_agent_execution_query_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2 in enabled_modules
    assert AGENT_EXECUTION_REPOSITORY_PROVIDER_MODULE_V2 in enabled_modules
    assert AGENT_EXECUTION_QUERY_MODULE_V2 in enabled_modules
    assert enabled_modules.index(
        CONVERSATION_REPOSITORY_PROVIDER_MODULE_V2
    ) < enabled_modules.index(AGENT_EXECUTION_QUERY_MODULE_V2)
    assert enabled_modules.index(AGENT_EXECUTION_REPOSITORY_PROVIDER_MODULE_V2) < (
        enabled_modules.index(AGENT_EXECUTION_QUERY_MODULE_V2)
    )
    application_entry = next(
        entry for entry in document.entries if entry.module_ref == AGENT_EXECUTION_QUERY_MODULE_V2
    )
    assert application_entry.inject == {
        "conversation_repository_provider": "service:persistence.conversation-repository-provider",
        "execution_repository_provider": (
            "service:persistence.agent-execution-repository-provider"
        ),
    }


async def test_agent_execution_query_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == AGENT_EXECUTION_REPOSITORY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=82)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-agent-execution-query" in str(error.value)


async def test_agent_execution_query_resolver_rejects_non_session_operation_service() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=83,
        version=83,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-execution-query:invalid-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, object())
            resolver = operation.require(AGENT_EXECUTION_QUERY_SERVICE_V2)
            assert isinstance(resolver, AgentExecutionQueryResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                _ = resolver.resolve(operation)

            assert error.value.code == "invalid_operation_db_session"
    finally:
        await host.close()


async def test_agent_execution_query_application_delegates_exact_scope() -> None:
    get_execution_history = AsyncMock(return_value=[{"id": "execution-a"}])
    manager = cast(
        ConversationManager,
        SimpleNamespace(get_execution_history=get_execution_history),
    )
    services = AgentExecutionQueryApplicationServicesV2(manager=manager)

    result = await services.get_execution_history(
        conversation_id="conversation-a",
        project_id="project-a",
        user_id="user-a",
        limit=17,
    )

    assert result == [{"id": "execution-a"}]
    get_execution_history.assert_awaited_once_with(
        conversation_id="conversation-a",
        project_id="project-a",
        user_id="user-a",
        limit=17,
    )
