"""Durable timeout recovery for Avernet-backed Agent Runtime deliveries."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.events.types import AgentEventType
from src.domain.llm_providers.llm_types import Message
from src.domain.model.agent import AgentExecutionEvent
from src.domain.model.agent.conversation.conversation import Conversation
from src.domain.model.agent.execution.event_time import EventTimeGenerator
from src.infrastructure.llm.model_pool import ModelPoolService, PoolFilter, get_model_pool_service
from src.infrastructure.workspace_core.client import (
    WorkspaceCoreClient,
    WorkspaceCoreNotFoundError,
    WorkspaceRuntimeCallbackAckRequest,
    WorkspaceRuntimeRecoveryClaimRequest,
    WorkspaceRuntimeRecoveryItem,
    WorkspaceRuntimeRecoveryJudgmentRequest,
    WorkspaceRuntimeTerminalReadResponse,
    WorkspaceRuntimeTerminalRequest,
)
from src.infrastructure.workspace_core.provider import (
    ProviderEventSink,
    ProviderRuntimeEvent,
    ProviderWebhookRequest,
)

logger = logging.getLogger(__name__)

RecoveryAction = Literal["continue", "fail", "escalate"]

_RECOVERY_NAMESPACE = uuid.UUID("dd2d8c70-20dc-4a99-8a47-f8c98aa97dcb")
_TERMINAL_EVENT_TYPES = {"complete", "error"}
_DEFAULT_STALE_AFTER_SECONDS = 120
_DEFAULT_LEASE_SECONDS = 60
_DEFAULT_BATCH_SIZE = 20
_DEFAULT_INTERVAL_SECONDS = 30.0
_RECOVERY_TOOL_NAME = "decide_runtime_recovery"

_RECOVERY_TOOL: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": _RECOVERY_TOOL_NAME,
            "description": (
                "Decide how to handle an Agent Runtime correlation that exceeded its recovery "
                "trigger and has no persisted terminal event. Choose continue when evidence is "
                "insufficient to end the run, fail only when the supplied structural evidence "
                "supports a terminal failure, or escalate when a human/operator must intervene."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["continue", "fail", "escalate"],
                    },
                    "rationale": {
                        "type": "string",
                        "description": "A concise evidence-based reason for the action.",
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["action", "rationale", "evidence"],
                "additionalProperties": False,
            },
        },
    }
]


class RuntimeRecoveryJudgeUnavailable(RuntimeError):
    """No valid structured Agent verdict was available."""


class RuntimeRecoveryVerdict(BaseModel):
    """Validated result of the recovery judgment tool call."""

    model_config = ConfigDict(extra="forbid")

    action: RecoveryAction
    rationale: str = Field(min_length=1)
    evidence: list[str]
    agent_id: str
    input_json: dict[str, Any]
    output_json: dict[str, Any]
    latency_ms: int = Field(ge=0)


class RuntimeRecoveryJudgePort(Protocol):
    async def decide(self, recovery: WorkspaceRuntimeRecoveryItem) -> RuntimeRecoveryVerdict: ...


class RuntimeRecoveryEvidencePort(Protocol):
    async def find_terminal(
        self,
        recovery: WorkspaceRuntimeRecoveryItem,
    ) -> AgentExecutionEvent | None: ...

    async def persist_failure(
        self,
        recovery: WorkspaceRuntimeRecoveryItem,
        *,
        audit_id: str,
    ) -> AgentExecutionEvent: ...


class _ConversationRepository(Protocol):
    async def find_by_id(self, conversation_id: str) -> Conversation | None: ...


class _AgentExecutionEventRepository(Protocol):
    async def save_and_commit(self, event: AgentExecutionEvent) -> None: ...

    async def get_events_by_message(
        self,
        conversation_id: str,
        message_id: str,
    ) -> list[AgentExecutionEvent]: ...

    async def get_last_event_time(self, conversation_id: str) -> tuple[int, int]: ...


class _ScopedContainer(Protocol):
    def conversation_repository(self) -> _ConversationRepository: ...

    def agent_execution_event_repository(self) -> _AgentExecutionEventRepository: ...


class _ApplicationContainer(Protocol):
    def with_db(self, db: AsyncSession) -> _ScopedContainer: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ContainerProvider = Callable[[], _ApplicationContainer | None]


class AgentRuntimeRecoveryJudge:
    """Make every semantic recovery decision through a structured Agent tool call."""

    def __init__(self, pool_service: ModelPoolService | None = None) -> None:
        super().__init__()
        self._pool = pool_service or get_model_pool_service()

    async def decide(self, recovery: WorkspaceRuntimeRecoveryItem) -> RuntimeRecoveryVerdict:
        candidates = await self._pool.list_candidates(
            tenant_id=recovery.tenant_id,
            pool_filter=PoolFilter(require_tools=True),
        )
        if not candidates:
            raise RuntimeRecoveryJudgeUnavailable("no tool-capable recovery judge is available")
        candidate = candidates[0]
        input_json = _judgment_input(recovery)
        started_at = time.perf_counter()
        try:
            from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
            from src.infrastructure.llm.model_catalog import get_model_catalog_service

            client = create_litellm_client(
                candidate.provider_config,
                catalog=get_model_catalog_service(),
            )
            response = await client.generate(
                messages=_judgment_messages(input_json),
                tools=_RECOVERY_TOOL,
                tool_choice={"type": "function", "function": {"name": _RECOVERY_TOOL_NAME}},
                temperature=0.0,
                max_tokens=384,
                model=candidate.model_name,
            )
            output_json = _extract_recovery_tool_call(cast("dict[str, object]", response))
            if output_json is None:
                raise RuntimeRecoveryJudgeUnavailable(
                    "recovery judge response omitted the required structured tool call"
                )
            action = output_json.get("action")
            rationale = output_json.get("rationale")
            evidence = output_json.get("evidence")
            if action not in {"continue", "fail", "escalate"}:
                raise RuntimeRecoveryJudgeUnavailable("recovery judge returned an invalid action")
            if not isinstance(rationale, str) or not rationale.strip():
                raise RuntimeRecoveryJudgeUnavailable("recovery judge returned an empty rationale")
            if not isinstance(evidence, list):
                raise RuntimeRecoveryJudgeUnavailable("recovery judge returned invalid evidence")
            evidence_items = cast("list[object]", evidence)
            if not all(isinstance(item, str) for item in evidence_items):
                raise RuntimeRecoveryJudgeUnavailable("recovery judge returned invalid evidence")
        except RuntimeRecoveryJudgeUnavailable:
            raise
        except Exception as exc:
            raise RuntimeRecoveryJudgeUnavailable(
                f"recovery judge failed with {type(exc).__name__}"
            ) from exc
        latency_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        logger.info(
            "Avernet runtime recovery judgment completed",
            extra={
                "correlation_id": recovery.correlation_id,
                "workspace_id": recovery.workspace_id,
                "agent_id": candidate.candidate_key,
                "tool_name": _RECOVERY_TOOL_NAME,
                "action": action,
                "latency_ms": latency_ms,
            },
        )
        return RuntimeRecoveryVerdict(
            action=cast("RecoveryAction", action),
            rationale=rationale.strip(),
            evidence=cast("list[str]", evidence_items),
            agent_id=candidate.candidate_key,
            input_json=input_json,
            output_json=output_json,
            latency_ms=latency_ms,
        )


class MemStackRuntimeRecoveryEvidence:
    """Read and create replayable terminal evidence in the legacy Runtime store."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        container_provider: ContainerProvider | None = None,
    ) -> None:
        super().__init__()
        self._session_factory = session_factory or _default_session_factory()
        self._container_provider = container_provider or _default_container_provider

    async def find_terminal(
        self,
        recovery: WorkspaceRuntimeRecoveryItem,
    ) -> AgentExecutionEvent | None:
        async with self._session_factory() as db:
            scoped = self._scoped_container(db)
            _ = await _authorized_conversation(scoped.conversation_repository(), recovery)
            events = await scoped.agent_execution_event_repository().get_events_by_message(
                recovery.conversation_id,
                _execution_message_id(recovery.delivery_request_id),
            )
        expected_event_type = {
            "completed": "complete",
            "failed": "error",
        }.get(recovery.status)
        return next(
            (
                event
                for event in reversed(events)
                if (
                    _event_type_value(event) == expected_event_type
                    if expected_event_type is not None
                    else _event_type_value(event) in _TERMINAL_EVENT_TYPES
                )
            ),
            None,
        )

    async def persist_failure(
        self,
        recovery: WorkspaceRuntimeRecoveryItem,
        *,
        audit_id: str,
    ) -> AgentExecutionEvent:
        async with self._session_factory() as db:
            scoped = self._scoped_container(db)
            _ = await _authorized_conversation(scoped.conversation_repository(), recovery)
            repository = scoped.agent_execution_event_repository()
            existing = await repository.get_events_by_message(
                recovery.conversation_id,
                _execution_message_id(recovery.delivery_request_id),
            )
            terminal = next(
                (
                    event
                    for event in reversed(existing)
                    if _event_type_value(event) in _TERMINAL_EVENT_TYPES
                ),
                None,
            )
            if terminal is not None:
                return terminal
            last_time_us, last_counter = await repository.get_last_event_time(
                recovery.conversation_id
            )
            event_time_us, event_counter = EventTimeGenerator(
                last_time_us,
                last_counter,
            ).next()
            event = AgentExecutionEvent(
                id=str(
                    uuid.uuid5(
                        _RECOVERY_NAMESPACE,
                        f"failure:{recovery.correlation_id}:{audit_id}",
                    )
                ),
                conversation_id=recovery.conversation_id,
                message_id=_execution_message_id(recovery.delivery_request_id),
                event_type="error",
                event_data={
                    "message": "Agent Runtime failed during timeout recovery",
                    "source": "avernet_runtime_recovery",
                    "delivery_request_id": recovery.delivery_request_id,
                    "recovery_audit_id": audit_id,
                },
                event_time_us=event_time_us,
                event_counter=event_counter,
            )
            await repository.save_and_commit(event)
            return event

    def _scoped_container(self, db: AsyncSession) -> _ScopedContainer:
        container = self._container_provider()
        if container is None:
            raise RuntimeError("MemStack application container is not initialized")
        return container.with_db(db)


@dataclass(frozen=True, kw_only=True)
class RuntimeRecoveryConfig:
    lease_owner: str
    stale_after_seconds: int = _DEFAULT_STALE_AFTER_SECONDS
    lease_seconds: int = _DEFAULT_LEASE_SECONDS
    batch_size: int = _DEFAULT_BATCH_SIZE
    interval_seconds: float = _DEFAULT_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        if not self.lease_owner.strip():
            raise ValueError("runtime recovery lease owner must not be blank")
        if min(self.stale_after_seconds, self.lease_seconds, self.batch_size) <= 0:
            raise ValueError("runtime recovery bounds must be positive")
        if self.interval_seconds <= 0:
            raise ValueError("runtime recovery interval must be positive")


class AvernetRuntimeRecoveryWorker:
    """Reconcile persisted terminals and Agent-judged stale correlations."""

    def __init__(
        self,
        *,
        core_client: WorkspaceCoreClient,
        event_sink: ProviderEventSink,
        judge: RuntimeRecoveryJudgePort,
        evidence: RuntimeRecoveryEvidencePort,
        config: RuntimeRecoveryConfig,
    ) -> None:
        super().__init__()
        self._core_client = core_client
        self._event_sink = event_sink
        self._judge = judge
        self._evidence = evidence
        self._config = config
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the process-scoped recovery loop exactly once."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="avernet-runtime-recovery",
        )

    async def stop(self) -> None:
        """Stop the recovery loop without abandoning an in-flight sweep."""
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._task = None

    async def sweep_once(self) -> int:
        """Claim and process one bounded recovery batch."""
        response = await self._core_client.claim_runtime_recoveries(
            WorkspaceRuntimeRecoveryClaimRequest(
                lease_owner=self._config.lease_owner,
                stale_after_seconds=self._config.stale_after_seconds,
                lease_seconds=self._config.lease_seconds,
                limit=self._config.batch_size,
            )
        )
        for recovery in response.recoveries:
            try:
                await self._process_recovery(recovery)
            except Exception:
                logger.exception(
                    "Avernet runtime recovery item failed",
                    extra={
                        "correlation_id": recovery.correlation_id,
                        "workspace_id": recovery.workspace_id,
                        "recovery_attempt": recovery.recovery_attempt_count,
                    },
                )
        return len(response.recoveries)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                claimed = await self.sweep_once()
                if claimed:
                    logger.info(
                        "Avernet runtime recovery sweep completed", extra={"claimed": claimed}
                    )
            except Exception:
                logger.exception("Avernet runtime recovery sweep failed")
            try:
                _ = await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._config.interval_seconds,
                )
            except TimeoutError:
                continue

    async def _process_recovery(self, recovery: WorkspaceRuntimeRecoveryItem) -> None:
        request = _callback_request(recovery)
        if recovery.status in {"completed", "failed", "aborted"}:
            try:
                terminal = await self._core_client.read_runtime_terminal(
                    recovery.correlation_id,
                    tenant_id=recovery.tenant_id,
                    project_id=recovery.project_id,
                    workspace_id=recovery.workspace_id,
                )
            except WorkspaceCoreNotFoundError:
                persisted = await self._evidence.find_terminal(recovery)
                if persisted is None or not _legacy_terminal_matches_status(
                    persisted,
                    recovery.status,
                ):
                    logger.warning(
                        "Avernet terminal proof is missing or conflicts with legacy evidence",
                        extra={
                            "correlation_id": recovery.correlation_id,
                            "workspace_id": recovery.workspace_id,
                            "status": recovery.status,
                        },
                    )
                    return
                event = _provider_event_from_legacy(recovery, persisted)
                await self._commit_terminal(recovery, event, persisted)
                await self._publish_and_ack(request, event)
            else:
                await self._publish_and_ack(request, _replayed_terminal_event(terminal))
            return

        persisted = await self._evidence.find_terminal(recovery)
        if persisted is not None:
            event = _provider_event_from_legacy(recovery, persisted)
            await self._commit_terminal(recovery, event, persisted)
            await self._publish_and_ack(request, event)
            return

        try:
            verdict = await self._judge.decide(recovery)
        except RuntimeRecoveryJudgeUnavailable:
            logger.warning(
                "Avernet runtime recovery judgment unavailable; lease will expire",
                extra={
                    "correlation_id": recovery.correlation_id,
                    "workspace_id": recovery.workspace_id,
                },
            )
            return
        audit_id = _recovery_audit_id(recovery)
        _ = await self._core_client.record_runtime_recovery_judgment(
            recovery.correlation_id,
            WorkspaceRuntimeRecoveryJudgmentRequest(
                audit_id=audit_id,
                tenant_id=recovery.tenant_id,
                project_id=recovery.project_id,
                workspace_id=recovery.workspace_id,
                lease_owner=self._config.lease_owner,
                action=verdict.action,
                agent_id=verdict.agent_id,
                tool_name=_RECOVERY_TOOL_NAME,
                input_json=verdict.input_json,
                output_json=verdict.output_json,
                rationale=verdict.rationale,
                latency_ms=verdict.latency_ms,
            ),
        )
        if verdict.action != "fail":
            return
        persisted = await self._evidence.persist_failure(recovery, audit_id=audit_id)
        event = _provider_event_from_legacy(recovery, persisted)
        await self._commit_terminal(recovery, event, persisted)
        await self._publish_and_ack(request, event)

    async def _commit_terminal(
        self,
        recovery: WorkspaceRuntimeRecoveryItem,
        event: ProviderRuntimeEvent,
        persisted: AgentExecutionEvent,
    ) -> None:
        execution_status: Literal["complete", "error"] = (
            "complete" if event.state == "final" else "error"
        )
        _ = await self._core_client.record_runtime_terminal(
            recovery.correlation_id,
            WorkspaceRuntimeTerminalRequest(
                tenant_id=recovery.tenant_id,
                project_id=recovery.project_id,
                workspace_id=recovery.workspace_id,
                execution_status=execution_status,
                terminal_message_id=persisted.message_id,
                terminal_event_id=persisted.id,
                report=_terminal_report(event, persisted),
            ),
        )
        event.persisted = True
        event.correlation_id = recovery.correlation_id

    async def _publish_and_ack(
        self,
        request: ProviderWebhookRequest,
        event: ProviderRuntimeEvent,
    ) -> None:
        await self._event_sink.publish(request, event)
        if event.correlation_id is None:
            raise RuntimeError("recovery terminal callback is missing its correlation id")
        _ = await self._core_client.acknowledge_runtime_terminal_callback(
            event.correlation_id,
            WorkspaceRuntimeCallbackAckRequest(
                tenant_id=_required_extension(request, "tenant_id"),
                project_id=_required_extension(request, "project_id"),
                workspace_id=_required_extension(request, "workspace_id"),
            ),
        )


def _judgment_input(recovery: WorkspaceRuntimeRecoveryItem) -> dict[str, Any]:
    return {
        "correlation_id": recovery.correlation_id,
        "tenant_id": recovery.tenant_id,
        "project_id": recovery.project_id,
        "workspace_id": recovery.workspace_id,
        "task_id": recovery.task_id,
        "plan_id": recovery.plan_id,
        "plan_node_id": recovery.plan_node_id,
        "conversation_id": recovery.conversation_id,
        "provider_run_id": recovery.provider_run_id,
        "status": recovery.status,
        "recovery_attempt_count": recovery.recovery_attempt_count,
        "persisted_terminal_present": False,
        "available_actions": ["continue", "fail", "escalate"],
    }


def _judgment_messages(input_json: dict[str, Any]) -> list[Message]:
    return [
        Message.system(
            " ".join(
                (
                    "You are the Avernet runtime recovery judge.",
                    "Use only the supplied structured evidence.",
                    "Call decide_runtime_recovery exactly once.",
                    "Do not infer from text, invent runtime state, or choose fail without evidence.",
                )
            )
        ),
        Message.user(json.dumps(input_json, sort_keys=True, separators=(",", ":"))),
    ]


def _extract_recovery_tool_call(response: Mapping[str, object]) -> dict[str, object] | None:
    tool_calls = _object_list(response.get("tool_calls"))
    if not tool_calls:
        choices = _object_list(response.get("choices"))
        first_choice = _object_mapping(choices[0]) if choices else None
        message = _object_mapping(first_choice.get("message")) if first_choice else None
        tool_calls = _object_list(message.get("tool_calls")) if message else []
    for raw_call in tool_calls:
        call = _object_mapping(raw_call)
        if call is None:
            continue
        function = _object_mapping(call.get("function"))
        if function is None or function.get("name") != _RECOVERY_TOOL_NAME:
            continue
        arguments = function.get("arguments")
        argument_mapping = _object_mapping(arguments)
        if argument_mapping is not None:
            return dict(argument_mapping)
        if isinstance(arguments, str):
            try:
                decoded: object = json.loads(arguments)
            except json.JSONDecodeError:
                return None
            decoded_mapping = _object_mapping(decoded)
            return dict(decoded_mapping) if decoded_mapping is not None else None
    return None


def _object_list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, dict):
        return None
    candidate = cast("dict[object, object]", value)
    if not all(isinstance(key, str) for key in candidate):
        return None
    return cast("dict[str, object]", candidate)


def _callback_request(recovery: WorkspaceRuntimeRecoveryItem) -> ProviderWebhookRequest:
    extensions = {
        "tenant_id": recovery.tenant_id,
        "project_id": recovery.project_id,
        "workspace_id": recovery.workspace_id,
        "user_id": recovery.user_id,
        "conversation_id": recovery.conversation_id,
    }
    for name, value in (
        ("task_id", recovery.task_id),
        ("plan_id", recovery.plan_id),
        ("plan_node_id", recovery.plan_node_id),
    ):
        if value is not None:
            extensions[name] = value
    return ProviderWebhookRequest.model_validate(
        {
            "type": "req",
            "id": recovery.provider_run_id,
            "method": "chat.send",
            "session_id": recovery.bcs_session_id,
            "bcn_group_id": recovery.bcs_group_id,
            "to_bot": {
                "provider_id": recovery.provider_id,
                "provider_bot_ref": recovery.provider_bot_ref,
            },
            "timeout_ms": 1,
            "extensions": extensions,
        }
    )


def _provider_event_from_legacy(
    recovery: WorkspaceRuntimeRecoveryItem,
    event: AgentExecutionEvent,
) -> ProviderRuntimeEvent:
    event_type = _event_type_value(event)
    if event_type not in _TERMINAL_EVENT_TYPES:
        raise ValueError("runtime recovery evidence is not terminal")
    content = _event_content(event.event_data)
    return ProviderRuntimeEvent(
        state="final" if event_type == "complete" else "error",
        sequence=0,
        message={"content": content} if content else None,
        error_message=content if event_type == "error" else None,
        stop_reason="end_turn" if event_type == "complete" else None,
        persisted=True,
        correlation_id=recovery.correlation_id,
    )


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
    return ProviderRuntimeEvent(
        state=terminal.report.provider_state,
        sequence=terminal.report.sequence,
        message={"content": terminal.report.content} if terminal.report.content else None,
        error_message=terminal.report.error_message,
        usage=terminal.report.usage,
        stop_reason=terminal.report.stop_reason,
        persisted=terminal.persisted,
        correlation_id=terminal.correlation_id,
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
            "event_type": _event_type_value(persisted_event),
            "event_time_us": persisted_event.event_time_us,
            "event_counter": persisted_event.event_counter,
            "event_data": persisted_event.event_data,
        },
    }


def _event_content(data: dict[str, Any]) -> str:
    for key in ("content", "message", "text", "delta"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _event_type_value(event: AgentExecutionEvent) -> str:
    event_type = event.event_type
    return event_type.value if isinstance(event_type, AgentEventType) else event_type


def _legacy_terminal_matches_status(event: AgentExecutionEvent, status: str) -> bool:
    expected_event_type = {
        "completed": "complete",
        "failed": "error",
    }.get(status)
    return expected_event_type is not None and _event_type_value(event) == expected_event_type


async def _authorized_conversation(
    repository: _ConversationRepository,
    recovery: WorkspaceRuntimeRecoveryItem,
) -> Conversation:
    conversation = await repository.find_by_id(recovery.conversation_id)
    if conversation is None:
        raise LookupError("Provider conversation was not found")
    if (
        conversation.tenant_id != recovery.tenant_id
        or conversation.project_id != recovery.project_id
        or conversation.user_id != recovery.user_id
        or conversation.workspace_id != recovery.workspace_id
    ):
        raise PermissionError("Provider conversation scope does not match")
    if (
        recovery.task_id is not None
        and conversation.linked_workspace_task_id is not None
        and conversation.linked_workspace_task_id != recovery.task_id
    ):
        raise PermissionError("Provider task scope does not match")
    return conversation


def _execution_message_id(delivery_request_id: str) -> str:
    provider_namespace = uuid.UUID("3f0936e7-2634-44a6-b299-0d5ba2819652")
    return str(uuid.uuid5(provider_namespace, f"message:{delivery_request_id}"))


def _recovery_audit_id(recovery: WorkspaceRuntimeRecoveryItem) -> str:
    return str(
        uuid.uuid5(
            _RECOVERY_NAMESPACE,
            f"audit:{recovery.correlation_id}:{recovery.recovery_attempt_count}",
        )
    )


def _required_extension(request: ProviderWebhookRequest, name: str) -> str:
    value = request.extensions.get(name)
    if value is None or not str(value).strip():
        raise ValueError(f"Avernet Provider request requires extensions.{name}")
    return str(value)


def _default_session_factory() -> SessionFactory:
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

    return cast("SessionFactory", async_session_factory)


def _default_container_provider() -> _ApplicationContainer | None:
    from src.infrastructure.adapters.primary.web.startup.container import get_app_container

    return cast("_ApplicationContainer | None", get_app_container())


def default_runtime_recovery_config() -> RuntimeRecoveryConfig:
    """Create one collision-resistant process lease identity with bounded defaults."""
    return RuntimeRecoveryConfig(lease_owner=f"memstack-api-{uuid.uuid4()}")


__all__ = [
    "AgentRuntimeRecoveryJudge",
    "AvernetRuntimeRecoveryWorker",
    "MemStackRuntimeRecoveryEvidence",
    "RuntimeRecoveryConfig",
    "RuntimeRecoveryJudgeUnavailable",
    "RuntimeRecoveryVerdict",
    "default_runtime_recovery_config",
]
