"""Unit tests for the skill evolution plugin."""

from __future__ import annotations

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
        assert config.min_avg_score == 0.8
        assert config.evolution_interval_minutes == 120
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
        for i, (success, score) in enumerate(
            [(True, 0.9), (False, 0.5), (True, 0.8)]
        ):
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
        )
        assert len(trajectory["steps"]) == 3
        assert trajectory["tool_call_count"] == 1
        assert trajectory["user_query"] == "read the file"


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
        assert result is None  # version tracking not yet implemented
        skill_service.update_skill_content.assert_awaited_once()


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
