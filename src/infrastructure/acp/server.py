"""MemStack ACP agent implementation."""
# ruff: noqa: ANN401

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from acp import PROTOCOL_VERSION, RequestError
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities,
    CloseSessionResponse,
    Implementation,
    InitializeResponse,
    McpCapabilities,
    NewSessionResponse,
    PromptCapabilities,
    PromptResponse,
    SessionCapabilities,
    SessionCloseCapabilities,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.configuration.config import Settings, get_settings
from src.infrastructure.acp.conversation_authority_v2 import (
    acp_conversation_access_authority_v2,
    acp_conversation_collection_authority_v2,
)
from src.infrastructure.acp.event_mapper import ACPUpdate, memstack_event_to_acp_updates
from src.infrastructure.plugins.v2.agent_turn_projection import current_agent_turn_service_v2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_agent_turn_operation_v2,
)

logger = logging.getLogger(__name__)

EmitUpdate = Callable[[str, ACPUpdate], Awaitable[None]]


@dataclass(slots=True)
class ACPSessionState:
    session_id: str
    conversation_id: str
    project_id: str
    cwd: str
    current_prompt_task: asyncio.Task[Any] | None = None


class MemStackACPAgent:
    """ACP Agent facade over MemStack conversations and stream events."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        user_id: str,
        tenant_id: str,
        api_key: str | None = None,
        emit_update: EmitUpdate | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._api_key = api_key
        self._emit_update_callback = emit_update
        self._settings = settings or get_settings()
        self._client: Client | None = None
        self._sessions: dict[str, ACPSessionState] = {}

    def on_connect(self, conn: Client) -> None:
        self._client = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any | None = None,
        client_info: Any | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        """Negotiate ACP protocol version and text-only prompt capability."""
        del protocol_version, client_capabilities, client_info, kwargs
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_info=Implementation(
                name="memstack",
                title="MemStack",
                version=os.environ.get("MEMSTACK_VERSION", "0.1.0"),
            ),
            agent_capabilities=AgentCapabilities(
                load_session=False,
                prompt_capabilities=PromptCapabilities(
                    audio=False,
                    embedded_context=False,
                    image=False,
                ),
                mcp_capabilities=McpCapabilities(http=False, sse=False),
                session_capabilities=SessionCapabilities(close=SessionCloseCapabilities()),
            ),
            auth_methods=[],
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        """Create a MemStack conversation and expose it as an ACP session."""
        if not Path(cwd).is_absolute():
            raise RequestError.invalid_params({"field": "cwd", "message": "cwd must be absolute"})
        for directory in additional_directories or []:
            if not Path(directory).is_absolute():
                raise RequestError.invalid_params(
                    {"field": "additionalDirectories", "message": "all paths must be absolute"}
                )

        project_id = self._extract_project_id(kwargs)
        if not project_id:
            raise RequestError.invalid_params(
                {
                    "field": "_meta.memstack.projectId",
                    "message": "projectId is required when ACP_DEFAULT_PROJECT_ID is unset",
                }
            )

        async with (
            self._session_factory() as db,
            acp_conversation_collection_authority_v2(
                operation_id=f"acp-session-create:{uuid.uuid4()}",
                db=db,
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                project_id=project_id,
            ) as authority,
        ):
            conversation = await authority.service.create_conversation(
                project_id=project_id,
                user_id=self._user_id,
                tenant_id=self._tenant_id,
                title=f"ACP: {Path(cwd).name or cwd}",
                agent_config={
                    "source": "acp",
                    "cwd": cwd,
                    "additional_directories": additional_directories or [],
                    "mcp_servers": [_dump_model(server) for server in mcp_servers or []],
                },
            )
            await db.commit()
            try:
                await authority.service.after_create_committed(conversation)
            except Exception as exc:
                logger.error(
                    "[ACP] Conversation post-commit dispatch failed: error_type=%s",
                    type(exc).__name__,
                )

        session_id = conversation.id
        self._sessions[session_id] = ACPSessionState(
            session_id=session_id,
            conversation_id=conversation.id,
            project_id=project_id,
            cwd=cwd,
        )
        return NewSessionResponse(session_id=session_id)

    async def prompt(
        self,
        prompt: list[Any],
        session_id: str,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> PromptResponse:
        """Run one MemStack chat turn for an ACP prompt."""
        del kwargs
        session = self._require_session(session_id)
        user_message = self._prompt_to_text(prompt)
        current_task = asyncio.current_task()
        session.current_prompt_task = current_task
        usage = None

        try:
            async with self._session_factory() as db:
                operation_message_id = message_id or str(uuid.uuid4())
                async with pin_agent_turn_operation_v2(
                    operation_id=f"acp-turn:{operation_message_id}",
                    tenant_id=self._tenant_id,
                    project_id=session.project_id,
                    session_id=session.conversation_id,
                    services={
                        OPERATION_DB_SESSION_SERVICE_V2: db,
                        OPERATION_IDENTITY_SERVICE_V2: {
                            "tenant_id": self._tenant_id,
                            "user_id": self._user_id,
                            "project_id": session.project_id,
                        },
                        OPERATION_METADATA_SERVICE_V2: {
                            "kind": "agent-turn",
                            "channel": "acp",
                            "conversation_id": session.conversation_id,
                            "message_id": message_id,
                        },
                    },
                ):
                    service = await current_agent_turn_service_v2()
                    agent_stream = cast(
                        AsyncGenerator[dict[str, Any], None],
                        service.stream_chat_v2(
                            conversation_id=session.conversation_id,
                            user_message=user_message,
                            project_id=session.project_id,
                            user_id=self._user_id,
                            tenant_id=self._tenant_id,
                            api_auth_token=self._api_key,
                        ),
                    )
                    async with aclosing(agent_stream) as events:
                        async for event in events:
                            for update in memstack_event_to_acp_updates(event):
                                await self._emit_update(session_id, update)
                            if str(event.get("type") or "") in {"complete", "error"}:
                                return PromptResponse(
                                    stop_reason="end_turn",
                                    user_message_id=message_id,
                                    usage=usage,
                                )
            return PromptResponse(
                stop_reason="end_turn",
                user_message_id=message_id,
                usage=usage,
            )
        except asyncio.CancelledError:
            return PromptResponse(
                stop_reason="cancelled",
                user_message_id=message_id,
                usage=usage,
            )
        finally:
            if session.current_prompt_task is current_task:
                session.current_prompt_task = None

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        """Cancel the active ACP prompt and the underlying MemStack execution."""
        del kwargs
        session = self._sessions.get(session_id)
        if session is None:
            return

        if session.current_prompt_task is not None:
            session.current_prompt_task.cancel()

        await self._cancel_underlying_execution(session)

    async def close_session(self, session_id: str, **kwargs: Any) -> CloseSessionResponse:
        """Close ACP session state without deleting the MemStack conversation."""
        del kwargs
        session = self._sessions.get(session_id)
        if session is not None and session.current_prompt_task is not None:
            await self.cancel(session_id)
        self._sessions.pop(session_id, None)
        return CloseSessionResponse()

    async def _emit_update(self, session_id: str, update: ACPUpdate) -> None:
        if self._emit_update_callback is not None:
            await self._emit_update_callback(session_id, update)
            return
        if self._client is not None:
            await self._client.session_update(session_id=session_id, update=update)

    async def _cancel_underlying_execution(self, session: ACPSessionState) -> None:
        from src.application.services.agent.runtime_cancellation import (
            cancel_conversation_runtime,
        )

        async with (
            self._session_factory() as db,
            acp_conversation_access_authority_v2(
                operation_id=f"acp-cancel:{session.session_id}:{uuid.uuid4()}",
                db=db,
                tenant_id=self._tenant_id,
                user_id=self._user_id,
                project_id=session.project_id,
                conversation_id=session.conversation_id,
            ) as authority,
        ):
            conversation = await authority.service.get_conversation(
                conversation_id=session.conversation_id,
                project_id=session.project_id,
                user_id=self._user_id,
            )
            if conversation is None or conversation.tenant_id != self._tenant_id:
                return
            _ = await cancel_conversation_runtime(conversation)

    def _extract_project_id(self, kwargs: dict[str, Any]) -> str | None:
        memstack_meta = kwargs.get("memstack")
        if isinstance(memstack_meta, dict):
            project_id = memstack_meta.get("projectId") or memstack_meta.get("project_id")
            if isinstance(project_id, str) and project_id:
                return project_id
        project_id = kwargs.get("projectId") or kwargs.get("project_id")
        if isinstance(project_id, str) and project_id:
            return project_id
        return self._settings.acp_default_project_id

    def _require_session(self, session_id: str) -> ACPSessionState:
        session = self._sessions.get(session_id)
        if session is None:
            raise RequestError.resource_not_found(session_id)
        return session

    def _prompt_to_text(self, prompt: list[Any]) -> str:
        parts: list[str] = []
        for block in prompt:
            block_type = getattr(block, "type", None)
            if block_type != "text":
                raise RequestError.invalid_params(
                    {
                        "field": "prompt",
                        "message": "MemStack ACP v1 supports text content blocks only",
                        "unsupportedType": block_type,
                    }
                )
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        if not parts:
            raise RequestError.invalid_params(
                {"field": "prompt", "message": "at least one text block is required"}
            )
        return "\n\n".join(parts)


def _dump_model(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value
