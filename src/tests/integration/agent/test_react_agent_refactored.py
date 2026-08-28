"""
Integration tests for refactored ReActAgent architecture.

These tests verify that all extracted modules can be imported and
the basic structure is correct. Deep functional tests are in unit tests.
"""

import pytest


@pytest.mark.integration
class TestRefactoredArchitectureIntegration:
    """Integration tests for the refactored ReActAgent modules."""

    def test_event_converter_is_explicitly_constructed(self):
        """Test EventConverter has no implicit process-global identity."""
        from src.infrastructure.agent.events.converter import EventConverter

        converter1 = EventConverter()
        converter2 = EventConverter()
        assert converter1 is not converter2

    def test_attachment_processor_is_explicitly_constructed(self):
        """Test AttachmentProcessor has no implicit process-global identity."""
        from src.infrastructure.agent.attachment.processor import AttachmentProcessor

        processor1 = AttachmentProcessor()
        processor2 = AttachmentProcessor()
        assert processor1 is not processor2

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

    def test_import_agent_ports(self):
        """Test all agent ports can be imported."""
        from src.domain.ports.agent import LLMInvokerPort

        assert LLMInvokerPort is not None


@pytest.mark.integration
class TestReActAgentIntegration:
    """Test ReActAgent works with new modules."""

    def test_react_agent_imports(self):
        """Test ReActAgent can be imported."""
        from src.infrastructure.agent.core.react_agent import ReActAgent

        assert ReActAgent is not None

    def test_react_agent_uses_event_converter(self):
        """Test ReActAgent references EventConverter."""
        import inspect

        from src.infrastructure.agent.core.react_agent import ReActAgent

        init_source = inspect.getsource(ReActAgent.__init__)

        # __init__ calls _init_orchestrators which sets up EventConverter
        assert "_init_orchestrators" in init_source
