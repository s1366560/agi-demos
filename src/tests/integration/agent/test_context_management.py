"""
Integration tests for context management refactoring.

Tests the full context building pipeline:
- ContextFacade integration with all components
- End-to-end context building flow
- Compression behavior
- DI container factory methods
"""

import pytest

from src.configuration.di_container import DIContainer
from src.domain.ports.agent.context_manager_port import (
    CompressionStrategy,
    ContextBuildRequest,
)
from src.infrastructure.agent.context import (
    AttachmentInjector,
    ContextFacade,
    ContextWindowConfig,
    ContextWindowManager,
    MessageBuilder,
)


class TestContextFacadeIntegration:
    """Integration tests for ContextFacade with all components."""

    @pytest.mark.asyncio
    async def test_full_context_build_flow(self):
        """Test complete context building with all components."""
        facade = ContextFacade()
        
        request = ContextBuildRequest(
            system_prompt="You are a helpful coding assistant.",
            conversation_context=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi! How can I help you?"},
                {"role": "user", "content": "I need help with Python"},
                {"role": "assistant", "content": "I'd be happy to help with Python!"},
            ],
            user_message="Can you explain list comprehensions?",
            attachment_metadata=[
                {
                    "filename": "example.py",
                    "sandbox_path": "/workspace/example.py",
                    "mime_type": "text/x-python",
                    "size_bytes": 256,
                }
            ],
        )
        
        result = await facade.build_context(request)
        
        # Verify result structure
        assert result.messages is not None
        assert len(result.messages) >= 3  # system + history + user
        assert result.final_message_count > 0
        assert result.estimated_tokens > 0
        assert result.token_budget > 0
        
        # Verify system message is first
        assert result.messages[0]["role"] == "system"
        assert "coding assistant" in result.messages[0]["content"]
        
        # Verify user message has attachment context
        last_msg = result.messages[-1]
        assert last_msg["role"] == "user"
        content = last_msg.get("content", "")
        if isinstance(content, str):
            assert "example.py" in content
            assert "list comprehensions" in content

    @pytest.mark.asyncio
    async def test_multimodal_attachment_handling(self):
        """Test context building with multimodal attachments."""
        facade = ContextFacade()
        
        request = ContextBuildRequest(
            system_prompt="You analyze images.",
            conversation_context=[],
            user_message="Describe this image",
            attachment_content=[
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/test.png"},
                }
            ],
        )
        
        result = await facade.build_context(request)
        
        # User message should be multimodal
        last_msg = result.messages[-1]
        assert isinstance(last_msg["content"], list)
        assert len(last_msg["content"]) == 2  # text + image
        assert last_msg["content"][0]["type"] == "text"
        assert last_msg["content"][1]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_compression_not_triggered_small_context(self):
        """Test that compression is not triggered for small contexts."""
        facade = ContextFacade()
        
        request = ContextBuildRequest(
            system_prompt="Short system.",
            conversation_context=[],
            user_message="Hi",
        )
        
        result = await facade.build_context(request)
        
        assert result.was_compressed is False
        assert result.compression_strategy == CompressionStrategy.NONE

    @pytest.mark.asyncio
    async def test_custom_window_config(self):
        """Test context building with custom window configuration."""
        config = ContextWindowConfig(
            max_context_tokens=32000,
            max_output_tokens=2048,
        )
        window_manager = ContextWindowManager(config)
        facade = ContextFacade(window_manager=window_manager)
        
        request = ContextBuildRequest(
            system_prompt="Test",
            conversation_context=[],
            user_message="Hello",
        )
        
        result = await facade.build_context(request)
        
        # Token budget should reflect custom config
        # Budget = max_context - max_output = 32000 - 2048 = 29952
        assert result.token_budget == 29952


class TestDIContainerContextFactories:
    """Integration tests for DI container context factories."""

    def test_message_builder_factory(self):
        """Test MessageBuilder from DI container."""
        container = DIContainer()
        builder = container.message_builder()
        
        assert isinstance(builder, MessageBuilder)
        
        # Verify it works
        messages = builder.convert_to_openai_format([
            {"role": "user", "content": "Hello"}
        ])
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_attachment_injector_factory(self):
        """Test AttachmentInjector from DI container."""
        container = DIContainer()
        injector = container.attachment_injector()
        
        assert isinstance(injector, AttachmentInjector)
        
        # Verify it works
        metadata_list = injector.parse_metadata_list([
            {"filename": "test.py", "sandbox_path": "/workspace/test.py"}
        ])
        assert len(metadata_list) == 1
        assert metadata_list[0].filename == "test.py"

    def test_context_facade_factory(self):
        """Test ContextFacade from DI container."""
        container = DIContainer()
        facade = container.context_facade()
        
        assert isinstance(facade, ContextFacade)
        assert facade.message_builder is not None
        assert facade.attachment_injector is not None
        assert facade.window_manager is not None

    @pytest.mark.asyncio
    async def test_context_facade_from_di_works(self):
        """Test ContextFacade from DI container works end-to-end."""
        container = DIContainer()
        facade = container.context_facade()
        
        request = ContextBuildRequest(
            system_prompt="Test system",
            conversation_context=[{"role": "user", "content": "Hi"}],
            user_message="Hello from DI test",
        )
        
        result = await facade.build_context(request)
        
        assert result.messages is not None
        assert result.final_message_count >= 2


class TestMessageBuilderIntegration:
    """Integration tests for MessageBuilder."""

    def test_full_conversation_conversion(self):
        """Test converting a full conversation."""
        builder = MessageBuilder()
        
        conversation = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!", "tool_calls": [
                {"id": "call_1", "function": {"name": "test"}}
            ]},
            {"role": "tool", "tool_call_id": "call_1", "name": "test", "content": "done"},
            {"role": "assistant", "content": "The tool finished."},
            {"role": "user", "content": "Thanks!"},
        ]
        
        result = builder.convert_to_openai_format(conversation)
        
        assert len(result) == 6
        assert result[0]["role"] == "system"
        assert result[2]["tool_calls"] is not None
        assert result[3]["tool_call_id"] == "call_1"
        assert result[3]["name"] == "test"


class TestAttachmentInjectorIntegration:
    """Integration tests for AttachmentInjector."""

    def test_full_attachment_workflow(self):
        """Test full attachment processing workflow."""
        injector = AttachmentInjector()
        
        # Parse metadata from raw dicts
        raw_metadata = [
            {
                "filename": "app.py",
                "sandbox_path": "/workspace/app.py",
                "mime_type": "text/x-python",
                "size_bytes": 2048,
            },
            {
                "filename": "config.json",
                "sandbox_path": "/workspace/config.json",
                "mime_type": "application/json",
                "size_bytes": 512,
            },
        ]
        
        metadata_list = injector.parse_metadata_list(raw_metadata)
        assert len(metadata_list) == 2
        
        # Build context
        context = injector.build_attachment_context(metadata_list)
        assert "app.py" in context
        assert "config.json" in context
        assert "2.0 KB" in context
        assert "512 bytes" in context
        
        # Inject into message
        original = "Please review these files"
        enhanced = injector.inject_into_message(original, metadata_list)
        assert "app.py" in enhanced
        assert original in enhanced
