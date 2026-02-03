"""
Unit tests for SubAgentOrchestrator module.

Tests cover:
- SubAgent matching
- Tool filtering
- Execution configuration
- Routing events
- Execution recording
- Singleton management
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.infrastructure.agent.routing.subagent_orchestrator import (
    SubAgentExecutionConfig,
    SubAgentOrchestrator,
    SubAgentOrchestratorConfig,
    SubAgentRoutingResult,
    create_subagent_orchestrator,
    get_subagent_orchestrator,
    set_subagent_orchestrator,
)

# ============================================================================
# Mock Classes
# ============================================================================


class MockAgentModel:
    """Mock AgentModel enum."""

    INHERIT = "inherit"
    GPT4 = "gpt-4"
    CLAUDE = "claude-3"

    def __init__(self, value: str):
        self._value = value

    @property
    def value(self):
        return self._value

    def __eq__(self, other):
        if isinstance(other, MockAgentModel):
            return self._value == other._value
        return self._value == other


@dataclass
class MockSubAgentTrigger:
    """Mock SubAgent trigger."""

    keywords: List[str]
    description: str = "Test trigger"


@dataclass
class MockSubAgent:
    """Mock SubAgent for testing."""

    id: str
    name: str
    display_name: str
    enabled: bool = True
    model: Any = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_iterations: int = 20
    system_prompt: str = "You are a helpful assistant."
    allowed_tools: List[str] = None
    allowed_skills: List[str] = None
    allowed_mcp_servers: List[str] = None
    trigger: MockSubAgentTrigger = None
    _execution_count: int = 0

    def __post_init__(self):
        if self.model is None:
            self.model = MockAgentModel(MockAgentModel.INHERIT)
        if self.allowed_tools is None:
            self.allowed_tools = ["*"]
        if self.allowed_skills is None:
            self.allowed_skills = []
        if self.allowed_mcp_servers is None:
            self.allowed_mcp_servers = []
        if self.trigger is None:
            self.trigger = MockSubAgentTrigger(keywords=["test"])

    def record_execution(self, execution_time_ms: int, success: bool) -> None:
        self._execution_count += 1


@dataclass
class MockSubAgentMatch:
    """Mock SubAgent match result."""

    subagent: Optional[MockSubAgent]
    confidence: float
    match_reason: str


class MockSubAgentRouter:
    """Mock SubAgentRouter for testing."""

    def __init__(self, subagents: List[MockSubAgent] = None):
        self._subagents = subagents or []
        self._match_result = None

    def set_match_result(self, result: MockSubAgentMatch):
        self._match_result = result

    def match(
        self,
        query: str,
        confidence_threshold: Optional[float] = None,
    ) -> MockSubAgentMatch:
        if self._match_result:
            return self._match_result
        return MockSubAgentMatch(
            subagent=None,
            confidence=0.0,
            match_reason="No match",
        )

    def filter_tools(
        self,
        subagent: MockSubAgent,
        available_tools: Dict[str, Any],
    ) -> Dict[str, Any]:
        if "*" in subagent.allowed_tools:
            return available_tools
        return {
            name: tool
            for name, tool in available_tools.items()
            if name in subagent.allowed_tools
        }

    def get_subagent_config(self, subagent: MockSubAgent) -> Dict[str, Any]:
        return {
            "model": subagent.model.value if hasattr(subagent.model, "value") else None,
            "temperature": subagent.temperature,
            "max_tokens": subagent.max_tokens,
            "max_iterations": subagent.max_iterations,
        }

    def list_subagents(self) -> List[MockSubAgent]:
        return [s for s in self._subagents if s.enabled]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_subagents():
    """Create sample SubAgents."""
    return [
        MockSubAgent(
            id="sa-1",
            name="code-agent",
            display_name="Code Agent",
            system_prompt="You are a coding assistant.",
            allowed_tools=["run_code", "read_file"],
            trigger=MockSubAgentTrigger(keywords=["code", "python", "javascript"]),
        ),
        MockSubAgent(
            id="sa-2",
            name="research-agent",
            display_name="Research Agent",
            model=MockAgentModel("claude-3"),
            system_prompt="You are a research assistant.",
            allowed_tools=["web_search", "summarize"],
            trigger=MockSubAgentTrigger(keywords=["research", "find", "search"]),
        ),
        MockSubAgent(
            id="sa-3",
            name="disabled-agent",
            display_name="Disabled Agent",
            enabled=False,
        ),
    ]


@pytest.fixture
def mock_router(sample_subagents):
    """Create mock router with sample SubAgents."""
    return MockSubAgentRouter(subagents=sample_subagents)


@pytest.fixture
def config():
    """Create orchestrator config."""
    return SubAgentOrchestratorConfig(
        default_confidence_threshold=0.5,
        emit_routing_events=True,
    )


@pytest.fixture
def orchestrator(mock_router, config):
    """Create orchestrator instance."""
    return SubAgentOrchestrator(
        router=mock_router,
        config=config,
        base_model="gpt-4-turbo",
        debug_logging=True,
    )


# ============================================================================
# Test Data Classes
# ============================================================================


@pytest.mark.unit
class TestSubAgentRoutingResult:
    """Test SubAgentRoutingResult dataclass."""

    def test_default_result(self):
        """Test default routing result."""
        result = SubAgentRoutingResult()
        assert result.subagent is None
        assert result.confidence == 0.0
        assert result.routed is False
        assert result.matched is False

    def test_matched_result(self):
        """Test matched routing result."""
        subagent = MockSubAgent(id="1", name="test", display_name="Test")
        result = SubAgentRoutingResult(
            subagent=subagent,
            confidence=0.85,
            match_reason="Keyword match",
            routed=True,
        )
        assert result.subagent is subagent
        assert result.confidence == 0.85
        assert result.routed is True
        assert result.matched is True

    def test_not_matched_when_not_routed(self):
        """Test matched is False when routed is False."""
        subagent = MockSubAgent(id="1", name="test", display_name="Test")
        result = SubAgentRoutingResult(
            subagent=subagent,
            confidence=0.3,
            routed=False,
        )
        assert result.matched is False


@pytest.mark.unit
class TestSubAgentExecutionConfig:
    """Test SubAgentExecutionConfig dataclass."""

    def test_default_config(self):
        """Test default execution config."""
        config = SubAgentExecutionConfig()
        assert config.model is None
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.max_iterations == 20
        assert config.system_prompt == ""
        assert config.allowed_tools == []

    def test_custom_config(self):
        """Test custom execution config."""
        config = SubAgentExecutionConfig(
            model="claude-3",
            temperature=0.5,
            max_tokens=8192,
            max_iterations=30,
            system_prompt="Custom prompt",
            allowed_tools=["tool1", "tool2"],
        )
        assert config.model == "claude-3"
        assert config.temperature == 0.5
        assert config.max_tokens == 8192
        assert config.max_iterations == 30
        assert config.system_prompt == "Custom prompt"
        assert config.allowed_tools == ["tool1", "tool2"]


@pytest.mark.unit
class TestSubAgentOrchestratorConfig:
    """Test SubAgentOrchestratorConfig dataclass."""

    def test_default_orchestrator_config(self):
        """Test default orchestrator config."""
        config = SubAgentOrchestratorConfig()
        assert config.default_confidence_threshold == 0.5
        assert config.emit_routing_events is True

    def test_custom_orchestrator_config(self):
        """Test custom orchestrator config."""
        config = SubAgentOrchestratorConfig(
            default_confidence_threshold=0.7,
            emit_routing_events=False,
        )
        assert config.default_confidence_threshold == 0.7
        assert config.emit_routing_events is False


# ============================================================================
# Test Initialization
# ============================================================================


@pytest.mark.unit
class TestSubAgentOrchestratorInit:
    """Test SubAgentOrchestrator initialization."""

    def test_init_with_router(self, mock_router, config):
        """Test initialization with router."""
        orch = SubAgentOrchestrator(router=mock_router, config=config)
        assert orch.has_router is True

    def test_init_without_router(self, config):
        """Test initialization without router."""
        orch = SubAgentOrchestrator(config=config)
        assert orch.has_router is False

    def test_available_subagents_with_router(self, orchestrator, sample_subagents):
        """Test available_subagents with router."""
        subagents = orchestrator.available_subagents
        # Should exclude disabled agent
        assert len(subagents) == 2
        assert all(s.enabled for s in subagents)

    def test_available_subagents_without_router(self, config):
        """Test available_subagents without router."""
        orch = SubAgentOrchestrator(config=config)
        assert orch.available_subagents == []


# ============================================================================
# Test Matching
# ============================================================================


@pytest.mark.unit
class TestSubAgentMatching:
    """Test SubAgent matching functionality."""

    def test_match_returns_result(self, orchestrator, mock_router, sample_subagents):
        """Test matching returns matched SubAgent."""
        mock_router.set_match_result(
            MockSubAgentMatch(
                subagent=sample_subagents[0],
                confidence=0.85,
                match_reason="Keyword match: code",
            )
        )

        result = orchestrator.match("Write some Python code")

        assert result.matched is True
        assert result.subagent.name == "code-agent"
        assert result.confidence == 0.85
        assert "Keyword" in result.match_reason

    def test_match_no_router(self, config):
        """Test matching without router."""
        orch = SubAgentOrchestrator(config=config)
        result = orch.match("test query")

        assert result.matched is False
        assert "No router" in result.match_reason

    def test_match_no_match_found(self, orchestrator, mock_router):
        """Test matching when no SubAgent matches."""
        mock_router.set_match_result(
            MockSubAgentMatch(
                subagent=None,
                confidence=0.0,
                match_reason="No match found",
            )
        )

        result = orchestrator.match("random query")

        assert result.matched is False
        assert result.subagent is None

    def test_match_custom_threshold(self, orchestrator, mock_router, sample_subagents):
        """Test matching with custom threshold."""
        mock_router.set_match_result(
            MockSubAgentMatch(
                subagent=sample_subagents[1],
                confidence=0.6,
                match_reason="Description match",
            )
        )

        result = orchestrator.match("research topic", confidence_threshold=0.7)

        # Should be routed because match() was called, even though confidence is below threshold
        # (threshold is checked by router, not orchestrator)
        assert result.matched is True


# ============================================================================
# Test Tool Filtering
# ============================================================================


@pytest.mark.unit
class TestToolFiltering:
    """Test tool filtering functionality."""

    def test_filter_tools_with_wildcard(self, orchestrator, sample_subagents):
        """Test tool filtering with wildcard allows all tools."""
        subagent = MockSubAgent(
            id="test",
            name="test",
            display_name="Test",
            allowed_tools=["*"],
        )
        available_tools = {"tool1": {}, "tool2": {}, "tool3": {}}

        filtered = orchestrator.filter_tools(subagent, available_tools)

        assert filtered == available_tools

    def test_filter_tools_specific_tools(self, orchestrator, sample_subagents):
        """Test tool filtering with specific tools."""
        subagent = sample_subagents[0]  # code-agent with ["run_code", "read_file"]
        available_tools = {
            "run_code": {},
            "read_file": {},
            "web_search": {},
            "summarize": {},
        }

        filtered = orchestrator.filter_tools(subagent, available_tools)

        assert "run_code" in filtered
        assert "read_file" in filtered
        assert "web_search" not in filtered
        assert "summarize" not in filtered

    def test_filter_tools_without_router(self, config, sample_subagents):
        """Test tool filtering without router uses subagent directly."""
        orch = SubAgentOrchestrator(config=config)
        subagent = sample_subagents[0]  # code-agent
        available_tools = {"run_code": {}, "web_search": {}}

        filtered = orch.filter_tools(subagent, available_tools)

        assert "run_code" in filtered
        assert "web_search" not in filtered


# ============================================================================
# Test Execution Configuration
# ============================================================================


@pytest.mark.unit
class TestExecutionConfiguration:
    """Test execution configuration building."""

    def test_get_execution_config_inherit_model(self, orchestrator, sample_subagents):
        """Test execution config with inherited model."""
        subagent = sample_subagents[0]  # code-agent with INHERIT model

        config = orchestrator.get_execution_config(subagent)

        assert config.model == "gpt-4-turbo"  # Base model
        assert config.temperature == subagent.temperature
        assert config.max_tokens == subagent.max_tokens
        assert config.system_prompt == subagent.system_prompt

    def test_get_execution_config_explicit_model(self, orchestrator, sample_subagents):
        """Test execution config with explicit model."""
        subagent = sample_subagents[1]  # research-agent with claude-3

        config = orchestrator.get_execution_config(subagent)

        assert config.model == "claude-3"

    def test_get_execution_config_with_override(self, orchestrator, sample_subagents):
        """Test execution config with model override."""
        subagent = sample_subagents[0]  # code-agent with INHERIT

        config = orchestrator.get_execution_config(subagent, override_model="gpt-4o")

        assert config.model == "gpt-4o"  # Override takes precedence


# ============================================================================
# Test Routing Events
# ============================================================================


@pytest.mark.unit
class TestRoutingEvents:
    """Test routing event creation."""

    def test_create_routing_event_matched(self, orchestrator, sample_subagents):
        """Test routing event for matched SubAgent."""
        result = SubAgentRoutingResult(
            subagent=sample_subagents[0],
            confidence=0.85,
            match_reason="Keyword match",
            routed=True,
        )

        event = orchestrator.create_routing_event(result)

        assert event is not None
        assert event["type"] == "subagent_routed"
        assert event["data"]["subagent_id"] == "sa-1"
        assert event["data"]["subagent_name"] == "Code Agent"
        assert event["data"]["confidence"] == 0.85
        assert "timestamp" in event

    def test_create_routing_event_not_matched(self, orchestrator):
        """Test routing event for unmatched result."""
        result = SubAgentRoutingResult(routed=False)

        event = orchestrator.create_routing_event(result)

        assert event is None

    def test_create_routing_event_disabled(self, mock_router):
        """Test routing event when disabled."""
        config = SubAgentOrchestratorConfig(emit_routing_events=False)
        orch = SubAgentOrchestrator(router=mock_router, config=config)

        subagent = MockSubAgent(id="1", name="test", display_name="Test")
        result = SubAgentRoutingResult(subagent=subagent, routed=True)

        event = orch.create_routing_event(result)

        assert event is None


# ============================================================================
# Test Execution Recording
# ============================================================================


@pytest.mark.unit
class TestExecutionRecording:
    """Test execution statistics recording."""

    def test_record_execution_success(self, orchestrator, sample_subagents):
        """Test recording successful execution."""
        subagent = sample_subagents[0]
        initial_count = subagent._execution_count

        orchestrator.record_execution(subagent, 1500, True)

        assert subagent._execution_count == initial_count + 1

    def test_record_execution_failure(self, orchestrator, sample_subagents):
        """Test recording failed execution."""
        subagent = sample_subagents[0]
        initial_count = subagent._execution_count

        orchestrator.record_execution(subagent, 500, False)

        assert subagent._execution_count == initial_count + 1

    def test_record_execution_handles_error(self, orchestrator):
        """Test recording handles errors gracefully."""
        # Create subagent that raises on record_execution
        subagent = MagicMock()
        subagent.record_execution.side_effect = Exception("Recording failed")
        subagent.name = "error-agent"

        # Should not raise
        orchestrator.record_execution(subagent, 1000, True)


# ============================================================================
# Test SubAgents Data
# ============================================================================


@pytest.mark.unit
class TestSubAgentsData:
    """Test SubAgents data export."""

    def test_get_subagents_data(self, orchestrator):
        """Test getting SubAgents as dict data."""
        data = orchestrator.get_subagents_data()

        assert data is not None
        assert len(data) == 2  # Excludes disabled
        assert all("id" in s for s in data)
        assert all("name" in s for s in data)
        assert all("display_name" in s for s in data)

    def test_get_subagents_data_no_router(self, config):
        """Test getting SubAgents data without router."""
        orch = SubAgentOrchestrator(config=config)
        data = orch.get_subagents_data()

        assert data is None

    def test_get_subagents_data_truncates_prompt(self, mock_router, config):
        """Test that long system prompts are truncated."""
        long_prompt = "x" * 500
        subagent = MockSubAgent(
            id="1",
            name="verbose",
            display_name="Verbose",
            system_prompt=long_prompt,
        )
        mock_router._subagents = [subagent]

        orch = SubAgentOrchestrator(router=mock_router, config=config)
        data = orch.get_subagents_data()

        assert len(data[0]["system_prompt_preview"]) < len(long_prompt)
        assert "..." in data[0]["system_prompt_preview"]


# ============================================================================
# Test Singleton Functions
# ============================================================================


@pytest.mark.unit
class TestSingletonFunctions:
    """Test singleton getter/setter functions."""

    def test_get_without_init_raises(self):
        """Test getting orchestrator without initialization raises."""
        import src.infrastructure.agent.routing.subagent_orchestrator as module

        module._orchestrator = None

        with pytest.raises(RuntimeError, match="not initialized"):
            get_subagent_orchestrator()

    def test_set_and_get(self, mock_router, config):
        """Test setting and getting orchestrator."""
        orch = SubAgentOrchestrator(router=mock_router, config=config)
        set_subagent_orchestrator(orch)

        result = get_subagent_orchestrator()
        assert result is orch

    def test_create_subagent_orchestrator(self, mock_router, config):
        """Test create_subagent_orchestrator function."""
        orch = create_subagent_orchestrator(
            router=mock_router,
            config=config,
            base_model="gpt-4o",
            debug_logging=True,
        )

        assert isinstance(orch, SubAgentOrchestrator)
        assert orch._debug_logging is True
        assert orch._base_model == "gpt-4o"

        result = get_subagent_orchestrator()
        assert result is orch
