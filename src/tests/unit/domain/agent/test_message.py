"""Unit tests for the Message domain entity."""

from src.domain.model.agent import (
    Message,
    MessageRole,
    MessageType,
    ToolCall,
    ToolResult,
)


class TestMessage:
    """Test Message domain entity behavior."""

    def test_create_user_message(self):
        """Test creating a user message."""
        message = Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello, agent!",
            message_type=MessageType.TEXT,
        )

        assert message.id == "msg-1"
        assert message.conversation_id == "conv-1"
        assert message.role == MessageRole.USER
        assert message.content == "Hello, agent!"
        assert message.message_type == MessageType.TEXT
        assert message.tool_calls == []
        assert message.tool_results == []
        assert message.metadata == {}

    def test_create_assistant_message_with_tool_calls(self):
        """Test creating an assistant message with tool calls."""
        tool_call = ToolCall(
            name="memory_search",
            arguments={"query": "test"},
        )
        message = Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.ASSISTANT,
            content="Let me search for that.",
            message_type=MessageType.TOOL_CALL,
            tool_calls=[tool_call],
        )

        assert message.role == MessageRole.ASSISTANT
        assert message.message_type == MessageType.TOOL_CALL
        assert len(message.tool_calls) == 1
        assert message.tool_calls[0].name == "memory_search"

    def test_is_from_user(self):
        """Test checking if message is from user."""
        user_message = Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello",
            message_type=MessageType.TEXT,
        )
        assistant_message = Message(
            id="msg-2",
            conversation_id="conv-1",
            role=MessageRole.ASSISTANT,
            content="Hi there",
            message_type=MessageType.TEXT,
        )

        assert user_message.is_from_user() is True
        assert assistant_message.is_from_user() is False

    def test_is_from_assistant(self):
        """Test checking if message is from assistant."""
        user_message = Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello",
            message_type=MessageType.TEXT,
        )
        assistant_message = Message(
            id="msg-2",
            conversation_id="conv-1",
            role=MessageRole.ASSISTANT,
            content="Hi there",
            message_type=MessageType.TEXT,
        )

        assert user_message.is_from_assistant() is False
        assert assistant_message.is_from_assistant() is True

    def test_has_tool_calls(self):
        """Test checking if message has tool calls."""
        message_without_tools = Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello",
            message_type=MessageType.TEXT,
        )

        tool_call = ToolCall(
            name="memory_search",
            arguments={"query": "test"},
        )
        message_with_tools = Message(
            id="msg-2",
            conversation_id="conv-1",
            role=MessageRole.ASSISTANT,
            content="Searching",
            message_type=MessageType.TOOL_CALL,
            tool_calls=[tool_call],
        )

        assert message_without_tools.has_tool_calls() is False
        assert message_with_tools.has_tool_calls() is True

    def test_add_tool_call(self):
        """Test adding a tool call to message."""
        message = Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.ASSISTANT,
            content="I'll search for that",
            message_type=MessageType.TEXT,
        )

        assert len(message.tool_calls) == 0

        tool_call = ToolCall(
            name="memory_search",
            arguments={"query": "test"},
        )
        message.add_tool_call(tool_call)

        assert len(message.tool_calls) == 1
        assert message.tool_calls[0] == tool_call

    def test_add_tool_result(self):
        """Test adding a tool result to message."""
        message = Message(
            id="msg-1",
            conversation_id="conv-1",
            role=MessageRole.ASSISTANT,
            content="I'll search for that",
            message_type=MessageType.TEXT,
        )

        assert len(message.tool_results) == 0

        tool_result = ToolResult(
            tool_call_id="call-1",
            result="Found 3 results",
        )
        message.add_tool_result(tool_result)

        assert len(message.tool_results) == 1
        assert message.tool_results[0] == tool_result
