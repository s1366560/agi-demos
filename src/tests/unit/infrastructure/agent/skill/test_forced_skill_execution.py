"""Tests for forced skill execution via /skill-name command."""

from dataclasses import dataclass, field
from enum import Enum
from unittest.mock import MagicMock

import pytest

from src.infrastructure.agent.skill.orchestrator import (
    SkillExecutionConfig,
    SkillExecutionMode,
    SkillMatchResult,
    SkillOrchestrator,
)


class MockSkillStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass
class MockSkill:
    """Minimal skill mock implementing SkillProtocol."""

    id: str = "skill-1"
    name: str = "test-skill"
    description: str = "A test skill"
    tools: list = field(default_factory=lambda: ["tool1"])
    status: MockSkillStatus = MockSkillStatus.ACTIVE
    agent_modes: list = field(default_factory=lambda: ["*"])
    trigger_patterns: list = field(default_factory=list)

    def matches_query(self, query: str) -> float:
        if self.name.lower() in query.lower():
            return 0.96
        return 0.3

    def is_accessible_by_agent(self, mode: str) -> bool:
        return "*" in self.agent_modes or mode in self.agent_modes


@pytest.mark.unit
class TestSkillOrchestratorFindByName:
    """Tests for SkillOrchestrator.find_by_name()."""

    def _create_orchestrator(self, skills=None):
        config = SkillExecutionConfig()
        executor = MagicMock()
        return SkillOrchestrator(
            skills=skills or [],
            config=config,
            skill_executor=executor,
            agent_mode="default",
        )

    def test_find_by_name_exact_match(self):
        skill = MockSkill(name="code-review")
        orch = self._create_orchestrator([skill])
        result = orch.find_by_name("code-review")

        assert result.matched
        assert result.skill is skill
        assert result.score == 1.0
        assert result.mode == SkillExecutionMode.DIRECT

    def test_find_by_name_case_insensitive(self):
        skill = MockSkill(name="Code-Review")
        orch = self._create_orchestrator([skill])
        result = orch.find_by_name("code-review")

        assert result.matched
        assert result.skill is skill

    def test_find_by_name_with_whitespace(self):
        skill = MockSkill(name="code-review")
        orch = self._create_orchestrator([skill])
        result = orch.find_by_name("  code-review  ")

        assert result.matched
        assert result.skill is skill

    def test_find_by_name_not_found(self):
        skill = MockSkill(name="code-review")
        orch = self._create_orchestrator([skill])
        result = orch.find_by_name("nonexistent")

        assert not result.matched
        assert result.skill is None
        assert result.score == 0.0

    def test_find_by_name_skips_inactive(self):
        skill = MockSkill(name="code-review", status=MockSkillStatus.DISABLED)
        orch = self._create_orchestrator([skill])
        result = orch.find_by_name("code-review")

        assert not result.matched

    def test_find_by_name_multiple_skills(self):
        skills = [
            MockSkill(id="s1", name="deploy"),
            MockSkill(id="s2", name="code-review"),
            MockSkill(id="s3", name="test-runner"),
        ]
        orch = self._create_orchestrator(skills)
        result = orch.find_by_name("code-review")

        assert result.matched
        assert result.skill.id == "s2"

    def test_find_by_name_empty_skills(self):
        orch = self._create_orchestrator([])
        result = orch.find_by_name("anything")

        assert not result.matched


@pytest.mark.unit
class TestForcedSkillMatchResult:
    """Tests for SkillMatchResult properties."""

    def test_forced_result_is_always_direct(self):
        skill = MockSkill()
        result = SkillMatchResult(
            skill=skill,
            score=1.0,
            mode=SkillExecutionMode.DIRECT,
        )
        assert result.matched
        assert result.mode == SkillExecutionMode.DIRECT
        assert result.score == 1.0

    def test_empty_result(self):
        result = SkillMatchResult()
        assert not result.matched
        assert result.skill is None
        assert result.score == 0.0
        assert result.mode == SkillExecutionMode.NONE
