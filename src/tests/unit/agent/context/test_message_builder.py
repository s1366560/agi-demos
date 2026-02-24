"""
Unit tests for MessageBuilder.

Tests cover:
- OpenAI format conversion
- Role normalization
- Multimodal message building
- System/assistant/tool message building
- Validation and utilities
"""

from src.domain.ports.agent.context_manager_port import AttachmentContent
from src.infrastructure.agent.context.builder.message_builder import (
    MessageBuilder,
    MessageBuilderConfig,
)


class TestMessageBuilderConfig:
    """Tests for MessageBuilderConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = MessageBuilderConfig()
        assert config.default_role == "user"
        assert config.content_key == "content"
        assert config.role_key == "role"
        assert config.max_text_length == 100_000
        assert config.debug_logging is False

    def test_custom_config(self):
        """Test custom configuration."""
        config = MessageBuilderConfig(
            default_role="assistant",
            max_text_length=50_000,
            debug_logging=True,
        )
        assert config.default_role == "assistant"
        assert config.max_text_length == 50_000
        assert config.debug_logging is True


class TestConvertToOpenAIFormat:
    """Tests for convert_to_openai_format method."""

    def test_empty_messages(self):
        """Test with empty message list."""
        builder = MessageBuilder()
        result = builder.convert_to_openai_format([])
        assert result == []

    def test_single_user_message(self):
        """Test converting single user message."""
        builder = MessageBuilder()
        messages = [{"role": "user", "content": "Hello"}]
        result = builder.convert_to_openai_format(messages)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_multiple_messages(self):
        """Test converting multiple messages."""
        builder = MessageBuilder()
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "How are you?"},
        ]
        result = builder.convert_to_openai_format(messages)
        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"

    def test_missing_content(self):
        """Test handling missing content field."""
        builder = MessageBuilder()
        messages = [{"role": "user"}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["content"] == ""

    def test_missing_role(self):
        """Test handling missing role field (uses default)."""
        builder = MessageBuilder()
        messages = [{"content": "Hello"}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_none_content(self):
        """Test handling None content."""
        builder = MessageBuilder()
        messages = [{"role": "user", "content": None}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["content"] == ""

    def test_empty_dict_skipped(self):
        """Test empty dict is skipped."""
        builder = MessageBuilder()
        messages = [{}]
        result = builder.convert_to_openai_format(messages)
        assert len(result) == 0

    def test_tool_message_with_fields(self):
        """Test tool message preserves extra fields."""
        builder = MessageBuilder()
        messages = [
            {
                "role": "tool",
                "content": "Result",
                "tool_call_id": "call_123",
                "name": "grep",
            }
        ]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_123"
        assert result[0]["name"] == "grep"

    def test_assistant_with_tool_calls(self):
        """Test assistant message with tool_calls."""
        builder = MessageBuilder()
        tool_calls = [{"id": "call_1", "function": {"name": "test"}}]
        messages = [{"role": "assistant", "content": "", "tool_calls": tool_calls}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["tool_calls"] == tool_calls


class TestRoleNormalization:
    """Tests for role normalization."""

    def test_normalize_human_to_user(self):
        """Test 'human' maps to 'user'."""
        builder = MessageBuilder()
        messages = [{"role": "human", "content": "Hi"}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["role"] == "user"

    def test_normalize_ai_to_assistant(self):
        """Test 'ai' maps to 'assistant'."""
        builder = MessageBuilder()
        messages = [{"role": "ai", "content": "Hello"}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["role"] == "assistant"

    def test_normalize_bot_to_assistant(self):
        """Test 'bot' maps to 'assistant'."""
        builder = MessageBuilder()
        messages = [{"role": "bot", "content": "Hi"}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["role"] == "assistant"

    def test_normalize_model_to_assistant(self):
        """Test 'model' maps to 'assistant'."""
        builder = MessageBuilder()
        messages = [{"role": "model", "content": "Hi"}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["role"] == "assistant"

    def test_normalize_function_to_tool(self):
        """Test 'function' maps to 'tool'."""
        builder = MessageBuilder()
        messages = [{"role": "function", "content": "result"}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["role"] == "tool"

    def test_case_insensitive(self):
        """Test role normalization is case insensitive."""
        builder = MessageBuilder()
        messages = [{"role": "USER", "content": "Hi"}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["role"] == "user"

    def test_whitespace_handling(self):
        """Test role with whitespace is trimmed."""
        builder = MessageBuilder()
        messages = [{"role": "  user  ", "content": "Hi"}]
        result = builder.convert_to_openai_format(messages)
        assert result[0]["role"] == "user"


class TestBuildUserMessage:
    """Tests for build_user_message method."""

    def test_simple_text_message(self):
        """Test building simple text message."""
        builder = MessageBuilder()
        result = builder.build_user_message("Hello world")
        assert result == {"role": "user", "content": "Hello world"}

    def test_empty_attachments(self):
        """Test with empty attachments list."""
        builder = MessageBuilder()
        result = builder.build_user_message("Hello", attachments=[])
        assert result == {"role": "user", "content": "Hello"}

    def test_with_image_url_attachment(self):
        """Test with image_url attachment."""
        builder = MessageBuilder()
        attachment = AttachmentContent(
            type="image_url",
            image_url={"url": "https://example.com/img.png", "detail": "auto"},
        )
        result = builder.build_user_message("Describe this", [attachment])
        assert result["role"] == "user"
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2
        assert result["content"][0] == {"type": "text", "text": "Describe this"}
        assert result["content"][1]["type"] == "image_url"

    def test_with_image_base64_attachment(self):
        """Test with base64 image attachment."""
        builder = MessageBuilder()
        attachment = AttachmentContent(
            type="image",
            content="data:image/png;base64,abc123",
            detail="high",
        )
        result = builder.build_user_message("What's this?", [attachment])
        assert len(result["content"]) == 2
        assert result["content"][1]["type"] == "image_url"
        assert result["content"][1]["image_url"]["url"] == "data:image/png;base64,abc123"
        assert result["content"][1]["image_url"]["detail"] == "high"

    def test_with_text_file_attachment(self):
        """Test with text file attachment."""
        builder = MessageBuilder()
        attachment = AttachmentContent(
            type="text",
            content="print('hello')",
            filename="test.py",
        )
        result = builder.build_user_message("Review this code", [attachment])
        assert len(result["content"]) == 2
        assert result["content"][1]["type"] == "text"
        assert "test.py" in result["content"][1]["text"]
        assert "print('hello')" in result["content"][1]["text"]

    def test_with_multiple_attachments(self):
        """Test with multiple attachments."""
        builder = MessageBuilder()
        attachments = [
            AttachmentContent(type="text", content="code here", filename="a.py"),
            AttachmentContent(type="image", content="data:image/png;base64,xyz"),
        ]
        result = builder.build_user_message("Analyze", attachments)
        assert len(result["content"]) == 3  # text + 2 attachments

    def test_invalid_attachment_type_skipped(self):
        """Test invalid attachment type is skipped."""
        builder = MessageBuilder()
        attachment = AttachmentContent(type="unknown", content="data")
        result = builder.build_user_message("Hi", [attachment])
        assert len(result["content"]) == 1  # only text


class TestBuildSystemMessage:
    """Tests for build_system_message method."""

    def test_simple_system_message(self):
        """Test building system message."""
        builder = MessageBuilder()
        result = builder.build_system_message("You are a helpful assistant.")
        assert result == {"role": "system", "content": "You are a helpful assistant."}

    def test_empty_prompt(self):
        """Test with empty prompt."""
        builder = MessageBuilder()
        result = builder.build_system_message("")
        assert result == {"role": "system", "content": ""}


class TestBuildAssistantMessage:
    """Tests for build_assistant_message method."""

    def test_simple_assistant_message(self):
        """Test building assistant message."""
        builder = MessageBuilder()
        result = builder.build_assistant_message("I can help with that.")
        assert result == {"role": "assistant", "content": "I can help with that."}

    def test_with_tool_calls(self):
        """Test assistant message with tool calls."""
        builder = MessageBuilder()
        tool_calls = [{"id": "call_1", "function": {"name": "grep", "arguments": "{}"}}]
        result = builder.build_assistant_message("", tool_calls=tool_calls)
        assert result["role"] == "assistant"
        assert result["tool_calls"] == tool_calls

    def test_without_tool_calls(self):
        """Test assistant message without tool calls has no key."""
        builder = MessageBuilder()
        result = builder.build_assistant_message("Hello")
        assert "tool_calls" not in result


class TestBuildToolMessage:
    """Tests for build_tool_message method."""

    def test_build_tool_message(self):
        """Test building tool message."""
        builder = MessageBuilder()
        result = builder.build_tool_message(
            tool_call_id="call_123",
            name="grep",
            content="Found 5 matches",
        )
        assert result == {
            "role": "tool",
            "tool_call_id": "call_123",
            "name": "grep",
            "content": "Found 5 matches",
        }


class TestValidateMessages:
    """Tests for validate_messages method."""

    def test_valid_messages(self):
        """Test validation with valid messages."""
        builder = MessageBuilder()
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        warnings = builder.validate_messages(messages)
        assert warnings == []

    def test_missing_role(self):
        """Test warning for missing role."""
        builder = MessageBuilder()
        messages = [{"content": "Hi"}]
        warnings = builder.validate_messages(messages)
        assert any("missing 'role'" in w for w in warnings)

    def test_missing_content(self):
        """Test warning for missing content."""
        builder = MessageBuilder()
        messages = [{"role": "user"}]
        warnings = builder.validate_messages(messages)
        assert any("missing 'content'" in w for w in warnings)

    def test_invalid_role(self):
        """Test warning for invalid role."""
        builder = MessageBuilder()
        messages = [{"role": "invalid", "content": "Hi"}]
        warnings = builder.validate_messages(messages)
        assert any("invalid role" in w for w in warnings)

    def test_overly_long_content(self):
        """Test warning for overly long content."""
        builder = MessageBuilder(MessageBuilderConfig(max_text_length=10))
        messages = [{"role": "user", "content": "a" * 100}]
        warnings = builder.validate_messages(messages)
        assert any("exceeds" in w for w in warnings)


class TestCountMessagesByRole:
    """Tests for count_messages_by_role method."""

    def test_count_empty(self):
        """Test counting empty list."""
        builder = MessageBuilder()
        counts = builder.count_messages_by_role([])
        assert counts == {}

    def test_count_single_role(self):
        """Test counting single role."""
        builder = MessageBuilder()
        messages = [{"role": "user", "content": "Hi"}]
        counts = builder.count_messages_by_role(messages)
        assert counts == {"user": 1}

    def test_count_multiple_roles(self):
        """Test counting multiple roles."""
        builder = MessageBuilder()
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Bye"},
        ]
        counts = builder.count_messages_by_role(messages)
        assert counts == {"user": 2, "assistant": 1}
