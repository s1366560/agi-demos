"""Production Avernet Provider adapter backed by the MemStack Agent Runtime."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.events.types import AgentEventType
from src.domain.model.agent import AgentExecutionEvent
from src.domain.model.agent.conversation.conversation import Conversation, ConversationStatus
from src.domain.model.agent.execution.event_time import EventTimeGenerator
from src.infrastructure.workspace_core.client import (
    WorkspaceRuntimeCorrelationRequest,
    WorkspaceRuntimeCorrelationResponse,
    WorkspaceRuntimeTerminalReadResponse,
    WorkspaceRuntimeTerminalRequest,
    WorkspaceRuntimeTerminalResponse,
)
from src.infrastructure.workspace_core.provider import (
    ProviderAbortResult,
    ProviderHistoryResult,
    ProviderRuntimeEvent,
    ProviderWebhookRequest,
)

logger = logging.getLogger(__name__)

_INJECTION_EVENT_TYPE = "avernet_context_injection"
_MESSAGE_EVENT_TYPES = {"user_message", "assistant_message"}
_TERMINAL_EVENT_TYPES = {"complete", "error"}
_PROVIDER_EVENT_NAMESPACE = uuid.UUID("3f0936e7-2634-44a6-b299-0d5ba2819652")
_MAX_HISTORY_LIMIT = 200
_DEFAULT_HISTORY_LIMIT = 50
_MAX_INJECTION_CONTEXT_EVENTS = 100
# Ray persists durable execution events on a 30-second periodic flush. Keep the
# Provider callback behind that authority even when the terminal stream frame
# arrives immediately before the next flush.
_MAX_TERMINAL_PERSIST_WAIT_SECONDS = 60.0


class _ConversationRepository(Protocol):
    async def find_by_id(self, conversation_id: str) -> Conversation | None: ...

    async def save(self, conversation: Conversation) -> Conversation: ...


class _AgentExecutionEventRepository(Protocol):
    async def save_and_commit(self, event: AgentExecutionEvent) -> None: ...

    async def get_events(
        self,
        conversation_id: str,
        from_time_us: int = 0,
        from_counter: int = 0,
        limit: int = 1000,
        event_types: set[str] | None = None,
        before_time_us: int | None = None,
        before_counter: int | None = None,
    ) -> list[AgentExecutionEvent]: ...

    async def get_last_event_time(self, conversation_id: str) -> tuple[int, int]: ...

    async def get_events_by_message(
        self,
        conversation_id: str,
        message_id: str,
    ) -> list[AgentExecutionEvent]: ...


class _AgentService(Protocol):
    def stream_chat_v2(  # noqa: PLR0913
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        preferred_language: str | None = None,
        attachment_ids: list[str] | None = None,
        file_metadata: list[dict[str, Any]] | None = None,
        forced_skill_name: str | None = None,
        app_model_context: dict[str, Any] | None = None,
        image_attachments: list[str] | None = None,
        agent_id: str | None = None,
        mentions: list[str] | None = None,
        api_auth_token: str | None = None,
        execution_message_id: str | None = None,
        canonical_run_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...


class _WorkspaceCoreRuntimeClient(Protocol):
    async def record_runtime_correlation(
        self,
        request: WorkspaceRuntimeCorrelationRequest,
    ) -> WorkspaceRuntimeCorrelationResponse: ...

    async def record_runtime_terminal(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeTerminalRequest,
    ) -> WorkspaceRuntimeTerminalResponse: ...

    async def read_runtime_terminal(
        self,
        correlation_id: str,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
    ) -> WorkspaceRuntimeTerminalReadResponse: ...


class _ScopedContainer(Protocol):
    def conversation_repository(self) -> _ConversationRepository: ...

    def agent_execution_event_repository(self) -> _AgentExecutionEventRepository: ...

    def agent_service(self, llm: object) -> _AgentService: ...


class _ApplicationContainer(Protocol):
    def with_db(self, db: AsyncSession) -> _ScopedContainer: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ContainerProvider = Callable[[], _ApplicationContainer | None]
LlmFactory = Callable[[str], Awaitable[object]]


@dataclass(frozen=True, kw_only=True)
class ProviderWorkspaceScope:
    """Tenant and Workspace authority carried by a trusted Provider frame."""

    tenant_id: str
    project_id: str
    workspace_id: str
    user_id: str
    conversation_id: str
    task_id: str | None
    plan_id: str | None
    plan_node_id: str | None

    @classmethod
    def from_request(cls, request: ProviderWebhookRequest) -> ProviderWorkspaceScope:
        required = {
            name: _required_extension(request, name)
            for name in (
                "tenant_id",
                "project_id",
                "workspace_id",
                "user_id",
                "conversation_id",
            )
        }
        return cls(
            **required,
            task_id=_optional_extension(request, "task_id"),
            plan_id=_optional_extension(request, "plan_id"),
            plan_node_id=_optional_extension(request, "plan_node_id"),
        )

    @property
    def correlation(self) -> dict[str, str]:
        values = {
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "plan_node_id": self.plan_node_id,
        }
        return {key: value for key, value in values.items() if value is not None}


class MemStackAgentRuntimeProvider:
    """Bridge Provider calls into session-scoped MemStack runtime services."""

    def __init__(
        self,
        *,
        workspace_core_client: _WorkspaceCoreRuntimeClient,
        session_factory: SessionFactory | None = None,
        container_provider: ContainerProvider | None = None,
        llm_factory: LlmFactory | None = None,
        terminal_persist_wait_seconds: float = _MAX_TERMINAL_PERSIST_WAIT_SECONDS,
    ) -> None:
        super().__init__()
        if terminal_persist_wait_seconds <= 0:
            raise ValueError("terminal persistence wait must be positive")
        self._workspace_core_client = workspace_core_client
        self._session_factory = session_factory or _default_session_factory()
        self._container_provider = container_provider or _default_container_provider
        self._llm_factory = llm_factory or _default_llm_factory
        self._terminal_persist_wait_seconds = terminal_persist_wait_seconds

    async def stream_send(
        self,
        request: ProviderWebhookRequest,
    ) -> AsyncIterator[ProviderRuntimeEvent]:
        scope = ProviderWorkspaceScope.from_request(request)
        message_text = _provider_message_text(request.message)
        if not message_text:
            raise ValueError("chat.send requires a text message")

        async with self._session_factory() as db:
            scoped = self._scoped_container(db)
            conversation = await _ensure_send_conversation(
                db,
                scoped.conversation_repository(),
                scope,
                request.to_bot.provider_bot_ref,
            )
            event_repo = scoped.agent_execution_event_repository()
            message_id = _provider_message_id(request.id)
            correlation_id = _provider_correlation_id(request.id)
            correlation = await self._workspace_core_client.record_runtime_correlation(
                _runtime_correlation_request(
                    request,
                    scope=scope,
                    correlation_id=correlation_id,
                )
            )
            if not correlation.created:
                logger.info(
                    "Handling duplicate Avernet Agent Runtime delivery",
                    extra={
                        "run_id": request.id,
                        "correlation_id": correlation.correlation_id,
                        "correlation_status": correlation.status,
                        **scope.correlation,
                    },
                )
                if correlation.status in {"completed", "failed", "aborted"}:
                    terminal = await self._workspace_core_client.read_runtime_terminal(
                        correlation.correlation_id,
                        tenant_id=scope.tenant_id,
                        project_id=scope.project_id,
                        workspace_id=scope.workspace_id,
                    )
                    yield _replayed_terminal_event(terminal)
                return
            llm = await self._llm_factory(scope.tenant_id)
            service = scoped.agent_service(llm)
            app_model_context = await _workspace_model_context(
                event_repo,
                request=request,
                scope=scope,
            )
            sequence = 0
            terminal_seen = False

            try:
                async for raw_event in service.stream_chat_v2(
                    conversation_id=conversation.id,
                    user_message=message_text,
                    project_id=scope.project_id,
                    user_id=scope.user_id,
                    tenant_id=scope.tenant_id,
                    app_model_context=app_model_context,
                    image_attachments=_provider_image_urls(request),
                    agent_id=request.to_bot.provider_bot_ref or None,
                    execution_message_id=message_id,
                    canonical_run_id=request.id,
                ):
                    provider_event = _map_runtime_event(raw_event, sequence=sequence)
                    if provider_event is None:
                        continue
                    sequence += 1
                    if provider_event.state in {"final", "error"}:
                        terminal_seen = await self._prepare_terminal_event(
                            db,
                            event_repo,
                            provider_event=provider_event,
                            correlation_id=correlation_id,
                            scope=scope,
                            request_id=request.id,
                            conversation_id=conversation.id,
                            message_id=message_id,
                            timeout_seconds=min(
                                self._terminal_persist_wait_seconds,
                                request.timeout_ms / 1000,
                            ),
                        )
                        if not terminal_seen:
                            return
                    yield provider_event
                    if terminal_seen:
                        return
            except Exception:
                logger.exception(
                    "MemStack Agent Runtime Provider send failed",
                    extra={"run_id": request.id, **scope.correlation},
                )
                persisted_error = await _persist_provider_error(
                    event_repo,
                    conversation_id=conversation.id,
                    message_id=message_id,
                    request_id=request.id,
                )
                if persisted_error is None:
                    return
                provider_event = ProviderRuntimeEvent(
                    state="error",
                    sequence=sequence,
                    error_message="Agent Runtime failed",
                )
                committed = await self._commit_runtime_terminal(
                    correlation_id=correlation_id,
                    scope=scope,
                    provider_event=provider_event,
                    persisted_event=persisted_error,
                    request_id=request.id,
                )
                if not committed:
                    return
                provider_event.persisted = True
                yield provider_event

    async def inject(self, request: ProviderWebhookRequest) -> None:
        scope = ProviderWorkspaceScope.from_request(request)
        content = _provider_message_text(request.message)
        if not content:
            raise ValueError("chat.inject requires a text message")
        async with self._session_factory() as db:
            scoped = self._scoped_container(db)
            conversation, _ = await _authorized_conversation(
                scoped.conversation_repository(),
                scope,
            )
            event_repo = scoped.agent_execution_event_repository()
            existing = await event_repo.get_events(
                conversation_id=conversation.id,
                event_types={_INJECTION_EVENT_TYPE},
                limit=1000,
            )
            if any(event.event_data.get("delivery_request_id") == request.id for event in existing):
                return
            last_time_us, last_counter = await event_repo.get_last_event_time(conversation.id)
            event_time_us, event_counter = EventTimeGenerator(
                last_time_us,
                last_counter,
            ).next()
            await event_repo.save_and_commit(
                AgentExecutionEvent(
                    id=_provider_event_id("inject", request.id),
                    conversation_id=conversation.id,
                    message_id=_provider_message_id(request.id),
                    event_type=_INJECTION_EVENT_TYPE,
                    event_data={
                        "role": "system",
                        "content": content,
                        "source": "avernet_chat_inject",
                        "delivery_request_id": request.id,
                        "bcs_session_id": request.session_id,
                        "bcs_group_id": request.bcn_group_id,
                        "provider_id": request.to_bot.provider_id,
                        "provider_bot_ref": request.to_bot.provider_bot_ref,
                        "extensions": scope.correlation,
                        "attachments": _safe_attachment_metadata(request),
                    },
                    event_time_us=event_time_us,
                    event_counter=event_counter,
                )
            )

    async def abort(self, request: ProviderWebhookRequest) -> ProviderAbortResult:
        from src.application.services.agent.runtime_cancellation import (
            cancel_conversation_runtime,
        )

        scope = ProviderWorkspaceScope.from_request(request)
        terminal_event: ProviderRuntimeEvent | None = None
        async with self._session_factory() as db:
            scoped = self._scoped_container(db)
            conversation, _ = await _authorized_conversation(
                scoped.conversation_repository(),
                scope,
            )
            result = await cancel_conversation_runtime(conversation)
            if (
                result.ray_cancelled or result.local_worker_cancelled
            ) and request.run_id is not None:
                persisted_abort = await _persist_provider_abort(
                    scoped.agent_execution_event_repository(),
                    conversation_id=conversation.id,
                    target_run_id=request.run_id,
                    abort_request_id=request.id,
                )
                if persisted_abort is not None:
                    terminal_event = await self._commit_abort_terminal(
                        correlation_id=_provider_correlation_id(request.run_id),
                        scope=scope,
                        persisted_event=persisted_abort,
                        target_run_id=request.run_id,
                    )
        return ProviderAbortResult(
            ray_cancelled=result.ray_cancelled,
            local_worker_cancelled=result.local_worker_cancelled,
            terminal_event=terminal_event,
        )

    async def history(self, request: ProviderWebhookRequest) -> ProviderHistoryResult:
        scope = ProviderWorkspaceScope.from_request(request)
        limit = min(max(request.limit or _DEFAULT_HISTORY_LIMIT, 1), _MAX_HISTORY_LIMIT)
        async with self._session_factory() as db:
            scoped = self._scoped_container(db)
            conversation, _ = await _authorized_conversation(
                scoped.conversation_repository(),
                scope,
            )
            event_repo = scoped.agent_execution_event_repository()
            before_time = request.before
            if before_time is None and request.after is None:
                before_time = (1 << 63) - 1
            events = await event_repo.get_events(
                conversation_id=conversation.id,
                from_time_us=request.after or 0,
                limit=limit + 1,
                event_types=set(_MESSAGE_EVENT_TYPES),
                before_time_us=before_time,
            )

        has_more = len(events) > limit
        if has_more and before_time is not None:
            events = events[-limit:]
        else:
            events = events[:limit]
        messages = [_history_message(event) for event in events]
        return ProviderHistoryResult(
            messages=messages,
            has_more=has_more,
            next_before=events[0].event_time_us if has_more and events else None,
            next_after=events[-1].event_time_us if has_more and events else None,
        )

    def _scoped_container(self, db: AsyncSession) -> _ScopedContainer:
        container = self._container_provider()
        if container is None:
            raise RuntimeError("MemStack application container is not initialized")
        return container.with_db(db)

    async def _commit_abort_terminal(
        self,
        *,
        correlation_id: str,
        scope: ProviderWorkspaceScope,
        persisted_event: AgentExecutionEvent,
        target_run_id: str,
    ) -> ProviderRuntimeEvent | None:
        provider_event = ProviderRuntimeEvent(
            state="aborted",
            sequence=0,
            message={"content": _event_content(persisted_event.event_data)},
            stop_reason="cancelled",
        )
        terminal_request = WorkspaceRuntimeTerminalRequest(
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            workspace_id=scope.workspace_id,
            execution_status="aborted",
            terminal_message_id=persisted_event.message_id,
            terminal_event_id=persisted_event.id,
            report=_terminal_report(provider_event, persisted_event),
        )
        try:
            _ = await self._workspace_core_client.record_runtime_terminal(
                correlation_id,
                terminal_request,
            )
        except Exception as commit_error:
            try:
                terminal = await self._workspace_core_client.read_runtime_terminal(
                    correlation_id,
                    tenant_id=scope.tenant_id,
                    project_id=scope.project_id,
                    workspace_id=scope.workspace_id,
                )
            except Exception:
                logger.exception(
                    "Avernet abort terminal commit failed without a durable winner",
                    extra={
                        "run_id": target_run_id,
                        "correlation_id": correlation_id,
                        **scope.correlation,
                    },
                )
                raise commit_error from None
            if terminal.status != "aborted":
                logger.info(
                    "Avernet abort preserved an existing runtime terminal",
                    extra={
                        "run_id": target_run_id,
                        "correlation_id": correlation_id,
                        "terminal_status": terminal.status,
                        **scope.correlation,
                    },
                )
                return None
            return _replayed_terminal_event(terminal)
        provider_event.persisted = True
        provider_event.correlation_id = correlation_id
        return provider_event

    async def _commit_runtime_terminal(
        self,
        *,
        correlation_id: str,
        scope: ProviderWorkspaceScope,
        provider_event: ProviderRuntimeEvent,
        persisted_event: AgentExecutionEvent,
        request_id: str,
    ) -> bool:
        execution_status: Literal["complete", "error"] = (
            "complete" if provider_event.state == "final" else "error"
        )
        try:
            _ = await self._workspace_core_client.record_runtime_terminal(
                correlation_id,
                WorkspaceRuntimeTerminalRequest(
                    tenant_id=scope.tenant_id,
                    project_id=scope.project_id,
                    workspace_id=scope.workspace_id,
                    execution_status=execution_status,
                    terminal_message_id=persisted_event.message_id,
                    terminal_event_id=persisted_event.id,
                    report=_terminal_report(provider_event, persisted_event),
                ),
            )
        except Exception:
            logger.exception(
                "Avernet terminal callback suppressed because Workspace Core commit failed",
                extra={
                    "run_id": request_id,
                    "correlation_id": correlation_id,
                    **scope.correlation,
                },
            )
            return False
        provider_event.correlation_id = correlation_id
        return True

    async def _prepare_terminal_event(
        self,
        db: AsyncSession,
        event_repo: _AgentExecutionEventRepository,
        *,
        provider_event: ProviderRuntimeEvent,
        correlation_id: str,
        scope: ProviderWorkspaceScope,
        request_id: str,
        conversation_id: str,
        message_id: str,
        timeout_seconds: float,
    ) -> bool:
        persisted_event = await _wait_for_persisted_terminal(
            db,
            event_repo,
            conversation_id=conversation_id,
            message_id=message_id,
            state=provider_event.state,
            timeout_seconds=timeout_seconds,
        )
        if persisted_event is None:
            logger.error(
                "Avernet terminal callback suppressed because persistence was not visible",
                extra={"run_id": request_id, **scope.correlation},
            )
            return False
        committed = await self._commit_runtime_terminal(
            correlation_id=correlation_id,
            scope=scope,
            provider_event=provider_event,
            persisted_event=persisted_event,
            request_id=request_id,
        )
        if not committed:
            return False
        provider_event.persisted = True
        if not _runtime_event_has_text(provider_event):
            provider_event.message = {"content": _event_content(persisted_event.event_data)}
        return True


async def _ensure_send_conversation(
    db: AsyncSession,
    repository: _ConversationRepository,
    scope: ProviderWorkspaceScope,
    agent_id: str,
) -> Conversation:
    conversation, created = await _authorized_conversation(
        repository,
        scope,
        create_agent_id=agent_id,
    )
    if created:
        await db.commit()
    return conversation


async def _authorized_conversation(
    repository: _ConversationRepository,
    scope: ProviderWorkspaceScope,
    *,
    create_agent_id: str | None = None,
) -> tuple[Conversation, bool]:
    conversation = await repository.find_by_id(scope.conversation_id)
    if conversation is None:
        if create_agent_id is None:
            raise LookupError("Provider conversation was not found")
        agent_id = create_agent_id.strip()
        if not agent_id:
            raise ValueError("Provider conversation requires a target Agent")
        expected_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"workspace:{scope.workspace_id}:agent:{agent_id}",
            )
        )
        if scope.conversation_id != expected_id:
            raise PermissionError("Provider conversation id does not match Workspace scope")
        created_at = datetime.now(UTC)
        metadata: dict[str, Any] = {
            "workspace_id": scope.workspace_id,
            "agent_id": agent_id,
            "source": "avernet_workspace_message",
            "created_at": created_at.isoformat(),
        }
        if scope.task_id is not None:
            metadata["workspace_task_id"] = scope.task_id
            metadata["linked_workspace_task_id"] = scope.task_id
        if scope.plan_id is not None:
            metadata["workspace_plan_id"] = scope.plan_id
        if scope.plan_node_id is not None:
            metadata["workspace_plan_node_id"] = scope.plan_node_id
        conversation = await repository.save(
            Conversation(
                id=scope.conversation_id,
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                user_id=scope.user_id,
                title=f"Workspace Chat - {agent_id}",
                status=ConversationStatus.ACTIVE,
                agent_config={"selected_agent_id": agent_id},
                metadata=metadata,
                message_count=0,
                created_at=created_at,
                workspace_id=scope.workspace_id,
                linked_workspace_task_id=scope.task_id,
            )
        )
        return conversation, True
    if (
        conversation.tenant_id != scope.tenant_id
        or conversation.project_id != scope.project_id
        or conversation.user_id != scope.user_id
        or conversation.workspace_id != scope.workspace_id
    ):
        raise PermissionError("Provider conversation scope does not match")
    if (
        scope.task_id is not None
        and conversation.linked_workspace_task_id is not None
        and conversation.linked_workspace_task_id != scope.task_id
    ):
        raise PermissionError("Provider task scope does not match")
    return conversation, False


async def _workspace_model_context(
    event_repo: _AgentExecutionEventRepository,
    *,
    request: ProviderWebhookRequest,
    scope: ProviderWorkspaceScope,
) -> dict[str, Any]:
    from src.infrastructure.agent.workspace.runtime_role_contract import (
        WORKSPACE_ROLE_LEADER,
        WORKSPACE_ROLE_WORKER,
        WORKSPACE_SESSION_ROLE_KEY,
    )

    injection_events = await event_repo.get_events(
        conversation_id=scope.conversation_id,
        event_types={_INJECTION_EVENT_TYPE},
        limit=_MAX_INJECTION_CONTEXT_EVENTS,
    )
    injections = [
        {
            "content": _event_content(event.event_data),
            "source": event.event_data.get("source"),
            "provider_bot_ref": event.event_data.get("provider_bot_ref"),
            "event_time_us": event.event_time_us,
        }
        for event in injection_events
    ]
    is_task_turn = scope.task_id is not None
    context: dict[str, Any] = {
        "context_type": (
            "workspace_worker_runtime" if is_task_turn else "workspace_collaboration_runtime"
        ),
        WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_WORKER
        if is_task_turn
        else WORKSPACE_ROLE_LEADER,
        "avernet": {
            "delivery_request_id": request.id,
            "bcs_session_id": request.session_id,
            "bcs_group_id": request.bcn_group_id,
            "provider_id": request.to_bot.provider_id,
            "provider_bot_ref": request.to_bot.provider_bot_ref,
            "collaboration_injections": injections,
        },
    }
    context["workspace_binding" if is_task_turn else "workspace_scope"] = scope.correlation
    return context


async def _wait_for_persisted_terminal(
    db: AsyncSession,
    event_repo: _AgentExecutionEventRepository,
    *,
    conversation_id: str,
    message_id: str,
    state: str,
    timeout_seconds: float,
) -> AgentExecutionEvent | None:
    expected_type = "complete" if state == "final" else "error"
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        events = await event_repo.get_events_by_message(conversation_id, message_id)
        terminal = next(
            (event for event in reversed(events) if _execution_event_type(event) == expected_type),
            None,
        )
        if terminal is not None:
            return terminal
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await db.rollback()
        await asyncio.sleep(0.05)


async def _persist_provider_error(
    event_repo: _AgentExecutionEventRepository,
    *,
    conversation_id: str,
    message_id: str,
    request_id: str,
) -> AgentExecutionEvent | None:
    try:
        last_time_us, last_counter = await event_repo.get_last_event_time(conversation_id)
        event_time_us, event_counter = EventTimeGenerator(
            last_time_us,
            last_counter,
        ).next()
        event = AgentExecutionEvent(
            id=_provider_event_id("error", request_id),
            conversation_id=conversation_id,
            message_id=message_id,
            event_type="error",
            event_data={
                "message": "Agent Runtime failed",
                "source": "avernet_provider",
                "delivery_request_id": request_id,
            },
            event_time_us=event_time_us,
            event_counter=event_counter,
        )
        await event_repo.save_and_commit(event)
        return event
    except Exception:
        logger.exception(
            "Failed to persist Avernet Provider terminal error",
            extra={"run_id": request_id, "conversation_id": conversation_id},
        )
        return None


async def _persist_provider_abort(
    event_repo: _AgentExecutionEventRepository,
    *,
    conversation_id: str,
    target_run_id: str,
    abort_request_id: str,
) -> AgentExecutionEvent | None:
    message_id = _provider_message_id(target_run_id)
    existing = await event_repo.get_events_by_message(conversation_id, message_id)
    terminal = next(
        (
            event
            for event in reversed(existing)
            if _execution_event_type(event) in {"complete", "error", "cancelled"}
        ),
        None,
    )
    if terminal is not None:
        return terminal if _execution_event_type(terminal) == "cancelled" else None

    last_time_us, last_counter = await event_repo.get_last_event_time(conversation_id)
    event_time_us, event_counter = EventTimeGenerator(last_time_us, last_counter).next()
    event = AgentExecutionEvent(
        id=_provider_event_id("abort", target_run_id),
        conversation_id=conversation_id,
        message_id=message_id,
        event_type=AgentEventType.CANCELLED,
        event_data={
            "message": "Agent Runtime cancelled",
            "source": "avernet_provider",
            "provider_run_id": target_run_id,
            "abort_delivery_request_id": abort_request_id,
        },
        event_time_us=event_time_us,
        event_counter=event_counter,
    )
    await event_repo.save_and_commit(event)
    return event


def _runtime_correlation_request(
    request: ProviderWebhookRequest,
    *,
    scope: ProviderWorkspaceScope,
    correlation_id: str,
) -> WorkspaceRuntimeCorrelationRequest:
    return WorkspaceRuntimeCorrelationRequest(
        correlation_id=correlation_id,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        workspace_id=scope.workspace_id,
        user_id=scope.user_id,
        task_id=scope.task_id,
        attempt_id=_optional_extension(request, "attempt_id"),
        plan_id=scope.plan_id,
        plan_node_id=scope.plan_node_id,
        conversation_id=scope.conversation_id,
        bcs_session_id=request.session_id,
        bcs_group_id=request.bcn_group_id,
        bcs_message_id=_optional_extension(request, "bcs_message_id"),
        state_machine_run_id=_optional_extension(request, "state_machine_run_id"),
        delivery_request_id=request.id,
        provider_run_id=request.id,
        provider_id=request.to_bot.provider_id,
        provider_bot_ref=request.to_bot.provider_bot_ref,
    )


def _terminal_report(
    provider_event: ProviderRuntimeEvent,
    persisted_event: AgentExecutionEvent,
) -> dict[str, Any]:
    return {
        "content": _event_content(persisted_event.event_data),
        "provider_state": provider_event.state,
        "sequence": provider_event.sequence,
        "usage": provider_event.usage,
        "stop_reason": provider_event.stop_reason,
        "error_message": provider_event.error_message,
        "legacy_event": {
            "event_id": persisted_event.id,
            "event_type": _execution_event_type(persisted_event),
            "event_time_us": persisted_event.event_time_us,
            "event_counter": persisted_event.event_counter,
            "event_data": persisted_event.event_data,
        },
    }


def _replayed_terminal_event(
    terminal: WorkspaceRuntimeTerminalReadResponse,
) -> ProviderRuntimeEvent:
    expected_state = {
        "completed": "final",
        "failed": "error",
        "aborted": "aborted",
    }[terminal.status]
    if terminal.report.provider_state != expected_state:
        raise ValueError("Workspace Core terminal status and Provider state do not match")
    message = {"content": terminal.report.content} if terminal.report.content else None
    return ProviderRuntimeEvent(
        state=terminal.report.provider_state,
        sequence=terminal.report.sequence,
        message=message,
        error_message=terminal.report.error_message,
        usage=terminal.report.usage,
        stop_reason=terminal.report.stop_reason,
        persisted=terminal.persisted,
        correlation_id=terminal.correlation_id,
    )


def _map_runtime_event(
    raw_event: Mapping[str, Any],
    *,
    sequence: int,
) -> ProviderRuntimeEvent | None:
    event_type = str(raw_event.get("type", ""))
    data: object | None = raw_event.get("data")
    event_data = _string_object_dict(data)
    if event_type == "complete":
        return ProviderRuntimeEvent(
            state="final",
            sequence=sequence,
            message={"content": _event_content(event_data)},
            usage=_event_usage(event_data),
            stop_reason=str(event_data.get("stop_reason") or "end_turn"),
        )
    if event_type == "error":
        return ProviderRuntimeEvent(
            state="error",
            sequence=sequence,
            error_message=str(event_data.get("message") or "Agent Runtime failed"),
        )
    if event_type not in {"text_delta", "text_end"}:
        return None
    content = _event_content(event_data)
    if not content:
        return None
    return ProviderRuntimeEvent(
        state="delta",
        sequence=sequence,
        message={"content": content},
    )


def _history_message(event: AgentExecutionEvent) -> dict[str, Any]:
    return {
        "id": event.message_id,
        "role": str(event.event_data.get("role") or "assistant"),
        "content": [{"type": "text", "text": _event_content(event.event_data)}],
        "timestamp": int(event.created_at.timestamp() * 1000),
        "sequence": event.event_time_us,
    }


def _provider_message_text(message: object | None) -> str:
    if isinstance(message, str):
        return message.strip()
    payload = _string_object_dict(message)
    if not payload:
        return ""
    content = payload.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        blocks = cast("list[object]", content)
        text_parts: list[str] = []
        for block in blocks:
            block_data = _string_object_dict(block)
            if block_data.get("type") == "text":
                text_parts.append(str(block_data.get("text", "")))
        return "".join(text_parts).strip()
    text = payload.get("text")
    return text.strip() if isinstance(text, str) else ""


def _event_content(event_data: Mapping[str, Any]) -> str:
    for name in ("content", "delta", "text", "message"):
        value = event_data.get(name)
        if isinstance(value, str):
            return value
    return ""


def _execution_event_type(event: AgentExecutionEvent) -> str:
    event_type = event.event_type
    return event_type.value if isinstance(event_type, AgentEventType) else event_type


def _event_usage(event_data: Mapping[str, Any]) -> dict[str, Any] | None:
    raw_usage: object | None = event_data.get("usage")
    usage = _string_object_dict(raw_usage)
    return cast("dict[str, Any]", usage) if usage else None


def _string_object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    candidate = cast("Mapping[object, object]", value)
    return {key: item for key, item in candidate.items() if isinstance(key, str)}


def _runtime_event_has_text(event: ProviderRuntimeEvent) -> bool:
    return bool(event.message and _event_content(event.message))


def _provider_image_urls(request: ProviderWebhookRequest) -> list[str] | None:
    urls = [
        str(attachment.get("url"))
        for attachment in request.attachments
        if attachment.get("type") == "image" and attachment.get("url")
    ]
    return urls or None


def _safe_attachment_metadata(request: ProviderWebhookRequest) -> list[dict[str, Any]]:
    safe_names = ("attachment_id", "type", "file_name", "mime_type", "size", "sha256")
    return [
        {name: attachment[name] for name in safe_names if attachment.get(name) is not None}
        for attachment in request.attachments
    ]


def _required_extension(request: ProviderWebhookRequest, name: str) -> str:
    value = _optional_extension(request, name)
    if value is None:
        raise ValueError(f"Provider extension {name} is required")
    return value


def _optional_extension(request: ProviderWebhookRequest, name: str) -> str | None:
    value = request.extensions.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _provider_message_id(request_id: str) -> str:
    return str(uuid.uuid5(_PROVIDER_EVENT_NAMESPACE, f"message:{request_id}"))


def _provider_correlation_id(request_id: str) -> str:
    return str(uuid.uuid5(_PROVIDER_EVENT_NAMESPACE, f"correlation:{request_id}"))


def _provider_event_id(kind: str, request_id: str) -> str:
    return str(uuid.uuid5(_PROVIDER_EVENT_NAMESPACE, f"{kind}:{request_id}"))


def _default_session_factory() -> SessionFactory:
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )

    return cast("SessionFactory", async_session_factory)


def _default_container_provider() -> _ApplicationContainer | None:
    from src.infrastructure.adapters.primary.web.startup.container import (
        get_app_container,
    )

    return cast("_ApplicationContainer | None", get_app_container())


async def _default_llm_factory(tenant_id: str) -> object:
    from src.configuration.factories import create_llm_client

    return await create_llm_client(tenant_id)


__all__ = ["MemStackAgentRuntimeProvider", "ProviderWorkspaceScope"]
