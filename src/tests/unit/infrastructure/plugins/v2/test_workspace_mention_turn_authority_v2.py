"""Pinned-generation authority coverage for Workspace mention turns."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import src.application.services.workspace_mention_router as mention_router_module
from src.application.services.workspace_mention_router import WorkspaceMentionRouter
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_message import (
    MessageSenderType,
    WorkspaceMessage,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    clear_process_generation_host_v2,
    current_operation_context_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_workspace_mention_turn_uses_one_process_host_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session = object()

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[object]:
        yield db_session

    router = WorkspaceMentionRouter(
        agent_repo_factory=lambda _db: object(),
        member_repo_factory=lambda _db: object(),
        message_service_factory=lambda _db, _publisher: object(),
        conversation_repo_factory=lambda _db: object(),
        db_session_factory=session_factory,
    )
    router._ensure_agent_conversation = AsyncMock()  # type: ignore[method-assign]
    router._post_agent_response = AsyncMock()  # type: ignore[method-assign]
    router._post_error_message = AsyncMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        mention_router_module,
        "_resolve_workspace_authority_context",
        AsyncMock(return_value=None),
    )

    observed: dict[str, object] = {}

    class AgentService:
        async def stream_chat_v2(self, **kwargs: object) -> AsyncIterator[dict[str, object]]:
            operation = current_operation_context_v2()
            observed["stream_operation"] = operation
            observed["db"] = operation.require(OPERATION_DB_SESSION_SERVICE_V2)
            observed["identity"] = operation.require(OPERATION_IDENTITY_SERVICE_V2)
            observed["metadata"] = operation.require(OPERATION_METADATA_SERVICE_V2)
            observed["stream_kwargs"] = dict(kwargs)
            yield {"type": "complete", "data": {"content": "Mention response"}}

    async def resolve_turn_service() -> AgentService:
        observed["resolver_operation"] = current_operation_context_v2()
        return AgentService()

    monkeypatch.setattr(
        mention_router_module,
        "current_agent_turn_service_v2",
        resolve_turn_service,
        raising=False,
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=741,
        version=741,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)

    agent = WorkspaceAgent(
        workspace_id="workspace-1",
        agent_id="agent-1",
        display_name="Agent One",
    )
    message = WorkspaceMessage(
        id="message-1",
        workspace_id="workspace-1",
        sender_id="user-1",
        sender_type=MessageSenderType.HUMAN,
        content="Please continue",
        mentions=["agent-1"],
        metadata={"sender_name": "User One"},
    )

    try:
        await router._trigger_agent(
            workspace_id="workspace-1",
            agent=agent,
            message=message,
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            chain_depth=2,
        )
    finally:
        clear_process_generation_host_v2(host)
        await host.close()

    operation = observed["stream_operation"]
    assert observed["resolver_operation"] is operation
    assert operation.descriptor.generation == 741
    assert observed["db"] is db_session
    assert observed["identity"] == {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "project_id": "project-1",
    }
    assert observed["metadata"] == {
        "kind": "workspace-mention-agent-turn",
        "workspace_id": "workspace-1",
        "conversation_id": WorkspaceMentionRouter.workspace_conversation_id(
            "workspace-1",
            "agent-1",
        ),
        "message_id": "message-1",
        "agent_id": "agent-1",
        "chain_depth": 2,
    }
    stream_kwargs = observed["stream_kwargs"]
    assert stream_kwargs["tenant_id"] == "tenant-1"
    assert stream_kwargs["project_id"] == "project-1"
    assert stream_kwargs["user_id"] == "user-1"
    assert stream_kwargs["agent_id"] == "agent-1"
    router._post_agent_response.assert_awaited_once_with(  # type: ignore[attr-defined]
        workspace_id="workspace-1",
        agent=agent,
        content="Mention response",
        user_id="user-1",
        parent_message_id="message-1",
        event_publisher=None,
        chain_depth=2,
    )


def test_workspace_mention_turn_has_no_static_agent_composition() -> None:
    constructor_source = inspect.getsource(WorkspaceMentionRouter.__init__)
    trigger_source = inspect.getsource(WorkspaceMentionRouter._trigger_agent)

    assert "agent_service_factory" not in constructor_source
    assert "agent_service_factory" not in trigger_source
    assert "create_llm_client" not in trigger_source
    assert "pin_agent_turn_operation_v2" in trigger_source
    assert "current_agent_turn_service_v2" in trigger_source
    assert "force_process_host_lease=True" in trigger_source
