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


class TestWorkerConversationLinkage:
    def test_worker_conversation_kwargs_include_canonical_linkage(self) -> None:
        class _Workspace:
            project_id = "project-1"
            tenant_id = "tenant-1"

        task = _make_task(task_id="task-link-1", workspace_id="workspace-link-1")
        task.metadata["preferred_language"] = "zh-CN"

        kwargs = wl._worker_conversation_kwargs(
            conversation_id="conversation-link-1",
            workspace_id=task.workspace_id,
            workspace=_Workspace(),
            task=task,
            actor_user_id="user-1",
            worker_agent_id="agent-1",
            worker_binding_id="binding-1",
            root_goal_task_id="root-1",
            attempt_id="attempt-1",
            active_status="active",
        )

        assert kwargs["workspace_id"] == task.workspace_id
        assert kwargs["linked_workspace_task_id"] == task.id
        assert kwargs["metadata"]["workspace_id"] == task.workspace_id
        assert kwargs["metadata"]["workspace_task_id"] == task.id
        assert kwargs["metadata"]["preferred_language"] == "zh-CN"

    def test_worker_conversation_linkage_backfills_empty_existing_row(self) -> None:
        class _Conversation:
            def __init__(self) -> None:
                self.workspace_id = None
                self.linked_workspace_task_id = None
                self.metadata: dict = {}
                self.updated_at = None

        conversation = _Conversation()

        conflict = wl._worker_conversation_linkage_conflict(
            conversation,
            workspace_id="workspace-link-1",
            task_id="task-link-1",
        )
        changed = wl._patch_worker_conversation_linkage(
            conversation,
            workspace_id="workspace-link-1",
            task_id="task-link-1",
        )

        assert conflict is None
        assert changed is True
        assert conversation.workspace_id == "workspace-link-1"
        assert conversation.linked_workspace_task_id == "task-link-1"
        assert conversation.metadata["workspace_id"] == "workspace-link-1"
        assert conversation.metadata["workspace_task_id"] == "task-link-1"
        assert conversation.updated_at is not None

    def test_worker_conversation_linkage_reports_conflict_without_overwrite(self) -> None:
        class _Conversation:
            def __init__(self) -> None:
                self.workspace_id = "other-workspace"
                self.linked_workspace_task_id = "task-link-1"
                self.metadata: dict = {}
                self.updated_at = None

        conversation = _Conversation()

        conflict = wl._worker_conversation_linkage_conflict(
            conversation,
            workspace_id="workspace-link-1",
            task_id="task-link-1",
        )

        assert conflict == {
            "conversation_workspace_id": "other-workspace",
            "linked_workspace_task_id": "task-link-1",
            "expected_workspace_id": "workspace-link-1",
            "expected_workspace_task_id": "task-link-1",
        }
        assert conversation.workspace_id == "other-workspace"


class TestWorkerLaunchHeartbeat:
    @pytest.mark.asyncio
    async def test_publish_worker_launch_heartbeat_emits_wtp_liveness(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        publish = AsyncMock(return_value="1-0")
        redis = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.agent.workspace.workspace_supervisor.publish_envelope_default",
            publish,
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.state.agent_worker_state.get_redis_client",
            AsyncMock(return_value=redis),
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
        redis.expire.assert_awaited_once_with(
            "workspace:worker_launch:cooldown:conv-1",
            wl.WORKER_LAUNCH_COOLDOWN_SECONDS,
        )

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


class TestWorkerStreamOrphanDetection:
    def test_finished_marker_stops_matching_worker_stream(self) -> None:
        should_stop, reason = wl._should_stop_orphaned_worker_stream(
            finished_message_id="msg-1",
            stream_message_id="msg-1",
            running_exists=False,
            idle_seconds=1,
        )

        assert should_stop is True
        assert reason == "agent_finished_without_terminal_event"

    def test_finished_marker_for_other_message_does_not_stop_stream(self) -> None:
        should_stop, reason = wl._should_stop_orphaned_worker_stream(
            finished_message_id="old-msg",
            stream_message_id="msg-1",
            running_exists=False,
            idle_seconds=1,
        )

        assert should_stop is False
        assert reason is None

    def test_missing_running_state_stops_only_after_orphan_grace(self) -> None:
        assert wl._should_stop_orphaned_worker_stream(
            finished_message_id=None,
            stream_message_id="msg-1",
            running_exists=False,
            idle_seconds=899,
            orphan_grace_seconds=900,
        ) == (False, None)

        assert wl._should_stop_orphaned_worker_stream(
            finished_message_id=None,
            stream_message_id="msg-1",
            running_exists=False,
            idle_seconds=900,
            orphan_grace_seconds=900,
        ) == (True, "agent_not_running_stream_idle")


class TestPreStreamLaunchFailure:
    @pytest.mark.asyncio
    async def test_reports_blocked_and_patches_launch_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        apply_report = AsyncMock()
        patch_launch_state = AsyncMock()
        monkeypatch.setattr(wl, "_patch_task_launch_state", patch_launch_state)

        await wl._report_pre_stream_launch_failure(
            workspace_id="ws-1",
            root_goal_task_id="root-1",
            task_id="task-1",
            attempt_id="attempt-1",
            conversation_id=None,
            actor_user_id="user-1",
            worker_agent_id="worker-1",
            leader_agent_id="leader-1",
            launch_state="setup_failed",
            summary="worker_launch.setup_failed: boom",
            apply_fn=apply_report,
        )

        apply_report.assert_awaited_once()
        kwargs = apply_report.await_args.kwargs
        assert kwargs["attempt_id"] == "attempt-1"
        assert kwargs["report_type"] == "blocked"
        assert kwargs["summary"] == "worker_launch.setup_failed: boom"
        patch_launch_state.assert_awaited_once_with(
            workspace_id="ws-1",
            task_id="task-1",
            actor_user_id="user-1",
            leader_agent_id="leader-1",
            launch_state="setup_failed",
        )

    @pytest.mark.asyncio
    async def test_skips_without_attempt_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        apply_report = AsyncMock()
        patch_launch_state = AsyncMock()
        monkeypatch.setattr(wl, "_patch_task_launch_state", patch_launch_state)

        await wl._report_pre_stream_launch_failure(
            workspace_id="ws-1",
            root_goal_task_id="root-1",
            task_id="task-1",
            attempt_id=None,
            conversation_id=None,
            actor_user_id="user-1",
            worker_agent_id="worker-1",
            leader_agent_id="leader-1",
            launch_state="setup_failed",
            summary="boom",
            apply_fn=apply_report,
        )

        apply_report.assert_not_awaited()
        patch_launch_state.assert_not_awaited()


class TestStreamCompletionFallback:
    @pytest.mark.asyncio
    async def test_reports_completed_when_stream_finishes_without_terminal_report(
        self,
    ) -> None:
        apply_report = AsyncMock()

        reported = await wl._report_terminal(
            workspace_id="ws-1",
            root_goal_task_id="root-1",
            task_id="task-1",
            attempt_id="attempt-1",
            conversation_id="conv-1",
            actor_user_id="user-1",
            worker_agent_id="worker-1",
            leader_agent_id="leader-1",
            report_type="completed",
            summary=wl._stream_completion_summary("Finished the implementation.", ""),
            apply_fn=apply_report,
        )

        assert reported is True
        apply_report.assert_awaited_once()
        kwargs = apply_report.await_args.kwargs
        assert kwargs["attempt_id"] == "attempt-1"
        assert kwargs["conversation_id"] == "conv-1"
        assert kwargs["report_type"] == "completed"
        assert kwargs["summary"] == "Finished the implementation."

    def test_stream_completion_summary_is_bounded(self) -> None:
        summary = wl._stream_completion_summary("", "x" * 2500)

        assert len(summary) == 2000
        assert summary.endswith("...")

    def test_stream_completion_summary_has_default(self) -> None:
        assert (
            wl._stream_completion_summary("", "")
            == "Worker stream completed without an explicit workspace terminal report."
        )

    def test_terminal_report_tool_denial_disables_text_completion_fallback(self) -> None:
        event = {
            "type": "observe",
            "data": {
                "tool_name": "workspace_report_complete",
                "result": (
                    '{"error": "completion denied: protected test/review node includes '
                    'failed evidence"}'
                ),
                "error": None,
            },
        }

        assert wl._terminal_report_tool_observation_status(event) == "denied"
        assert (
            wl._should_synthesize_stream_completion_report(terminal_report_tool_observed=True)
            is False
        )

    def test_terminal_report_tool_apply_disables_text_completion_fallback(self) -> None:
        event = {
            "type": "observe",
            "data": {
                "tool_name": "workspace_report_blocked",
                "result": '{"applied_report": {"applied": true}}',
                "error": None,
            },
        }

        assert wl._terminal_report_tool_observation_status(event) == "applied"
        assert (
            wl._should_synthesize_stream_completion_report(terminal_report_tool_observed=True)
            is False
        )

    def test_text_completion_fallback_remains_available_without_terminal_tool(self) -> None:
        event = {
            "type": "observe",
            "data": {"tool_name": "bash", "result": "done", "error": None},
        }

        assert wl._terminal_report_tool_observation_status(event) is None
        assert (
            wl._should_synthesize_stream_completion_report(terminal_report_tool_observed=False)
            is True
        )


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
        assert "## Completion gate" in brief
        assert "## Shell execution discipline" in brief
        assert "nohup" in brief
        assert "Do not assume `ss` exists" in brief
        assert "preflight:read-progress" in brief
        assert "preflight:git-status" in brief
        assert "git status --short" in brief
        assert "stage intended untracked files" in brief

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
            preferred_language="en-US",
        )
        assert system_context["workspace_binding"]["attempt_id"] == "att-2"
        assert system_context["preferred_language"] == "en-US"
        assert system_context["additional_instructions"] == "Be brief."
        assert "workspace_root_override" not in system_context
        assert "native tool-call" in system_context["tool_protocol"]["instruction"]
        reporting = system_context["reporting"]
        assert reporting["completion_contract"]["required_verification_refs"] == [
            "preflight:read-progress",
            "preflight:git-status",
        ]
        assert "git_diff_summary" in reporting["completion_contract"]["required_change_evidence"]
        assert "workspace_report_complete" in reporting["completion_contract"]["example"]
        assert "preflight:read-progress" in " ".join(reporting["instructions"])
        assert "commit_ref" in " ".join(reporting["instructions"])
        assert "git status --short" in " ".join(reporting["instructions"])
        assert "untracked file" in " ".join(reporting["instructions"])
        quality_policy = system_context["code_quality_policy"]
        assert quality_policy["source"] == "workspace_generic_quality_gate"
        quality_instructions = " ".join(quality_policy["instructions"])
        assert "frontend/backend" in quality_instructions
        assert "hard acceptance criteria" in quality_instructions
        assert "hashes or prefixes" in quality_instructions
        assert "git diff" in quality_instructions
        assert "project_guidance:checked" in quality_instructions
        assert "preserve assertion strength" in quality_instructions
        assert "git add -A" in quality_instructions
        assert "unrelated changes" in quality_instructions
        assert (
            system_context["artifact_write_policy"]["max_single_write_chars"]
            == wl.WORKER_MAX_SINGLE_WRITE_CHARS
        )
        assert (
            system_context["artifact_write_policy"]["max_single_bash_command_chars"]
            == wl.WORKER_MAX_SINGLE_BASH_COMMAND_CHARS
        )
        assert "smaller chunks" in " ".join(system_context["artifact_write_policy"]["instructions"])
        assert "giant heredoc" in " ".join(system_context["artifact_write_policy"]["instructions"])
        shell_instructions = " ".join(system_context["shell_execution_policy"]["instructions"])
        assert "nohup" in shell_instructions
        assert "playwright install --with-deps" in shell_instructions
        assert "port is already in use" in shell_instructions
        assert "stop the stale PID" in shell_instructions
        assert "E2E_BASE_URL" in shell_instructions
        assert "empty string" in shell_instructions
        assert "ss" in shell_instructions

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

    def test_system_context_protects_verification_scripts_from_plan_node_phase(self) -> None:
        task = _make_task()

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={"iteration_phase": "test"},
        )

        policy = system_context["workspace_verification_integrity"]
        assert policy["source"] == "workspace_plan_node_metadata"
        assert policy["iteration_phase"] == "test"
        assert policy["protected_script_changes"] is True
        assert policy["allow_verification_script_changes"] is False
        assert "allow_verification_script_changes=true" in policy["rule"]

    def test_system_context_honors_explicit_verification_script_change_contract(self) -> None:
        task = _make_task()

        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={
                "iteration_phase": "review",
                "allow_verification_script_changes": True,
            },
        )

        policy = system_context["workspace_verification_integrity"]
        assert policy["iteration_phase"] == "review"
        assert policy["protected_script_changes"] is False
        assert policy["allow_verification_script_changes"] is True

    def test_brief_surfaces_protected_test_node_integrity_gate(self) -> None:
        task = _make_task()

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={"iteration_phase": "test"},
        )

        assert "## Test/review integrity gate" in brief
        assert "protected `test` workspace node" in brief
        assert "do not call workspace_report_complete" in brief
        assert "Do not edit, replace, regenerate, or loosen test" in brief
        assert "workspace_report_blocked" in brief
        assert "13/14 or 85/86 as complete" in brief

    def test_brief_marks_handoff_failed_tests_as_historical_for_protected_nodes(self) -> None:
        task = _make_task()

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            plan_node_metadata={"iteration_phase": "test"},
            extra_instructions=(
                "[feature-checkpoint]\n"
                "worktree_path=/workspace/.memstack/worktrees/att-2\n"
                "[/feature-checkpoint]\n\n"
                "[handoff-package]\n"
                "completed_step=last_report=completed\n"
                "test_command=13 passed 1 failed node test-data-persistence.js\n"
                "[/handoff-package]"
            ),
        )

        assert "## Handoff package interpretation" in brief
        assert "historical context from previous attempts" in brief
        assert "last_report=completed" in brief
        assert "fresh 0-failed evidence" in brief
        assert "workspace_report_blocked" in brief

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
        assert "## Code root discipline" in brief
        assert "mkdir -p /workspace/my-evo && cd /workspace/my-evo" in brief
        assert "Do not place `package.json`" in brief
        assert "Artifact write discipline" in brief
        assert "git_diff_summary" in brief
        assert "## Code quality gate" in brief
        assert "AGENTS.md/project guidance" in brief
        assert "Schema changes need reproducible migrations" in brief
        assert "Do not silently show mock" in brief
        assert "hard acceptance criteria" in brief
        assert "project_guidance:checked" in brief
        assert "never weaken or replace the verification script" in brief
        assert "git add -A" in brief
        assert "owned files only" in brief

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
        assert code_context_payload["required_tool_workdir"] == "/workspace/my-evo"
        assert code_context_payload["bootstrap_command"] == (
            "mkdir -p /workspace/my-evo && cd /workspace/my-evo"
        )
        assert code_context_payload["agents_files"][0]["content"] == "Always run npm test."
        assert "Before the first file operation" in code_context_payload["rule"]
        assert (
            "Bash commands must also start from the selected root" in code_context_payload["rule"]
        )
        assert (
            "Do not create project files directly under /workspace" in code_context_payload["rule"]
        )
        quality_policy = system_context["code_quality_policy"]
        assert quality_policy["source"] == "workspace_generic_quality_gate"
        quality_instructions = " ".join(quality_policy["instructions"])
        assert "AGENTS.md/project guidance" in quality_instructions
        assert "do not rely on local db push" in quality_instructions
        assert "matching lockfile" in quality_instructions
        assert "mock or fake data" in quality_instructions
        assert "project_guidance:checked" in quality_instructions
        assert "preserve assertion strength" in quality_instructions
        assert "explicit git add <path>" in quality_instructions

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

        assert "## Workspace checkpoint and worktree" in brief
        assert "worktree_path=/workspace/my-evo/../.memstack/worktrees/att-2" in brief
        assert "${sandbox_code_root}" not in brief
        assert "use that path as the task root" in brief
        assert "every absolute file_path must start with that worktree_path" in brief
        assert "bash commands must not create temp scripts" in brief
        assert "For bash, do not write temp scripts" in brief
        assert "Do not edit the main sandbox checkout" in brief
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
        assert (
            "worktree_path overrides code_context.sandbox_code_root"
            in (system_context["workspace_root_override"]["rule"])
        )
        assert "file_path arguments" in system_context["workspace_root_override"]["rule"]
        assert "bash writes" in system_context["workspace_root_override"]["rule"]
        assert "temp scripts" in system_context["workspace_root_override"]["rule"]
        assert (
            "check additional_instructions for a worktree_path"
            in (system_context["code_context"]["rule"])
        )

    def test_rewrites_checkpoint_commands_to_attempt_worktree_root(self) -> None:
        task = _make_task()
        code_context = WorkspaceCodeContext(sandbox_code_root="/workspace/my-evo")
        extra_instructions = (
            "[feature-checkpoint]\n"
            "worktree_path=${sandbox_code_root}/../.memstack/worktrees/att-2\n"
            "test_command=cd /workspace/my-evo && npm test\n"
            "[/feature-checkpoint]\n\n"
            "[preflight-checks]\n"
            "check_id=test-command-1 kind=test_command required=True "
            "command=cd /workspace/my-evo && npm test\n"
            "[/preflight-checks]"
        )

        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            extra_instructions=extra_instructions,
        )
        system_context = wl._build_worker_system_context(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            code_context=code_context,
            extra_instructions=extra_instructions,
        )

        worktree_command = "cd /workspace/.memstack/worktrees/att-2 && npm test"
        assert f"test_command={worktree_command}" in brief
        assert f"command={worktree_command}" in brief
        assert "test_command=cd /workspace/my-evo && npm test" not in brief
        assert "command=cd /workspace/my-evo && npm test" not in brief
        assert f"test_command={worktree_command}" in system_context["additional_instructions"]
        assert f"command={worktree_command}" in system_context["additional_instructions"]

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
