"""Tests for durable Avernet Agent Runtime recovery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest

from src.domain.events.types import AgentEventType
from src.domain.model.agent import AgentExecutionEvent
from src.domain.model.agent.conversation.conversation import Conversation
from src.infrastructure.workspace_core.client import (
    WorkspaceCoreClient,
    WorkspaceCoreNotFoundError,
    WorkspaceRuntimeCallbackAckRequest,
    WorkspaceRuntimeRecoveryClaimRequest,
    WorkspaceRuntimeRecoveryClaimResponse,
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
from src.infrastructure.workspace_core.runtime_recovery import (
    AvernetRuntimeRecoveryWorker,
    MemStackRuntimeRecoveryEvidence,
    RuntimeRecoveryConfig,
    RuntimeRecoveryJudgeUnavailable,
    RuntimeRecoveryVerdict,
)


def _recovery(
    *,
    status: str = "running",
    **overrides: object,
) -> WorkspaceRuntimeRecoveryItem:
    values: dict[str, object] = {
        "correlation_id": "correlation-1",
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "user_id": "user-1",
        "task_id": "task-1",
        "plan_id": "plan-1",
        "plan_node_id": "node-1",
        "conversation_id": "conversation-1",
        "bcs_session_id": "session-1",
        "bcs_group_id": "group-1",
        "delivery_request_id": "delivery-1",
        "provider_run_id": "run-1",
        "provider_id": "memstack-agent-runtime",
        "provider_bot_ref": "bot-1",
        "status": status,
        "recovery_attempt_count": 2,
        **overrides,
    }
    return WorkspaceRuntimeRecoveryItem.model_validate(values)


def _legacy_terminal(
    event_type: AgentEventType | str = AgentEventType.COMPLETE,
) -> AgentExecutionEvent:
    return AgentExecutionEvent(
        id="legacy-event-1",
        conversation_id="conversation-1",
        message_id="message-1",
        event_type=event_type,
        event_data=(
            {"content": "finished"}
            if event_type == AgentEventType.COMPLETE
            else {"message": "failed"}
        ),
        event_time_us=100,
        event_counter=1,
    )


def _core_terminal() -> WorkspaceRuntimeTerminalReadResponse:
    return WorkspaceRuntimeTerminalReadResponse.model_validate(
        {
            "correlation_id": "correlation-1",
            "status": "completed",
            "outbox_id": "outbox-1",
            "terminal_id": "terminal-1",
            "terminal_message_id": "message-1",
            "terminal_event_id": "legacy-event-1",
            "report": {
                "content": "finished",
                "provider_state": "final",
                "sequence": 4,
                "usage": {"total_tokens": 12},
                "stop_reason": "end_turn",
                "error_message": None,
                "legacy_event": {"event_id": "legacy-event-1"},
            },
            "report_hash": "0" * 64,
            "persisted": True,
        }
    )


def _verdict(action: str) -> RuntimeRecoveryVerdict:
    return RuntimeRecoveryVerdict.model_validate(
        {
            "action": action,
            "rationale": f"judge selected {action}",
            "evidence": ["stale correlation"],
            "agent_id": "provider:model",
            "input_json": {"status": "running"},
            "output_json": {"action": action},
            "latency_ms": 7,
        }
    )


class _FakeCoreClient:
    def __init__(
        self,
        operations: list[str],
        recovery: WorkspaceRuntimeRecoveryItem,
    ) -> None:
        self.operations = operations
        self.recovery = recovery
        self.terminal = _core_terminal()
        self.terminal_requests: list[WorkspaceRuntimeTerminalRequest] = []
        self.judgment_requests: list[WorkspaceRuntimeRecoveryJudgmentRequest] = []
        self.ack_requests: list[WorkspaceRuntimeCallbackAckRequest] = []
        self.ack_error: Exception | None = None
        self.read_error: Exception | None = None

    async def claim_runtime_recoveries(
        self,
        request: WorkspaceRuntimeRecoveryClaimRequest,
    ) -> WorkspaceRuntimeRecoveryClaimResponse:
        self.operations.append("claim")
        assert request.lease_owner == "worker-1"
        return WorkspaceRuntimeRecoveryClaimResponse(recoveries=[self.recovery])

    async def read_runtime_terminal(
        self,
        correlation_id: str,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
    ) -> WorkspaceRuntimeTerminalReadResponse:
        self.operations.append("read")
        assert (correlation_id, tenant_id, project_id, workspace_id) == (
            "correlation-1",
            "tenant-1",
            "project-1",
            "workspace-1",
        )
        if self.read_error is not None:
            raise self.read_error
        return self.terminal

    async def record_runtime_terminal(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeTerminalRequest,
    ) -> object:
        self.operations.append("terminal")
        assert correlation_id == "correlation-1"
        self.terminal_requests.append(request)
        return object()

    async def record_runtime_recovery_judgment(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeRecoveryJudgmentRequest,
    ) -> object:
        self.operations.append("judgment")
        assert correlation_id == "correlation-1"
        self.judgment_requests.append(request)
        return object()

    async def acknowledge_runtime_terminal_callback(
        self,
        correlation_id: str,
        request: WorkspaceRuntimeCallbackAckRequest,
    ) -> object:
        self.operations.append("ack")
        assert correlation_id == "correlation-1"
        self.ack_requests.append(request)
        if self.ack_error is not None:
            raise self.ack_error
        return object()


class _FakeSink:
    def __init__(self, operations: list[str]) -> None:
        self.operations = operations
        self.events: list[ProviderRuntimeEvent] = []
        self.error: Exception | None = None

    async def publish(
        self,
        request: ProviderWebhookRequest,
        event: ProviderRuntimeEvent,
    ) -> None:
        self.operations.append("publish")
        assert request.id == "run-1"
        self.events.append(event)
        if self.error is not None:
            raise self.error


class _FakeEvidence:
    def __init__(
        self,
        operations: list[str],
        terminal: AgentExecutionEvent | None = None,
    ) -> None:
        self.operations = operations
        self.terminal = terminal
        self.persisted_audit_ids: list[str] = []

    async def find_terminal(
        self,
        recovery: WorkspaceRuntimeRecoveryItem,
    ) -> AgentExecutionEvent | None:
        self.operations.append("find")
        return self.terminal

    async def persist_failure(
        self,
        recovery: WorkspaceRuntimeRecoveryItem,
        *,
        audit_id: str,
    ) -> AgentExecutionEvent:
        self.operations.append("persist")
        self.persisted_audit_ids.append(audit_id)
        return _legacy_terminal("error")


class _FakeJudge:
    def __init__(
        self,
        operations: list[str],
        result: RuntimeRecoveryVerdict | Exception,
    ) -> None:
        self.operations = operations
        self.result = result

    async def decide(self, recovery: WorkspaceRuntimeRecoveryItem) -> RuntimeRecoveryVerdict:
        self.operations.append("judge")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _worker(
    recovery: WorkspaceRuntimeRecoveryItem,
    *,
    terminal: AgentExecutionEvent | None = None,
    verdict: RuntimeRecoveryVerdict | Exception | None = None,
) -> tuple[
    AvernetRuntimeRecoveryWorker,
    _FakeCoreClient,
    _FakeSink,
    _FakeEvidence,
    list[str],
]:
    operations: list[str] = []
    core = _FakeCoreClient(operations, recovery)
    sink = _FakeSink(operations)
    evidence = _FakeEvidence(operations, terminal)
    judge = _FakeJudge(operations, verdict or _verdict("continue"))
    worker = AvernetRuntimeRecoveryWorker(
        core_client=cast(WorkspaceCoreClient, core),
        event_sink=cast(ProviderEventSink, sink),
        judge=judge,
        evidence=evidence,
        config=RuntimeRecoveryConfig(
            lease_owner="worker-1",
            interval_seconds=0.01,
        ),
    )
    return worker, core, sink, evidence, operations


@pytest.mark.unit
async def test_terminal_but_unacknowledged_replays_core_terminal() -> None:
    worker, core, sink, _, operations = _worker(_recovery(status="completed"))

    assert await worker.sweep_once() == 1

    assert operations == ["claim", "read", "publish", "ack"]
    assert sink.events[0].state == "final"
    assert sink.events[0].persisted is True
    assert core.ack_requests[0].workspace_id == "workspace-1"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "legacy_event_type", "expected_state"),
    [
        ("completed", AgentEventType.COMPLETE, "final"),
        ("failed", "error", "error"),
    ],
)
async def test_terminal_status_without_core_terminal_repairs_from_matching_legacy_evidence(
    status: str,
    legacy_event_type: AgentEventType | str,
    expected_state: str,
) -> None:
    worker, core, sink, _, operations = _worker(
        _recovery(status=status),
        terminal=_legacy_terminal(legacy_event_type),
    )
    core.read_error = WorkspaceCoreNotFoundError("terminal proof is missing")

    assert await worker.sweep_once() == 1

    assert operations == ["claim", "read", "find", "terminal", "publish", "ack"]
    assert core.terminal_requests[0].execution_status == (
        "complete" if status == "completed" else "error"
    )
    assert sink.events[0].state == expected_state


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "legacy_event_type"),
    [
        ("failed", AgentEventType.COMPLETE),
        ("aborted", "error"),
    ],
)
async def test_terminal_status_without_matching_legacy_evidence_stays_fail_closed(
    status: str,
    legacy_event_type: AgentEventType | str,
) -> None:
    worker, core, sink, _, operations = _worker(
        _recovery(status=status),
        terminal=_legacy_terminal(legacy_event_type),
    )
    core.read_error = WorkspaceCoreNotFoundError("terminal proof is missing")

    assert await worker.sweep_once() == 1

    assert operations == ["claim", "read", "find"]
    assert core.terminal_requests == []
    assert sink.events == []


@pytest.mark.unit
async def test_running_with_legacy_terminal_commits_core_before_callback() -> None:
    worker, core, sink, _, operations = _worker(
        _recovery(),
        terminal=_legacy_terminal(),
    )

    assert await worker.sweep_once() == 1

    assert operations == ["claim", "find", "terminal", "publish", "ack"]
    assert core.terminal_requests[0].execution_status == "complete"
    assert sink.events[0].correlation_id == "correlation-1"
    assert sink.events[0].persisted is True


@pytest.mark.unit
@pytest.mark.parametrize("action", ["continue", "escalate"])
async def test_nonterminal_judgments_do_not_create_fake_terminal(action: str) -> None:
    worker, core, sink, evidence, operations = _worker(
        _recovery(),
        verdict=_verdict(action),
    )

    assert await worker.sweep_once() == 1

    assert operations == ["claim", "find", "judge", "judgment"]
    assert core.judgment_requests[0].action == action
    assert core.terminal_requests == []
    assert evidence.persisted_audit_ids == []
    assert sink.events == []


@pytest.mark.unit
async def test_fail_judgment_is_audited_before_persisted_terminal_and_ack() -> None:
    worker, core, sink, evidence, operations = _worker(
        _recovery(),
        verdict=_verdict("fail"),
    )

    assert await worker.sweep_once() == 1

    assert operations == [
        "claim",
        "find",
        "judge",
        "judgment",
        "persist",
        "terminal",
        "publish",
        "ack",
    ]
    assert evidence.persisted_audit_ids == [core.judgment_requests[0].audit_id]
    assert core.terminal_requests[0].execution_status == "error"
    assert sink.events[0].state == "error"


@pytest.mark.unit
async def test_unavailable_judge_has_no_semantic_fallback() -> None:
    worker, core, sink, _, operations = _worker(
        _recovery(),
        verdict=RuntimeRecoveryJudgeUnavailable("no judge"),
    )

    assert await worker.sweep_once() == 1

    assert operations == ["claim", "find", "judge"]
    assert core.judgment_requests == []
    assert core.terminal_requests == []
    assert sink.events == []


@pytest.mark.unit
@pytest.mark.parametrize("failure_stage", ["publish", "ack"])
async def test_callback_failure_leaves_committed_terminal_recoverable(
    failure_stage: str,
) -> None:
    worker, core, sink, _, operations = _worker(
        _recovery(),
        terminal=_legacy_terminal(),
    )
    if failure_stage == "publish":
        sink.error = RuntimeError("callback unavailable")
    else:
        core.ack_error = RuntimeError("ack unavailable")

    assert await worker.sweep_once() == 1

    assert "terminal" in operations
    assert operations.index("terminal") < operations.index("publish")
    assert len(core.terminal_requests) == 1
    if failure_stage == "publish":
        assert "ack" not in operations
    else:
        assert operations[-1] == "ack"


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _ConversationRepository:
    def __init__(self, conversation: Conversation) -> None:
        self.conversation = conversation

    async def find_by_id(self, conversation_id: str) -> Conversation | None:
        return self.conversation if conversation_id == self.conversation.id else None


class _ScopedContainer:
    def __init__(self, conversation: Conversation) -> None:
        self.repository = _ConversationRepository(conversation)

    def conversation_repository(self) -> _ConversationRepository:
        return self.repository

    def agent_execution_event_repository(self) -> Any:
        raise AssertionError("scope mismatch must reject before reading events")


class _Container:
    def __init__(self, conversation: Conversation) -> None:
        self.scoped = _ScopedContainer(conversation)

    def with_db(self, _db: object) -> _ScopedContainer:
        return self.scoped


class _ExecutionEventRepository:
    def __init__(self, events: list[AgentExecutionEvent]) -> None:
        self.events = events

    async def get_events_by_message(
        self,
        conversation_id: str,
        message_id: str,
    ) -> list[AgentExecutionEvent]:
        assert conversation_id == "conversation-1"
        assert message_id
        return self.events


class _ScopedContainerWithEvents(_ScopedContainer):
    def __init__(
        self,
        conversation: Conversation,
        events: list[AgentExecutionEvent],
    ) -> None:
        super().__init__(conversation)
        self.events = _ExecutionEventRepository(events)

    def agent_execution_event_repository(self) -> _ExecutionEventRepository:
        return self.events


class _ContainerWithEvents(_Container):
    def __init__(
        self,
        conversation: Conversation,
        events: list[AgentExecutionEvent],
    ) -> None:
        super().__init__(conversation)
        self.scoped = _ScopedContainerWithEvents(conversation, events)


@pytest.mark.unit
async def test_evidence_selects_terminal_matching_core_status() -> None:
    conversation = Conversation(
        id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        user_id="user-1",
        title="Provider conversation",
        workspace_id="workspace-1",
        linked_workspace_task_id="task-1",
    )
    error_event = _legacy_terminal("error")
    complete_event = _legacy_terminal()
    container = _ContainerWithEvents(conversation, [error_event, complete_event])
    evidence = MemStackRuntimeRecoveryEvidence(
        session_factory=cast(Callable[[], Any], _SessionContext),
        container_provider=lambda: cast(Any, container),
    )

    terminal = await evidence.find_terminal(_recovery(status="failed"))

    assert terminal is error_event


@pytest.mark.unit
async def test_evidence_rejects_cross_scope_conversation() -> None:
    conversation = Conversation(
        id="conversation-1",
        tenant_id="other-tenant",
        project_id="project-1",
        user_id="user-1",
        title="Provider conversation",
        workspace_id="workspace-1",
        linked_workspace_task_id="task-1",
    )
    container = _Container(conversation)
    session_factory = cast(Callable[[], Any], _SessionContext)
    evidence = MemStackRuntimeRecoveryEvidence(
        session_factory=session_factory,
        container_provider=lambda: cast(Any, container),
    )

    with pytest.raises(PermissionError, match="scope does not match"):
        await evidence.find_terminal(_recovery())
