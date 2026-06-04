"""Unit tests for the skill evolution plugin."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.plugins.skill_evolution.aggregation import (
    SkillSessionAggregator,
    SkillSessionGroup,
)
from src.infrastructure.agent.plugins.skill_evolution.config import SkillEvolutionConfig


class TestSkillEvolutionConfig:
    def test_defaults(self) -> None:
        config = SkillEvolutionConfig()
        assert config.enabled is True
        assert config.min_sessions_per_skill == 5
        assert config.scoring_min_sessions_per_skill == 5
        assert config.min_avg_score == 0.6
        assert config.evolution_interval_minutes == 60

    def test_from_env_defaults(self) -> None:
        config = SkillEvolutionConfig.from_env()
        assert isinstance(config, SkillEvolutionConfig)

    @patch.dict(
        "os.environ",
        {
            "SKILL_EVOLUTION_ENABLED": "false",
            "SKILL_EVOLUTION_MIN_SESSIONS": "10",
            "SKILL_EVOLUTION_SCORING_MIN_SESSIONS": "7",
            "SKILL_EVOLUTION_MIN_AVG_SCORE": "0.8",
            "SKILL_EVOLUTION_INTERVAL_MINUTES": "120",
            "SKILL_EVOLUTION_PUBLISH_MODE": "direct",
            "SKILL_EVOLUTION_AUTO_APPLY": "true",
        },
    )
    def test_from_env_overrides(self) -> None:
        config = SkillEvolutionConfig.from_env()
        assert config.enabled is False
        assert config.min_sessions_per_skill == 10
        assert config.scoring_min_sessions_per_skill == 7
        assert config.min_avg_score == 0.8
        assert config.evolution_interval_minutes == 120
        assert config.publish_mode == "direct"
        assert config.auto_apply is True

    def test_with_overrides_clamps_persisted_strategy(self) -> None:
        config = SkillEvolutionConfig().with_overrides(
            {
                "enabled": False,
                "min_sessions_per_skill": 0,
                "scoring_min_sessions_per_skill": 4,
                "min_avg_score": 2,
                "max_sessions_per_batch": 0,
                "publish_mode": "direct",
                "auto_apply": True,
            }
        )

        assert config.enabled is False
        assert config.min_sessions_per_skill == 1
        assert config.scoring_min_sessions_per_skill == 4
        assert config.min_avg_score == 1.0
        assert config.max_sessions_per_batch == 1
        assert config.publish_mode == "direct"
        assert config.auto_apply is True


class TestSkillSessionGroup:
    def test_empty_group(self) -> None:
        group = SkillSessionGroup(skill_name="test-skill")
        assert group.skill_name == "test-skill"
        assert group.session_count == 0
        assert group.avg_score == 0.0
        assert group.success_rate == 0.0

    def test_add_session(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )

        group = SkillSessionGroup(skill_name="test-skill")
        session = SkillEvolutionSession(
            id="s1",
            skill_name="test-skill",
            tenant_id="t1",
            conversation_id="c1",
            user_query="query",
            success=True,
            overall_score=0.9,
        )
        group.add(session)
        assert group.session_count == 1
        assert group.avg_score == 0.9
        assert group.success_rate == 1.0

    def test_add_multiple_sessions(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )

        group = SkillSessionGroup(skill_name="test-skill")
        for i, (success, score) in enumerate([(True, 0.9), (False, 0.5), (True, 0.8)]):
            group.add(
                SkillEvolutionSession(
                    id=f"s{i}",
                    skill_name="test-skill",
                    tenant_id="t1",
                    conversation_id=f"c{i}",
                    user_query=f"query{i}",
                    success=success,
                    overall_score=score,
                )
            )
        assert group.session_count == 3
        assert group.avg_score == pytest.approx((0.9 + 0.5 + 0.8) / 3)
        assert group.success_rate == pytest.approx(2 / 3)


class TestSessionCollector:
    def test_build_session_with_skill(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.session_collector import (
            SessionCollector,
        )

        collector = SessionCollector(SkillEvolutionConfig())
        session = collector.build_session(
            tenant_id="t1",
            project_id="p1",
            conversation_id="c1",
            user_message="fix the bug",
            final_content="done",
            matched_skill_name="debug-systematically",
            conversation_context=[
                {"role": "user", "content": "fix the bug"},
                {"role": "assistant", "content": "Let me check..."},
                {"role": "tool", "content": "file contents", "name": "read_file"},
            ],
            success=True,
        )
        assert session is not None
        assert session.skill_name == "debug-systematically"
        assert session.tenant_id == "t1"
        assert session.project_id == "p1"
        assert session.success is True
        assert session.tool_call_count == 1
        assert session.trajectory is not None
        assert "steps" in session.trajectory

    def test_build_session_no_skill(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.session_collector import (
            SessionCollector,
        )

        collector = SessionCollector(SkillEvolutionConfig())
        session = collector.build_session(
            tenant_id="t1",
            project_id=None,
            conversation_id="c1",
            user_message="hello",
            final_content="hi",
            matched_skill_name=None,
            conversation_context=[],
            success=True,
        )
        assert session is not None
        assert session.skill_name == "__no_skill__"

    def test_trajectory_steps(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.session_collector import (
            _build_trajectory,
        )

        trajectory = _build_trajectory(
            conversation_context=[
                {"role": "assistant", "content": "Let me read the file"},
                {"role": "tool", "content": "hello world", "name": "read_file"},
                {"role": "assistant", "content": "The file says hello world"},
            ],
            user_message="read the file",
            final_content="The file says hello world",
            tool_events=[
                {
                    "tool_name": "write_file",
                    "success": True,
                    "result": "wrote file",
                    "metadata": {"path": "demo.txt"},
                }
            ],
        )
        assert len(trajectory["steps"]) == 4
        assert trajectory["steps"][-1]["type"] == "tool_execution"
        assert trajectory["steps"][-1]["name"] == "write_file"
        assert trajectory["tool_call_count"] == 2
        assert trajectory["user_query"] == "read the file"

    @pytest.mark.asyncio
    async def test_capture_from_hook_records_loaded_skill_names(self, monkeypatch) -> None:
        from src.infrastructure.agent.plugins.skill_evolution import (
            session_collector as collector_module,
        )
        from src.infrastructure.agent.plugins.skill_evolution.session_collector import (
            SessionCollector,
        )

        class FakeSessionContext:
            async def __aenter__(self) -> FakeSessionContext:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def commit(self) -> None:
                return None

        repo = MagicMock()
        repo.save_session = AsyncMock()
        monkeypatch.setattr(collector_module, "_get_repo", lambda _db: repo)

        await SessionCollector(SkillEvolutionConfig()).capture_from_hook(
            {
                "tenant_id": "t1",
                "project_id": "p1",
                "conversation_id": "c1",
                "user_message": "use loaded skills",
                "final_content": "done",
                "loaded_skill_names": ["dynamic-a", "dynamic-b", "dynamic-a"],
                "tool_events": [
                    {
                        "tool_name": "skill_loader",
                        "success": True,
                        "result": "loaded dynamic-a",
                    }
                ],
                "conversation_context": [{"role": "assistant", "content": "done"}],
                "success": True,
            },
            session_factory=lambda: FakeSessionContext(),
        )

        saved_sessions = [call.args[0] for call in repo.save_session.await_args_list]
        assert [session.skill_name for session in saved_sessions] == [
            "dynamic-a",
            "dynamic-b",
        ]
        assert saved_sessions[0].trajectory["tool_call_count"] == 1

    @pytest.mark.asyncio
    async def test_matched_skill_takes_precedence_over_loaded_skill_names(
        self, monkeypatch
    ) -> None:
        from src.infrastructure.agent.plugins.skill_evolution import (
            session_collector as collector_module,
        )
        from src.infrastructure.agent.plugins.skill_evolution.session_collector import (
            SessionCollector,
        )

        class FakeSessionContext:
            async def __aenter__(self) -> FakeSessionContext:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def commit(self) -> None:
                return None

        repo = MagicMock()
        repo.save_session = AsyncMock()
        monkeypatch.setattr(collector_module, "_get_repo", lambda _db: repo)

        await SessionCollector(SkillEvolutionConfig()).capture_from_hook(
            {
                "tenant_id": "t1",
                "conversation_id": "c1",
                "user_message": "forced skill",
                "final_content": "done",
                "matched_skill_name": "forced-skill",
                "loaded_skill_names": ["dynamic-skill"],
                "conversation_context": [],
                "success": True,
            },
            session_factory=lambda: FakeSessionContext(),
        )

        saved_sessions = [call.args[0] for call in repo.save_session.await_args_list]
        assert [session.skill_name for session in saved_sessions] == ["forced-skill"]


class TestSessionSummarizer:
    @pytest.mark.asyncio
    async def test_summarize_wraps_llm_trajectory_list_as_steps(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.summarizer import (
            SessionSummarizer,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "trajectory": [
                                        {
                                            "step": 1,
                                            "action": "Checked output",
                                            "tool": None,
                                            "outcome": "partial",
                                        }
                                    ],
                                    "summary": "The skill needs clearer verification guidance.",
                                }
                            )
                        }
                    }
                ]
            }
        )
        session = SkillEvolutionSession(
            id="s1",
            skill_name="test-skill",
            tenant_id="t1",
            conversation_id="c1",
            user_query="query",
            trajectory={"steps": []},
            success=True,
        )

        trajectory, summary = await SessionSummarizer(SkillEvolutionConfig())._summarize_one(
            session, llm_client
        )

        assert trajectory == {
            "steps": [
                {
                    "step": 1,
                    "action": "Checked output",
                    "tool": None,
                    "outcome": "partial",
                }
            ]
        }
        assert summary == "The skill needs clearer verification guidance."

    @pytest.mark.asyncio
    async def test_summarize_falls_back_when_llm_returns_non_json(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.summarizer import (
            SessionSummarizer,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value={"content": "not json"})
        session = SkillEvolutionSession(
            id="s-fallback",
            skill_name="test-skill",
            tenant_id="t1",
            conversation_id="c1",
            user_query="query",
            trajectory={"steps": [], "final_response": "done"},
            success=True,
        )

        trajectory, summary = await SessionSummarizer(SkillEvolutionConfig())._summarize_one(
            session, llm_client
        )

        assert trajectory == {"steps": [], "final_response": "done"}
        assert "Automatic fallback summary" in summary
        assert "not json" in summary

    @pytest.mark.asyncio
    async def test_summarize_parses_fenced_json(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.summarizer import (
            SessionSummarizer,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(
            return_value={
                "content": (
                    "```json\n"
                    '{"trajectory":[{"step":1,"action":"Loaded skill","tool":"skill_loader",'
                    '"outcome":"success"}],"summary":"The run completed."}\n'
                    "```"
                )
            }
        )
        session = SkillEvolutionSession(
            id="s-fenced",
            skill_name="test-skill",
            tenant_id="t1",
            conversation_id="c1",
            user_query="query",
            trajectory={"steps": []},
            success=True,
        )

        trajectory, summary = await SessionSummarizer(SkillEvolutionConfig())._summarize_one(
            session, llm_client
        )

        assert trajectory["steps"][0]["tool"] == "skill_loader"
        assert summary == "The run completed."

    @pytest.mark.asyncio
    async def test_summarize_preserves_final_response_from_raw_trajectory(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.summarizer import (
            SessionSummarizer,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(
            return_value={
                "content": json.dumps(
                    {
                        "trajectory": [
                            {
                                "step": 1,
                                "action": "Completed the requested work",
                                "tool": None,
                                "outcome": "success",
                            }
                        ],
                        "summary": "The run completed.",
                    }
                )
            }
        )
        session = SkillEvolutionSession(
            id="s-final",
            skill_name="test-skill",
            tenant_id="t1",
            conversation_id="c1",
            user_query="query",
            trajectory={"steps": [], "final_response": "This is the final answer."},
            success=True,
        )

        trajectory, summary = await SessionSummarizer(SkillEvolutionConfig())._summarize_one(
            session, llm_client
        )

        assert trajectory["final_response"] == "This is the final answer."
        assert summary == "The run completed."

    @pytest.mark.asyncio
    async def test_summarize_enriches_sparse_trajectory_from_execution_events(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.summarizer import (
            SessionSummarizer,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "trajectory": [
                                        {
                                            "step": 1,
                                            "action": "Used todowrite after loading the skill",
                                            "tool": "todowrite",
                                            "outcome": "success",
                                        }
                                    ],
                                    "summary": "The event stream showed real tool usage.",
                                }
                            )
                        }
                    }
                ]
            }
        )
        repo = MagicMock()
        repo.get_conversation_trace_events = AsyncMock(
            return_value=[
                {
                    "event_type": "assistant_message",
                    "event_data": {"content": "I will create tasks."},
                },
                {
                    "event_type": "act",
                    "event_data": {
                        "tool_name": "todowrite",
                        "tool_input": {"action": "replace"},
                        "status": "running",
                    },
                },
                {
                    "event_type": "observe",
                    "event_data": {
                        "tool_name": "todowrite",
                        "result": '{"success": true}',
                        "status": "completed",
                    },
                },
                {
                    "event_type": "complete",
                    "event_data": {"content": "Tasks were created."},
                },
            ]
        )
        repo.update_summary = AsyncMock()
        session = SkillEvolutionSession(
            id="s-sparse",
            skill_name="research",
            tenant_id="t1",
            conversation_id="c1",
            user_query="decompose and execute",
            trajectory={
                "steps": [
                    {
                        "step": 1,
                        "tool": "skill_loader",
                        "action": "Loaded research",
                        "outcome": "success",
                    }
                ]
            },
            success=True,
            tool_call_count=1,
        )

        count = await SessionSummarizer(SkillEvolutionConfig()).summarize_batch(
            [session], llm_client, repo
        )

        assert count == 1
        prompt = llm_client.generate.await_args.kwargs["messages"][1].content
        assert "todowrite" in prompt
        assert "Tasks were created." in prompt
        persisted_trajectory = repo.update_summary.await_args.kwargs["trajectory"]
        assert persisted_trajectory["final_response"] == "Tasks were created."
        assert session.trajectory["trajectory_source"] == "agent_execution_events"

    @pytest.mark.asyncio
    async def test_summarize_enriches_missing_final_response_from_execution_events(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.summarizer import (
            SessionSummarizer,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(
            return_value={
                "content": json.dumps(
                    {
                        "trajectory": [
                            {
                                "step": 1,
                                "action": "Summarized existing non-sparse steps",
                                "tool": "read_file",
                                "outcome": "success",
                            }
                        ],
                        "summary": "The event stream supplied the missing final answer.",
                    }
                )
            }
        )
        repo = MagicMock()
        repo.get_conversation_trace_events = AsyncMock(
            return_value=[
                {
                    "event_type": "complete",
                    "event_data": {"content": "A complete answer was delivered."},
                },
            ]
        )
        repo.update_summary = AsyncMock()
        session = SkillEvolutionSession(
            id="s-missing-final",
            skill_name="research",
            tenant_id="t1",
            conversation_id="c1",
            user_query="research this",
            trajectory={
                "steps": [
                    {
                        "step": 1,
                        "tool": "read_file",
                        "action": "Read context",
                        "outcome": "success",
                    },
                    {
                        "step": 2,
                        "tool": "web_search",
                        "action": "Searched references",
                        "outcome": "success",
                    },
                ]
            },
            success=True,
            tool_call_count=2,
        )

        count = await SessionSummarizer(SkillEvolutionConfig()).summarize_batch(
            [session], llm_client, repo
        )

        assert count == 1
        prompt = llm_client.generate.await_args.kwargs["messages"][1].content
        assert "A complete answer was delivered." in prompt
        persisted_trajectory = repo.update_summary.await_args.kwargs["trajectory"]
        assert persisted_trajectory["final_response"] == "A complete answer was delivered."


class TestSessionJudge:
    @pytest.mark.asyncio
    async def test_judge_falls_back_when_llm_returns_non_json(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.session_judge import (
            SessionJudge,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value={"content": "plain text"})
        session = SkillEvolutionSession(
            id="j-fallback",
            skill_name="test-skill",
            tenant_id="t1",
            conversation_id="c1",
            user_query="query",
            summary="summary",
            trajectory={"steps": []},
            success=True,
            tool_call_count=1,
        )

        scores, overall = await SessionJudge(SkillEvolutionConfig())._judge_one(session, llm_client)

        assert scores["task_completion"] == 0.65
        assert scores["tool_usage"] == 0.55
        assert "Automatic fallback score" in str(scores["rationale"])
        assert 0.0 < overall < 1.0

    @pytest.mark.asyncio
    async def test_judge_parses_fenced_json(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.session_judge import (
            SessionJudge,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(
            return_value={
                "content": (
                    "```json\n"
                    '{"task_completion":0.9,"response_quality":0.8,"efficiency":0.7,'
                    '"tool_usage":0.6,"rationale":"Good run"}\n'
                    "```"
                )
            }
        )
        session = SkillEvolutionSession(
            id="j-fenced",
            skill_name="test-skill",
            tenant_id="t1",
            conversation_id="c1",
            user_query="query",
            summary="summary",
            trajectory={"steps": []},
            success=True,
        )

        scores, overall = await SessionJudge(SkillEvolutionConfig())._judge_one(
            session,
            llm_client,
        )

        assert scores["task_completion"] == 0.9
        assert scores["rationale"] == "Good run"
        assert overall == pytest.approx(0.83)

    @pytest.mark.asyncio
    async def test_judge_prompt_includes_final_response(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.session_judge import (
            SessionJudge,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock(
            return_value={
                "content": json.dumps(
                    {
                        "task_completion": 0.8,
                        "response_quality": 0.7,
                        "efficiency": 0.9,
                        "tool_usage": 0.6,
                        "rationale": "final response was useful",
                    }
                )
            }
        )
        session = SkillEvolutionSession(
            id="j-final",
            skill_name="test-skill",
            tenant_id="t1",
            conversation_id="c1",
            user_query="query",
            summary="summary",
            trajectory={"steps": [], "final_response": "This is the actual answer."},
            success=True,
            tool_call_count=1,
        )

        await SessionJudge(SkillEvolutionConfig())._judge_one(session, llm_client)

        prompt = llm_client.generate.await_args.kwargs["messages"][1].content
        assert "Final response:" in prompt
        assert "This is the actual answer." in prompt


class TestSkillMerger:
    @pytest.mark.asyncio
    async def test_apply_skip_action(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionJob,
        )
        from src.infrastructure.agent.plugins.skill_evolution.skill_merger import (
            SkillMerger,
        )

        job = SkillEvolutionJob(
            id="j1",
            skill_name="test-skill",
            tenant_id="t1",
            action="skip",
        )
        skill_service = MagicMock()
        merger = SkillMerger(skill_service)
        result = await merger.apply_evolution(job, tenant_id="t1")
        assert result is None
        skill_service.get_skill_by_name.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_improve_skill_not_found(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionJob,
        )
        from src.infrastructure.agent.plugins.skill_evolution.skill_merger import (
            SkillMerger,
        )

        skill_service = MagicMock()
        skill_service.get_skill_by_name = AsyncMock(return_value=None)
        merger = SkillMerger(skill_service)

        job = SkillEvolutionJob(
            id="j2",
            skill_name="missing-skill",
            tenant_id="t1",
            action="improve_skill",
            candidate_content="# Improved Skill",
            rationale="Better triggers",
        )
        result = await merger.apply_evolution(job, tenant_id="t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_apply_improve_skill(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionJob,
        )
        from src.infrastructure.agent.plugins.skill_evolution.skill_merger import (
            SkillMerger,
        )

        skill = MagicMock()
        skill.id = "sk1"
        skill.name = "test-skill"
        skill.current_version = 2
        skill.full_content = "# Old SKILL.md"

        skill_service = MagicMock()
        skill_service.get_skill_by_name = AsyncMock(return_value=skill)
        skill_service.update_skill_content = AsyncMock()
        merger = SkillMerger(skill_service)

        job = SkillEvolutionJob(
            id="j3",
            skill_name="test-skill",
            tenant_id="t1",
            action="improve_skill",
            candidate_content="# Improved SKILL.md",
            rationale="Added better examples",
        )
        result = await merger.apply_evolution(job, tenant_id="t1")
        assert result is None
        skill_service.update_skill_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_apply_improve_skill_creates_version_when_repositories_provided(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionJob,
        )
        from src.infrastructure.agent.plugins.skill_evolution.skill_merger import (
            SkillMerger,
        )

        skill = MagicMock()
        skill.id = "sk1"
        skill.name = "test-skill"
        skill.current_version = 2
        skill.version_label = "2"
        skill.full_content = "# Old SKILL.md"

        skill_service = MagicMock()
        skill_repository = MagicMock()
        skill_repository.get_by_name = AsyncMock(return_value=skill)
        skill_repository.update = AsyncMock(return_value=skill)
        version_repository = MagicMock()
        version_repository.get_max_version_number = AsyncMock(return_value=2)
        version_repository.create = AsyncMock()
        merger = SkillMerger(skill_service)

        job = SkillEvolutionJob(
            id="j4",
            skill_name="test-skill",
            tenant_id="t1",
            action="improve_skill",
            candidate_content="# Improved SKILL.md",
            rationale="Added better examples",
        )
        result = await merger.apply_evolution(
            job,
            tenant_id="t1",
            skill_repository=skill_repository,
            skill_version_repository=version_repository,
        )

        assert result is not None
        version_repository.create.assert_awaited_once()
        created_version = version_repository.create.await_args.args[0]
        assert created_version.version_number == 3
        assert created_version.skill_md_content == "# Improved SKILL.md"
        assert created_version.created_by == "evolution"
        assert skill.current_version == 3
        assert skill.full_content == "# Improved SKILL.md"
        skill_repository.update.assert_awaited_once_with(skill)

    @pytest.mark.asyncio
    async def test_apply_filesystem_skill_imports_database_copy_before_version(self) -> None:
        from src.domain.model.agent.skill import Skill, SkillScope
        from src.domain.model.agent.skill_source import SkillSource
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionJob,
        )
        from src.infrastructure.agent.plugins.skill_evolution.skill_merger import (
            SkillMerger,
        )

        filesystem_skill = Skill(
            id="fs-skill-1",
            tenant_id="t1",
            name="research",
            description="Research with structured reports.",
            tools=["web_search"],
            source=SkillSource.FILESYSTEM,
            file_path="/repo/.memstack/skills/research/SKILL.md",
            full_content="# Current filesystem skill",
            scope=SkillScope.TENANT,
        )
        skill_service = MagicMock()
        skill_service.get_skill_by_name = AsyncMock(return_value=filesystem_skill)
        skill_repository = MagicMock()
        skill_repository.get_by_name = AsyncMock(return_value=None)
        skill_repository.create = AsyncMock()
        skill_repository.update = AsyncMock()
        version_repository = MagicMock()
        version_repository.get_max_version_number = AsyncMock(return_value=0)
        version_repository.create = AsyncMock()
        merger = SkillMerger(skill_service)

        job = SkillEvolutionJob(
            id="j-fs",
            skill_name="research",
            tenant_id="t1",
            action="improve_skill",
            candidate_content="# Improved DB skill",
            rationale="Persist filesystem evolution to DB.",
        )

        version_id = await merger.apply_evolution(
            job,
            tenant_id="t1",
            skill_repository=skill_repository,
            skill_version_repository=version_repository,
        )

        assert version_id is not None
        skill_repository.create.assert_awaited_once()
        imported_skill = skill_repository.create.await_args.args[0]
        assert imported_skill.name == "research"
        assert imported_skill.scope == SkillScope.TENANT
        assert imported_skill.is_system_skill is False
        assert imported_skill.metadata["evolution_imported_from"] == "filesystem"
        assert imported_skill.metadata["source_file_path"].endswith("research/SKILL.md")
        version_repository.create.assert_awaited_once()
        created_version = version_repository.create.await_args.args[0]
        assert created_version.skill_id == imported_skill.id
        assert created_version.skill_md_content == "# Improved DB skill"
        assert imported_skill.full_content == "# Improved DB skill"
        skill_repository.update.assert_awaited_once_with(imported_skill)

    @pytest.mark.asyncio
    async def test_optimize_description_keeps_skill_body(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionJob,
        )
        from src.infrastructure.agent.plugins.skill_evolution.skill_merger import (
            SkillMerger,
        )

        skill = MagicMock()
        skill.id = "sk1"
        skill.name = "test-skill"
        skill.current_version = 1
        skill.full_content = "---\nname: test-skill\ndescription: Old\n---\n\n# Body"

        skill_repository = MagicMock()
        skill_repository.get_by_name = AsyncMock(return_value=skill)
        skill_repository.update = AsyncMock(return_value=skill)
        version_repository = MagicMock()
        version_repository.get_max_version_number = AsyncMock(return_value=1)
        version_repository.create = AsyncMock()
        merger = SkillMerger(MagicMock())

        job = SkillEvolutionJob(
            id="j5",
            skill_name="test-skill",
            tenant_id="t1",
            action="optimize_description",
            candidate_content="New description",
            rationale="Usage data showed clearer trigger language is needed",
        )

        await merger.apply_evolution(
            job,
            tenant_id="t1",
            skill_repository=skill_repository,
            skill_version_repository=version_repository,
        )

        assert "description: New description" in skill.full_content
        assert "# Body" in skill.full_content


class TestHookRegistration:
    """Verify the hook is registered in the global plugin registry."""

    def test_hook_registered_in_registry(self) -> None:
        from src.infrastructure.agent.plugins.registry import (
            AgentPluginRegistry,
        )
        from src.infrastructure.agent.plugins.skill_evolution.plugin import (
            register_builtin_skill_evolution_plugin,
        )

        registry = AgentPluginRegistry()
        plugin = register_builtin_skill_evolution_plugin(
            registry,
            config=SkillEvolutionConfig(enabled=True),
            skill_service=MagicMock(),
            llm_provider_manager=MagicMock(),
            session_factory=None,
        )
        assert plugin is not None
        assert plugin.config.enabled is True

    def test_plugin_disabled_when_config_disabled(self) -> None:
        from src.infrastructure.agent.plugins.registry import (
            AgentPluginRegistry,
        )
        from src.infrastructure.agent.plugins.skill_evolution.plugin import (
            register_builtin_skill_evolution_plugin,
        )

        registry = AgentPluginRegistry()
        plugin = register_builtin_skill_evolution_plugin(
            registry,
            config=SkillEvolutionConfig(enabled=False),
            skill_service=MagicMock(),
            llm_provider_manager=MagicMock(),
            session_factory=None,
        )
        assert plugin.config.enabled is False

    @pytest.mark.asyncio
    async def test_skill_loader_hook_attributes_next_turn_capture(self) -> None:
        from src.infrastructure.agent.plugins.registry import AgentPluginRegistry
        from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi
        from src.infrastructure.agent.plugins.skill_evolution import plugin as plugin_module
        from src.infrastructure.agent.plugins.skill_evolution.plugin import (
            _after_tool_execution,
            _after_turn_complete,
        )

        collector = MagicMock()
        collector.capture_from_hook = AsyncMock()
        previous_collector = plugin_module._collector
        previous_session_factory = plugin_module._session_factory
        plugin_module._collector = collector
        plugin_module._session_factory = object()
        plugin_module._loaded_skill_names_by_turn.clear()
        plugin_module._tool_events_by_turn.clear()

        registry = AgentPluginRegistry()
        api = PluginRuntimeApi("skill-evolution", registry=registry)
        api.register_hook("after_tool_execution", _after_tool_execution)
        api.register_hook("after_turn_complete", _after_turn_complete)

        try:
            await registry.apply_hook(
                "after_tool_execution",
                payload={
                    "tool_name": "skill_loader",
                    "conversation_id": "conv-1",
                    "result_metadata": {"name": "dynamic-skill"},
                    "result": "Loaded skill: dynamic-skill",
                },
            )
            await registry.apply_hook(
                "after_turn_complete",
                payload={
                    "tenant_id": "t1",
                    "conversation_id": "conv-1",
                    "user_message": "use the dynamic skill",
                    "final_content": "done",
                    "conversation_context": [],
                    "success": True,
                },
            )
        finally:
            plugin_module._collector = previous_collector
            plugin_module._session_factory = previous_session_factory
            plugin_module._loaded_skill_names_by_turn.clear()
            plugin_module._tool_events_by_turn.clear()

        captured_payload = collector.capture_from_hook.await_args.args[0]
        assert captured_payload["loaded_skill_names"] == ["dynamic-skill"]
        assert captured_payload["tool_events"][0]["tool_name"] == "skill_loader"

    @pytest.mark.asyncio
    async def test_after_turn_capture_schedules_autonomous_evolution(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution import plugin as plugin_module
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.plugin import (
            _after_turn_complete,
        )

        collector = MagicMock()
        collector.capture_from_hook = AsyncMock(
            return_value=[
                SkillEvolutionSession(
                    id="evs-1",
                    skill_name="dynamic-skill",
                    tenant_id="tenant-1",
                    project_id="project-1",
                    conversation_id="conv-1",
                    user_query="use skill",
                ),
                SkillEvolutionSession(
                    id="evs-2",
                    skill_name="__no_skill__",
                    tenant_id="tenant-1",
                    conversation_id="conv-2",
                    user_query="plain chat",
                ),
            ]
        )
        scheduler = MagicMock()
        previous_collector = plugin_module._collector
        previous_session_factory = plugin_module._session_factory
        previous_scheduler = plugin_module._scheduler
        plugin_module._collector = collector
        plugin_module._session_factory = object()
        plugin_module._scheduler = scheduler

        try:
            await _after_turn_complete(
                {
                    "tenant_id": "tenant-1",
                    "conversation_id": "conv-1",
                    "user_message": "use skill",
                    "final_content": "done",
                    "conversation_context": [],
                    "success": True,
                }
            )
        finally:
            plugin_module._collector = previous_collector
            plugin_module._session_factory = previous_session_factory
            plugin_module._scheduler = previous_scheduler

        scheduler.schedule_run.assert_called_once_with(
            tenant_id="tenant-1",
            project_id="project-1",
            skill_name="dynamic-skill",
            reason="capture",
        )


class TestEvolutionScheduler:
    def _make_scheduler(self, session_factory=None):
        from src.infrastructure.agent.plugins.skill_evolution.scheduler import (
            EvolutionScheduler,
        )

        return EvolutionScheduler(
            config=SkillEvolutionConfig(enabled=True, evolution_interval_minutes=60),
            summarizer=MagicMock(),
            judge=MagicMock(),
            aggregator=MagicMock(),
            engine=MagicMock(),
            llm_provider_manager=MagicMock(),
            session_factory=session_factory or MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_capture_requests_are_coalesced_per_tenant_project_skill(self) -> None:
        scheduler = self._make_scheduler()
        scheduler._running = True
        scheduler._execute_cycle = AsyncMock(return_value={"jobs": 1})

        first = scheduler.schedule_run(
            tenant_id="tenant-1",
            project_id="project-1",
            skill_name="skill-a",
            delay_seconds=0,
        )
        second = scheduler.schedule_run(
            tenant_id="tenant-1",
            project_id="project-1",
            skill_name="skill-a",
            delay_seconds=0,
        )

        assert first is True
        assert second is False
        await asyncio.gather(*list(scheduler._pending_tasks.values()))
        scheduler._execute_cycle.assert_awaited_once_with(
            tenant_id="tenant-1",
            project_id="project-1",
            skill_name="skill-a",
        )

    @pytest.mark.asyncio
    async def test_manual_run_can_queue_when_scheduler_not_running(self) -> None:
        scheduler = self._make_scheduler()
        scheduler._running = False
        scheduler._delayed_execute_request = AsyncMock()

        scheduled = scheduler.schedule_run(
            tenant_id="tenant-1",
            reason="manual",
            delay_seconds=0,
            allow_when_stopped=True,
        )

        assert scheduled is True
        await asyncio.gather(*list(scheduler._pending_tasks.values()))
        scheduler._delayed_execute_request.assert_awaited_once()
        assert scheduler._delayed_execute_request.await_args.kwargs["require_running"] is False

    @pytest.mark.asyncio
    async def test_start_schedules_startup_sweep_without_waiting_for_interval(self) -> None:
        scheduler = self._make_scheduler()
        scheduler._execute_all_tenants = AsyncMock()

        await scheduler.start()
        await asyncio.sleep(0.2)
        await scheduler.stop()

        scheduler._execute_all_tenants.assert_awaited_once_with(reason="startup")

    @pytest.mark.asyncio
    async def test_saturated_batch_schedules_backlog_continuation(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.scheduler import (
            _EvolutionRunRequest,
        )

        scheduler = self._make_scheduler()
        scheduler._running = True
        scheduler._delayed_execute_request = AsyncMock()

        scheduler._schedule_backlog_continuation(
            _EvolutionRunRequest("tenant-1"),
            {"summarized": scheduler._config.max_sessions_per_batch, "judged": 0},
        )

        assert len(scheduler._pending_tasks) == 1
        await asyncio.gather(*list(scheduler._pending_tasks.values()))
        scheduler._delayed_execute_request.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_discover_tenants_orders_by_captured_session_volume(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )

        with tempfile.TemporaryDirectory(prefix="skill-evolution-tenants-") as tmp:
            engine = create_async_engine(f"sqlite+aiosqlite:///{Path(tmp) / 'tenants.db'}")
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with engine.begin() as conn:
                await conn.run_sync(
                    lambda sync_conn: SkillEvolutionSession.__table__.create(
                        sync_conn,
                        checkfirst=True,
                    )
                )

            async with session_factory() as db:
                db.add_all(
                    [
                        SkillEvolutionSession(
                            id=f"large-{i}",
                            skill_name="skill-a",
                            tenant_id="tenant-large",
                            conversation_id=f"conv-large-{i}",
                            user_query="q",
                        )
                        for i in range(3)
                    ]
                    + [
                        SkillEvolutionSession(
                            id="small-1",
                            skill_name="skill-b",
                            tenant_id="tenant-small",
                            conversation_id="conv-small-1",
                            user_query="q",
                        )
                    ]
                )
                await db.commit()

            scheduler = self._make_scheduler(session_factory=session_factory)
            tenants = await scheduler._discover_tenants()
            await engine.dispose()

        assert tenants[:2] == ["tenant-large", "tenant-small"]


class TestSkillEvolutionEndToEnd:
    @pytest.mark.asyncio
    async def test_trigger_evolution_applies_job_and_links_version(self) -> None:  # noqa: PLR0915
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from src.domain.model.agent.skill import Skill, SkillScope
        from src.infrastructure.adapters.secondary.persistence import models as db_models
        from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
            SqlSkillRepository,
        )
        from src.infrastructure.agent.plugins.registry import AgentPluginRegistry
        from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi
        from src.infrastructure.agent.plugins.skill_evolution import plugin as plugin_module
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionJob,
            SkillEvolutionSession,
        )
        from src.infrastructure.agent.plugins.skill_evolution.plugin import (
            SkillEvolutionPlugin,
        )

        tenant_id = "tenant-evolution-smoke"
        project_id = "project-evolution-smoke"
        skill_name = "evolution-smoke-skill"
        evolved_content = (
            "---\n"
            "name: evolution-smoke-skill\n"
            "description: Evolved smoke skill.\n"
            "---\n\n"
            "# Evolution Smoke Skill\n\n"
            "Include explicit verification evidence.\n"
        )

        class FakeLLMClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def generate(self, messages, max_tokens=None):
                system = str(messages[0].content)
                self.calls.append(system)
                if "session analyst" in system:
                    content = json.dumps(
                        {
                            "trajectory": [
                                {
                                    "step": 1,
                                    "action": "Observed weak final response",
                                    "tool": None,
                                    "outcome": "partial",
                                }
                            ],
                            "summary": "The skill should require verification evidence.",
                        }
                    )
                elif "session quality judge" in system:
                    content = json.dumps(
                        {
                            "task_completion": 0.9,
                            "response_quality": 0.82,
                            "efficiency": 0.95,
                            "tool_usage": 0.8,
                            "rationale": "The skill needs clearer verification instructions.",
                        }
                    )
                elif "skill evolution specialist" in system:
                    content = json.dumps(
                        {
                            "action": "improve_skill",
                            "rationale": "Missing verification evidence guidance.",
                            "skill_content": evolved_content,
                        }
                    )
                else:  # pragma: no cover - defensive guard for prompt drift
                    raise AssertionError(f"Unexpected prompt: {system[:120]}")
                return {"choices": [{"message": {"content": content}}]}

        class FakeLLMProviderManager:
            def __init__(self, client: FakeLLMClient) -> None:
                self.client = client

            async def get_llm_client(self) -> FakeLLMClient:
                return self.client

        class FakeSkillService:
            def __init__(self, session_factory) -> None:
                self._session_factory = session_factory

            async def get_skill_by_name(self, *, tenant_id: str, skill_name: str):
                async with self._session_factory() as db:
                    return await SqlSkillRepository(db).get_by_name(tenant_id, skill_name)

            async def update_skill_content(self, skill_id: str, full_content: str):
                raise AssertionError("direct repository-backed merge should be used")

        with tempfile.TemporaryDirectory(prefix="skill-evolution-smoke-") as tmp:
            engine = create_async_engine(f"sqlite+aiosqlite:///{Path(tmp) / 'smoke.db'}")
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with engine.begin() as conn:
                for table in (
                    db_models.Skill.__table__,
                    db_models.SkillVersion.__table__,
                    SkillEvolutionSession.__table__,
                    SkillEvolutionJob.__table__,
                ):
                    await conn.run_sync(
                        lambda sync_conn, table=table: table.create(sync_conn, checkfirst=True)
                    )

            async with session_factory() as db:
                await SqlSkillRepository(db).create(
                    Skill(
                        id="skill-evolution-smoke-id",
                        tenant_id=tenant_id,
                        name=skill_name,
                        description="Initial smoke skill",
                        tools=["terminal"],
                        full_content=(
                            "---\n"
                            "name: evolution-smoke-skill\n"
                            "description: Initial smoke skill.\n"
                            "---\n\n"
                            "# Evolution Smoke Skill\n"
                        ),
                        scope=SkillScope.TENANT,
                        current_version=0,
                    )
                )
                await db.commit()

            client = FakeLLMClient()
            config = SkillEvolutionConfig(
                enabled=True,
                min_sessions_per_skill=1,
                scoring_min_sessions_per_skill=1,
                min_avg_score=0.5,
                max_sessions_per_batch=5,
                publish_mode="direct",
                auto_apply=True,
            )
            plugin = SkillEvolutionPlugin(
                config=config,
                skill_service=FakeSkillService(session_factory),
                llm_provider_manager=FakeLLMProviderManager(client),
                session_factory=session_factory,
            )

            registry = AgentPluginRegistry()
            plugin.setup(PluginRuntimeApi("skill-evolution", registry=registry))
            hook_result = await registry.apply_hook(
                "after_turn_complete",
                payload={
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "conversation_id": "conv-evolution-smoke",
                    "user_message": "Please answer and show verification evidence.",
                    "final_content": "Done.",
                    "matched_skill_name": skill_name,
                    "conversation_context": [{"role": "assistant", "content": "Done."}],
                    "success": True,
                    "execution_time_ms": 120,
                },
            )

            result = await plugin.trigger_evolution(
                tenant_id=tenant_id,
                project_id=project_id,
                skill_name=skill_name,
            )

            async with session_factory() as db:
                session = (
                    await db.execute(
                        select(SkillEvolutionSession).where(
                            SkillEvolutionSession.skill_name == skill_name
                        )
                    )
                ).scalar_one()
                job = (
                    await db.execute(
                        select(SkillEvolutionJob).where(SkillEvolutionJob.skill_name == skill_name)
                    )
                ).scalar_one()
                version = (
                    await db.execute(
                        select(db_models.SkillVersion).where(
                            db_models.SkillVersion.id == job.skill_version_id
                        )
                    )
                ).scalar_one()
                skill = (
                    await db.execute(
                        select(db_models.Skill).where(db_models.Skill.name == skill_name)
                    )
                ).scalar_one()

            await engine.dispose()
            plugin_module._collector = None
            plugin_module._config = None
            plugin_module._scheduler = None
            plugin_module._session_factory = None

        assert "after_turn_complete" in registry.list_hooks()
        assert hook_result.diagnostics == []
        assert result == {
            "summarized": 1,
            "judged": 1,
            "groups": 1,
            "jobs": 1,
            "blocked_by_review": 0,
        }
        assert len(client.calls) == 3
        assert session.processed is True
        assert isinstance(session.trajectory, dict)
        assert "steps" in session.trajectory
        assert session.summary
        assert session.overall_score is not None
        assert session.overall_score >= 0.5
        assert job.action == "improve_skill"
        assert job.status == "applied"
        assert job.skill_version_id == version.id
        assert version.created_by == "evolution"
        assert "explicit verification evidence" in version.skill_md_content
        assert skill.current_version == version.version_number == 1
        assert skill.version_label == "1"
        assert "explicit verification evidence" in (skill.full_content or "")


class TestModels:
    def test_session_repr(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )

        s = SkillEvolutionSession(
            id="s1",
            skill_name="test",
            tenant_id="t1",
            conversation_id="c1",
            user_query="q",
        )
        assert "SkillEvolutionSession" in repr(s)

    def test_job_repr(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionJob,
        )

        j = SkillEvolutionJob(
            id="j1",
            skill_name="test",
            tenant_id="t1",
            action="skip",
        )
        assert "SkillEvolutionJob" in repr(j)


class TestAggregator:
    @pytest.mark.asyncio
    async def test_aggregate_empty(self) -> None:
        repo = MagicMock()
        repo.get_scored_sessions_grouped_by_skill = AsyncMock(return_value=[])

        config = SkillEvolutionConfig(min_sessions_per_skill=3, min_avg_score=0.5)
        aggregator = SkillSessionAggregator(config)

        groups = await aggregator.aggregate(repo, tenant_id="t1")
        assert len(groups) == 0

    @pytest.mark.asyncio
    async def test_aggregate_with_groups(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )

        repo = MagicMock()
        repo.get_scored_sessions_grouped_by_skill = AsyncMock(
            return_value=[
                {
                    "skill_name": "debug-skill",
                    "session_count": 10,
                    "avg_score": 0.85,
                    "success_count": 8,
                }
            ]
        )
        repo.get_sessions_by_skill = AsyncMock(
            return_value=[
                SkillEvolutionSession(
                    id=f"s{i}",
                    skill_name="debug-skill",
                    tenant_id="t1",
                    conversation_id=f"c{i}",
                    user_query=f"query {i}",
                    success=(i % 2 == 0),
                    overall_score=0.7 + (i * 0.03),
                )
                for i in range(5)
            ]
        )

        config = SkillEvolutionConfig(min_sessions_per_skill=3, min_avg_score=0.5)
        aggregator = SkillSessionAggregator(config)

        groups = await aggregator.aggregate(repo, tenant_id="t1")
        assert "debug-skill" in groups
        assert groups["debug-skill"].session_count == 5


class TestEvolutionEngine:
    @pytest.mark.asyncio
    async def test_filesystem_skill_fallback_can_be_evolved(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.evolution_engine import (
            EvolutionEngine,
        )
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )

        class FakeLLMClient:
            def __init__(self) -> None:
                self.prompt = ""

            async def generate(self, messages, max_tokens: int):
                self.prompt = messages[-1].content
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "action": "improve_skill",
                                        "rationale": "Repeated sessions show a reusable workflow.",
                                        "skill_content": (
                                            "---\nname: deep-research\n"
                                            "description: Run deep research.\n---\n"
                                            "# Deep Research\n"
                                        ),
                                    }
                                )
                            }
                        }
                    ]
                }

        group = SkillSessionGroup(skill_name="deep-research")
        for i in range(5):
            group.add(
                SkillEvolutionSession(
                    id=f"s{i}",
                    skill_name="deep-research",
                    tenant_id="t1",
                    conversation_id=f"c{i}",
                    user_query="research this",
                    summary="Needed reusable research workflow.",
                    success=True,
                    overall_score=0.8,
                )
            )

        skill_service = MagicMock()
        filesystem_skill = MagicMock()
        filesystem_skill.full_content = "---\nname: deep-research\n---\n# Deep Research\n"
        skill_service.get_skill_by_name = AsyncMock(return_value=filesystem_skill)
        skill_repo = MagicMock()
        skill_repo.get_by_name = AsyncMock(return_value=None)
        skill_repo.list_by_tenant = AsyncMock(return_value=[])
        repo = MagicMock()
        repo.has_job_for_sessions = AsyncMock(return_value=False)
        repo.save_job = AsyncMock()

        client = FakeLLMClient()
        engine = EvolutionEngine(
            SkillEvolutionConfig(), skill_service=skill_service, merger=MagicMock()
        )

        jobs = await engine.evolve_all(
            {"deep-research": group},
            client,
            repo,
            tenant_id="t1",
            skill_repository=skill_repo,
        )

        assert len(jobs) == 1
        assert jobs[0].action == "improve_skill"
        assert jobs[0].status == "pending_review"
        assert "Current SKILL.md for 'deep-research'" in client.prompt
        assert "No managed or file-system SKILL.md exists" not in client.prompt
        repo.save_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skip_decision_is_not_pending_review(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.evolution_engine import (
            EvolutionEngine,
        )
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )

        class FakeLLMClient:
            async def generate(self, messages, max_tokens: int):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "action": "skip",
                                        "rationale": "The skill is working well.",
                                    }
                                )
                            }
                        }
                    ]
                }

        skill = MagicMock()
        skill.full_content = "---\nname: stable-skill\n---\n# Stable Skill\n"
        group = SkillSessionGroup(skill_name="stable-skill")
        for i in range(5):
            group.add(
                SkillEvolutionSession(
                    id=f"s{i}",
                    skill_name="stable-skill",
                    tenant_id="t1",
                    conversation_id=f"c{i}",
                    user_query="do stable work",
                    summary="Completed successfully.",
                    success=True,
                    overall_score=0.9,
                )
            )

        skill_repo = MagicMock()
        skill_repo.get_by_name = AsyncMock(return_value=skill)
        skill_repo.list_by_tenant = AsyncMock(return_value=[skill])
        repo = MagicMock()
        repo.has_job_for_sessions = AsyncMock(return_value=False)
        repo.save_job = AsyncMock()

        engine = EvolutionEngine(
            SkillEvolutionConfig(), skill_service=MagicMock(), merger=MagicMock()
        )

        jobs = await engine.evolve_all(
            {"stable-skill": group},
            FakeLLMClient(),
            repo,
            tenant_id="t1",
            skill_repository=skill_repo,
        )

        assert len(jobs) == 1
        assert jobs[0].action == "skip"
        assert jobs[0].status == "skipped"
        repo.save_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_existing_session_batch_is_not_evolved_again(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.evolution_engine import (
            EvolutionEngine,
        )
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )

        llm_client = MagicMock()
        llm_client.generate = AsyncMock()
        group = SkillSessionGroup(skill_name="stable-skill")
        for i in range(5):
            group.add(
                SkillEvolutionSession(
                    id=f"s{i}",
                    skill_name="stable-skill",
                    tenant_id="t1",
                    conversation_id=f"c{i}",
                    user_query="do stable work",
                    success=True,
                    overall_score=0.9,
                )
            )

        repo = MagicMock()
        repo.has_job_for_sessions = AsyncMock(return_value=True)
        repo.save_job = AsyncMock()

        engine = EvolutionEngine(
            SkillEvolutionConfig(), skill_service=MagicMock(), merger=MagicMock()
        )

        jobs = await engine.evolve_all(
            {"stable-skill": group},
            llm_client,
            repo,
            tenant_id="t1",
        )

        assert jobs == []
        assert engine.last_blocked_by_review_count == 1
        llm_client.generate.assert_not_awaited()
        repo.save_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejected_session_batch_can_be_evolved_again(self) -> None:
        from src.infrastructure.agent.plugins.skill_evolution.evolution_engine import (
            EvolutionEngine,
        )
        from src.infrastructure.agent.plugins.skill_evolution.models import (
            SkillEvolutionSession,
        )

        class FakeLLMClient:
            async def generate(self, messages, max_tokens: int):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "action": "improve_skill",
                                        "rationale": "Rejected prior candidate; try again.",
                                        "skill_content": "# Improved again",
                                    }
                                )
                            }
                        }
                    ]
                }

        skill = MagicMock()
        skill.full_content = "# Current"
        group = SkillSessionGroup(skill_name="retry-skill")
        for i in range(5):
            group.add(
                SkillEvolutionSession(
                    id=f"s{i}",
                    skill_name="retry-skill",
                    tenant_id="t1",
                    conversation_id=f"c{i}",
                    user_query="retry evolution",
                    success=True,
                    overall_score=0.9,
                )
            )

        skill_repo = MagicMock()
        skill_repo.get_by_name = AsyncMock(return_value=skill)
        skill_repo.list_by_tenant = AsyncMock(return_value=[skill])
        repo = MagicMock()
        repo.get_job_for_sessions = AsyncMock(return_value=None)
        repo.save_job = AsyncMock()

        engine = EvolutionEngine(
            SkillEvolutionConfig(), skill_service=MagicMock(), merger=MagicMock()
        )

        jobs = await engine.evolve_all(
            {"retry-skill": group},
            FakeLLMClient(),
            repo,
            tenant_id="t1",
            skill_repository=skill_repo,
        )

        assert len(jobs) == 1
        assert jobs[0].candidate_content == "# Improved again"
        assert engine.last_blocked_by_review_count == 0
        repo.save_job.assert_awaited_once()
