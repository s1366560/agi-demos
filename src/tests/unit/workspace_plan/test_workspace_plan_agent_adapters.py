"""Tests for builtin-agent backed workspace plan adapters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.ports.services.iteration_review_port import IterationReviewContext
from src.domain.ports.services.workspace_supervisor_decision_port import (
    WorkspaceSupervisorDecisionAction,
    WorkspaceSupervisorDecisionRequest,
)
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationJudgeRequest,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID,
    BUILTIN_WORKSPACE_PLANNER_ID,
    BUILTIN_WORKSPACE_SUPERVISOR_ID,
    BUILTIN_WORKSPACE_VERIFIER_ID,
    BUILTIN_WORKSPACE_WORKTREE_MANAGER_ID,
)
from src.infrastructure.agent.workspace.contract_agent_runtime import (
    create_workspace_contract_agent_service,
)
from src.infrastructure.agent.workspace.planner_agent_decomposer import (
    RuntimeWorkspacePlannerAgentTurnRunner,
    _planning_contract_from_event,
)
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_CONTRACT,
    WORKSPACE_SESSION_ROLE_KEY,
)
from src.infrastructure.agent.workspace_plan.iteration_review import (
    RuntimeWorkspaceIterationReviewAgentTurnRunner,
    WorkspaceIterationReviewAgentProvider,
    _iteration_review_from_event,
)
from src.infrastructure.agent.workspace_plan.supervisor_decision import (
    RuntimeWorkspaceSupervisorAgentTurnRunner,
    WorkspaceSupervisorAgentDecisionProvider,
)
from src.infrastructure.agent.workspace_plan.verification_judge import (
    RuntimeWorkspaceVerifierAgentTurnRunner,
    WorkspaceVerifierAgentJudge,
    _verification_judgment_from_event,
)
from src.infrastructure.agent.workspace_plan.worktree_agent import (
    RuntimeWorkspaceWorktreeAgentTurnRunner,
    WorkspaceWorktreeAgentPreparer,
    _worktree_preparation_from_event,
)
from src.infrastructure.agent.workspace_plan.worktree_manager import (
    AttemptWorktreePreparationRequest,
)

pytestmark = pytest.mark.unit


@dataclass
class _VerifierRunner:
    payload: dict[str, Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run_verification_turn(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


@dataclass
class _SequentialVerifierRunner:
    payloads: list[dict[str, Any] | None]
    calls: list[dict[str, Any]] = field(default_factory=list)
    last_diagnostics: dict[str, Any] = field(default_factory=dict)

    async def run_verification_turn(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(kwargs)
        self.last_diagnostics = {
            "conversation_id": "verifier-conversation",
            "event_count": 1293,
            "observed_tools": ["read", "bash"],
            "judgment_submitted": False,
        }
        if not self.payloads:
            return None
        return self.payloads.pop(0)


@dataclass
class _ReviewRunner:
    payload: dict[str, Any] | None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run_review_turn(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(kwargs)
        return self.payload


@dataclass
class _SequentialReviewRunner:
    payloads: list[dict[str, Any] | None]
    calls: list[dict[str, Any]] = field(default_factory=list)
    last_diagnostics: dict[str, Any] = field(default_factory=dict)

    async def run_review_turn(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(kwargs)
        self.last_diagnostics = {
            "conversation_id": "review-conversation",
            "event_count": 1786,
            "observed_tools": ["bash", "glob", "read", "grep"],
            "review_submitted": False,
        }
        if not self.payloads:
            return None
        return self.payloads.pop(0)


@dataclass
class _SupervisorDecisionRunner:
    payload: dict[str, Any] | None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run_decision_turn(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(kwargs)
        return self.payload


@dataclass
class _SequentialSupervisorDecisionRunner:
    payloads: list[dict[str, Any] | None]
    calls: list[dict[str, Any]] = field(default_factory=list)
    last_diagnostics: dict[str, Any] = field(default_factory=dict)

    async def run_decision_turn(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(kwargs)
        self.last_diagnostics = {
            "conversation_id": "supervisor-conversation",
            "event_count": 42,
            "observed_tools": ["read"],
            "decision_submitted": False,
        }
        if not self.payloads:
            return None
        return self.payloads.pop(0)


@dataclass
class _WorktreePreparationRunner:
    payload: dict[str, Any] | None
    calls: list[dict[str, Any]] = field(default_factory=list)
    last_diagnostics: dict[str, Any] = field(default_factory=dict)

    async def run_preparation_turn(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(kwargs)
        return self.payload


def _patch_contract_agent_stream_runtime(  # noqa: C901
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[dict[str, Any]],
    persist_calls: list[dict[str, Any]],
    stream_calls: list[dict[str, Any]],
    actor_user_id: str | None = "user-1",
    cancel_calls: list[str] | None = None,
    stream_factory: Any | None = None,
) -> None:
    async def fake_resolve_workspace_actor_user_id(
        *,
        workspace_id: str,
        actor_user_id: str | None = None,
    ) -> str | None:
        _ = workspace_id
        return actor_user_id or actor_user_id_override

    async def fake_ensure_workspace_llm_conversation(**kwargs: Any) -> bool:
        persist_calls.append(kwargs)
        return True

    async def fake_recover_workspace_contract_payload(**kwargs: Any) -> dict[str, Any] | None:
        _ = kwargs
        return None

    async def fake_cancel_workspace_contract_chat(conversation_id: str) -> None:
        if cancel_calls is not None:
            cancel_calls.append(conversation_id)

    async def fake_create_llm_client(tenant_id: str) -> str:
        return f"llm:{tenant_id}"

    async def fake_get_redis_client() -> str:
        return "redis:test"

    class FakeSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: Any) -> None:
            _ = args
            return None

    def fake_async_session_factory() -> FakeSessionContext:
        return FakeSessionContext()

    class FakeAgentService:
        def stream_chat_v2(self, **kwargs: Any) -> Any:
            stream_calls.append(kwargs)
            if stream_factory is not None:
                return stream_factory()

            async def _events() -> Any:
                for event in events:
                    yield event

            return _events()

    class FakeDIContainer:
        def __init__(self, *, db: object, redis_client: object | None = None) -> None:
            self.db = db
            self.redis_client = redis_client

        def agent_service(self, llm: str) -> FakeAgentService:
            assert llm == "llm:tenant-1"
            return FakeAgentService()

    actor_user_id_override = actor_user_id

    from src.configuration import di_container, factories
    from src.infrastructure.adapters.primary.web.startup import container as startup_container
    from src.infrastructure.adapters.secondary.persistence import database
    from src.infrastructure.agent.state import agent_worker_state
    from src.infrastructure.agent.workspace import (
        contract_agent_runtime,
        session_conversations,
    )

    monkeypatch.setattr(startup_container, "get_app_container", lambda: None)
    monkeypatch.setattr(
        contract_agent_runtime,
        "resolve_workspace_actor_user_id",
        fake_resolve_workspace_actor_user_id,
    )
    monkeypatch.setattr(
        contract_agent_runtime,
        "recover_workspace_contract_payload",
        fake_recover_workspace_contract_payload,
    )
    monkeypatch.setattr(
        contract_agent_runtime,
        "cancel_workspace_contract_chat",
        fake_cancel_workspace_contract_chat,
    )
    monkeypatch.setattr(
        session_conversations,
        "ensure_workspace_llm_conversation",
        fake_ensure_workspace_llm_conversation,
    )
    monkeypatch.setattr(database, "async_session_factory", fake_async_session_factory)
    monkeypatch.setattr(factories, "create_llm_client", fake_create_llm_client)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)
    monkeypatch.setattr(agent_worker_state, "get_redis_client", fake_get_redis_client)


async def test_workspace_contract_agent_service_uses_app_container_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = object()
    agent_service = object()
    with_db_calls: list[object] = []

    class FakeScopedContainer:
        def agent_service(self, llm: str) -> object:
            assert llm == "llm:tenant-1"
            return agent_service

    class FakeAppContainer:
        def with_db(self, scoped_db: object) -> FakeScopedContainer:
            with_db_calls.append(scoped_db)
            return FakeScopedContainer()

    from src.configuration import di_container
    from src.infrastructure.adapters.primary.web.startup import container as startup_container

    class ForbiddenDIContainer:
        def __init__(self, **kwargs: object) -> None:
            raise AssertionError(f"unexpected fallback container: {kwargs}")

    monkeypatch.setattr(startup_container, "get_app_container", lambda: FakeAppContainer())
    monkeypatch.setattr(di_container, "DIContainer", ForbiddenDIContainer)

    assert await create_workspace_contract_agent_service(db=db, llm="llm:tenant-1") is agent_service
    assert with_db_calls == [db]


async def test_workspace_contract_agent_service_fallback_injects_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = object()
    agent_service = object()
    init_calls: list[dict[str, object | None]] = []

    class FakeDIContainer:
        def __init__(self, *, db: object, redis_client: object | None = None) -> None:
            init_calls.append({"db": db, "redis_client": redis_client})

        def agent_service(self, llm: str) -> object:
            assert llm == "llm:tenant-1"
            return agent_service

    from src.configuration import di_container
    from src.infrastructure.adapters.primary.web.startup import container as startup_container
    from src.infrastructure.agent.state import agent_worker_state

    async def fake_get_redis_client() -> str:
        return "redis:fallback"

    monkeypatch.setattr(startup_container, "get_app_container", lambda: None)
    monkeypatch.setattr(agent_worker_state, "get_redis_client", fake_get_redis_client)
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)

    assert await create_workspace_contract_agent_service(db=db, llm="llm:tenant-1") is agent_service
    assert init_calls == [{"db": db, "redis_client": "redis:fallback"}]


async def test_workspace_verifier_agent_judge_uses_builtin_agent_turn_runner() -> None:
    runner = _VerifierRunner(
        {
            "verdict": "needs_rework",
            "rationale": "Falling tests remain.",
            "failed_criteria": ["failed_test_evidence"],
            "satisfied_guard_failures": ["clean_worktree_after_commit"],
            "required_next_action": "fix tests",
            "next_action_kind": "create_repair_node",
            "repair_brief": {
                "failed_items": ["failed_test_evidence"],
                "minimum_verifications": ["npm test"],
            },
            "feedback_items": [
                {
                    "target_layer": "planner",
                    "feedback_kind": "test_policy_conflict",
                    "severity": "blocking",
                    "recommended_action": "create_repair_node",
                    "failure_signature": "test-policy-conflict",
                }
            ],
            "confidence": 0.84,
        }
    )
    judge = WorkspaceVerifierAgentJudge(
        tenant_id="tenant-1",
        project_id="project-1",
        turn_runner=runner,
    )

    result = await judge.judge(
        WorkspaceVerificationJudgeRequest(
            workspace_id="ws-1",
            node_id="node-1",
            attempt_id="attempt-1",
            node_title="Run tests",
            node_description="Verify tests.",
            linked_workspace_task_id="task-1",
        )
    )

    assert runner.calls[0]["verifier_agent"].id == BUILTIN_WORKSPACE_VERIFIER_ID
    assert runner.calls[0]["linked_workspace_task_id"] == "task-1"
    assert "workspace_submit_verification_judgment" in runner.calls[0]["user_prompt"]
    assert result.verdict.value == "needs_rework"
    assert result.failed_criteria == ("failed_test_evidence",)
    assert result.satisfied_guard_failures == ("clean_worktree_after_commit",)
    assert result.next_action_kind.value == "create_repair_node"
    assert result.repair_brief == {
        "failed_items": ["failed_test_evidence"],
        "minimum_verifications": ["npm test"],
    }
    assert result.feedback_items[0].target_layer.value == "planner"
    assert result.feedback_items[0].failure_signature == "test-policy-conflict"


async def test_verifier_agent_judge_retries_missing_contract_submission() -> None:
    runner = _SequentialVerifierRunner(
        [
            None,
            {
                "verdict": "accepted",
                "rationale": "Current evidence satisfies the node.",
                "failed_criteria": [],
                "satisfied_guard_failures": [],
                "required_next_action": "",
                "next_action_kind": "none",
                "confidence": 0.91,
            },
        ]
    )
    judge = WorkspaceVerifierAgentJudge(
        tenant_id="tenant-1",
        project_id="project-1",
        turn_runner=runner,
    )

    result = await judge.judge(
        WorkspaceVerificationJudgeRequest(
            workspace_id="ws-1",
            node_id="node-1",
            attempt_id="attempt-1",
            node_title="Validate CI",
            node_description="Check pipeline evidence.",
            linked_workspace_task_id="task-1",
        )
    )

    assert len(runner.calls) == 2
    assert "Verify this workspace plan node" in runner.calls[0]["user_prompt"]
    retry_prompt = runner.calls[1]["user_prompt"]
    assert "Contract retry" in retry_prompt
    assert "did not call workspace_submit_verification_judgment" in retry_prompt
    assert '"event_count": 1293' in retry_prompt
    assert result.verdict.value == "accepted"
    assert result.next_action_kind.value == "none"
    assert result.confidence == 0.91


async def test_supervisor_agent_decision_provider_submits_structured_action() -> None:
    runner = _SupervisorDecisionRunner(
        {
            "action": "request_pipeline",
            "rationale": "Verifier requires harness-native pipeline evidence.",
            "confidence": 0.87,
            "feedback_items": [
                {
                    "target_layer": "runtime",
                    "recommended_action": "retry_infra",
                    "summary": "Pipeline gate is missing.",
                }
            ],
        }
    )
    provider = WorkspaceSupervisorAgentDecisionProvider(
        tenant_id="tenant-1",
        project_id="project-1",
        turn_runner=runner,
    )

    result = await provider.decide(
        WorkspaceSupervisorDecisionRequest(
            workspace_id="ws-1",
            plan_id="plan-1",
            node_id="node-1",
            attempt_id="attempt-1",
            linked_workspace_task_id="task-1",
            node_snapshot={"title": "Deploy"},
            verification_report={"passed": False},
            allowed_actions=tuple(WorkspaceSupervisorDecisionAction),
        )
    )

    assert runner.calls[0]["supervisor_agent"].id == BUILTIN_WORKSPACE_SUPERVISOR_ID
    assert runner.calls[0]["linked_workspace_task_id"] == "task-1"
    assert "workspace_submit_supervisor_decision" in runner.calls[0]["user_prompt"]
    assert result.action is WorkspaceSupervisorDecisionAction.REQUEST_PIPELINE
    assert result.confidence == 0.87
    assert result.feedback_items[0]["target_layer"] == "runtime"


async def test_supervisor_agent_decision_provider_retries_missing_contract_submission() -> None:
    runner = _SequentialSupervisorDecisionRunner(
        [
            None,
            {
                "action": "retry_same_node",
                "rationale": "Same node can collect missing evidence.",
                "confidence": 0.73,
            },
        ]
    )
    provider = WorkspaceSupervisorAgentDecisionProvider(
        tenant_id="tenant-1",
        project_id="project-1",
        turn_runner=runner,
    )

    result = await provider.decide(
        WorkspaceSupervisorDecisionRequest(
            workspace_id="ws-1",
            plan_id="plan-1",
            node_id="node-1",
            attempt_id="attempt-1",
            linked_workspace_task_id="task-1",
            allowed_actions=tuple(WorkspaceSupervisorDecisionAction),
        )
    )

    assert len(runner.calls) == 2
    retry_prompt = runner.calls[1]["user_prompt"]
    assert "Contract retry" in retry_prompt
    assert "did not call workspace_submit_supervisor_decision" in retry_prompt
    assert '"event_count": 42' in retry_prompt
    assert result.action is WorkspaceSupervisorDecisionAction.RETRY_SAME_NODE
    assert result.confidence == 0.73


async def test_runtime_supervisor_agent_turn_runner_times_out_and_cancels_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []
    stream_calls: list[dict[str, Any]] = []
    cancel_calls: list[str] = []

    async def never_events() -> Any:
        await asyncio.sleep(10)
        if False:
            yield {}

    _patch_contract_agent_stream_runtime(
        monkeypatch,
        events=[],
        persist_calls=persist_calls,
        stream_calls=stream_calls,
        actor_user_id="workspace-created-user",
        cancel_calls=cancel_calls,
        stream_factory=never_events,
    )

    runner = RuntimeWorkspaceSupervisorAgentTurnRunner(
        tenant_id="tenant-1",
        project_id="project-1",
        turn_timeout_seconds=0.01,
    )

    result = await runner.run_decision_turn(
        supervisor_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_SUPERVISOR_ID),
        user_prompt="decide",
        workspace_id="ws-1",
        plan_id="plan-1",
        node_id="node-1",
        attempt_id="attempt-1",
        linked_workspace_task_id="task-1",
    )

    assert result is None
    assert persist_calls
    assert stream_calls
    assert runner.last_diagnostics["timed_out"] is True
    assert runner.last_diagnostics["event_count"] == 0
    assert cancel_calls == [runner.last_diagnostics["conversation_id"]]


async def test_worktree_agent_preparer_uses_builtin_agent_turn_runner() -> None:
    runner = _WorktreePreparationRunner(
        {
            "status": "prepared",
            "worktree_path": "/repo/.memstack/worktrees/attempt-1",
            "branch_name": "workspace/node-attempt-1",
            "base_ref": "HEAD",
            "original_base_ref": "HEAD",
            "resolved_base_ref": "HEAD",
            "output": "git_head=abc123",
        }
    )
    preparer = WorkspaceWorktreeAgentPreparer(
        tenant_id="tenant-1",
        project_id="project-1",
        turn_runner=runner,
    )

    result = await preparer.prepare_worktree(
        AttemptWorktreePreparationRequest(
            workspace_id="ws-1",
            task_id="task-1",
            attempt_id="attempt-1",
            workspace_root="/repo",
            sandbox_code_root="/repo/app",
            worktree_path="/repo/.memstack/worktrees/attempt-1",
            branch_name="workspace/node-attempt-1",
            base_ref="HEAD",
            original_base_ref="HEAD",
            setup_command="echo setup",
            diagnostics_command="echo diagnostics",
        )
    )

    assert result is not None
    assert runner.calls[0]["worktree_agent"].id == BUILTIN_WORKSPACE_WORKTREE_MANAGER_ID
    assert runner.calls[0]["workspace_id"] == "ws-1"
    assert runner.calls[0]["task_id"] == "task-1"
    assert "workspace_submit_worktree_preparation" in runner.calls[0]["user_prompt"]
    assert result.setup_status == "prepared"
    assert result.worktree_path == "/repo/.memstack/worktrees/attempt-1"
    assert result.is_isolated is True


async def test_verifier_agent_judge_uses_fallback_linked_task_in_prompts() -> None:
    runner = _SequentialVerifierRunner(
        [
            None,
            {
                "verdict": "accepted",
                "rationale": "Evidence passes.",
                "failed_criteria": [],
                "satisfied_guard_failures": [],
                "required_next_action": "",
                "next_action_kind": "none",
                "confidence": 0.91,
            },
        ]
    )
    judge = WorkspaceVerifierAgentJudge(
        tenant_id="tenant-1",
        project_id="project-1",
        linked_workspace_task_id="root-task-1",
        turn_runner=runner,
    )

    result = await judge.judge(
        WorkspaceVerificationJudgeRequest(
            workspace_id="ws-1",
            node_id="node-1",
            attempt_id="attempt-1",
            node_title="Validate CI",
            node_description="Check pipeline evidence.",
        )
    )

    assert result.verdict.value == "accepted"
    assert '"linked_workspace_task_id": "root-task-1"' in runner.calls[0]["user_prompt"]
    assert '"linked_workspace_task_id": "root-task-1"' in runner.calls[1]["user_prompt"]


async def test_runtime_workspace_planner_uses_stream_chat_v2_with_actor_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []
    stream_calls: list[dict[str, Any]] = []
    planning_contract = {
        "task_graph": {"subtasks": []},
        "delivery_cicd": {"services": []},
        "reasoning": "ok",
        "evidence_refs": [],
        "confidence": 0.8,
    }
    _patch_contract_agent_stream_runtime(
        monkeypatch,
        events=[
            {
                "type": "observe",
                "data": {
                    "tool_name": "workspace_submit_planning_contract",
                    "result": {"planning_contract": planning_contract},
                },
            }
        ],
        persist_calls=persist_calls,
        stream_calls=stream_calls,
        actor_user_id="workspace-created-user",
    )

    runner = RuntimeWorkspacePlannerAgentTurnRunner(tenant_id="tenant-1", project_id="project-1")

    result = await runner.run_planning_turn(
        planner_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_PLANNER_ID, max_iterations=1),
        user_prompt="plan",
        workspace_id="ws-1",
        root_task_id="root-task-1",
        actor_user_id="user-2",
        workspace_metadata={"code_context": {"repo": "agi-demos"}},
        root_metadata={},
        contract_only=True,
    )

    assert result == planning_contract
    assert persist_calls[0]["actor_user_id"] == "user-2"
    assert persist_calls[0]["agent_id"] == BUILTIN_WORKSPACE_PLANNER_ID
    assert persist_calls[0]["metadata"]["contract_only"] is True
    assert stream_calls[0]["conversation_id"].startswith(
        "workspace-contract:planner:tenant-1:project-1:ws-1:root-task-1:"
    )
    assert stream_calls[0]["user_message"] == "plan"
    assert stream_calls[0]["user_id"] == "user-2"
    assert stream_calls[0]["tenant_id"] == "tenant-1"
    assert stream_calls[0]["project_id"] == "project-1"
    assert stream_calls[0]["agent_id"] == BUILTIN_WORKSPACE_PLANNER_ID
    assert stream_calls[0]["app_model_context"]["context_type"] == "workspace_worker_runtime"
    assert (
        stream_calls[0]["app_model_context"][WORKSPACE_SESSION_ROLE_KEY]
        == WORKSPACE_ROLE_CONTRACT
    )
    assert stream_calls[0]["app_model_context"]["workspace_binding"]["workspace_id"] == "ws-1"
    assert stream_calls[0]["app_model_context"]["code_context"] == {"repo": "agi-demos"}
    assert stream_calls[0]["app_model_context"]["runtime_limits"] == {"max_tokens": 8192}
    assert stream_calls[0]["app_model_context"]["llm_overrides"] == {"max_tokens": 8192}


async def test_runtime_workspace_planner_recovers_persisted_contract_without_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planning_contract = {
        "task_graph": {"subtasks": []},
        "delivery_cicd": {"services": []},
        "reasoning": "already submitted",
        "evidence_refs": [],
        "confidence": 0.8,
    }

    async def fake_recover_workspace_contract_payload(**kwargs: Any) -> dict[str, Any] | None:
        assert kwargs["conversation_id"].startswith(
            "workspace-contract:planner:tenant-1:project-1:ws-1:root-task-1:"
        )
        assert kwargs["extract_payload"] is _planning_contract_from_event
        return planning_contract

    async def forbidden_resolve_workspace_actor_user_id(**kwargs: Any) -> str:
        raise AssertionError(f"unexpected actor resolution after recovery: {kwargs}")

    from src.infrastructure.agent.workspace import contract_agent_runtime

    monkeypatch.setattr(
        contract_agent_runtime,
        "recover_workspace_contract_payload",
        fake_recover_workspace_contract_payload,
    )
    monkeypatch.setattr(
        contract_agent_runtime,
        "resolve_workspace_actor_user_id",
        forbidden_resolve_workspace_actor_user_id,
    )

    runner = RuntimeWorkspacePlannerAgentTurnRunner(tenant_id="tenant-1", project_id="project-1")

    result = await runner.run_planning_turn(
        planner_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_PLANNER_ID),
        user_prompt="plan",
        workspace_id="ws-1",
        root_task_id="root-task-1",
        actor_user_id="user-2",
        workspace_metadata={},
        root_metadata={},
        contract_only=False,
    )

    assert result == planning_contract
    assert runner.last_diagnostics["recovered_from_events"] is True
    assert runner.last_diagnostics["contract_submitted"] is True


async def test_runtime_workspace_planner_input_changes_get_distinct_conversations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []
    stream_calls: list[dict[str, Any]] = []
    _patch_contract_agent_stream_runtime(
        monkeypatch,
        events=[],
        persist_calls=persist_calls,
        stream_calls=stream_calls,
        actor_user_id="user-1",
    )
    runner = RuntimeWorkspacePlannerAgentTurnRunner(tenant_id="tenant-1", project_id="project-1")
    common: dict[str, Any] = {
        "planner_agent": SimpleNamespace(id=BUILTIN_WORKSPACE_PLANNER_ID),
        "workspace_id": "ws-1",
        "root_task_id": "root-task-1",
        "actor_user_id": "user-1",
        "workspace_metadata": {"code_context": {"repo": "agi-demos"}},
        "root_metadata": {},
        "contract_only": False,
    }

    await runner.run_planning_turn(user_prompt="plan first goal", **common)
    await runner.run_planning_turn(user_prompt="plan revised goal", **common)

    assert len(stream_calls) == 2
    assert stream_calls[0]["conversation_id"] != stream_calls[1]["conversation_id"]


async def test_runtime_workspace_verifier_persists_linked_workspace_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []
    stream_calls: list[dict[str, Any]] = []
    cancel_calls: list[str] = []
    _patch_contract_agent_stream_runtime(
        monkeypatch,
        events=[
            {
                "type": "observe",
                "data": {
                    "tool_name": "workspace_submit_verification_judgment",
                    "result": {
                        "verification_judgment": {
                            "verdict": "accepted",
                            "rationale": "Evidence passes.",
                        }
                    },
                },
            }
        ],
        persist_calls=persist_calls,
        stream_calls=stream_calls,
        cancel_calls=cancel_calls,
    )

    runner = RuntimeWorkspaceVerifierAgentTurnRunner(tenant_id="tenant-1", project_id="project-1")

    result = await runner.run_verification_turn(
        verifier_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_VERIFIER_ID),
        user_prompt="judge",
        workspace_id="ws-1",
        node_id="node-1",
        attempt_id="attempt-1",
        linked_workspace_task_id="task-1",
    )

    assert result == {"verdict": "accepted", "rationale": "Evidence passes."}
    assert persist_calls[0]["linked_workspace_task_id"] == "task-1"
    assert persist_calls[0]["actor_user_id"] == "user-1"
    assert persist_calls[0]["metadata"]["linked_workspace_task_id"] == "task-1"
    assert stream_calls[0]["conversation_id"].startswith(
        "workspace-contract:verifier:tenant-1:project-1:ws-1:node-1:"
    )
    assert stream_calls[0]["user_message"] == "judge"
    assert stream_calls[0]["user_id"] == "user-1"
    assert stream_calls[0]["tenant_id"] == "tenant-1"
    assert stream_calls[0]["project_id"] == "project-1"
    assert stream_calls[0]["agent_id"] == BUILTIN_WORKSPACE_VERIFIER_ID
    assert stream_calls[0]["app_model_context"]["context_type"] == "workspace_worker_runtime"
    assert (
        stream_calls[0]["app_model_context"][WORKSPACE_SESSION_ROLE_KEY]
        == WORKSPACE_ROLE_CONTRACT
    )
    assert stream_calls[0]["app_model_context"]["runtime_limits"] == {"max_tokens": 8192}
    assert (
        stream_calls[0]["app_model_context"]["workspace_binding"]["linked_workspace_task_id"]
        == "task-1"
    )
    assert cancel_calls == [stream_calls[0]["conversation_id"]]


async def test_runtime_workspace_verifier_ignores_unpersisted_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream_called = False

    async def fake_ensure_workspace_llm_conversation(**kwargs: Any) -> bool:
        _ = kwargs
        return False

    class FakeAgentService:
        def stream_chat_v2(self, **kwargs: Any) -> Any:
            nonlocal stream_called
            stream_called = True

            async def _events() -> Any:
                if False:
                    yield {}

            return _events()

    class FakeDIContainer:
        def __init__(self, *, db: object, redis_client: object | None = None) -> None:
            self.db = db
            self.redis_client = redis_client

        def agent_service(self, llm: object) -> FakeAgentService:
            _ = llm
            return FakeAgentService()

    from src.configuration import di_container
    from src.infrastructure.agent.workspace import contract_agent_runtime, session_conversations

    async def fake_resolve_workspace_actor_user_id(
        *,
        workspace_id: str,
        actor_user_id: str | None = None,
    ) -> str | None:
        _ = (workspace_id, actor_user_id)
        return "user-1"

    async def fake_recover_workspace_contract_payload(**kwargs: Any) -> dict[str, Any] | None:
        _ = kwargs
        return None

    monkeypatch.setattr(
        session_conversations,
        "ensure_workspace_llm_conversation",
        fake_ensure_workspace_llm_conversation,
    )
    monkeypatch.setattr(
        contract_agent_runtime,
        "resolve_workspace_actor_user_id",
        fake_resolve_workspace_actor_user_id,
    )
    monkeypatch.setattr(
        contract_agent_runtime,
        "recover_workspace_contract_payload",
        fake_recover_workspace_contract_payload,
    )
    monkeypatch.setattr(di_container, "DIContainer", FakeDIContainer)

    runner = RuntimeWorkspaceVerifierAgentTurnRunner(tenant_id="tenant-1", project_id="project-1")

    result = await runner.run_verification_turn(
        verifier_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_VERIFIER_ID),
        user_prompt="judge",
        workspace_id="ws-1",
        node_id="node-1",
        attempt_id="attempt-1",
        linked_workspace_task_id="task-1",
    )

    assert result is None
    assert stream_called is False


async def test_runtime_workspace_verifier_keeps_diagnostics_when_judgment_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []
    stream_calls: list[dict[str, Any]] = []
    _patch_contract_agent_stream_runtime(
        monkeypatch,
        events=[
            {
                "type": "observe",
                "data": {
                    "tool_name": "read",
                    "result": "ok",
                },
            }
        ],
        persist_calls=persist_calls,
        stream_calls=stream_calls,
    )

    runner = RuntimeWorkspaceVerifierAgentTurnRunner(tenant_id="tenant-1", project_id="project-1")

    result = await runner.run_verification_turn(
        verifier_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_VERIFIER_ID),
        user_prompt="judge",
        workspace_id="ws-1",
        node_id="node-1",
        attempt_id="attempt-1",
        linked_workspace_task_id="task-1",
    )

    assert result is None
    assert runner.last_diagnostics["event_count"] == 1
    assert runner.last_diagnostics["observed_tools"] == ["read"]
    assert runner.last_diagnostics["judgment_submitted"] is False


async def test_iteration_review_agent_provider_uses_builtin_agent_turn_runner() -> None:
    runner = _ReviewRunner(
        {
            "verdict": "continue_next_iteration",
            "confidence": 0.91,
            "summary": "One proof sprint remains.",
            "next_sprint_goal": "Collect browser proof.",
            "feedback_items": ["Browser proof missing."],
            "next_tasks": [
                {
                    "id": "browser-proof",
                    "description": "Run browser parity verification.",
                    "phase": "test",
                }
            ],
        }
    )
    provider = WorkspaceIterationReviewAgentProvider(
        tenant_id="tenant-1",
        project_id="project-1",
        linked_workspace_task_id="root-task-1",
        max_next_tasks=6,
        turn_runner=runner,
    )

    result = await provider.review(
        IterationReviewContext(
            workspace_id="ws-1",
            plan_id="plan-1",
            iteration_index=7,
            goal_title="Goal",
            goal_description="Goal description.",
            max_next_tasks=6,
        )
    )

    assert runner.calls[0]["reviewer_agent"].id == BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID
    assert runner.calls[0]["linked_workspace_task_id"] == "root-task-1"
    assert "workspace_submit_iteration_review" in runner.calls[0]["user_prompt"]
    assert result.verdict == "continue_next_iteration"
    assert result.next_tasks[0].id == "browser-proof"


async def test_iteration_review_agent_provider_retries_missing_contract_submission() -> None:
    runner = _SequentialReviewRunner(
        [
            None,
            {
                "verdict": "complete_goal",
                "confidence": 0.88,
                "summary": "The iteration has enough evidence to finish.",
            },
        ]
    )
    provider = WorkspaceIterationReviewAgentProvider(
        tenant_id="tenant-1",
        project_id="project-1",
        linked_workspace_task_id="root-task-1",
        max_next_tasks=6,
        turn_runner=runner,
    )

    result = await provider.review(
        IterationReviewContext(
            workspace_id="ws-1",
            plan_id="plan-1",
            iteration_index=7,
            goal_title="Goal",
            goal_description="Goal description.",
            max_next_tasks=6,
        )
    )

    assert len(runner.calls) == 2
    assert "Review this completed workspace iteration" in runner.calls[0]["user_prompt"]
    retry_prompt = runner.calls[1]["user_prompt"]
    assert "Contract retry" in retry_prompt
    assert "did not call workspace_submit_iteration_review" in retry_prompt
    assert '"event_count": 1786' in retry_prompt
    assert result.verdict == "complete_goal"
    assert result.summary == "The iteration has enough evidence to finish."


async def test_runtime_iteration_reviewer_persists_linked_workspace_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []
    stream_calls: list[dict[str, Any]] = []
    _patch_contract_agent_stream_runtime(
        monkeypatch,
        events=[
            {
                "type": "tool_result",
                "data": {
                    "tool_name": "workspace_submit_iteration_review",
                    "result": {
                        "iteration_review": {
                            "verdict": "complete_goal",
                            "confidence": 0.9,
                            "summary": "Done.",
                        }
                    },
                },
            }
        ],
        persist_calls=persist_calls,
        stream_calls=stream_calls,
    )

    runner = RuntimeWorkspaceIterationReviewAgentTurnRunner(
        tenant_id="tenant-1",
        project_id="project-1",
    )

    result = await runner.run_review_turn(
        reviewer_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID),
        user_prompt="review",
        workspace_id="ws-1",
        plan_id="plan-1",
        iteration_index=3,
        linked_workspace_task_id="root-task-1",
    )

    assert result == {"verdict": "complete_goal", "confidence": 0.9, "summary": "Done."}
    assert persist_calls[0]["linked_workspace_task_id"] == "root-task-1"
    assert persist_calls[0]["actor_user_id"] == "user-1"
    assert persist_calls[0]["metadata"]["linked_workspace_task_id"] == "root-task-1"
    assert stream_calls[0]["conversation_id"].startswith(
        "workspace-contract:iteration-review:tenant-1:project-1:ws-1:plan-1:"
    )
    assert stream_calls[0]["user_message"] == "review"
    assert stream_calls[0]["user_id"] == "user-1"
    assert stream_calls[0]["tenant_id"] == "tenant-1"
    assert stream_calls[0]["project_id"] == "project-1"
    assert stream_calls[0]["agent_id"] == BUILTIN_WORKSPACE_ITERATION_REVIEWER_ID
    assert stream_calls[0]["app_model_context"]["context_type"] == "workspace_worker_runtime"
    assert (
        stream_calls[0]["app_model_context"][WORKSPACE_SESSION_ROLE_KEY]
        == WORKSPACE_ROLE_CONTRACT
    )
    assert stream_calls[0]["app_model_context"]["runtime_limits"] == {"max_tokens": 8192}
    assert (
        stream_calls[0]["app_model_context"]["workspace_binding"]["linked_workspace_task_id"]
        == "root-task-1"
    )
    assert stream_calls[0]["app_model_context"]["iteration_review"]["plan_id"] == "plan-1"


async def test_runtime_worktree_manager_persists_linked_workspace_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []
    stream_calls: list[dict[str, Any]] = []
    payload = {
        "status": "prepared",
        "worktree_path": "/repo/.memstack/worktrees/attempt-1",
        "branch_name": "workspace/node-attempt-1",
        "base_ref": "HEAD",
    }
    _patch_contract_agent_stream_runtime(
        monkeypatch,
        events=[
            {
                "type": "observe",
                "data": {
                    "tool_name": "workspace_submit_worktree_preparation",
                    "result": {"worktree_preparation": payload},
                },
            }
        ],
        persist_calls=persist_calls,
        stream_calls=stream_calls,
    )

    runner = RuntimeWorkspaceWorktreeAgentTurnRunner(
        tenant_id="tenant-1",
        project_id="project-1",
    )

    result = await runner.run_preparation_turn(
        worktree_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_WORKTREE_MANAGER_ID),
        user_prompt="prepare",
        workspace_id="ws-1",
        task_id="task-1",
        attempt_id="attempt-1",
    )

    assert result == payload
    assert persist_calls[0]["linked_workspace_task_id"] == "task-1"
    assert persist_calls[0]["actor_user_id"] == "user-1"
    assert persist_calls[0]["metadata"]["linked_workspace_task_id"] == "task-1"
    assert stream_calls[0]["conversation_id"].startswith(
        "workspace-contract:worktree-manager:tenant-1:project-1:ws-1:task-1:"
    )
    assert stream_calls[0]["user_message"] == "prepare"
    assert stream_calls[0]["user_id"] == "user-1"
    assert stream_calls[0]["agent_id"] == BUILTIN_WORKSPACE_WORKTREE_MANAGER_ID
    assert stream_calls[0]["app_model_context"]["context_type"] == "workspace_worker_runtime"
    assert (
        stream_calls[0]["app_model_context"][WORKSPACE_SESSION_ROLE_KEY]
        == WORKSPACE_ROLE_CONTRACT
    )
    assert (
        stream_calls[0]["app_model_context"]["workspace_binding"]["linked_workspace_task_id"]
        == "task-1"
    )
    assert stream_calls[0]["app_model_context"]["worktree_manager"]["task_id"] == "task-1"


async def test_runtime_worktree_manager_turn_runner_times_out_and_cancels_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persist_calls: list[dict[str, Any]] = []
    stream_calls: list[dict[str, Any]] = []
    cancel_calls: list[str] = []

    async def never_events() -> Any:
        await asyncio.sleep(10)
        if False:
            yield {}

    _patch_contract_agent_stream_runtime(
        monkeypatch,
        events=[],
        persist_calls=persist_calls,
        stream_calls=stream_calls,
        actor_user_id="workspace-created-user",
        cancel_calls=cancel_calls,
        stream_factory=never_events,
    )

    runner = RuntimeWorkspaceWorktreeAgentTurnRunner(
        tenant_id="tenant-1",
        project_id="project-1",
        turn_timeout_seconds=0.01,
    )

    result = await runner.run_preparation_turn(
        worktree_agent=SimpleNamespace(id=BUILTIN_WORKSPACE_WORKTREE_MANAGER_ID),
        user_prompt="prepare",
        workspace_id="ws-1",
        task_id="task-1",
        attempt_id="attempt-1",
    )

    assert result is None
    assert persist_calls
    assert stream_calls
    assert runner.last_diagnostics["timed_out"] is True
    assert runner.last_diagnostics["event_count"] == 0
    assert cancel_calls == [runner.last_diagnostics["conversation_id"]]


def test_planning_contract_event_parser_accepts_observe_result_metadata() -> None:
    payload = {
        "task_graph": {"subtasks": []},
        "delivery_cicd": {"services": []},
        "reasoning": "ok",
        "evidence_refs": [],
        "confidence": 0.8,
    }

    assert (
        _planning_contract_from_event(
            {
                "type": "observe",
                "data": {
                    "tool_name": "workspace_submit_planning_contract",
                    "result": {"planning_contract": payload},
                },
            }
        )
        == payload
    )


def test_iteration_review_event_parser_accepts_tool_result_metadata() -> None:
    payload = {
        "verdict": "complete_goal",
        "confidence": 0.9,
        "summary": "Done.",
    }

    assert (
        _iteration_review_from_event(
            {
                "type": "tool_result",
                "data": {
                    "tool_name": "workspace_submit_iteration_review",
                    "result": {"iteration_review": payload},
                },
            }
        )
        == payload
    )


def test_verification_judgment_event_parser_accepts_observe_result_metadata() -> None:
    payload = {
        "verdict": "accepted",
        "rationale": "Evidence passes.",
        "confidence": 0.9,
    }

    assert (
        _verification_judgment_from_event(
            {
                "type": "observe",
                "data": {
                    "tool_name": "workspace_submit_verification_judgment",
                    "result": {"verification_judgment": payload},
                },
            }
        )
        == payload
    )


def test_worktree_preparation_event_parser_accepts_observe_result_metadata() -> None:
    payload = {
        "status": "prepared",
        "worktree_path": "/repo/.memstack/worktrees/attempt-1",
        "branch_name": "workspace/node-attempt-1",
        "base_ref": "HEAD",
    }

    assert (
        _worktree_preparation_from_event(
            {
                "type": "observe",
                "data": {
                    "tool_name": "workspace_submit_worktree_preparation",
                    "result": {"worktree_preparation": payload},
                },
            }
        )
        == payload
    )


def test_verification_judgment_event_parser_accepts_tool_result_metadata_json() -> None:
    payload = {
        "verdict": "accepted",
        "rationale": "Evidence passes.",
        "confidence": 0.9,
    }

    assert (
        _verification_judgment_from_event(
            {
                "type": "tool_result",
                "data": {
                    "tool_name": "workspace_submit_verification_judgment",
                    "metadata": {"verification_judgment": payload},
                },
            }
        )
        == payload
    )
    assert (
        _verification_judgment_from_event(
            {
                "type": "observe",
                "data": {
                    "tool_name": "workspace_submit_verification_judgment",
                    "observation": (
                        '{"verification_judgment":{"verdict":"accepted",'
                        '"rationale":"Evidence passes.","confidence":0.9}}'
                    ),
                },
            }
        )
        == payload
    )


def test_iteration_review_event_parser_accepts_json_observation() -> None:
    payload = {
        "verdict": "continue_next_iteration",
        "confidence": 0.82,
        "summary": "Need one proof sprint.",
    }

    assert (
        _iteration_review_from_event(
            {
                "type": "observe",
                "data": {
                    "tool_name": "workspace_submit_iteration_review",
                    "observation": '{"iteration_review":{"verdict":"continue_next_iteration",'
                    '"confidence":0.82,"summary":"Need one proof sprint."}}',
                },
            }
        )
        == payload
    )
