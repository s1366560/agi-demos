"""Unit tests for ProcessorFactory - centralized processor creation.

Tests for:
- ProcessorFactory immutability (frozen dataclass)
- create_for_subagent() model resolution (INHERIT vs explicit)
- create_for_main() shared dep injection
- RunContext dataclass
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.domain.model.agent.subagent import AgentModel, SubAgent
from src.infrastructure.agent.processor.factory import ProcessorFactory
from src.infrastructure.agent.processor.processor import ProcessorConfig, ToolDefinition
from src.infrastructure.agent.processor.run_context import RunContext

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Create a mock LLM client."""
    return MagicMock()


@pytest.fixture
def mock_permission_manager() -> MagicMock:
    """Create a mock PermissionManager."""
    return MagicMock()


@pytest.fixture
def mock_artifact_service() -> MagicMock:
    """Create a mock ArtifactService."""
    return MagicMock()


@pytest.fixture
def sample_tools() -> list[ToolDefinition]:
    """Create sample tool definitions."""
    return [
        ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            execute=MagicMock(),
        ),
    ]


@pytest.fixture
def inherit_subagent() -> SubAgent:
    """Create a SubAgent with INHERIT model."""
    return SubAgent.create(
        tenant_id="tenant-1",
        name="inherit-coder",
        display_name="Inherit Coder",
        system_prompt="You are a coding assistant.",
        trigger_description="Coding tasks",
        trigger_keywords=["code"],
        trigger_examples=["Write code"],
        model=AgentModel.INHERIT,
        color="green",
        allowed_tools=["*"],
        max_tokens=4096,
        temperature=0.7,
        max_iterations=10,
    )


@pytest.fixture
def explicit_subagent() -> SubAgent:
    """Create a SubAgent with an explicit model."""
    return SubAgent.create(
        tenant_id="tenant-1",
        name="explicit-coder",
        display_name="Explicit Coder",
        system_prompt="You are a coding assistant.",
        trigger_description="Coding tasks",
        trigger_keywords=["code"],
        trigger_examples=["Write code"],
        model=AgentModel.GPT4O,
        color="blue",
        allowed_tools=["*"],
        max_tokens=8192,
        temperature=0.5,
        max_iterations=20,
    )


@pytest.fixture
def factory(
    mock_llm_client: MagicMock,
    mock_permission_manager: MagicMock,
    mock_artifact_service: MagicMock,
) -> ProcessorFactory:
    """Create a ProcessorFactory with all deps."""
    return ProcessorFactory(
        llm_client=mock_llm_client,
        permission_manager=mock_permission_manager,
        artifact_service=mock_artifact_service,
        base_model="gemini-2.0-flash",
        base_api_key="test-key",
        base_url="https://api.example.com",
    )


# ============================================================================
# ProcessorFactory Immutability Tests
# ============================================================================


@pytest.mark.unit
class TestProcessorFactoryImmutability:
    """Tests for frozen dataclass behavior."""

    def test_factory_is_frozen(self, factory: ProcessorFactory) -> None:
        """Factory should be immutable after creation."""
        with pytest.raises(AttributeError):
            factory.base_model = "changed"  # type: ignore[misc]

    def test_factory_creation_with_defaults(self) -> None:
        """Factory can be created with all defaults."""
        f = ProcessorFactory()
        assert f.llm_client is None
        assert f.permission_manager is None
        assert f.artifact_service is None
        assert f.base_model == ""
        assert f.base_api_key is None
        assert f.base_url is None


# ============================================================================
# create_for_subagent Tests
# ============================================================================


@pytest.mark.unit
class TestCreateForSubagent:
    """Tests for ProcessorFactory.create_for_subagent()."""

    def test_inherit_model_uses_base_model(
        self,
        factory: ProcessorFactory,
        inherit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """SubAgent with INHERIT model should use factory's base_model."""
        processor = factory.create_for_subagent(inherit_subagent, sample_tools)

        assert processor.config.model == "gemini-2.0-flash"

    def test_inherit_model_with_override(
        self,
        factory: ProcessorFactory,
        inherit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """model_override takes precedence over base_model for INHERIT."""
        processor = factory.create_for_subagent(
            inherit_subagent, sample_tools, model_override="gpt-4o-mini"
        )

        assert processor.config.model == "gpt-4o-mini"

    def test_explicit_model_ignores_base_and_override(
        self,
        factory: ProcessorFactory,
        explicit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """SubAgent with explicit model should use its own model."""
        processor = factory.create_for_subagent(
            explicit_subagent, sample_tools, model_override="ignored-model"
        )

        assert processor.config.model == AgentModel.GPT4O.value

    def test_subagent_settings_propagated(
        self,
        factory: ProcessorFactory,
        explicit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """SubAgent temperature, max_tokens, max_steps should be propagated."""
        processor = factory.create_for_subagent(explicit_subagent, sample_tools)

        assert processor.config.temperature == explicit_subagent.temperature
        assert processor.config.max_tokens == explicit_subagent.max_tokens
        assert processor.config.max_steps == explicit_subagent.max_iterations

    def test_shared_deps_injected(
        self,
        factory: ProcessorFactory,
        inherit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
        mock_permission_manager: MagicMock,
        mock_artifact_service: MagicMock,
    ) -> None:
        """Shared deps (permission_manager, artifact_service) should be injected."""
        processor = factory.create_for_subagent(inherit_subagent, sample_tools)

        assert processor.permission_manager is mock_permission_manager
        assert processor._artifact_service is mock_artifact_service

    def test_tools_passed_through(
        self,
        factory: ProcessorFactory,
        inherit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """Tools should be passed to the created processor."""
        processor = factory.create_for_subagent(inherit_subagent, sample_tools)

        assert len(processor.tools) == 1
        assert "test_tool" in processor.tools


# ============================================================================
# create_for_main Tests
# ============================================================================


@pytest.mark.unit
class TestCreateForMain:
    """Tests for ProcessorFactory.create_for_main()."""

    def test_config_passed_through(
        self,
        factory: ProcessorFactory,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """Pre-built ProcessorConfig should be passed through unchanged."""
        config = ProcessorConfig(
            model="custom-model",
            api_key="custom-key",
            temperature=0.3,
            max_tokens=2048,
            max_steps=5,
        )

        processor = factory.create_for_main(config, sample_tools)

        assert processor.config.model == "custom-model"
        assert processor.config.api_key == "custom-key"
        assert processor.config.temperature == 0.3

    def test_shared_deps_injected_for_main(
        self,
        factory: ProcessorFactory,
        sample_tools: list[ToolDefinition],
        mock_permission_manager: MagicMock,
        mock_artifact_service: MagicMock,
    ) -> None:
        """Shared deps should be injected for main processor too."""
        config = ProcessorConfig(model="test-model")
        processor = factory.create_for_main(config, sample_tools)

        assert processor.permission_manager is mock_permission_manager
        assert processor._artifact_service is mock_artifact_service

    def test_forced_skill_config_preserved(
        self,
        factory: ProcessorFactory,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """Forced skill name/tools on config should be preserved."""
        config = ProcessorConfig(model="test-model")
        config.forced_skill_name = "my-skill"
        config.forced_skill_tools = ["tool_a", "tool_b"]

        processor = factory.create_for_main(config, sample_tools)

        assert processor.config.forced_skill_name == "my-skill"
        assert processor.config.forced_skill_tools == ["tool_a", "tool_b"]


# ============================================================================
# RunContext Tests
# ============================================================================


@pytest.mark.unit
class TestRunContext:
    """Tests for RunContext dataclass."""

    def test_default_creation(self) -> None:
        """RunContext should have sane defaults."""
        ctx = RunContext()
        assert ctx.abort_signal is None
        assert ctx.conversation_id is None
        assert ctx.trace_id is None
        assert ctx.start_time > 0

    def test_custom_creation(self) -> None:
        """RunContext should accept custom values."""
        import asyncio

        signal = asyncio.Event()
        ctx = RunContext(
            abort_signal=signal,
            conversation_id="conv-123",
            trace_id="trace-abc",
            start_time=1000.0,
        )
        assert ctx.abort_signal is signal
        assert ctx.conversation_id == "conv-123"
        assert ctx.trace_id == "trace-abc"
        assert ctx.start_time == 1000.0

    def test_mutable(self) -> None:
        """RunContext should be mutable (not frozen)."""
        ctx = RunContext()
        ctx.conversation_id = "updated"
        assert ctx.conversation_id == "updated"
