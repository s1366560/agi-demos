"""
Unit tests for ProjectReActAgent WebSocketNotifier integration.

Tests TDD: RED phase - These tests should fail before implementation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
import pytest

from src.infrastructure.agent.core.project_react_agent import (
    ProjectAgentConfig,
    ProjectReActAgent,
)
from src.infrastructure.adapters.secondary.websocket_notifier import (
    WebSocketNotifier,
    LifecycleState,
)

# The correct import path for patching is where the module imports these functions
# For functions imported inside initialize(), we need to patch the full path
TEMPORAL_IMPORTS = "src.infrastructure.adapters.secondary.temporal.agent_worker_state"


class MockConnectionManager:
    """Mock ConnectionManager for testing."""

    def __init__(self):
        self.broadcast_calls = []

    async def broadcast_to_project(
        self, tenant_id: str, project_id: str, message: dict
    ) -> int:
        """Mock broadcast that records calls."""
        self.broadcast_calls.append({
            "tenant_id": tenant_id,
            "project_id": project_id,
            "message": message,
        })
        return 1


@pytest.fixture
def mock_manager():
    """Fixture for mock connection manager."""
    return MockConnectionManager()


@pytest.fixture
def mock_notifier(mock_manager):
    """Fixture for mock WebSocketNotifier."""
    return WebSocketNotifier(mock_manager)


@pytest.fixture
def agent_config():
    """Fixture for test agent config."""
    return ProjectAgentConfig(
        tenant_id="test-tenant",
        project_id="test-project",
        agent_mode="default",
        max_concurrent_chats=10,
    )


@pytest.fixture
def mock_graph_service():
    """Fixture for mock graph service."""
    return MagicMock()


@pytest.fixture
def mock_redis_client():
    """Fixture for mock redis client."""
    return AsyncMock()


@pytest.fixture
def mock_llm_client():
    """Fixture for mock LLM client."""
    return MagicMock()


@pytest.fixture
def mock_provider_config():
    """Fixture for mock provider config."""
    config = MagicMock()
    config.llm_model = "test-model"
    config.base_url = "http://test"
    return config


@pytest.fixture
def mock_session_context():
    """Fixture for mock session context."""
    ctx = MagicMock()
    ctx.tool_definitions = {}
    ctx.system_prompt_manager = MagicMock()
    ctx.subagent_router = MagicMock()
    return ctx


class TestProjectReActAgentLifecycleNotifications:
    """
    Test suite for ProjectReActAgent lifecycle WebSocket notifications.

    Tests that lifecycle state changes are properly broadcast via WebSocket.
    """

    @pytest.mark.asyncio
    async def test_initialize_sends_initializing_and_ready_notifications(
        self,
        agent_config,
        mock_notifier,
        mock_graph_service,
        mock_redis_client,
        mock_llm_client,
        mock_provider_config,
        mock_session_context,
    ):
        """
        Test that initialize() sends 'initializing' then 'ready' notifications.

        Expected behavior:
        1. When initialize() starts, sends 'initializing' state
        2. When initialize() completes successfully, sends 'ready' state with tool counts
        """
        agent = ProjectReActAgent(agent_config)

        mock_tools = {"test_tool": lambda x: x}
        mock_skills = [MagicMock(name="skill1")]
        mock_subagents = []

        # Patch all the dependencies imported in initialize()
        # Note: Must use the full import path since they're imported inside the method
        with patch(
            f"{TEMPORAL_IMPORTS}.get_agent_graph_service",
            return_value=mock_graph_service,
        ):
            with patch(
                f"{TEMPORAL_IMPORTS}.get_redis_client",
                return_value=mock_redis_client,
            ):
                with patch(
                    f"{TEMPORAL_IMPORTS}.get_or_create_provider_config",
                    new_callable=AsyncMock,
                    return_value=mock_provider_config,
                ):
                    with patch(
                        f"{TEMPORAL_IMPORTS}.get_or_create_llm_client",
                        new_callable=AsyncMock,
                        return_value=mock_llm_client,
                    ):
                        with patch(
                            f"{TEMPORAL_IMPORTS}.get_or_create_tools",
                            new_callable=AsyncMock,
                            return_value=mock_tools,
                        ):
                            with patch(
                                f"{TEMPORAL_IMPORTS}.get_or_create_skills",
                                new_callable=AsyncMock,
                                return_value=mock_skills,
                            ):
                                with patch.object(
                                    agent,
                                    "_load_subagents",
                                    new_callable=AsyncMock,
                                    return_value=mock_subagents,
                                ):
                                    with patch(
                                        f"{TEMPORAL_IMPORTS}.get_or_create_agent_session",
                                        new_callable=AsyncMock,
                                        return_value=mock_session_context,
                                    ):
                                        with patch(
                                            "src.infrastructure.agent.core.react_agent.ReActAgent",
                                        ):
                                            # Inject the mock notifier
                                            with patch(
                                                "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
                                                return_value=mock_notifier,
                                            ):
                                                await agent.initialize()

        # Verify broadcast calls
        calls = mock_notifier._manager.broadcast_calls
        assert len(calls) == 2, f"Expected 2 calls, got {len(calls)}"

        # First call should be 'initializing'
        assert calls[0]["tenant_id"] == "test-tenant"
        assert calls[0]["project_id"] == "test-project"
        assert calls[0]["message"]["type"] == "lifecycle_state_change"
        assert calls[0]["message"]["data"]["lifecycle_state"] == "initializing"

        # Second call should be 'ready'
        assert calls[1]["message"]["data"]["lifecycle_state"] == "ready"
        assert calls[1]["message"]["data"]["is_initialized"] is True
        assert calls[1]["message"]["data"]["tool_count"] == 1

    @pytest.mark.asyncio
    async def test_initialize_failure_sends_error_notification(
        self,
        agent_config,
        mock_notifier,
        mock_graph_service,
    ):
        """
        Test that initialization failure sends 'error' notification.

        Expected behavior:
        1. When initialize() fails, sends 'error' state with error message
        """
        agent = ProjectReActAgent(agent_config)

        # Patch get_agent_graph_service to raise an error
        with patch(
            f"{TEMPORAL_IMPORTS}.get_agent_graph_service",
            return_value=None,
        ):
            # Inject the mock notifier
            with patch(
                "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
                return_value=mock_notifier,
            ):
                result = await agent.initialize()

        # Verify initialization failed
        assert result is False

        # Verify error notification was sent
        calls = mock_notifier._manager.broadcast_calls
        error_calls = [
            c
            for c in calls
            if c["message"].get("data", {}).get("lifecycle_state") == "error"
        ]
        assert len(error_calls) >= 1
        assert "error_message" in error_calls[0]["message"]["data"]

    @pytest.mark.asyncio
    async def test_pause_sends_paused_notification(
        self, agent_config, mock_notifier
    ):
        """
        Test that pause() sends 'paused' notification.

        Expected behavior:
        1. When pause() is called, sends 'paused' state
        """
        agent = ProjectReActAgent(agent_config)
        agent._initialized = True

        # Inject the mock notifier
        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=mock_notifier,
        ):
            await agent.pause()

        # Verify paused notification
        calls = mock_notifier._manager.broadcast_calls
        assert len(calls) >= 1
        assert calls[0]["message"]["data"]["lifecycle_state"] == "paused"
        assert calls[0]["message"]["data"]["is_active"] is False

    @pytest.mark.asyncio
    async def test_resume_sends_ready_notification(
        self, agent_config, mock_notifier
    ):
        """
        Test that resume() sends 'ready' notification.

        Expected behavior:
        1. When resume() is called, sends 'ready' state
        """
        agent = ProjectReActAgent(agent_config)
        agent._initialized = True

        # Inject the mock notifier
        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=mock_notifier,
        ):
            await agent.resume()

        # Verify ready notification
        calls = mock_notifier._manager.broadcast_calls
        assert len(calls) >= 1
        assert calls[0]["message"]["data"]["lifecycle_state"] == "ready"
        assert calls[0]["message"]["data"]["is_active"] is True

    @pytest.mark.asyncio
    async def test_stop_sends_shutting_down_notification(
        self, agent_config, mock_notifier
    ):
        """
        Test that stop() sends 'shutting_down' notification.

        Expected behavior:
        1. When stop() is called, sends 'shutting_down' state
        """
        agent = ProjectReActAgent(agent_config)
        agent._initialized = True

        # Inject the mock notifier
        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=mock_notifier,
        ):
            await agent.stop()

        # Verify shutting_down notification
        calls = mock_notifier._manager.broadcast_calls
        assert len(calls) >= 1
        assert calls[0]["message"]["data"]["lifecycle_state"] == "shutting_down"
        assert calls[0]["message"]["data"]["is_active"] is False

    @pytest.mark.asyncio
    async def test_execute_chat_sends_executing_notification(
        self, agent_config, mock_notifier
    ):
        """
        Test that execute_chat() sends 'executing' notification.

        Expected behavior:
        1. When execute_chat() starts, sends 'executing' state with conversation_id
        """
        agent = ProjectReActAgent(agent_config)
        agent._initialized = True

        # Mock the react_agent.stream method
        async def mock_stream(**kwargs):
            yield {"type": "start", "data": {}}
            yield {"type": "complete", "data": {"content": "Test response"}}

        mock_react = MagicMock()
        mock_react.stream = mock_stream
        agent._react_agent = mock_react

        # Inject the mock notifier
        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=mock_notifier,
        ):
            events = []
            async for event in agent.execute_chat(
                conversation_id="test-conv",
                user_message="Hello",
                user_id="test-user",
            ):
                events.append(event)

        # Verify broadcast calls
        calls = mock_notifier._manager.broadcast_calls

        # Should have 'executing' notification
        executing_calls = [
            c
            for c in calls
            if c["message"].get("data", {}).get("lifecycle_state") == "executing"
        ]
        assert len(executing_calls) >= 1
        assert (
            executing_calls[0]["message"]["data"]["conversation_id"]
            == "test-conv"
        )

    @pytest.mark.asyncio
    async def test_execute_chat_sends_ready_after_completion(
        self, agent_config, mock_notifier
    ):
        """
        Test that execute_chat() sends 'ready' notification after completion.

        Expected behavior:
        1. When execute_chat() completes successfully, sends 'ready' state
        """
        agent = ProjectReActAgent(agent_config)
        agent._initialized = True

        # Mock the react_agent.stream method
        async def mock_stream(**kwargs):
            yield {"type": "start", "data": {}}
            yield {"type": "complete", "data": {"content": "Test response"}}

        mock_react = MagicMock()
        mock_react.stream = mock_stream
        agent._react_agent = mock_react

        # Inject the mock notifier
        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=mock_notifier,
        ):
            events = []
            async for event in agent.execute_chat(
                conversation_id="test-conv",
                user_message="Hello",
                user_id="test-user",
            ):
                events.append(event)

        # Verify 'ready' notification was sent after completion
        calls = mock_notifier._manager.broadcast_calls
        ready_calls = [
            c
            for c in calls
            if c["message"].get("data", {}).get("lifecycle_state") == "ready"
        ]
        # At least one 'ready' call (after execution completes)
        assert len(ready_calls) >= 1

    @pytest.mark.asyncio
    async def test_execute_chat_error_sends_error_notification(
        self, agent_config, mock_notifier
    ):
        """
        Test that execute_chat() errors send 'error' notification.

        Expected behavior:
        1. When execute_chat() encounters an error, sends 'error' state
        """
        agent = ProjectReActAgent(agent_config)
        agent._initialized = True

        # Mock the react_agent.stream method to raise error
        async def mock_stream_error(**kwargs):
            yield {"type": "start", "data": {}}
            raise RuntimeError("Stream error")

        mock_react = MagicMock()
        mock_react.stream = mock_stream_error
        agent._react_agent = mock_react

        # Inject the mock notifier
        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=mock_notifier,
        ):
            events = []
            async for event in agent.execute_chat(
                conversation_id="test-conv",
                user_message="Hello",
                user_id="test-user",
            ):
                events.append(event)

        # Verify error notification
        calls = mock_notifier._manager.broadcast_calls
        error_calls = [
            c
            for c in calls
            if c["message"].get("data", {}).get("lifecycle_state") == "error"
        ]
        assert len(error_calls) >= 1
        assert "error_message" in error_calls[0]["message"]["data"]


class TestProjectReActAgentNotificationContent:
    """
    Test suite for notification content validation.

    Ensures that notifications contain the correct data fields.
    """

    @pytest.mark.asyncio
    async def test_ready_notification_includes_tool_counts(
        self,
        agent_config,
        mock_notifier,
        mock_graph_service,
        mock_redis_client,
        mock_llm_client,
        mock_provider_config,
        mock_session_context,
    ):
        """
        Test that 'ready' notification includes tool/skill/subagent counts.

        Expected behavior:
        1. Ready notification includes tool_count, skill_count, subagent_count
        """
        agent = ProjectReActAgent(agent_config)

        mock_tools = {"tool1": lambda x: x, "tool2": lambda x: x}
        mock_skills = [MagicMock(name="skill1"), MagicMock(name="skill2")]
        mock_subagents = [MagicMock(name="subagent1")]

        with patch(
            f"{TEMPORAL_IMPORTS}.get_agent_graph_service",
            return_value=mock_graph_service,
        ):
            with patch(
                f"{TEMPORAL_IMPORTS}.get_redis_client",
                return_value=mock_redis_client,
            ):
                with patch(
                    f"{TEMPORAL_IMPORTS}.get_or_create_provider_config",
                    new_callable=AsyncMock,
                    return_value=mock_provider_config,
                ):
                    with patch(
                        f"{TEMPORAL_IMPORTS}.get_or_create_llm_client",
                        new_callable=AsyncMock,
                        return_value=mock_llm_client,
                    ):
                        with patch(
                            f"{TEMPORAL_IMPORTS}.get_or_create_tools",
                            new_callable=AsyncMock,
                            return_value=mock_tools,
                        ):
                            with patch(
                                f"{TEMPORAL_IMPORTS}.get_or_create_skills",
                                new_callable=AsyncMock,
                                return_value=mock_skills,
                            ):
                                with patch.object(
                                    agent,
                                    "_load_subagents",
                                    new_callable=AsyncMock,
                                    return_value=mock_subagents,
                                ):
                                    with patch(
                                        f"{TEMPORAL_IMPORTS}.get_or_create_agent_session",
                                        new_callable=AsyncMock,
                                        return_value=mock_session_context,
                                    ):
                                        with patch(
                                            "src.infrastructure.agent.core.react_agent.ReActAgent",
                                        ):
                                            # Inject the mock notifier
                                            with patch(
                                                "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
                                                return_value=mock_notifier,
                                            ):
                                                await agent.initialize()

        # Find the 'ready' notification
        calls = mock_notifier._manager.broadcast_calls
        ready_call = next(
            (
                c
                for c in calls
                if c["message"].get("data", {}).get("lifecycle_state") == "ready"
            ),
            None,
        )

        assert ready_call is not None
        data = ready_call["message"]["data"]
        assert data["tool_count"] == 2
        assert data["skill_count"] == 2
        assert data["subagent_count"] == 1

    @pytest.mark.asyncio
    async def test_executing_notification_includes_conversation_id(
        self, agent_config, mock_notifier
    ):
        """
        Test that 'executing' notification includes conversation_id.

        Expected behavior:
        1. Executing notification includes the conversation_id being executed
        """
        agent = ProjectReActAgent(agent_config)
        agent._initialized = True

        async def mock_stream(**kwargs):
            yield {"type": "start", "data": {}}

        mock_react = MagicMock()
        mock_react.stream = mock_stream
        agent._react_agent = mock_react

        # Inject the mock notifier
        with patch(
            "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
            return_value=mock_notifier,
        ):
            async for _ in agent.execute_chat(
                conversation_id="conv-12345",
                user_message="Test",
                user_id="user-123",
            ):
                pass

        # Find the 'executing' notification
        calls = mock_notifier._manager.broadcast_calls
        executing_call = next(
            (
                c
                for c in calls
                if c["message"].get("data", {}).get("lifecycle_state") == "executing"
            ),
            None,
        )

        assert executing_call is not None
        assert (
            executing_call["message"]["data"]["conversation_id"] == "conv-12345"
        )

    @pytest.mark.asyncio
    async def test_error_notification_includes_error_message(
        self, agent_config, mock_notifier, mock_graph_service
    ):
        """
        Test that 'error' notification includes error message.

        Expected behavior:
        1. Error notification includes the error_message field
        """
        agent = ProjectReActAgent(agent_config)

        # Mock initialization to raise a specific error
        with patch(
            f"{TEMPORAL_IMPORTS}.get_agent_graph_service",
            return_value=None,
        ):
            # Inject the mock notifier
            with patch(
                "src.infrastructure.agent.core.project_react_agent.get_websocket_notifier",
                return_value=mock_notifier,
            ):
                await agent.initialize()

        # Find the 'error' notification
        calls = mock_notifier._manager.broadcast_calls
        error_call = next(
            (
                c
                for c in calls
                if c["message"].get("data", {}).get("lifecycle_state") == "error"
            ),
            None,
        )

        assert error_call is not None
        assert "error_message" in error_call["message"]["data"]
