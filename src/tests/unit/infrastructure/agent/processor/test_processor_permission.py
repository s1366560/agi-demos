"""Unit tests for SessionProcessor permission handling via HITLCoordinator.

Tests that the processor uses HITLCoordinator for permission requests,
enabling proper response routing through the global coordinator registry.

TDD Task: Fix Sandbox Bash tool permission timeout issue

Root Cause:
  processor.py uses PermissionManager.ask() which creates isolated asyncio.Event
  that is NOT registered in HITLCoordinator's global registry. User responses
  cannot reach the waiting code, causing 5-minute timeouts.

Fix:
  Permission requests should use HITLCoordinator.prepare_request() and
  wait_for_response() so responses are routed via resolve_by_request_id().
"""

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.agent.hitl_types import HITLType
from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.permission.rules import PermissionAction, PermissionRule
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.permission.manager import PermissionManager


async def async_execute(name: str, **kwargs) -> str:
    """Async execute helper."""
    return f"Executed {name}"


def create_tool_def(
    name: str,
    description: str = "Test tool",
    permission: str = None,
) -> ToolDefinition:
    """Helper to create a ToolDefinition."""
    return ToolDefinition(
        name=name,
        description=description,
        parameters={"type": "object", "properties": {}, "required": []},
        execute=lambda **kwargs: async_execute(name, **kwargs),
        permission=permission,
    )


def create_ask_permission_manager(permission_type: str = "bash") -> PermissionManager:
    """Create a PermissionManager with ASK rule for the given permission type."""
    return PermissionManager(ruleset=[
        PermissionRule(permission_type, "*", PermissionAction.ASK)
    ])


@pytest.mark.unit
class TestProcessorPermissionUsesHITLCoordinator:
    """Tests that permission requests use HITLCoordinator for proper routing."""

    @pytest.mark.asyncio
    async def test_permission_ask_uses_hitl_coordinator_prepare_request(self):
        """Should use HITLCoordinator.prepare_request for permission ASK actions."""
        config = ProcessorConfig(model="test-model")
        permission_manager = create_ask_permission_manager("bash")

        processor = SessionProcessor(
            config=config,
            tools=[create_tool_def("bash_tool", permission="bash")],
            permission_manager=permission_manager,
        )

        processor._langfuse_context = {
            "conversation_id": "conv-123",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "message_id": "msg-1",
        }

        processor._pending_tool_calls["call-1"] = ToolPart(
            call_id="call-1",
            tool="bash_tool",
            input={"command": "ls"},
            status=ToolState.RUNNING,
        )

        # Create mock coordinator with spec to ensure proper attribute access
        mock_coordinator = MagicMock(spec=["conversation_id", "prepare_request", "wait_for_response"])
        mock_coordinator.conversation_id = "conv-123"
        mock_coordinator.prepare_request = AsyncMock(return_value="perm_test123")
        mock_coordinator.wait_for_response = AsyncMock(return_value=True)

        # Set coordinator BEFORE the test so _get_hitl_coordinator returns it
        processor._hitl_coordinator = mock_coordinator

        events = []
        async for event in processor._execute_tool(
            session_id="session-1",
            call_id="call-1",
            tool_name="bash_tool",
            arguments={"command": "ls"},
        ):
            events.append(event)

        # Verify HITLCoordinator.prepare_request was called with PERMISSION type
        mock_coordinator.prepare_request.assert_called_once()
        call_args = mock_coordinator.prepare_request.call_args
        # Arguments are passed as keyword args, not positional
        assert call_args.kwargs.get("hitl_type") == HITLType.PERMISSION

    @pytest.mark.asyncio
    async def test_permission_ask_uses_hitl_coordinator_wait_for_response(self):
        """Should use HITLCoordinator.wait_for_response to await user response."""
        config = ProcessorConfig(model="test-model")
        permission_manager = create_ask_permission_manager("bash")

        processor = SessionProcessor(
            config=config,
            tools=[create_tool_def("bash_tool", permission="bash")],
            permission_manager=permission_manager,
        )

        processor._langfuse_context = {
            "conversation_id": "conv-456",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        }

        processor._pending_tool_calls["call-2"] = ToolPart(
            call_id="call-2",
            tool="bash_tool",
            input={"command": "rm -rf /"},
            status=ToolState.RUNNING,
        )

        # Create mock coordinator with spec to ensure proper attribute access
        mock_coordinator = MagicMock(spec=["conversation_id", "prepare_request", "wait_for_response"])
        mock_coordinator.conversation_id = "conv-456"
        mock_coordinator.prepare_request = AsyncMock(return_value="perm_test456")
        mock_coordinator.wait_for_response = AsyncMock(return_value=True)

        # Set coordinator BEFORE the test so _get_hitl_coordinator returns it
        processor._hitl_coordinator = mock_coordinator

        async for _ in processor._execute_tool(
            session_id="session-2",
            call_id="call-2",
            tool_name="bash_tool",
            arguments={"command": "rm -rf /"},
        ):
            pass

        # Verify wait_for_response was called
        mock_coordinator.wait_for_response.assert_called_once()
        call_args = mock_coordinator.wait_for_response.call_args
        assert call_args.kwargs.get("request_id") == "perm_test456"
        assert call_args.kwargs.get("hitl_type") == HITLType.PERMISSION

    @pytest.mark.asyncio
    async def test_permission_response_routes_via_global_registry(self):
        """Permission responses should be resolvable via resolve_by_request_id."""
        from src.infrastructure.agent.hitl.coordinator import (
            resolve_by_request_id,
        )

        config = ProcessorConfig(model="test-model")
        permission_manager = create_ask_permission_manager("bash")

        processor = SessionProcessor(
            config=config,
            tools=[create_tool_def("bash_tool", permission="bash")],
            permission_manager=permission_manager,
        )

        processor._langfuse_context = {
            "conversation_id": "conv-789",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        }

        processor._pending_tool_calls["call-3"] = ToolPart(
            call_id="call-3",
            tool="bash_tool",
            input={"command": "echo test"},
            status=ToolState.RUNNING,
        )

        from src.infrastructure.agent.hitl.coordinator import HITLCoordinator

        coordinator = HITLCoordinator(
            conversation_id="conv-789",
            tenant_id="tenant-1",
            project_id="project-1",
        )
        processor._hitl_coordinator = coordinator

        with patch(
            "src.infrastructure.agent.hitl.coordinator._persist_hitl_request",
            new_callable=AsyncMock,
        ):
            execution_task = asyncio.create_task(
                processor._execute_tool(
                    session_id="session-3",
                    call_id="call-3",
                    tool_name="bash_tool",
                    arguments={"command": "echo test"},
                ).__anext__()
            )

            await asyncio.sleep(0.1)

            assert coordinator.pending_count == 1
            request_id = coordinator.pending_request_ids[0]

            resolved = resolve_by_request_id(
                request_id,
                {"action": "allow", "remember": False},
            )

            assert resolved is True

            try:
                await execution_task
            except StopAsyncIteration:
                pass

    @pytest.mark.asyncio
    async def test_permission_denied_when_user_responds_deny(self):
        """Should deny tool execution when user responds with deny."""
        config = ProcessorConfig(model="test-model")
        permission_manager = create_ask_permission_manager("bash")

        processor = SessionProcessor(
            config=config,
            tools=[create_tool_def("bash_tool", permission="bash")],
            permission_manager=permission_manager,
        )

        processor._langfuse_context = {
            "conversation_id": "conv-deny",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        }

        processor._pending_tool_calls["call-deny"] = ToolPart(
            call_id="call-deny",
            tool="bash_tool",
            input={"command": "dangerous"},
            status=ToolState.RUNNING,
        )

        mock_coordinator = MagicMock()
        mock_coordinator.conversation_id = "conv-deny"
        mock_coordinator.prepare_request = AsyncMock(return_value="perm_deny")
        mock_coordinator.wait_for_response = AsyncMock(return_value=False)

        processor._hitl_coordinator = mock_coordinator

        events = []
        async for event in processor._execute_tool(
            session_id="session-deny",
            call_id="call-deny",
            tool_name="bash_tool",
            arguments={"command": "dangerous"},
        ):
            events.append(event)

        from src.domain.events.agent_events import AgentObserveEvent

        error_events = [e for e in events if isinstance(e, AgentObserveEvent) and e.error]
        assert len(error_events) == 1
        assert "rejected" in error_events[0].error.lower()

    @pytest.mark.asyncio
    async def test_permission_timeout_returns_default_deny(self):
        """Should deny permission on timeout (safe default)."""
        config = ProcessorConfig(model="test-model", permission_timeout=0.1)
        permission_manager = create_ask_permission_manager("bash")

        processor = SessionProcessor(
            config=config,
            tools=[create_tool_def("bash_tool", permission="bash")],
            permission_manager=permission_manager,
        )

        processor._langfuse_context = {
            "conversation_id": "conv-timeout",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        }

        processor._pending_tool_calls["call-timeout"] = ToolPart(
            call_id="call-timeout",
            tool="bash_tool",
            input={"command": "test"},
            status=ToolState.RUNNING,
        )

        mock_coordinator = MagicMock()
        mock_coordinator.conversation_id = "conv-timeout"
        mock_coordinator.prepare_request = AsyncMock(return_value="perm_timeout")
        mock_coordinator.wait_for_response = AsyncMock(
            side_effect=asyncio.TimeoutError("Permission timeout")
        )

        processor._hitl_coordinator = mock_coordinator

        events = []
        async for event in processor._execute_tool(
            session_id="session-timeout",
            call_id="call-timeout",
            tool_name="bash_tool",
            arguments={"command": "test"},
        ):
            events.append(event)

        from src.domain.events.agent_events import AgentObserveEvent

        error_events = [e for e in events if isinstance(e, AgentObserveEvent) and e.error]
        assert len(error_events) == 1
        assert "timed out" in error_events[0].error.lower()


@pytest.mark.unit
class TestProcessorPermissionBackwardCompatibility:
    """Tests for backward compatibility during migration."""

    @pytest.mark.asyncio
    async def test_permission_allow_without_ask_continues_normally(self):
        """Should execute tool without HITL when permission rule is ALLOW."""
        config = ProcessorConfig(model="test-model")
        permission_manager = PermissionManager(ruleset=[
            PermissionRule("read", "*", PermissionAction.ALLOW)
        ])

        processor = SessionProcessor(
            config=config,
            tools=[create_tool_def("read_tool", permission="read")],
            permission_manager=permission_manager,
        )

        processor._langfuse_context = {
            "conversation_id": "conv-allow",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        }

        processor._pending_tool_calls["call-allow"] = ToolPart(
            call_id="call-allow",
            tool="read_tool",
            input={},
            status=ToolState.RUNNING,
        )

        mock_coordinator = MagicMock()
        processor._hitl_coordinator = mock_coordinator

        events = []
        async for event in processor._execute_tool(
            session_id="session-allow",
            call_id="call-allow",
            tool_name="read_tool",
            arguments={},
        ):
            events.append(event)

        mock_coordinator.prepare_request.assert_not_called()
        mock_coordinator.wait_for_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_permission_deny_without_ask_errors_immediately(self):
        """Should error immediately when permission rule is DENY."""
        config = ProcessorConfig(model="test-model")
        permission_manager = PermissionManager(ruleset=[
            PermissionRule("dangerous", "*", PermissionAction.DENY)
        ])

        processor = SessionProcessor(
            config=config,
            tools=[create_tool_def("dangerous_tool", permission="dangerous")],
            permission_manager=permission_manager,
        )

        processor._langfuse_context = {
            "conversation_id": "conv-deny-rule",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        }

        processor._pending_tool_calls["call-deny-rule"] = ToolPart(
            call_id="call-deny-rule",
            tool="dangerous_tool",
            input={},
            status=ToolState.RUNNING,
        )

        mock_coordinator = MagicMock()
        processor._hitl_coordinator = mock_coordinator

        events = []
        async for event in processor._execute_tool(
            session_id="session-deny-rule",
            call_id="call-deny-rule",
            tool_name="dangerous_tool",
            arguments={},
        ):
            events.append(event)

        from src.domain.events.agent_events import AgentObserveEvent

        error_events = [e for e in events if isinstance(e, AgentObserveEvent) and e.error]
        assert len(error_events) == 1
        assert "denied" in error_events[0].error.lower()

        mock_coordinator.prepare_request.assert_not_called()
        mock_coordinator.wait_for_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_hitl_coordinator_falls_back_gracefully(self):
        """Should handle missing HITLCoordinator gracefully (edge case)."""
        config = ProcessorConfig(model="test-model")
        permission_manager = create_ask_permission_manager("bash")

        processor = SessionProcessor(
            config=config,
            tools=[create_tool_def("bash_tool", permission="bash")],
            permission_manager=permission_manager,
        )

        processor._langfuse_context = None
        processor._hitl_coordinator = None

        processor._pending_tool_calls["call-no-coord"] = ToolPart(
            call_id="call-no-coord",
            tool="bash_tool",
            input={"command": "test"},
            status=ToolState.RUNNING,
        )

        events = []
        async for event in processor._execute_tool(
            session_id="session-no-coord",
            call_id="call-no-coord",
            tool_name="bash_tool",
            arguments={"command": "test"},
        ):
            events.append(event)

        assert len(events) > 0


@pytest.mark.unit
class TestProcessorPermissionEventData:
    """Tests for permission event data structure."""

    @pytest.mark.asyncio
    async def test_permission_event_includes_tool_name_and_input(self):
        """Permission asked event should include tool context."""
        config = ProcessorConfig(model="test-model")
        permission_manager = create_ask_permission_manager("bash")

        processor = SessionProcessor(
            config=config,
            tools=[create_tool_def("bash_tool", permission="bash")],
            permission_manager=permission_manager,
        )

        processor._langfuse_context = {
            "conversation_id": "conv-event",
            "tenant_id": "tenant-1",
            "project_id": "project-1",
        }

        processor._pending_tool_calls["call-event"] = ToolPart(
            call_id="call-event",
            tool="bash_tool",
            input={"command": "ls -la"},
            status=ToolState.RUNNING,
        )

        # Create mock coordinator with spec to ensure proper attribute access
        mock_coordinator = MagicMock(spec=["conversation_id", "prepare_request", "wait_for_response"])
        mock_coordinator.conversation_id = "conv-event"
        mock_coordinator.prepare_request = AsyncMock(return_value="perm_event")
        mock_coordinator.wait_for_response = AsyncMock(return_value=True)

        # Set coordinator BEFORE the test so _get_hitl_coordinator returns it
        processor._hitl_coordinator = mock_coordinator

        events = []
        async for event in processor._execute_tool(
            session_id="session-event",
            call_id="call-event",
            tool_name="bash_tool",
            arguments={"command": "ls -la"},
        ):
            events.append(event)

        call_args = mock_coordinator.prepare_request.call_args
        request_data = call_args.kwargs.get("request_data")

        assert request_data.get("tool_name") == "bash_tool"
        # Check that input is in details
        details = request_data.get("details", {})
        assert "input" in details
        assert "command" in details["input"]
