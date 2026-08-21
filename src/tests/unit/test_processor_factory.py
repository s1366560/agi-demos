"""Unit tests for ProcessorFactory - centralized processor creation.

Tests for:
- ProcessorFactory immutability (frozen dataclass)
- create_for_subagent() model resolution (INHERIT vs explicit)
- create_for_main() shared dep injection
- RunContext dataclass
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.domain.model.agent.subagent import AgentModel, SubAgent
from src.infrastructure.agent.model_route import ModelRouteRef
from src.infrastructure.agent.processor.factory import ProcessorFactory
from src.infrastructure.agent.processor.processor import ProcessorConfig, ToolDefinition
from src.infrastructure.agent.processor.run_context import RunContext
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error

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
        base_provider_id="gemini",
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
        assert f.base_provider_id == ""


# ============================================================================
# create_for_subagent Tests
# ============================================================================


@pytest.mark.unit
class TestCreateForSubagent:
    """Tests for ProcessorFactory.create_for_subagent()."""

    @pytest.fixture(autouse=True)
    def _pin_v2_loop_resolver(self):
        with patch(
            "src.infrastructure.agent.processor.factory._default_loop_resolver",
            return_value=MagicMock(),
        ) as resolver:
            yield resolver

    def test_pinned_v2_loop_resolver_and_provider_are_propagated(
        self,
        inherit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
        _pin_v2_loop_resolver: MagicMock,
    ) -> None:
        factory = ProcessorFactory(
            base_model="gemini-2.0-flash",
            base_provider_id="gemini",
        )

        processor = factory.create_for_subagent(inherit_subagent, sample_tools)

        assert processor.config.loop_resolver is _pin_v2_loop_resolver.return_value
        assert processor.config.provider_id == "gemini"
        _pin_v2_loop_resolver.assert_called_once_with()

    def test_inherit_model_uses_base_model(
        self,
        factory: ProcessorFactory,
        inherit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """SubAgent with INHERIT model should use factory's base_model."""
        processor = factory.create_for_subagent(inherit_subagent, sample_tools)

        assert processor.config.model == "gemini-2.0-flash"

    def test_inherit_model_with_bare_override_fails_closed(
        self,
        factory: ProcessorFactory,
        inherit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """A retry/spawn override cannot inherit the base provider implicitly."""
        with pytest.raises(RuntimeV2Error) as exc_info:
            factory.create_for_subagent(
                inherit_subagent,
                sample_tools,
                model_override="gpt-4o-mini",
            )

        assert exc_info.value.code == "subagent_model_override_route_missing"

    def test_inherit_model_with_structured_override_uses_exact_route(
        self,
        factory: ProcessorFactory,
        inherit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        route = ModelRouteRef(provider_id="openai", model_id="gpt-4o-mini")

        processor = factory.create_for_subagent(
            inherit_subagent,
            sample_tools,
            model_override="gpt-4o-mini",
            model_route_override=route,
        )

        assert processor.config.model == "gpt-4o-mini"
        assert processor.config.provider_id == "openai"

    def test_explicit_model_without_configured_route_fails_closed(
        self,
        factory: ProcessorFactory,
        explicit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        with pytest.raises(RuntimeV2Error) as exc_info:
            factory.create_for_subagent(explicit_subagent, sample_tools)

        assert exc_info.value.code == "subagent_model_route_missing"

    def test_explicit_model_uses_configured_route(
        self,
        factory: ProcessorFactory,
        explicit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        route = ModelRouteRef(provider_id="openai", model_id=AgentModel.GPT4O.value)

        processor = factory.create_for_subagent(
            explicit_subagent,
            sample_tools,
            configured_model_route=route,
        )

        assert processor.config.model == AgentModel.GPT4O.value
        assert processor.config.provider_id == "openai"

    def test_structured_override_model_mismatch_fails_closed(
        self,
        factory: ProcessorFactory,
        inherit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        with pytest.raises(RuntimeV2Error) as exc_info:
            factory.create_for_subagent(
                inherit_subagent,
                sample_tools,
                model_override="gpt-4o-mini",
                model_route_override=ModelRouteRef(
                    provider_id="openai",
                    model_id="gpt-4.1-mini",
                ),
            )

        assert exc_info.value.code == "subagent_model_override_route_mismatch"

    def test_subagent_settings_propagated(
        self,
        factory: ProcessorFactory,
        explicit_subagent: SubAgent,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """SubAgent temperature, max_tokens, max_steps should be propagated."""
        processor = factory.create_for_subagent(
            explicit_subagent,
            sample_tools,
            configured_model_route=ModelRouteRef(
                provider_id="openai",
                model_id=AgentModel.GPT4O.value,
            ),
        )

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

    @pytest.fixture(autouse=True)
    def _pin_v2_loop_resolver(self):
        with patch(
            "src.infrastructure.agent.processor.factory._default_loop_resolver",
            return_value=MagicMock(),
        ) as resolver:
            yield resolver

    def test_stale_caller_resolver_is_replaced_from_pinned_operation(
        self,
        factory: ProcessorFactory,
        sample_tools: list[ToolDefinition],
        _pin_v2_loop_resolver: MagicMock,
    ) -> None:
        stale_resolver = object()
        config = ProcessorConfig(model="custom-model", loop_resolver=stale_resolver)

        processor = factory.create_for_main(config, sample_tools)

        assert processor.config.loop_resolver is _pin_v2_loop_resolver.return_value
        _pin_v2_loop_resolver.assert_called_once_with()

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
            loop_resolver=object(),
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
        config = ProcessorConfig(model="test-model", loop_resolver=object())
        processor = factory.create_for_main(config, sample_tools)

        assert processor.permission_manager is mock_permission_manager
        assert processor._artifact_service is mock_artifact_service

    def test_forced_skill_config_preserved(
        self,
        factory: ProcessorFactory,
        sample_tools: list[ToolDefinition],
    ) -> None:
        """Forced skill name/tools on config should be preserved."""
        config = ProcessorConfig(model="test-model", loop_resolver=object())
        config.forced_skill_name = "my-skill"
        config.forced_skill_tools = ["tool_a", "tool_b"]

        processor = factory.create_for_main(config, sample_tools)

        assert processor.config.forced_skill_name == "my-skill"
        assert processor.config.forced_skill_tools == ["tool_a", "tool_b"]

    def test_react_agent_propagates_provider_to_subagent_factory(self) -> None:
        from src.infrastructure.agent.core.react_agent import ReActAgent

        agent = ReActAgent(
            model="test-model",
            tools={},
            provider_id="test-provider",
        )

        assert agent._processor_factory.base_provider_id == "test-provider"


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
