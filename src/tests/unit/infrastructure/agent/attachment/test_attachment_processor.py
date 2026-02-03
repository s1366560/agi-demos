"""
Unit tests for AttachmentProcessor.

Tests the unified attachment processing logic extracted from ReActAgent.
"""

import pytest

from src.infrastructure.agent.attachment.processor import (
    AttachmentContext,
    AttachmentProcessor,
    ProcessedAttachment,
    get_attachment_processor,
    set_attachment_processor,
)


# ============================================================
# Test Fixtures
# ============================================================


@pytest.fixture
def processor():
    """Create a fresh AttachmentProcessor instance."""
    return AttachmentProcessor(debug_logging=False)


@pytest.fixture
def debug_processor():
    """Create an AttachmentProcessor with debug logging."""
    return AttachmentProcessor(debug_logging=True)


@pytest.fixture
def sample_metadata():
    """Sample attachment metadata."""
    return [
        {
            "filename": "document.pdf",
            "sandbox_path": "/workspace/document.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 1024000,
        },
        {
            "filename": "image.png",
            "sandbox_path": "/workspace/image.png",
            "mime_type": "image/png",
            "size_bytes": 50000,
        },
    ]


@pytest.fixture
def sample_image_content():
    """Sample image attachment content."""
    return [
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64,iVBORw0KGgo...",
                "detail": "auto",
            },
            "filename": "image.png",
        }
    ]


@pytest.fixture
def sample_text_content():
    """Sample text attachment content."""
    return [
        {
            "type": "text",
            "text": "This is the content of the text file.",
            "filename": "readme.txt",
        }
    ]


# ============================================================
# Test ProcessedAttachment
# ============================================================


@pytest.mark.unit
class TestProcessedAttachment:
    """Test ProcessedAttachment dataclass."""

    def test_image_url_to_llm_content(self):
        """Test converting image_url attachment to LLM content."""
        attachment = ProcessedAttachment(
            type="image_url",
            content={"url": "data:image/png;base64,abc", "detail": "auto"},
            filename="test.png",
        )

        result = attachment.to_llm_content()

        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == "data:image/png;base64,abc"

    def test_text_to_llm_content(self):
        """Test converting text attachment to LLM content."""
        attachment = ProcessedAttachment(
            type="text",
            content="File contents here",
            filename="data.txt",
        )

        result = attachment.to_llm_content()

        assert result["type"] == "text"
        assert "--- Attached file: data.txt ---" in result["text"]
        assert "File contents here" in result["text"]

    def test_unknown_type_to_llm_content(self):
        """Test converting unknown attachment type to LLM content."""
        attachment = ProcessedAttachment(
            type="binary",
            content=b"binary data",
            filename="data.bin",
        )

        result = attachment.to_llm_content()

        assert result["type"] == "text"
        assert "data.bin" in result["text"]
        assert "(type: binary)" in result["text"]


# ============================================================
# Test AttachmentContext
# ============================================================


@pytest.mark.unit
class TestAttachmentContext:
    """Test AttachmentContext dataclass."""

    def test_has_attachments_with_files(self):
        """Test has_attachments with file count."""
        context = AttachmentContext(file_count=2)
        assert context.has_attachments is True

    def test_has_attachments_with_processed(self):
        """Test has_attachments with processed attachments."""
        context = AttachmentContext(
            processed_attachments=[ProcessedAttachment(type="text", content="test")]
        )
        assert context.has_attachments is True

    def test_has_attachments_empty(self):
        """Test has_attachments when empty."""
        context = AttachmentContext()
        assert context.has_attachments is False


# ============================================================
# Test AttachmentProcessor.build_context
# ============================================================


@pytest.mark.unit
class TestBuildContext:
    """Test build_context method."""

    def test_build_context_with_metadata(self, processor, sample_metadata):
        """Test building context with metadata only."""
        context = processor.build_context(attachment_metadata=sample_metadata)

        assert context.file_count == 2
        assert context.total_size_bytes == 1074000  # 1024000 + 50000
        assert "document.pdf" in context.context_prompt
        assert "/workspace/document.pdf" in context.context_prompt

    def test_build_context_with_content(self, processor, sample_image_content):
        """Test building context with content only."""
        context = processor.build_context(attachment_content=sample_image_content)

        assert len(context.processed_attachments) == 1
        assert context.processed_attachments[0].type == "image_url"

    def test_build_context_with_both(
        self, processor, sample_metadata, sample_image_content
    ):
        """Test building context with both metadata and content."""
        context = processor.build_context(
            attachment_metadata=sample_metadata,
            attachment_content=sample_image_content,
        )

        assert context.file_count == 2
        assert len(context.processed_attachments) == 1
        assert context.has_attachments is True

    def test_build_context_empty(self, processor):
        """Test building context with no attachments."""
        context = processor.build_context()

        assert context.file_count == 0
        assert context.context_prompt == ""
        assert len(context.processed_attachments) == 0
        assert context.has_attachments is False


# ============================================================
# Test Context Prompt Generation
# ============================================================


@pytest.mark.unit
class TestContextPromptGeneration:
    """Test context prompt generation."""

    def test_prompt_contains_file_info(self, processor, sample_metadata):
        """Test that prompt contains all file information."""
        context = processor.build_context(attachment_metadata=sample_metadata)

        # Check both files are mentioned
        assert "document.pdf" in context.context_prompt
        assert "image.png" in context.context_prompt

        # Check sandbox paths
        assert "/workspace/document.pdf" in context.context_prompt
        assert "/workspace/image.png" in context.context_prompt

        # Check mime types
        assert "application/pdf" in context.context_prompt
        assert "image/png" in context.context_prompt

    def test_prompt_contains_instructions(self, processor, sample_metadata):
        """Test that prompt contains usage instructions."""
        context = processor.build_context(attachment_metadata=sample_metadata)

        assert "沙箱路径" in context.context_prompt
        assert "cat" in context.context_prompt

    def test_size_formatting_bytes(self, processor):
        """Test file size formatting for bytes."""
        metadata = [{"filename": "tiny.txt", "size_bytes": 500}]
        context = processor.build_context(attachment_metadata=metadata)

        assert "500 bytes" in context.context_prompt

    def test_size_formatting_kb(self, processor):
        """Test file size formatting for KB."""
        metadata = [{"filename": "small.txt", "size_bytes": 5000}]
        context = processor.build_context(attachment_metadata=metadata)

        assert "4.9 KB" in context.context_prompt

    def test_size_formatting_mb(self, processor):
        """Test file size formatting for MB."""
        metadata = [{"filename": "large.zip", "size_bytes": 5000000}]
        context = processor.build_context(attachment_metadata=metadata)

        assert "4.8 MB" in context.context_prompt


# ============================================================
# Test Content Processing
# ============================================================


@pytest.mark.unit
class TestContentProcessing:
    """Test attachment content processing."""

    def test_process_image_url(self, processor):
        """Test processing image_url type."""
        content = [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,abc"},
                "filename": "test.png",
            }
        ]

        context = processor.build_context(attachment_content=content)

        assert len(context.processed_attachments) == 1
        assert context.processed_attachments[0].type == "image_url"
        assert context.processed_attachments[0].content["url"] == "data:image/png;base64,abc"

    def test_process_legacy_image(self, processor):
        """Test processing legacy image type."""
        content = [
            {
                "type": "image",
                "content": "data:image/jpeg;base64,xyz",
                "detail": "high",
                "filename": "photo.jpg",
            }
        ]

        context = processor.build_context(attachment_content=content)

        assert len(context.processed_attachments) == 1
        assert context.processed_attachments[0].type == "image_url"
        assert context.processed_attachments[0].content["detail"] == "high"

    def test_process_text_with_text_field(self, processor):
        """Test processing text type with 'text' field."""
        content = [
            {
                "type": "text",
                "text": "Hello world",
                "filename": "greeting.txt",
            }
        ]

        context = processor.build_context(attachment_content=content)

        assert len(context.processed_attachments) == 1
        assert context.processed_attachments[0].type == "text"
        assert context.processed_attachments[0].content == "Hello world"

    def test_process_text_with_content_field(self, processor):
        """Test processing text type with 'content' field (fallback)."""
        content = [
            {
                "type": "text",
                "content": "Fallback content",
                "filename": "file.txt",
            }
        ]

        context = processor.build_context(attachment_content=content)

        assert len(context.processed_attachments) == 1
        assert context.processed_attachments[0].content == "Fallback content"

    def test_process_empty_content_skipped(self, processor):
        """Test that empty content is skipped."""
        content = [
            {"type": "image_url", "image_url": {}},  # Empty
            {"type": "text", "text": ""},  # Empty
            {"type": "image", "content": ""},  # Empty
        ]

        context = processor.build_context(attachment_content=content)

        assert len(context.processed_attachments) == 0


# ============================================================
# Test build_user_message
# ============================================================


@pytest.mark.unit
class TestBuildUserMessage:
    """Test build_user_message method."""

    def test_simple_message_no_attachments(self, processor):
        """Test building message without attachments."""
        context = AttachmentContext()
        result = processor.build_user_message("Hello", context)

        assert result["role"] == "user"
        assert result["content"] == "Hello"

    def test_message_with_context_prompt(self, processor, sample_metadata):
        """Test that context prompt is prepended."""
        context = processor.build_context(attachment_metadata=sample_metadata)
        result = processor.build_user_message("Analyze this file", context)

        assert result["role"] == "user"
        # Content should contain context prompt
        assert "document.pdf" in result["content"]
        assert "Analyze this file" in result["content"]

    def test_multimodal_message(self, processor, sample_image_content):
        """Test building multimodal message with images."""
        context = processor.build_context(attachment_content=sample_image_content)
        result = processor.build_user_message("What's in this image?", context)

        assert result["role"] == "user"
        # Content should be a list for multimodal
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2  # text + image
        assert result["content"][0]["type"] == "text"
        assert result["content"][1]["type"] == "image_url"

    def test_multimodal_with_multiple_attachments(self, processor):
        """Test building message with multiple attachments."""
        content = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,a"}},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,b"}},
            {"type": "text", "text": "description", "filename": "desc.txt"},
        ]
        context = processor.build_context(attachment_content=content)
        result = processor.build_user_message("Process these", context)

        assert len(result["content"]) == 4  # text + 3 attachments


# ============================================================
# Test enhance_message_with_context
# ============================================================


@pytest.mark.unit
class TestEnhanceMessage:
    """Test enhance_message_with_context convenience method."""

    def test_enhance_with_full_params(self, processor, sample_metadata, sample_image_content):
        """Test the convenience method with all params."""
        result = processor.enhance_message_with_context(
            user_message="Check this",
            attachment_metadata=sample_metadata,
            attachment_content=sample_image_content,
        )

        assert result["role"] == "user"
        # Should have multimodal content
        assert isinstance(result["content"], list)
        # Should include context about files
        text_content = result["content"][0]["text"]
        assert "document.pdf" in text_content

    def test_enhance_without_attachments(self, processor):
        """Test convenience method without attachments."""
        result = processor.enhance_message_with_context(user_message="Hello")

        assert result["role"] == "user"
        assert result["content"] == "Hello"


# ============================================================
# Test Singleton Functions
# ============================================================


@pytest.mark.unit
class TestSingletonFunctions:
    """Test singleton getter/setter functions."""

    def test_get_attachment_processor(self):
        """Test getting default processor."""
        processor = get_attachment_processor()
        assert isinstance(processor, AttachmentProcessor)

    def test_get_returns_same_instance(self):
        """Test that getter returns same instance."""
        p1 = get_attachment_processor()
        p2 = get_attachment_processor()
        assert p1 is p2

    def test_set_attachment_processor(self):
        """Test setting custom processor."""
        custom = AttachmentProcessor(debug_logging=True)
        set_attachment_processor(custom)

        result = get_attachment_processor()
        assert result is custom

        # Cleanup
        set_attachment_processor(AttachmentProcessor())


# ============================================================
# Test Edge Cases
# ============================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_metadata_fields(self, processor):
        """Test handling metadata with missing fields."""
        metadata = [{"filename": "test.txt"}]  # Missing most fields

        context = processor.build_context(attachment_metadata=metadata)

        assert context.file_count == 1
        assert "test.txt" in context.context_prompt
        # Should use defaults for missing fields
        assert "/workspace/test.txt" in context.context_prompt
        assert "unknown" in context.context_prompt  # mime_type default

    def test_debug_logging_enabled(self, debug_processor, sample_metadata, caplog):
        """Test that debug logging produces output."""
        import logging

        caplog.set_level(logging.INFO)

        debug_processor.build_context(attachment_metadata=sample_metadata)

        assert any("AttachmentProcessor" in record.message for record in caplog.records)

    def test_very_long_filename(self, processor):
        """Test handling very long filenames."""
        long_name = "a" * 500 + ".txt"
        metadata = [{"filename": long_name}]

        context = processor.build_context(attachment_metadata=metadata)

        assert long_name in context.context_prompt

    def test_special_characters_in_filename(self, processor):
        """Test handling special characters in filenames."""
        metadata = [{"filename": "文件 (copy) [final].pdf"}]

        context = processor.build_context(attachment_metadata=metadata)

        assert "文件 (copy) [final].pdf" in context.context_prompt

    def test_zero_size_file(self, processor):
        """Test handling zero-size files."""
        metadata = [{"filename": "empty.txt", "size_bytes": 0}]

        context = processor.build_context(attachment_metadata=metadata)

        assert "0 bytes" in context.context_prompt
