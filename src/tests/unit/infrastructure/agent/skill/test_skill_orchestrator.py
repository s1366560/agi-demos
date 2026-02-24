"""
Unit tests for SkillOrchestrator module.

Tests cover:
- Skill matching
- Execution mode determination
- Direct execution flow
- Event conversion
- Result summarization
- Singleton management
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.skill.orchestrator import (
    SkillExecutionConfig,
    SkillExecutionContext,
    SkillExecutionMode,
    SkillMatchResult,
    SkillOrchestrator,
    create_skill_orchestrator,
    get_skill_orchestrator,
    set_skill_orchestrator,
)

# ============================================================================
# Mock Skill Class
# ============================================================================


@dataclass
class MockSkillStatus:
    """Mock skill status."""

    value: str = "active"


@dataclass
class MockSkill:
    """Mock skill for testing."""

    id: str
    name: str
    description: str
    tools: list[str]
    prompt_template: str | None = None
    status: MockSkillStatus = None
    _match_score: float = 0.0
    _accessible: bool = True

    def __post_init__(self):
        if self.status is None:
            self.status = MockSkillStatus()

    def is_accessible_by_agent(self, agent_mode: str) -> bool:
        return self._accessible

    def matches_query(self, query: str) -> float:
        return self._match_score

    def record_usage(self, success: bool) -> None:
        pass


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_skill_executor():
    """Create mock skill executor."""
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=iter([]))
    return executor


@pytest.fixture
def sample_skills():
    """Create sample skills for testing."""
    return [
        MockSkill(
            id="skill-1",
            name="search_skill",
            description="Search for information",
            tools=["web_search", "summarize"],
            _match_score=0.8,
        ),
        MockSkill(
            id="skill-2",
            name="code_skill",
            description="Generate and execute code",
            tools=["code_generate", "code_execute"],
            _match_score=0.96,
        ),
        MockSkill(
            id="skill-3",
            name="inactive_skill",
            description="Inactive skill",
            tools=["tool1"],
            status=MockSkillStatus(value="inactive"),
        ),
    ]


@pytest.fixture
def config():
    """Create execution config."""
    return SkillExecutionConfig(
        match_threshold=0.7,
        direct_execute_threshold=0.95,
        fallback_on_error=True,
        execution_timeout=300,
    )


@pytest.fixture
def orchestrator(sample_skills, mock_skill_executor, config):
    """Create SkillOrchestrator instance."""
    return SkillOrchestrator(
        skills=sample_skills,
        skill_executor=mock_skill_executor,
        config=config,
        debug_logging=True,
    )


@pytest.fixture
def execution_context():
    """Create execution context."""
    return SkillExecutionContext(
        project_id="proj-001",
        user_id="user-001",
        tenant_id="tenant-001",
        query="Generate some Python code",
    )


# ============================================================================
# Test Data Classes
# ============================================================================


@pytest.mark.unit
class TestSkillExecutionMode:
    """Test SkillExecutionMode enum."""

    def test_none_mode(self):
        """Test none mode."""
        assert SkillExecutionMode.NONE.value == "none"

    def test_direct_mode(self):
        """Test direct mode."""
        assert SkillExecutionMode.DIRECT.value == "direct"

    def test_inject_mode(self):
        """Test inject mode."""
        assert SkillExecutionMode.INJECT.value == "inject"


@pytest.mark.unit
class TestSkillMatchResult:
    """Test SkillMatchResult dataclass."""

    def test_default_result(self):
        """Test default match result."""
        result = SkillMatchResult()
        assert result.skill is None
        assert result.score == 0.0
        assert result.mode == SkillExecutionMode.NONE
        assert result.matched is False

    def test_matched_result(self):
        """Test matched result."""
        skill = MockSkill(id="1", name="test", description="test", tools=[])
        result = SkillMatchResult(
            skill=skill,
            score=0.85,
            mode=SkillExecutionMode.INJECT,
        )
        assert result.skill is skill
        assert result.score == 0.85
        assert result.mode == SkillExecutionMode.INJECT
        assert result.matched is True

    def test_not_matched_with_none_mode(self):
        """Test skill present but mode is NONE."""
        skill = MockSkill(id="1", name="test", description="test", tools=[])
        result = SkillMatchResult(
            skill=skill,
            score=0.3,
            mode=SkillExecutionMode.NONE,
        )
        assert result.matched is False


@pytest.mark.unit
class TestSkillExecutionConfig:
    """Test SkillExecutionConfig dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        config = SkillExecutionConfig()
        assert config.match_threshold == 0.9
        assert config.direct_execute_threshold == 0.95
        assert config.fallback_on_error is True
        assert config.execution_timeout == 300

    def test_custom_config(self):
        """Test custom configuration."""
        config = SkillExecutionConfig(
            match_threshold=0.7,
            direct_execute_threshold=0.9,
            fallback_on_error=False,
            execution_timeout=60,
        )
        assert config.match_threshold == 0.7
        assert config.direct_execute_threshold == 0.9
        assert config.fallback_on_error is False
        assert config.execution_timeout == 60


@pytest.mark.unit
class TestSkillExecutionContext:
    """Test SkillExecutionContext dataclass."""

    def test_required_fields(self):
        """Test required fields."""
        ctx = SkillExecutionContext(
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            query="test query",
        )
        assert ctx.project_id == "proj-1"
        assert ctx.sandbox_id is None

    def test_with_sandbox_id(self):
        """Test with sandbox_id."""
        ctx = SkillExecutionContext(
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            query="test",
            sandbox_id="sandbox-123",
        )
        assert ctx.sandbox_id == "sandbox-123"


# ============================================================================
# Test SkillOrchestrator Initialization
# ============================================================================


@pytest.mark.unit
class TestSkillOrchestratorInit:
    """Test SkillOrchestrator initialization."""

    def test_init_with_skills(self, sample_skills, mock_skill_executor, config):
        """Test initialization with skills."""
        orch = SkillOrchestrator(
            skills=sample_skills,
            skill_executor=mock_skill_executor,
            config=config,
        )
        assert orch.has_skills is True
        assert orch.has_executor is True

    def test_init_without_skills(self, mock_skill_executor):
        """Test initialization without skills."""
        orch = SkillOrchestrator(skill_executor=mock_skill_executor)
        assert orch.has_skills is False
        assert orch.has_executor is True

    def test_init_without_executor(self, sample_skills):
        """Test initialization without executor."""
        orch = SkillOrchestrator(skills=sample_skills)
        assert orch.has_skills is True
        assert orch.has_executor is False


# ============================================================================
# Test Skill Matching
# ============================================================================


@pytest.mark.unit
class TestSkillMatching:
    """Test skill matching functionality."""

    def test_match_returns_best_skill(self, orchestrator):
        """Test matching returns highest scoring skill."""
        result = orchestrator.match("Generate Python code")

        # code_skill has 0.96 score, should be direct execute
        assert result.matched is True
        assert result.skill.name == "code_skill"
        assert result.mode == SkillExecutionMode.DIRECT

    def test_match_no_skills(self, mock_skill_executor, config):
        """Test matching with no skills."""
        orch = SkillOrchestrator(
            skills=[],
            skill_executor=mock_skill_executor,
            config=config,
        )
        result = orch.match("test query")
        assert result.matched is False

    def test_match_below_threshold(self, mock_skill_executor, config):
        """Test matching below threshold returns no match."""
        low_score_skill = MockSkill(
            id="low",
            name="low_skill",
            description="Low score",
            tools=["tool1"],
            _match_score=0.3,  # Below match_threshold of 0.7
        )
        orch = SkillOrchestrator(
            skills=[low_score_skill],
            skill_executor=mock_skill_executor,
            config=config,
        )
        result = orch.match("test query")
        assert result.matched is False
        assert result.mode == SkillExecutionMode.NONE

    def test_match_inject_mode(self, mock_skill_executor, config):
        """Test matching returns inject mode for medium scores."""
        medium_skill = MockSkill(
            id="med",
            name="medium_skill",
            description="Medium score",
            tools=["tool1"],
            _match_score=0.8,  # Above match_threshold but below direct_execute
        )
        orch = SkillOrchestrator(
            skills=[medium_skill],
            skill_executor=mock_skill_executor,
            config=config,
        )
        result = orch.match("test query")
        assert result.matched is True
        assert result.mode == SkillExecutionMode.INJECT

    def test_match_skips_inactive_skills(self, orchestrator):
        """Test matching skips inactive skills."""
        # inactive_skill has status "inactive"
        result = orchestrator.match("test")
        # Should not match inactive skill even if it has highest score
        assert result.skill is None or result.skill.name != "inactive_skill"

    def test_match_respects_agent_mode(self, mock_skill_executor, config):
        """Test matching respects agent mode."""
        restricted_skill = MockSkill(
            id="restricted",
            name="restricted_skill",
            description="Restricted",
            tools=["tool1"],
            _match_score=0.99,
            _accessible=False,  # Not accessible
        )
        orch = SkillOrchestrator(
            skills=[restricted_skill],
            skill_executor=mock_skill_executor,
            config=config,
            agent_mode="restricted_mode",
        )
        result = orch.match("test query")
        assert result.matched is False


# ============================================================================
# Test Execution Mode Determination
# ============================================================================


@pytest.mark.unit
class TestExecutionModeDetermination:
    """Test execution mode determination."""

    def test_direct_mode_with_high_score(self, orchestrator):
        """Test direct mode for high scores."""
        skill = MockSkill(id="1", name="test", description="test", tools=[], _match_score=0.96)
        mode = orchestrator._determine_mode(skill, 0.96)
        assert mode == SkillExecutionMode.DIRECT

    def test_inject_mode_with_medium_score(self, orchestrator):
        """Test inject mode for medium scores."""
        skill = MockSkill(id="1", name="test", description="test", tools=[], _match_score=0.8)
        mode = orchestrator._determine_mode(skill, 0.8)
        assert mode == SkillExecutionMode.INJECT

    def test_none_mode_with_low_score(self, orchestrator):
        """Test none mode for low scores."""
        skill = MockSkill(id="1", name="test", description="test", tools=[], _match_score=0.5)
        mode = orchestrator._determine_mode(skill, 0.5)
        assert mode == SkillExecutionMode.NONE

    def test_none_mode_without_skill(self, orchestrator):
        """Test none mode when skill is None."""
        mode = orchestrator._determine_mode(None, 0.95)
        assert mode == SkillExecutionMode.NONE


# ============================================================================
# Test Result Summarization
# ============================================================================


@pytest.mark.unit
class TestResultSummarization:
    """Test result summarization."""

    def test_summarize_success(self, orchestrator):
        """Test summary for successful execution."""
        skill = MockSkill(id="1", name="test_skill", description="", tools=["tool1"])
        tool_results = [
            {"tool_name": "tool1", "result": "Done successfully"},
        ]
        summary = orchestrator._summarize_results(skill, tool_results, True, None)

        assert "test_skill" in summary
        assert "tool1" in summary
        assert "Done successfully" in summary

    def test_summarize_failure_with_error(self, orchestrator):
        """Test summary for failure with error message."""
        skill = MockSkill(id="1", name="test_skill", description="", tools=[])
        summary = orchestrator._summarize_results(skill, [], False, "Connection failed")

        assert "failed" in summary.lower()
        assert "Connection failed" in summary

    def test_summarize_failure_with_tool_error(self, orchestrator):
        """Test summary for failure at specific tool."""
        skill = MockSkill(id="1", name="test_skill", description="", tools=[])
        tool_results = [
            {"tool_name": "tool1", "result": "ok", "error": None},
            {"tool_name": "tool2", "result": None, "error": "Tool2 error"},
        ]
        summary = orchestrator._summarize_results(skill, tool_results, False, None)

        assert "tool2" in summary.lower()

    def test_summarize_truncates_long_output(self, orchestrator):
        """Test summary truncates long outputs."""
        skill = MockSkill(id="1", name="test_skill", description="", tools=[])
        long_result = "x" * 500
        tool_results = [{"tool_name": "tool1", "result": long_result}]

        summary = orchestrator._summarize_results(skill, tool_results, True, None)
        assert "..." in summary
        assert len(summary) < len(long_result)


# ============================================================================
# Test Skills Data Conversion
# ============================================================================


@pytest.mark.unit
class TestSkillsDataConversion:
    """Test skills data conversion for prompt context."""

    def test_to_skill_dict(self, orchestrator):
        """Test converting skill to dict."""
        skill = MockSkill(
            id="skill-1",
            name="test_skill",
            description="Test description",
            tools=["tool1", "tool2"],
            prompt_template="Do {{task}}",
        )
        result = orchestrator.to_skill_dict(skill)

        assert result["id"] == "skill-1"
        assert result["name"] == "test_skill"
        assert result["description"] == "Test description"
        assert result["tools"] == ["tool1", "tool2"]
        assert result["prompt_template"] == "Do {{task}}"

    def test_get_skills_data(self, orchestrator):
        """Test getting all skills as data."""
        data = orchestrator.get_skills_data()

        assert data is not None
        assert len(data) >= 2  # At least 2 active, accessible skills
        assert all("id" in s for s in data)
        assert all("name" in s for s in data)

    def test_get_skills_data_empty(self, mock_skill_executor):
        """Test getting skills data when no skills."""
        orch = SkillOrchestrator(skills=[], skill_executor=mock_skill_executor)
        data = orch.get_skills_data()
        assert data is None


# ============================================================================
# Test Direct Execution
# ============================================================================


@pytest.mark.unit
class TestDirectExecution:
    """Test direct skill execution."""

    async def test_execute_directly_without_executor_raises(self, sample_skills, config):
        """Test direct execution without executor raises error."""
        orch = SkillOrchestrator(
            skills=sample_skills,
            skill_executor=None,  # No executor
            config=config,
        )
        skill = sample_skills[0]
        ctx = SkillExecutionContext(project_id="p", user_id="u", tenant_id="t", query="test")

        with pytest.raises(ValueError, match="not initialized"):
            async for _ in orch.execute_directly(skill, ctx):
                pass

    async def test_execute_directly_emits_start_event(
        self, sample_skills, mock_skill_executor, config
    ):
        """Test direct execution emits start event."""

        async def mock_execute(*args, **kwargs):
            return
            yield  # Make it a generator

        mock_skill_executor.execute = mock_execute

        orch = SkillOrchestrator(
            skills=sample_skills,
            skill_executor=mock_skill_executor,
            config=config,
        )
        skill = sample_skills[0]
        ctx = SkillExecutionContext(project_id="p", user_id="u", tenant_id="t", query="test")

        events = []
        async for event in orch.execute_directly(skill, ctx):
            events.append(event)

        assert len(events) >= 1
        assert events[0]["type"] == "skill_execution_start"
        assert events[0]["data"]["skill_name"] == skill.name


# ============================================================================
# Test Singleton Functions
# ============================================================================


@pytest.mark.unit
class TestSingletonFunctions:
    """Test singleton getter/setter functions."""

    def test_get_without_init_raises(self):
        """Test getting orchestrator without initialization raises."""
        import src.infrastructure.agent.skill.orchestrator as module

        module._orchestrator = None

        with pytest.raises(RuntimeError, match="not initialized"):
            get_skill_orchestrator()

    def test_set_and_get(self, sample_skills, mock_skill_executor, config):
        """Test setting and getting orchestrator."""
        orch = SkillOrchestrator(
            skills=sample_skills,
            skill_executor=mock_skill_executor,
            config=config,
        )
        set_skill_orchestrator(orch)

        result = get_skill_orchestrator()
        assert result is orch

    def test_create_skill_orchestrator(self, sample_skills, mock_skill_executor, config):
        """Test create_skill_orchestrator function."""
        orch = create_skill_orchestrator(
            skills=sample_skills,
            skill_executor=mock_skill_executor,
            config=config,
            debug_logging=True,
        )

        assert isinstance(orch, SkillOrchestrator)
        assert orch._debug_logging is True

        result = get_skill_orchestrator()
        assert result is orch
