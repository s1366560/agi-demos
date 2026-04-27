"""Unit tests for src.infrastructure.agent.workspace.worker_launch (P3 M-bug)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskStatus,
)
from src.domain.model.workspace.wtp_envelope import WtpVerb
from src.infrastructure.agent.workspace import worker_launch as wl
from src.infrastructure.agent.workspace.code_context import (
    AgentsInstructionFile,
    WorkspaceCodeContext,
)


def _make_task(
    *,
    task_id: str = "task-1",
    workspace_id: str = "ws-1",
    title: str = "Build report",
    description: str | None = "Render quarterly stats",
    metadata: dict | None = None,
) -> WorkspaceTask:
    return WorkspaceTask(
        id=task_id,
        workspace_id=workspace_id,
        title=title,
        description=description,
        created_by="user-1",
        status=WorkspaceTaskStatus.TODO,
        metadata=metadata or {"task_role": "execution_task", "root_goal_task_id": "root-1"},
    )


class TestConversationScope:
    def test_without_attempt(self) -> None:
        assert wl._conversation_scope_for_task("t1") == "task:t1"

    def test_with_attempt(self) -> None:
        assert wl._conversation_scope_for_task("t1", "att-9") == "task:t1:attempt:att-9"


class TestConversationId:
    def test_deterministic_and_distinct_per_scope(self) -> None:
        a = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-X", task_id="t1"
        )
        b = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-X", task_id="t1"
        )
        c = wl._conversation_id_for_worker(
            workspace_id="w",
            worker_agent_id="agent-X",
            task_id="t1",
            attempt_id="att-9",
        )
        assert a == b
        assert a != c
        # UUIDv5 length
        assert len(a) == 36

    def test_distinct_per_agent(self) -> None:
        a = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-A", task_id="t1"
        )
        b = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-B", task_id="t1"
        )
        assert a != b


class TestWorkerLaunchHeartbeat:
    @pytest.mark.asyncio
    async def test_publish_worker_launch_heartbeat_emits_wtp_liveness(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        publish = AsyncMock(return_value="1-0")
        monkeypatch.setattr(
            "src.infrastructure.agent.workspace.workspace_supervisor.publish_envelope_default",
            publish,
        )

        await wl._publish_worker_launch_heartbeat(
            workspace_id="ws-1",
            task_id="task-1",
            attempt_id="attempt-1",
            root_goal_task_id="root-1",
            conversation_id="conv-1",
            actor_user_id="user-1",
            worker_agent_id="worker-1",
            leader_agent_id="leader-1",
        )

        publish.assert_awaited_once()
        envelope = publish.await_args.args[0]
        assert envelope.verb is WtpVerb.TASK_HEARTBEAT
        assert envelope.workspace_id == "ws-1"
        assert envelope.task_id == "task-1"
        assert envelope.attempt_id == "attempt-1"
        assert envelope.root_goal_task_id == "root-1"
        assert envelope.extra_metadata["worker_conversation_id"] == "conv-1"
        assert envelope.extra_metadata["worker_agent_id"] == "worker-1"
        assert envelope.extra_metadata["leader_agent_id"] == "leader-1"
        assert envelope.extra_metadata["actor_user_id"] == "user-1"
        assert envelope.extra_metadata["source"] == "workspace_worker_launch"

    @pytest.mark.asyncio
    async def test_publish_worker_launch_heartbeat_skips_without_attempt_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        publish = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.agent.workspace.workspace_supervisor.publish_envelope_default",
            publish,
        )

        await wl._publish_worker_launch_heartbeat(
            workspace_id="ws-1",
            task_id="task-1",
            attempt_id=None,
            root_goal_task_id="root-1",
            conversation_id="conv-1",
            actor_user_id="user-1",
            worker_agent_id="worker-1",
            leader_agent_id="leader-1",
        )

        publish.assert_not_awaited()


class TestBuildBrief:
    def test_includes_binding_block_and_title(self) -> None:
        task = _make_task(
            metadata={
                "task_role": "execution_task",
                "root_goal_task_id": "root-1",
                "workspace_agent_binding_id": "binding-1",
            }
        )
        brief = wl._build_worker_brief(
            workspace_id="ws-1",
            task=task,
            attempt_id=None,
            leader_agent_id="leader-1",
        )
        assert "[workspace-task-binding]" in brief
        assert "workspace_id=ws-1" in brief
        assert "workspace_task_id=task-1" in brief
        assert "workspace_agent_binding_id=binding-1" in brief
        assert "root_goal_task_id=root-1" in brief
        assert "leader_agent_id=leader-1" in brief
        assert "## Task title" in brief
        assert "Build report" in brief
        assert "Render quarterly stats" in brief

    def test_omits_attempt_when_none(self) -> None:
        task = _make_task()
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id=None,
            leader_agent_id=None,
        )
        assert "attempt_id=" not in brief

    def test_includes_attempt_and_extra(self) -> None:
        task = _make_task()
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            extra_instructions="Be brief.",
        )
        assert "attempt_id=att-2" in brief
        assert "Additional instructions" not in brief
        assert "Be brief." not in brief

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            extra_instructions="Be brief.",
        )
        assert system_context["workspace_binding"]["attempt_id"] == "att-2"
        assert system_context["additional_instructions"] == "Be brief."
        assert "native tool-call" in system_context["tool_protocol"]["instruction"]
        assert system_context["artifact_write_policy"]["max_single_write_chars"] == 12000
        assert "smaller chunks" in " ".join(
            system_context["artifact_write_policy"]["instructions"]
        )

    def test_system_context_includes_harness_preflight_contract(self) -> None:
        task = _make_task(
            metadata={
                "task_role": "execution_task",
                "root_goal_task_id": "root-1",
                "harness_feature_id": "feature-001",
                "preflight_checks": [
                    {
                        "check_id": "git-status",
                        "kind": "git_status",
                        "command": "git status --short",
                        "required": True,
                        "status": "pending",
                    },
                    {
                        "check_id": "test-command-1",
                        "kind": "test_command",
                        "command": "uv run pytest src/tests/unit/example.py -q",
                        "required": True,
                        "status": "pending",
                    },
                ],
            }
        )

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
        )

        harness = system_context["harness"]
        assert harness["feature_id"] == "feature-001"
        assert harness["required_evidence_prefix"] == "preflight:"
        assert harness["preflight_checks"][0]["command"] == "git status --short"
        assert harness["preflight_checks"][1]["check_id"] == "test-command-1"
        assert "preflight:<check_id>" in " ".join(harness["instructions"])

    def test_handles_missing_description(self) -> None:
        task = _make_task(description=None)
        brief = wl._build_worker_brief(
            workspace_id="w", task=task, attempt_id=None, leader_agent_id=None
        )
        assert "Task description" not in brief

    def test_includes_software_code_context_and_agents_instructions(self) -> None:
        task = _make_task()
        code_context = WorkspaceCodeContext(
            sandbox_code_root="/workspace/my-evo",
            agents_files=(
                AgentsInstructionFile(
                    sandbox_path="/workspace/my-evo/AGENTS.md",
                    content="Always run npm test.",
                ),
            ),
        )
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
        )

        assert "[workspace-code-context]" not in brief
        assert "Always run npm test." not in brief

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
        )
        code_context_payload = system_context["code_context"]
        assert code_context_payload["sandbox_code_root"] == "/workspace/my-evo"
        assert code_context_payload["loaded_agents_files"] == ["/workspace/my-evo/AGENTS.md"]
        assert code_context_payload["agents_files"][0]["content"] == "Always run npm test."
        assert "Perform repository inspection" in code_context_payload["rule"]

    def test_renders_code_root_placeholder_in_extra_instructions(self) -> None:
        task = _make_task()
        code_context = WorkspaceCodeContext(sandbox_code_root="/workspace/my-evo")
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            extra_instructions="worktree_path=${sandbox_code_root}/../.memstack/worktrees/att-2",
        )

        assert "worktree_path=" not in brief
        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            extra_instructions="worktree_path=${sandbox_code_root}/../.memstack/worktrees/att-2",
        )

        assert (
            system_context["additional_instructions"]
            == "worktree_path=/workspace/my-evo/../.memstack/worktrees/att-2"
        )

    def test_code_context_metadata_preserves_digest_and_agents_scope(self) -> None:
        code_context = WorkspaceCodeContext(
            sandbox_code_root="/workspace/my-evo",
            agents_files=(
                AgentsInstructionFile(
                    sandbox_path="/workspace/my-evo/AGENTS.md",
                    content="Always run npm test.",
                ),
            ),
        )

        metadata = wl._code_context_metadata(code_context)

        assert metadata["sandbox_code_root"] == "/workspace/my-evo"
        assert metadata["loaded_agents_files"] == ["/workspace/my-evo/AGENTS.md"]
        assert isinstance(metadata["agents_digest"], str)
        assert "Always run npm test." in str(metadata["agents_excerpt"])


class TestLaunchWorkerSession:
    @pytest.mark.asyncio
    async def test_missing_worker_agent_id(self) -> None:
        task = _make_task()
        out = await wl.launch_worker_session(
            workspace_id="w",
            task=task,
            worker_agent_id="",
            actor_user_id="u1",
        )
        assert out == {
            "launched": False,
            "conversation_id": None,
            "attempt_id": None,
            "reason": "worker_agent_id_missing",
        }

    @pytest.mark.asyncio
    async def test_workspace_not_found_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the workspace does not exist we must not attempt to stream."""
        task = _make_task()

        class _Repo:
            def __init__(self, db: object) -> None:
                pass

            async def find_by_id(self, _wid: str) -> None:
                return None

        class _Session:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *_: object) -> None:
                return None

        def _fake_session_factory() -> _Session:
            return _Session()

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence."
            "sql_workspace_repository.SqlWorkspaceRepository",
            _Repo,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            _fake_session_factory,
        )

        async def _fake_redis() -> None:
            return None

        monkeypatch.setattr(
            "src.infrastructure.agent.state.agent_worker_state.get_redis_client",
            _fake_redis,
        )
        out = await wl.launch_worker_session(
            workspace_id="w",
            task=task,
            worker_agent_id="agent-X",
            actor_user_id="u1",
        )
        assert out["launched"] is False
        assert out["reason"] == "workspace_not_found"
        assert out["conversation_id"] is None

    @pytest.mark.asyncio
    async def test_rejects_when_worker_equals_leader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Leader must never be dispatched as a worker for its own tasks.

        Regression: a workspace leader could self-assign a task (via
        ``todowrite``) or be picked up by the heal sweep, causing a
        "Workspace Worker - ..." conversation to be opened for the leader.
        ``worker_launch`` is the single enforcement point.
        """
        task = _make_task()

        class _Workspace:
            id = "w"
            project_id = "p"
            tenant_id = "t"

        class _WorkspaceRepo:
            def __init__(self, db: object) -> None:
                pass

            async def find_by_id(self, _wid: str) -> _Workspace:
                return _Workspace()

        class _Binding:
            is_active = True

        class _AgentRepo:
            def __init__(self, db: object) -> None:
                pass

            async def find_by_workspace_and_agent_id(
                self, *, workspace_id: str, agent_id: str
            ) -> _Binding:
                return _Binding()

        class _Session:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *_: object) -> None:
                return None

        def _fake_session_factory() -> _Session:
            return _Session()

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence."
            "sql_workspace_repository.SqlWorkspaceRepository",
            _WorkspaceRepo,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence."
            "sql_workspace_agent_repository.SqlWorkspaceAgentRepository",
            _AgentRepo,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            _fake_session_factory,
        )

        async def _fake_redis() -> None:
            return None

        monkeypatch.setattr(
            "src.infrastructure.agent.state.agent_worker_state.get_redis_client",
            _fake_redis,
        )

        # Sentinels: if the guard fails, these would be imported/invoked and
        # raise, making the test fail loudly instead of silently creating a
        # Conversation row.
        def _boom(*_a: object, **_kw: object) -> None:
            raise AssertionError("worker_is_leader guard failed: downstream code invoked")

        monkeypatch.setattr(
            "src.infrastructure.agent.workspace.workspace_goal_runtime._build_attempt_service",
            _boom,
        )

        leader_id = "builtin:sisyphus"
        out = await wl.launch_worker_session(
            workspace_id="w",
            task=task,
            worker_agent_id=leader_id,
            actor_user_id="u1",
            leader_agent_id=leader_id,
        )
        assert out["launched"] is False
        assert out["reason"] == "worker_is_leader"
        assert out["conversation_id"] is None


class TestScheduleWorkerSession:
    @pytest.mark.asyncio
    async def test_schedules_background_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: dict[str, object] = {}

        async def _fake_launch(**kwargs: object) -> dict[str, object]:
            called.update(kwargs)
            return {"launched": True, "conversation_id": "cid", "reason": "launched"}

        monkeypatch.setattr(wl, "launch_worker_session", _fake_launch)
        task = _make_task()
        wl.schedule_worker_session(
            workspace_id="w",
            task=task,
            worker_agent_id="agent-X",
            actor_user_id="u1",
            leader_agent_id="leader-1",
            attempt_id="att-1",
        )
        # let the scheduled task run
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert called["worker_agent_id"] == "agent-X"
        assert called["task"] is task
        assert called["leader_agent_id"] == "leader-1"
        assert called["attempt_id"] == "att-1"
