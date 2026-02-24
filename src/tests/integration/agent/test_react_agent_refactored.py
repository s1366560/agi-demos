"""
Integration tests for refactored ReActAgent architecture.

These tests verify that all extracted modules can be imported and
the basic structure is correct. Deep functional tests are in unit tests.
"""

import pytest


@pytest.mark.integration
class TestRefactoredArchitectureIntegration:
    """Integration tests for the refactored ReActAgent modules."""

    def test_event_converter_singleton(self):
        """Test EventConverter singleton pattern."""
        from src.infrastructure.agent.events.converter import (
            get_event_converter,
        )

        converter1 = get_event_converter()
        converter2 = get_event_converter()
        assert converter1 is converter2

    def test_skill_orchestrator_creation(self):
        """Test SkillOrchestrator can be created."""
        from src.infrastructure.agent.skill.orchestrator import create_skill_orchestrator

        orchestrator = create_skill_orchestrator()
        assert orchestrator is not None
        assert hasattr(orchestrator, "match")

    def test_subagent_orchestrator_creation(self):
        """Test SubAgentOrchestrator can be created."""
        from src.infrastructure.agent.routing.subagent_orchestrator import (
            create_subagent_orchestrator,
        )

        orchestrator = create_subagent_orchestrator()
        assert orchestrator is not None

    def test_attachment_processor_singleton(self):
        """Test AttachmentProcessor singleton pattern."""
        from src.infrastructure.agent.attachment.processor import (
            AttachmentProcessor,
            get_attachment_processor,
        )

        processor = get_attachment_processor()
        assert processor is not None
        assert isinstance(processor, AttachmentProcessor)

    def test_llm_invoker_class_exists(self):
        """Test LLMInvoker class exists with expected structure."""
        from src.infrastructure.agent.llm.invoker import LLMInvoker

        assert hasattr(LLMInvoker, "invoke")
        # Check for async stream method
        assert callable(getattr(LLMInvoker, "invoke", None))

    def test_tool_executor_class_exists(self):
        """Test ToolExecutor class exists with expected structure."""
        from src.infrastructure.agent.tools.executor import ToolExecutor

        assert hasattr(ToolExecutor, "execute")

    def test_hitl_strategies_exist(self):
        """Test HITL strategy classes exist."""
        from src.infrastructure.agent.hitl.hitl_strategies import (
            ClarificationStrategy,
            DecisionStrategy,
        )

        assert ClarificationStrategy is not None
        assert DecisionStrategy is not None

    def test_artifact_extractor_singleton(self):
        """Test ArtifactExtractor singleton pattern."""
        from src.infrastructure.agent.artifact.extractor import (
            ArtifactExtractor,
            get_artifact_extractor,
        )

        extractor = get_artifact_extractor()
        assert extractor is not None
        assert isinstance(extractor, ArtifactExtractor)

    def test_work_plan_generator_singleton(self):
        """Test WorkPlanGenerator singleton pattern."""
        from src.infrastructure.agent.planning.work_plan_generator import (
            WorkPlanGenerator,
            get_work_plan_generator,
        )

        generator = get_work_plan_generator()
        assert generator is not None
        assert isinstance(generator, WorkPlanGenerator)

    def test_react_loop_class_exists(self):
        """Test ReActLoop class exists."""
        from src.infrastructure.agent.core.react_loop import ReActLoop

        assert ReActLoop is not None
        assert hasattr(ReActLoop, "run")


@pytest.mark.integration
class TestDIContainerIntegration:
    """Test DI container properly creates all agent components."""

    def test_di_container_creates_event_converter(self):
        """Test DIContainer.event_converter() works."""
        from src.configuration.di_container import DIContainer

        container = DIContainer()
        converter = container.event_converter()
        assert converter is not None

    def test_di_container_creates_skill_orchestrator(self):
        """Test DIContainer.skill_orchestrator() works."""
        from src.configuration.di_container import DIContainer

        container = DIContainer()
        orchestrator = container.skill_orchestrator()
        assert orchestrator is not None

    def test_di_container_creates_subagent_orchestrator(self):
        """Test DIContainer.subagent_orchestrator() works."""
        from src.configuration.di_container import DIContainer

        container = DIContainer()
        orchestrator = container.subagent_orchestrator()
        assert orchestrator is not None

    def test_di_container_creates_attachment_processor(self):
        """Test DIContainer.attachment_processor() works."""
        from src.configuration.di_container import DIContainer

        container = DIContainer()
        processor = container.attachment_processor()
        assert processor is not None


@pytest.mark.integration
class TestModuleImports:
    """Test all modules can be imported correctly."""

    def test_import_event_converter(self):
        """Test EventConverter module imports."""
        from src.infrastructure.agent.events.converter import (
            EventConverter,
        )

        assert EventConverter is not None

    def test_import_attachment_processor(self):
        """Test AttachmentProcessor module imports."""
        from src.infrastructure.agent.attachment.processor import (
            AttachmentProcessor,
        )

        assert AttachmentProcessor is not None

    def test_import_skill_orchestrator(self):
        """Test SkillOrchestrator module imports."""
        from src.infrastructure.agent.skill.orchestrator import (
            SkillOrchestrator,
        )

        assert SkillOrchestrator is not None

    def test_import_subagent_orchestrator(self):
        """Test SubAgentOrchestrator module imports."""
        from src.infrastructure.agent.routing.subagent_orchestrator import (
            SubAgentOrchestrator,
        )

        assert SubAgentOrchestrator is not None

    def test_import_llm_invoker(self):
        """Test LLMInvoker module imports."""
        from src.infrastructure.agent.llm.invoker import LLMInvoker

        assert LLMInvoker is not None

    def test_import_tool_executor(self):
        """Test ToolExecutor module imports."""
        from src.infrastructure.agent.tools.executor import ToolExecutor

        assert ToolExecutor is not None

    def test_import_hitl_strategies(self):
        """Test HITL strategies module imports."""
        from src.infrastructure.agent.hitl.hitl_strategies import (
            ClarificationStrategy,
        )

        assert ClarificationStrategy is not None

    def test_import_artifact_extractor(self):
        """Test ArtifactExtractor module imports."""
        from src.infrastructure.agent.artifact.extractor import (
            ArtifactExtractor,
        )

        assert ArtifactExtractor is not None

    def test_import_work_plan_generator(self):
        """Test WorkPlanGenerator module imports."""
        from src.infrastructure.agent.planning.work_plan_generator import (
            WorkPlanGenerator,
        )

        assert WorkPlanGenerator is not None

    def test_import_react_loop(self):
        """Test ReActLoop module imports."""
        from src.infrastructure.agent.core.react_loop import ReActLoop

        assert ReActLoop is not None

    def test_import_agent_ports(self):
        """Test all agent ports can be imported."""
        from src.domain.ports.agent import (
            LLMInvokerPort,
            ReActLoopPort,
        )

        assert LLMInvokerPort is not None
        assert ReActLoopPort is not None


@pytest.mark.integration
class TestReActAgentIntegration:
    """Test ReActAgent works with new modules."""

    def test_react_agent_imports(self):
        """Test ReActAgent can be imported."""
        from src.infrastructure.agent.core.react_agent import ReActAgent

        assert ReActAgent is not None

    def test_react_agent_uses_orchestrators(self):
        """Test ReActAgent has orchestrator attributes."""
        # Check class has the expected orchestrator imports in __init__
        import inspect

        from src.infrastructure.agent.core.react_agent import ReActAgent

        init_source = inspect.getsource(ReActAgent.__init__)

        # Verify orchestrators are used
        assert "EventConverter" in init_source or "event_converter" in init_source
        assert "SkillOrchestrator" in init_source or "skill_orchestrator" in init_source
        assert "SubAgentOrchestrator" in init_source or "subagent_orchestrator" in init_source
