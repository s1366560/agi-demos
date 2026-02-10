"""
Integration tests for Plan Mode detection and ReActAgent.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.

This test file ensures that:
1. Simple queries bypass Plan Mode (fast path)
2. Complex queries trigger Plan Mode detection
3. Plan Mode events are properly emitted
4. Plan Mode disabled mode works correctly
5. Error handling and fallback behavior
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.domain.model.agent.skill import Skill, SkillStatus, TriggerPattern, TriggerType
from src.domain.model.agent.subagent import AgentTrigger, SubAgent
from src.infrastructure.agent.core.react_agent import ReActAgent
from src.infrastructure.agent.planning import (
    DetectionResult,
    HybridPlanModeDetector,
)


@pytest.mark.integration
class TestPlanModeDetectionIntegration:
    """Integration tests for Plan Mode detection in ReActAgent."""

    @pytest.fixture
    def mock_tools(self):
        """Mock tools for ReActAgent."""
        tools = {}
        memory_search = Mock()
        memory_search.description = "Search memory for information"
        memory_search.get_parameters_schema = Mock(
            return_value={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        )
        memory_search.execute = AsyncMock(return_value="Search results")
        tools["memory_search"] = memory_search
        return tools

    @pytest.fixture
    def simple_detector(self):
        """Create a detector that always returns false (disabled mode)."""
        detector = Mock(spec=HybridPlanModeDetector)
        detector.detect = AsyncMock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.0,
                method="disabled",
            )
        )
        detector.enabled = False
        return detector

    @pytest.mark.asyncio
    @patch("src.infrastructure.agent.processor.processor.LLMStream")
    async def test_simple_query_bypasses_plan_mode(
        self, mock_llm_stream, mock_tools, simple_detector
    ):
        """Test that simple queries bypass Plan Mode entirely."""
        mock_stream_instance = AsyncMock()
        mock_stream_instance.generate = AsyncMock()
        mock_llm_stream.return_value = mock_stream_instance

        agent = ReActAgent(
            model="gpt-4",
            tools=mock_tools,
            api_key="test-key",
            plan_mode_detector=simple_detector,
        )

        events = []
        async for event in agent.stream(
            conversation_id="conv-1",
            user_message="hello",
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_context=[],
        ):
            events.append(event)
            if len(events) >= 3:
                break

        # Should have plan_mode_triggered event with disabled method
        plan_mode_events = [e for e in events if e.get("type") == "plan_mode_triggered"]
        assert len(plan_mode_events) == 1
        assert plan_mode_events[0]["data"]["method"] == "disabled"
        assert plan_mode_events[0]["data"]["should_trigger"] is False

    @pytest.mark.asyncio
    @patch("src.infrastructure.agent.processor.processor.LLMStream")
    async def test_detector_none_graceful_handling(
        self, mock_llm_stream, mock_tools
    ):
        """Test that agent handles None detector gracefully."""
        mock_stream_instance = AsyncMock()
        mock_stream_instance.generate = AsyncMock()
        mock_llm_stream.return_value = mock_stream_instance

        agent = ReActAgent(
            model="gpt-4",
            tools=mock_tools,
            api_key="test-key",
            plan_mode_detector=None,
        )

        events = []
        async for event in agent.stream(
            conversation_id="conv-1",
            user_message="hello",
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_context=[],
        ):
            events.append(event)
            if len(events) >= 3:
                break

        # Should have some events (not erroring out)
        assert len(events) > 0


@pytest.mark.integration
class TestPlanModeEventFlow:
    """Integration tests for Plan Mode event flow."""

    @pytest.fixture
    def mock_tools(self):
        """Mock tools."""
        tool = Mock()
        tool.description = "Test tool"
        tool.get_parameters_schema = Mock(
            return_value={"type": "object", "properties": {}}
        )
        tool.execute = AsyncMock(return_value="Result")
        return {"test_tool": tool}

    @pytest.mark.asyncio
    @patch("src.infrastructure.agent.processor.processor.LLMStream")
    async def test_plan_mode_event_structure(
        self, mock_llm_stream, mock_tools
    ):
        """Test that plan_mode_triggered event has correct structure."""
        detector = Mock(spec=HybridPlanModeDetector)
        detector.detect = AsyncMock(
            return_value=DetectionResult(
                should_trigger=True,
                confidence=0.85,
                method="heuristic",
            )
        )

        agent = ReActAgent(
            model="gpt-4",
            tools=mock_tools,
            api_key="test-key",
            plan_mode_detector=detector,
        )

        events = []
        async for event in agent.stream(
            conversation_id="conv-1",
            user_message="test query",
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_context=[],
        ):
            events.append(event)
            if len(events) >= 5:
                break

        # Find plan_mode_triggered event
        plan_mode_events = [e for e in events if e.get("type") == "plan_mode_triggered"]

        for event in plan_mode_events:
            assert "type" in event
            assert event["type"] == "plan_mode_triggered"
            assert "data" in event
            assert "method" in event["data"]
            assert "confidence" in event["data"]
            assert isinstance(event["data"]["confidence"], (int, float))
            assert 0.0 <= event["data"]["confidence"] <= 1.0
            assert "timestamp" in event

    @pytest.mark.asyncio
    @patch("src.infrastructure.agent.processor.processor.LLMStream")
    async def test_conversation_context_passed_to_detector(
        self, mock_llm_stream, mock_tools
    ):
        """Test that conversation context is passed to detector."""
        detector = Mock(spec=HybridPlanModeDetector)
        detector.detect = AsyncMock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.0,
                method="heuristic",
            )
        )

        agent = ReActAgent(
            model="gpt-4",
            tools=mock_tools,
            api_key="test-key",
            plan_mode_detector=detector,
        )

        conversation_context = [
            {"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"},
        ]

        async for event in agent.stream(
            conversation_id="conv-1",
            user_message="new question",
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_context=conversation_context,
        ):
            if event.get("type") == "plan_mode_triggered":
                break

        # Verify detector was called
        assert detector.detect.called


@pytest.mark.integration
class TestPlanModeWithSkillsAndSubagents:
    """Integration tests for Plan Mode with Skills and SubAgents."""

    @pytest.fixture
    def mock_tools(self):
        """Mock tools."""
        tool = Mock()
        tool.description = "Test tool"
        tool.get_parameters_schema = Mock(
            return_value={"type": "object", "properties": {}}
        )
        tool.execute = AsyncMock(return_value="Result")
        return {"test_tool": tool}

    @pytest.mark.asyncio
    @patch("src.infrastructure.agent.processor.processor.LLMStream")
    async def test_plan_mode_with_matched_skill(
        self, mock_llm_stream, mock_tools
    ):
        """Test Plan Mode behavior when a skill is matched."""
        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            name="test-skill",
            description="A test skill",
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[TriggerPattern(pattern="test")],
            tools=["test_tool"],
            status=SkillStatus.ACTIVE,
        )

        detector = Mock(spec=HybridPlanModeDetector)
        detector.detect = AsyncMock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.0,
                method="heuristic",
            )
        )

        agent = ReActAgent(
            model="gpt-4",
            tools=mock_tools,
            api_key="test-key",
            skills=[skill],
            plan_mode_detector=detector,
        )

        events = []
        async for event in agent.stream(
            conversation_id="conv-1",
            user_message="test",
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_context=[],
        ):
            events.append(event)
            if len(events) >= 3:
                break

        # Detector should still be checked
        assert detector.detect.called

    @pytest.mark.asyncio
    @patch("src.infrastructure.agent.processor.processor.LLMStream")
    async def test_plan_mode_with_subagent(
        self, mock_llm_stream, mock_tools
    ):
        """Test Plan Mode behavior when a subagent is routed."""
        subagent = SubAgent(
            id="subagent-1",
            tenant_id="tenant-1",
            name="test-subagent",
            display_name="Test SubAgent",
            system_prompt="You are a helpful assistant.",
            trigger=AgentTrigger(
                description="A test subagent",
                keywords=["test"],
            ),
        )

        detector = Mock(spec=HybridPlanModeDetector)
        detector.detect = AsyncMock(
            return_value=DetectionResult(
                should_trigger=False,
                confidence=0.0,
                method="heuristic",
            )
        )

        agent = ReActAgent(
            model="gpt-4",
            tools=mock_tools,
            api_key="test-key",
            subagents=[subagent],
            plan_mode_detector=detector,
        )

        events = []
        async for event in agent.stream(
            conversation_id="conv-1",
            user_message="test",
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_context=[],
        ):
            events.append(event)
            if len(events) >= 3:
                break

        # Detector should still be checked
        assert detector.detect.called


@pytest.mark.integration
class TestPlanModeErrorHandling:
    """Integration tests for Plan Mode error handling."""

    @pytest.fixture
    def mock_tools(self):
        """Mock tools."""
        tool = Mock()
        tool.description = "Test tool"
        tool.get_parameters_schema = Mock(
            return_value={"type": "object", "properties": {}}
        )
        tool.execute = AsyncMock(return_value="Result")
        return {"test_tool": tool}

    @pytest.mark.asyncio
    @patch("src.infrastructure.agent.processor.processor.LLMStream")
    async def test_detector_exception_fallback(
        self, mock_llm_stream, mock_tools
    ):
        """Test that detector exceptions fall back to regular ReAct."""
        detector = Mock(spec=HybridPlanModeDetector)
        detector.detect = AsyncMock(side_effect=Exception("Detector error"))

        agent = ReActAgent(
            model="gpt-4",
            tools=mock_tools,
            api_key="test-key",
            plan_mode_detector=detector,
        )

        events = []
        async for event in agent.stream(
            conversation_id="conv-1",
            user_message="test",
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_context=[],
        ):
            events.append(event)
            if len(events) >= 3:
                break

        # Should have plan_mode_failed event
        failed_events = [e for e in events if e.get("type") == "plan_mode_failed"]
        assert len(failed_events) == 1
        assert failed_events[0]["data"]["fallback"] == "react"

    @pytest.mark.asyncio
    @patch("src.infrastructure.agent.processor.processor.LLMStream")
    async def test_detector_times_out_gracefully(
        self, mock_llm_stream, mock_tools
    ):
        """Test that detector timeout falls back gracefully."""
        import asyncio

        detector = Mock(spec=HybridPlanModeDetector)
        detector.detect = AsyncMock(side_effect=asyncio.TimeoutError("Timeout"))

        agent = ReActAgent(
            model="gpt-4",
            tools=mock_tools,
            api_key="test-key",
            plan_mode_detector=detector,
        )

        events = []
        async for event in agent.stream(
            conversation_id="conv-1",
            user_message="test",
            project_id="proj-1",
            user_id="user-1",
            tenant_id="tenant-1",
            conversation_context=[],
        ):
            events.append(event)
            if len(events) >= 3:
                break

        # Should have completed despite detector timeout
        assert len(events) > 0
