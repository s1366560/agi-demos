"""
Unit tests for SkillExecutor with resource injection support.

TDD Approach: Tests written first, then implementation.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.skill import (
    Skill,
    SkillStatus,
    TriggerPattern,
    TriggerType,
)
from src.infrastructure.agent.core.skill_executor import SkillExecutor
from src.infrastructure.agent.skill.skill_resource_injector import SkillResourceInjector
from src.infrastructure.agent.skill.skill_resource_loader import SkillResourceLoader


@pytest.fixture
def mock_sandbox_adapter():
    """Create a mock SandboxPort adapter."""
    adapter = AsyncMock()
    adapter.call_tool.return_value = {
        "content": [{"type": "text", "text": "Success"}],
        "isError": False,
    }
    return adapter


@pytest.fixture
def resource_loader(tmp_path: Path):
    """Create a SkillResourceLoader with temp path."""

    return SkillResourceLoader(tmp_path)


@pytest.fixture
def resource_injector(resource_loader):
    """Create a mock SkillResourceInjector."""
    injector = MagicMock(spec=SkillResourceInjector)
    injector.inject_skill = AsyncMock(return_value={})
    injector.setup_skill_environment = AsyncMock(return_value=True)
    return injector


@pytest.fixture
def mock_tool():
    """Create a mock tool."""
    tool = AsyncMock()
    tool.execute.return_value = "Tool executed successfully"
    return tool


class TestSkillExecutorWithResourceInjection:
    """Tests for SkillExecutor with resource injection capability."""

    def test_init_with_optional_dependencies(self, mock_tool):
        """Test SkillExecutor initialization with optional dependencies."""
        tools = {"bash": mock_tool}

        # Without dependencies
        executor = SkillExecutor(tools=tools)
        assert executor.tools == tools
        assert executor._resource_injector is None
        assert executor._sandbox_adapter is None

    def test_init_with_resource_injector(self, mock_tool, resource_injector, mock_sandbox_adapter):
        """Test SkillResourceInjector initialization with dependencies."""
        tools = {"bash": mock_tool}

        executor = SkillExecutor(
            tools=tools,
            resource_injector=resource_injector,
            sandbox_adapter=mock_sandbox_adapter,
        )

        assert executor.tools == tools
        assert executor._resource_injector == resource_injector
        assert executor._sandbox_adapter == mock_sandbox_adapter

    @pytest.mark.asyncio
    async def test_execute_with_sandbox_id_injects_resources(
        self, mock_tool, resource_injector, mock_sandbox_adapter
    ):
        """Test execute with sandbox_id triggers resource injection."""
        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            project_id="project-1",
            name="test-skill",
            description="Test skill with scripts",
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[TriggerPattern(pattern="test", weight=1.0)],
            tools=["bash"],
            prompt_template="Run scripts/test.sh",
            status=SkillStatus.ACTIVE,
            success_count=0,
            failure_count=0,
            metadata={},
            source="filesystem",
        )

        tools = {"bash": mock_tool}
        executor = SkillExecutor(
            tools=tools,
            resource_injector=resource_injector,
            sandbox_adapter=mock_sandbox_adapter,
        )

        # Collect all events
        events = []
        async for event in executor.execute(skill, "test query", sandbox_id="sandbox-123"):
            events.append(event)

        # Verify inject_skill was called
        resource_injector.inject_skill.assert_called_once_with(
            mock_sandbox_adapter,
            sandbox_id="sandbox-123",
            skill_name="test-skill",
            skill_content=skill.prompt_template,
        )

        # Verify setup_skill_environment was called
        resource_injector.setup_skill_environment.assert_called_once_with(
            mock_sandbox_adapter,
            sandbox_id="sandbox-123",
            skill_name="test-skill",
        )

        # Verify tool was executed
        mock_tool.execute.assert_called_once()

        # Verify events
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_execute_without_sandbox_id_skips_injection(self, mock_tool, resource_injector):
        """Test execute without sandbox_id skips resource injection."""
        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            name="test-skill",
            description="Test skill",
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[],
            tools=["bash"],
            prompt_template="Run command",
            status=SkillStatus.ACTIVE,
        )

        tools = {"bash": mock_tool}
        executor = SkillExecutor(
            tools=tools,
            resource_injector=resource_injector,
            sandbox_adapter=None,  # No adapter
        )

        # Execute without sandbox_id
        events = []
        async for event in executor.execute(skill, "test query"):
            events.append(event)

        # Verify inject_skill was NOT called
        resource_injector.inject_skill.assert_not_called()

        # Verify tool was still executed
        mock_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_without_resource_injector_skips_injection(
        self, mock_tool, mock_sandbox_adapter
    ):
        """Test execute without resource_injector skips injection."""
        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            name="test-skill",
            description="Test skill",
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[],
            tools=["bash"],
            prompt_template="Run command",
            status=SkillStatus.ACTIVE,
        )

        tools = {"bash": mock_tool}
        executor = SkillExecutor(
            tools=tools,
            resource_injector=None,  # No injector
            sandbox_adapter=mock_sandbox_adapter,
        )

        # Execute with sandbox_id but no injector
        events = []
        async for event in executor.execute(skill, "test query", sandbox_id="sandbox-123"):
            events.append(event)

        # Tool should still execute
        mock_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_handles_injection_error_gracefully(
        self, mock_tool, resource_injector, mock_sandbox_adapter
    ):
        """Test execute continues even if resource injection fails."""
        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            name="test-skill",
            description="Test skill",
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[],
            tools=["bash"],
            prompt_template="Run command",
            status=SkillStatus.ACTIVE,
        )

        # Make inject_skill raise an exception
        resource_injector.inject_skill.side_effect = Exception("Injection failed")

        tools = {"bash": mock_tool}
        executor = SkillExecutor(
            tools=tools,
            resource_injector=resource_injector,
            sandbox_adapter=mock_sandbox_adapter,
        )

        # Execute should not raise exception
        events = []
        async for event in executor.execute(skill, "test query", sandbox_id="sandbox-123"):
            events.append(event)

        # Tool should still execute despite injection failure
        mock_tool.execute.assert_called_once()

        # Should have completion event
        from src.domain.events.agent_events import AgentSkillExecutionCompleteEvent

        assert any(isinstance(e, AgentSkillExecutionCompleteEvent) for e in events)
