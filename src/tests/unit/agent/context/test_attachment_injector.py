"""
Unit tests for AttachmentInjector.

Tests cover:
- Attachment context building
- Message injection
- Multimodal content preparation
- Metadata parsing
- Configuration customization
"""


from src.domain.ports.agent.context_manager_port import (
    AttachmentContent,
    AttachmentMetadata,
)
from src.infrastructure.agent.context.builder.attachment_injector import (
    DEFAULT_CONTEXT_TEMPLATE,
    DEFAULT_FILE_TEMPLATE,
    AttachmentInjector,
    AttachmentInjectorConfig,
)


class TestAttachmentInjectorConfig:
    """Tests for AttachmentInjectorConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = AttachmentInjectorConfig()
        assert config.context_template == DEFAULT_CONTEXT_TEMPLATE
        assert config.file_template == DEFAULT_FILE_TEMPLATE
        assert config.file_separator == "\n\n"
        assert config.default_workspace == "/workspace"
        assert config.debug_logging is False

    def test_custom_config(self):
        """Test custom configuration."""
        config = AttachmentInjectorConfig(
            file_separator="\n---\n",
            default_workspace="/home/user",
            debug_logging=True,
        )
        assert config.file_separator == "\n---\n"
        assert config.default_workspace == "/home/user"
        assert config.debug_logging is True


class TestAttachmentMetadata:
    """Tests for AttachmentMetadata dataclass."""

    def test_format_size_bytes(self):
        """Test size formatting for bytes."""
        meta = AttachmentMetadata(
            filename="test.txt",
            sandbox_path="/workspace/test.txt",
            size_bytes=500,
        )
        assert meta.format_size() == "500 bytes"

    def test_format_size_kilobytes(self):
        """Test size formatting for KB."""
        meta = AttachmentMetadata(
            filename="test.txt",
            sandbox_path="/workspace/test.txt",
            size_bytes=2048,  # 2 KB
        )
        assert meta.format_size() == "2.0 KB"

    def test_format_size_megabytes(self):
        """Test size formatting for MB."""
        meta = AttachmentMetadata(
            filename="test.txt",
            sandbox_path="/workspace/test.txt",
            size_bytes=5 * 1024 * 1024,  # 5 MB
        )
        assert meta.format_size() == "5.0 MB"

    def test_format_size_zero(self):
        """Test size formatting for zero bytes."""
        meta = AttachmentMetadata(
            filename="empty.txt",
            sandbox_path="/workspace/empty.txt",
            size_bytes=0,
        )
        assert meta.format_size() == "0 bytes"


class TestBuildAttachmentContext:
    """Tests for build_attachment_context method."""

    def test_empty_metadata_list(self):
        """Test with empty metadata list."""
        injector = AttachmentInjector()
        result = injector.build_attachment_context([])
        assert result == ""

    def test_single_file(self):
        """Test context for single file."""
        injector = AttachmentInjector()
        metadata = [
            AttachmentMetadata(
                filename="test.py",
                sandbox_path="/workspace/test.py",
                mime_type="text/x-python",
                size_bytes=1024,
            )
        ]
        result = injector.build_attachment_context(metadata)
        assert "test.py" in result
        assert "/workspace/test.py" in result
        assert "text/x-python" in result
        assert "1.0 KB" in result

    def test_multiple_files(self):
        """Test context for multiple files."""
        injector = AttachmentInjector()
        metadata = [
            AttachmentMetadata(
                filename="a.py",
                sandbox_path="/workspace/a.py",
                mime_type="text/x-python",
                size_bytes=512,
            ),
            AttachmentMetadata(
                filename="b.txt",
                sandbox_path="/workspace/b.txt",
                mime_type="text/plain",
                size_bytes=256,
            ),
        ]
        result = injector.build_attachment_context(metadata)
        assert "a.py" in result
        assert "b.txt" in result
        assert "/workspace/a.py" in result
        assert "/workspace/b.txt" in result

    def test_context_has_header(self):
        """Test context includes header."""
        injector = AttachmentInjector()
        metadata = [
            AttachmentMetadata(
                filename="test.py",
                sandbox_path="/workspace/test.py",
            )
        ]
        result = injector.build_attachment_context(metadata)
        assert "用户本次消息上传的文件" in result or "CURRENT MESSAGE ATTACHMENTS" in result

    def test_context_has_instructions(self):
        """Test context includes instructions."""
        injector = AttachmentInjector()
        metadata = [
            AttachmentMetadata(
                filename="test.py",
                sandbox_path="/workspace/test.py",
            )
        ]
        result = injector.build_attachment_context(metadata)
        assert "沙箱路径" in result
        assert "cat" in result or "bash" in result


class TestInjectIntoMessage:
    """Tests for inject_into_message method."""

    def test_no_attachments(self):
        """Test injection with no attachments."""
        injector = AttachmentInjector()
        result = injector.inject_into_message("Hello world", [])
        assert result == "Hello world"

    def test_prepend_context(self):
        """Test context is prepended to message."""
        injector = AttachmentInjector()
        metadata = [
            AttachmentMetadata(
                filename="test.py",
                sandbox_path="/workspace/test.py",
            )
        ]
        result = injector.inject_into_message("Check this file", metadata)
        # Context should come before message
        assert result.index("test.py") < result.index("Check this file")

    def test_original_message_preserved(self):
        """Test original message is preserved."""
        injector = AttachmentInjector()
        metadata = [
            AttachmentMetadata(
                filename="test.py",
                sandbox_path="/workspace/test.py",
            )
        ]
        original = "Please analyze the code quality"
        result = injector.inject_into_message(original, metadata)
        assert original in result


class TestPrepareMultimodalContent:
    """Tests for prepare_multimodal_content method."""

    def test_text_only(self):
        """Test with text only (no attachments)."""
        injector = AttachmentInjector()
        result = injector.prepare_multimodal_content("Hello", [])
        assert result == [{"type": "text", "text": "Hello"}]

    def test_empty_text_no_attachments(self):
        """Test with empty text and no attachments."""
        injector = AttachmentInjector()
        result = injector.prepare_multimodal_content("", [])
        assert result == []

    def test_with_image_url(self):
        """Test with image_url attachment."""
        injector = AttachmentInjector()
        attachments = [
            AttachmentContent(
                type="image_url",
                image_url={"url": "https://example.com/img.png"},
            )
        ]
        result = injector.prepare_multimodal_content("Describe", attachments)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image_url"

    def test_with_base64_image(self):
        """Test with base64 image attachment."""
        injector = AttachmentInjector()
        attachments = [
            AttachmentContent(
                type="image",
                content="data:image/png;base64,abc",
                detail="low",
            )
        ]
        result = injector.prepare_multimodal_content("What is this?", attachments)
        assert len(result) == 2
        assert result[1]["image_url"]["url"] == "data:image/png;base64,abc"
        assert result[1]["image_url"]["detail"] == "low"

    def test_with_text_attachment(self):
        """Test with text file attachment."""
        injector = AttachmentInjector()
        attachments = [
            AttachmentContent(
                type="text",
                content="def hello(): pass",
                filename="hello.py",
            )
        ]
        result = injector.prepare_multimodal_content("Review", attachments)
        assert len(result) == 2
        assert "hello.py" in result[1]["text"]
        assert "def hello(): pass" in result[1]["text"]

    def test_with_multiple_attachments(self):
        """Test with multiple attachments."""
        injector = AttachmentInjector()
        attachments = [
            AttachmentContent(type="text", content="code", filename="a.py"),
            AttachmentContent(type="image", content="data:image/png;base64,x"),
            AttachmentContent(type="text", content="more code", filename="b.py"),
        ]
        result = injector.prepare_multimodal_content("Analyze", attachments)
        assert len(result) == 4  # text + 3 attachments

    def test_invalid_attachment_skipped(self):
        """Test invalid attachment type is skipped."""
        injector = AttachmentInjector()
        attachments = [
            AttachmentContent(type="video", content="data"),
        ]
        result = injector.prepare_multimodal_content("Hi", attachments)
        assert len(result) == 1  # only text


class TestParseMetadataFromDict:
    """Tests for parse_metadata_from_dict method."""

    def test_full_dict(self):
        """Test parsing full dict."""
        injector = AttachmentInjector()
        data = {
            "filename": "test.py",
            "sandbox_path": "/workspace/test.py",
            "mime_type": "text/x-python",
            "size_bytes": 1024,
        }
        result = injector.parse_metadata_from_dict(data)
        assert result.filename == "test.py"
        assert result.sandbox_path == "/workspace/test.py"
        assert result.mime_type == "text/x-python"
        assert result.size_bytes == 1024

    def test_minimal_dict(self):
        """Test parsing minimal dict with defaults."""
        injector = AttachmentInjector()
        data = {"filename": "test.txt"}
        result = injector.parse_metadata_from_dict(data)
        assert result.filename == "test.txt"
        assert result.sandbox_path == "/workspace/test.txt"
        assert result.mime_type == "application/octet-stream"
        assert result.size_bytes == 0

    def test_empty_dict(self):
        """Test parsing empty dict uses all defaults."""
        injector = AttachmentInjector()
        result = injector.parse_metadata_from_dict({})
        assert result.filename == "unknown"
        assert result.sandbox_path == "/workspace/unknown"


class TestParseMetadataList:
    """Tests for parse_metadata_list method."""

    def test_none_list(self):
        """Test parsing None returns empty list."""
        injector = AttachmentInjector()
        result = injector.parse_metadata_list(None)
        assert result == []

    def test_empty_list(self):
        """Test parsing empty list."""
        injector = AttachmentInjector()
        result = injector.parse_metadata_list([])
        assert result == []

    def test_multiple_items(self):
        """Test parsing multiple items."""
        injector = AttachmentInjector()
        data = [
            {"filename": "a.py", "sandbox_path": "/workspace/a.py"},
            {"filename": "b.py", "sandbox_path": "/workspace/b.py"},
        ]
        result = injector.parse_metadata_list(data)
        assert len(result) == 2
        assert result[0].filename == "a.py"
        assert result[1].filename == "b.py"


class TestParseContentFromDict:
    """Tests for parse_content_from_dict method."""

    def test_image_url_content(self):
        """Test parsing image_url content."""
        injector = AttachmentInjector()
        data = {
            "type": "image_url",
            "image_url": {"url": "https://example.com/img.png"},
        }
        result = injector.parse_content_from_dict(data)
        assert result.type == "image_url"
        assert result.image_url == {"url": "https://example.com/img.png"}

    def test_text_content(self):
        """Test parsing text content."""
        injector = AttachmentInjector()
        data = {
            "type": "text",
            "content": "file content",
            "filename": "test.txt",
        }
        result = injector.parse_content_from_dict(data)
        assert result.type == "text"
        assert result.content == "file content"
        assert result.filename == "test.txt"

    def test_text_with_text_key(self):
        """Test parsing text with 'text' key instead of 'content'."""
        injector = AttachmentInjector()
        data = {
            "type": "text",
            "text": "file content via text key",
        }
        result = injector.parse_content_from_dict(data)
        assert result.content == "file content via text key"

    def test_image_with_detail(self):
        """Test parsing image with detail setting."""
        injector = AttachmentInjector()
        data = {
            "type": "image",
            "content": "data:image/png;base64,abc",
            "detail": "high",
        }
        result = injector.parse_content_from_dict(data)
        assert result.type == "image"
        assert result.content == "data:image/png;base64,abc"
        assert result.detail == "high"


class TestParseContentList:
    """Tests for parse_content_list method."""

    def test_none_list(self):
        """Test parsing None returns empty list."""
        injector = AttachmentInjector()
        result = injector.parse_content_list(None)
        assert result == []

    def test_empty_list(self):
        """Test parsing empty list."""
        injector = AttachmentInjector()
        result = injector.parse_content_list([])
        assert result == []

    def test_multiple_items(self):
        """Test parsing multiple content items."""
        injector = AttachmentInjector()
        data = [
            {"type": "text", "content": "a"},
            {"type": "image", "content": "data:image/png;base64,x"},
        ]
        result = injector.parse_content_list(data)
        assert len(result) == 2
        assert result[0].type == "text"
        assert result[1].type == "image"


class TestCustomTemplate:
    """Tests for custom template configuration."""

    def test_custom_context_template(self):
        """Test using custom context template."""
        config = AttachmentInjectorConfig(
            context_template="Files: {file_list}\n\n---\n\n"
        )
        injector = AttachmentInjector(config)
        metadata = [
            AttachmentMetadata(
                filename="test.py",
                sandbox_path="/workspace/test.py",
            )
        ]
        result = injector.build_attachment_context(metadata)
        assert result.startswith("Files:")
        assert result.endswith("---\n\n")

    def test_custom_file_template(self):
        """Test using custom file template."""
        config = AttachmentInjectorConfig(
            file_template="[{filename}] -> {sandbox_path}",
            context_template="{file_list}"
        )
        injector = AttachmentInjector(config)
        metadata = [
            AttachmentMetadata(
                filename="test.py",
                sandbox_path="/workspace/test.py",
            )
        ]
        result = injector.build_attachment_context(metadata)
        assert "[test.py] -> /workspace/test.py" in result
