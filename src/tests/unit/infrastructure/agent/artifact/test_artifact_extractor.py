"""
Unit tests for ArtifactExtractor.

Tests the artifact extraction logic extracted from SessionProcessor.
"""

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.artifact.extractor import (
    ArtifactData,
    ArtifactExtractionResult,
    ArtifactExtractor,
    ExtractionContext,
    get_artifact_extractor,
    set_artifact_extractor,
)

# ============================================================
# Test Fixtures
# ============================================================


@pytest.fixture
def extractor():
    """Create a fresh ArtifactExtractor without service."""
    return ArtifactExtractor(artifact_service=None, debug_logging=False)


@pytest.fixture
def debug_extractor():
    """Create an ArtifactExtractor with debug logging."""
    return ArtifactExtractor(artifact_service=None, debug_logging=True)


@pytest.fixture
def mock_artifact_service():
    """Create a mock artifact service."""
    service = AsyncMock()

    # Create mock artifact object
    mock_artifact = MagicMock()
    mock_artifact.id = "artifact-001"
    mock_artifact.filename = "test_output.png"
    mock_artifact.mime_type = "image/png"
    mock_artifact.category = MagicMock(value="image")
    mock_artifact.size_bytes = 1000
    mock_artifact.url = "https://storage.example.com/artifacts/test_output.png"
    mock_artifact.preview_url = "https://storage.example.com/artifacts/test_output_preview.png"

    service.create_artifact.return_value = mock_artifact
    return service


@pytest.fixture
def extractor_with_service(mock_artifact_service):
    """Create an ArtifactExtractor with mock service."""
    return ArtifactExtractor(artifact_service=mock_artifact_service)


@pytest.fixture
def valid_context():
    """Create a valid extraction context."""
    return ExtractionContext(
        project_id="proj-123",
        tenant_id="tenant-456",
        conversation_id="conv-789",
    )


@pytest.fixture
def sample_image_base64():
    """Sample base64 encoded image (1x1 red PNG)."""
    # 1x1 red PNG
    png_bytes = bytes(
        [
            0x89,
            0x50,
            0x4E,
            0x47,
            0x0D,
            0x0A,
            0x1A,
            0x0A,
            0x00,
            0x00,
            0x00,
            0x0D,
            0x49,
            0x48,
            0x44,
            0x52,
            0x00,
            0x00,
            0x00,
            0x01,
            0x00,
            0x00,
            0x00,
            0x01,
            0x08,
            0x02,
            0x00,
            0x00,
            0x00,
            0x90,
            0x77,
            0x53,
            0xDE,
            0x00,
            0x00,
            0x00,
            0x0C,
            0x49,
            0x44,
            0x41,
            0x54,
            0x08,
            0xD7,
            0x63,
            0xF8,
            0xCF,
            0xC0,
            0x00,
            0x00,
            0x00,
            0x03,
            0x00,
            0x01,
            0x00,
            0x05,
            0xFE,
            0xD4,
            0xEF,
            0x00,
            0x00,
            0x00,
            0x00,
            0x49,
            0x45,
            0x4E,
            0x44,
            0xAE,
            0x42,
            0x60,
            0x82,
        ]
    )
    return base64.b64encode(png_bytes).decode("ascii")


# ============================================================
# Test ExtractionContext
# ============================================================


@pytest.mark.unit
class TestExtractionContext:
    """Test ExtractionContext dataclass."""

    def test_is_valid_true(self, valid_context):
        """Test valid context."""
        assert valid_context.is_valid is True

    def test_is_valid_missing_project_id(self):
        """Test invalid context without project_id."""
        context = ExtractionContext(project_id="", tenant_id="tenant-123")
        assert context.is_valid is False

    def test_is_valid_missing_tenant_id(self):
        """Test invalid context without tenant_id."""
        context = ExtractionContext(project_id="proj-123", tenant_id="")
        assert context.is_valid is False


# ============================================================
# Test ArtifactData
# ============================================================


@pytest.mark.unit
class TestArtifactData:
    """Test ArtifactData dataclass."""

    def test_auto_calculate_size(self):
        """Test automatic size calculation."""
        data = ArtifactData(
            content=b"Hello World",
            filename="test.txt",
            mime_type="text/plain",
        )
        assert data.size_bytes == 11

    def test_explicit_size(self):
        """Test explicit size override."""
        data = ArtifactData(
            content=b"Hello",
            filename="test.txt",
            mime_type="text/plain",
            size_bytes=100,
        )
        assert data.size_bytes == 100

    def test_default_values(self):
        """Test default values."""
        data = ArtifactData(
            content=b"test",
            filename="test.bin",
            mime_type="application/octet-stream",
        )
        assert data.category == "other"
        assert data.source_tool == ""
        assert data.source_path is None
        assert data.metadata == {}


# ============================================================
# Test ArtifactExtractionResult
# ============================================================


@pytest.mark.unit
class TestArtifactExtractionResult:
    """Test ArtifactExtractionResult dataclass."""

    def test_has_artifacts_true(self):
        """Test has_artifacts when artifacts present."""
        result = ArtifactExtractionResult(
            artifacts=[ArtifactData(content=b"test", filename="test.txt", mime_type="text/plain")]
        )
        assert result.has_artifacts is True

    def test_has_artifacts_false(self):
        """Test has_artifacts when empty."""
        result = ArtifactExtractionResult()
        assert result.has_artifacts is False


# ============================================================
# Test Extraction from MCP Image Content
# ============================================================


@pytest.mark.unit
class TestMCPImageExtraction:
    """Test extraction from MCP image content."""

    def test_extract_image_content(self, extractor, sample_image_base64):
        """Test extracting image from MCP content."""
        result = {
            "content": [
                {
                    "type": "image",
                    "data": sample_image_base64,
                    "mimeType": "image/png",
                }
            ]
        }

        extraction = extractor.extract_only(result, "screenshot")

        assert extraction.has_artifacts
        assert len(extraction.artifacts) == 1
        artifact = extraction.artifacts[0]
        assert artifact.mime_type == "image/png"
        assert artifact.category == "image"
        assert artifact.filename == "screenshot_output_0.png"

    def test_extract_multiple_images(self, extractor, sample_image_base64):
        """Test extracting multiple images."""
        result = {
            "content": [
                {"type": "image", "data": sample_image_base64, "mimeType": "image/png"},
                {"type": "image", "data": sample_image_base64, "mimeType": "image/jpeg"},
            ]
        }

        extraction = extractor.extract_only(result, "multi_image")

        assert len(extraction.artifacts) == 2
        assert extraction.artifacts[0].filename == "multi_image_output_0.png"
        assert extraction.artifacts[1].filename == "multi_image_output_1.jpg"

    def test_skip_empty_image_data(self, extractor):
        """Test skipping images with empty data."""
        result = {
            "content": [
                {"type": "image", "data": "", "mimeType": "image/png"},
            ]
        }

        extraction = extractor.extract_only(result, "test")

        assert not extraction.has_artifacts


# ============================================================
# Test Extraction from Export Artifact
# ============================================================


@pytest.mark.unit
class TestExportArtifactExtraction:
    """Test extraction from export_artifact format."""

    def test_extract_base64_artifact(self, extractor, sample_image_base64):
        """Test extracting base64 encoded artifact."""
        result = {
            "artifact": {
                "filename": "chart.png",
                "mime_type": "image/png",
                "encoding": "base64",
                "data": sample_image_base64,
                "category": "image",
            },
            "content": [],
        }

        extraction = extractor.extract_only(result, "export_artifact")

        assert extraction.has_artifacts
        artifact = extraction.artifacts[0]
        assert artifact.filename == "chart.png"
        assert artifact.mime_type == "image/png"
        assert artifact.metadata["extracted_from"] == "export_artifact"

    def test_extract_text_artifact(self, extractor):
        """Test extracting text artifact."""
        result = {
            "artifact": {
                "filename": "report.txt",
                "mime_type": "text/plain",
                "encoding": "utf-8",
            },
            "content": [{"type": "text", "text": "Report content here"}],
        }

        extraction = extractor.extract_only(result, "export_artifact")

        assert extraction.has_artifacts
        artifact = extraction.artifacts[0]
        assert artifact.filename == "report.txt"
        assert artifact.content == b"Report content here"

    def test_extract_base64_from_image_content(self, extractor, sample_image_base64):
        """Test extracting base64 from image content when artifact.data is missing."""
        result = {
            "artifact": {
                "filename": "image.png",
                "encoding": "base64",
            },
            "content": [{"type": "image", "data": sample_image_base64}],
        }

        extraction = extractor.extract_only(result, "export")

        assert extraction.has_artifacts

    def test_error_missing_base64_data(self, extractor):
        """Test error when base64 encoding but no data."""
        result = {
            "artifact": {
                "filename": "file.bin",
                "encoding": "base64",
            },
            "content": [],
        }

        extraction = extractor.extract_only(result, "export")

        assert not extraction.has_artifacts
        assert len(extraction.errors) > 0

    def test_error_empty_text_content(self, extractor):
        """Test error when text encoding but empty content."""
        result = {
            "artifact": {
                "filename": "file.txt",
                "encoding": "utf-8",
            },
            "content": [{"type": "text", "text": ""}],
        }

        extraction = extractor.extract_only(result, "export")

        assert not extraction.has_artifacts
        assert len(extraction.errors) > 0


# ============================================================
# Test Extraction from MCP Resource Content
# ============================================================


@pytest.mark.unit
class TestMCPResourceExtraction:
    """Test extraction from MCP resource content."""

    def test_extract_blob_resource(self, extractor, sample_image_base64):
        """Test extracting binary resource."""
        result = {
            "content": [
                {
                    "type": "resource",
                    "uri": "file:///workspace/image.png",
                    "blob": sample_image_base64,
                    "mimeType": "image/png",
                }
            ]
        }

        extraction = extractor.extract_only(result, "file_reader")

        assert extraction.has_artifacts
        artifact = extraction.artifacts[0]
        assert artifact.filename == "image.png"
        assert artifact.source_path == "file:///workspace/image.png"

    def test_extract_text_resource(self, extractor):
        """Test extracting text resource."""
        result = {
            "content": [
                {
                    "type": "resource",
                    "uri": "file:///workspace/config.json",
                    "text": '{"key": "value"}',
                    "mimeType": "application/json",
                }
            ]
        }

        extraction = extractor.extract_only(result, "file_reader")

        assert extraction.has_artifacts
        artifact = extraction.artifacts[0]
        assert artifact.content == b'{"key": "value"}'

    def test_skip_empty_resource(self, extractor):
        """Test skipping resources with no content."""
        result = {
            "content": [
                {
                    "type": "resource",
                    "uri": "file:///workspace/empty",
                }
            ]
        }

        extraction = extractor.extract_only(result, "file_reader")

        assert not extraction.has_artifacts


# ============================================================
# Test Process Method with Service
# ============================================================


@pytest.mark.unit
class TestProcessWithService:
    """Test the full process method with artifact service."""

    async def test_process_creates_artifact(
        self, extractor_with_service, valid_context, sample_image_base64
    ):
        """Test that process creates artifacts via service."""
        result = {
            "content": [{"type": "image", "data": sample_image_base64, "mimeType": "image/png"}]
        }

        events = []
        async for event in extractor_with_service.process(
            tool_name="screenshot",
            result=result,
            context=valid_context,
            tool_execution_id="exec-001",
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0].artifact_id == "artifact-001"
        assert events[0].source_tool == "screenshot"

    async def test_process_without_service(self, extractor, valid_context, sample_image_base64):
        """Test that process skips when no service configured."""
        result = {
            "content": [{"type": "image", "data": sample_image_base64, "mimeType": "image/png"}]
        }

        events = []
        async for event in extractor.process(
            tool_name="test", result=result, context=valid_context
        ):
            events.append(event)

        assert len(events) == 0

    async def test_process_with_invalid_context(self, extractor_with_service, sample_image_base64):
        """Test that process skips with invalid context."""
        invalid_context = ExtractionContext(project_id="", tenant_id="")
        result = {
            "content": [{"type": "image", "data": sample_image_base64, "mimeType": "image/png"}]
        }

        events = []
        async for event in extractor_with_service.process(
            tool_name="test", result=result, context=invalid_context
        ):
            events.append(event)

        assert len(events) == 0

    async def test_process_non_dict_result(self, extractor_with_service, valid_context):
        """Test that process handles non-dict results."""
        events = []
        async for event in extractor_with_service.process(
            tool_name="test", result="string result", context=valid_context
        ):
            events.append(event)

        assert len(events) == 0

    async def test_process_no_artifacts_in_result(self, extractor_with_service, valid_context):
        """Test processing result with no artifacts."""
        result = {"content": [{"type": "text", "text": "Just text"}]}

        events = []
        async for event in extractor_with_service.process(
            tool_name="test", result=result, context=valid_context
        ):
            events.append(event)

        assert len(events) == 0


# ============================================================
# Test Category Detection
# ============================================================


@pytest.mark.unit
class TestCategoryDetection:
    """Test MIME type to category mapping."""

    def test_image_category(self, extractor):
        """Test image MIME types."""
        assert extractor._get_category_from_mime("image/png") == "image"
        assert extractor._get_category_from_mime("image/jpeg") == "image"
        assert extractor._get_category_from_mime("image/svg+xml") == "image"

    def test_video_category(self, extractor):
        """Test video MIME types."""
        assert extractor._get_category_from_mime("video/mp4") == "video"
        assert extractor._get_category_from_mime("video/webm") == "video"

    def test_audio_category(self, extractor):
        """Test audio MIME types."""
        assert extractor._get_category_from_mime("audio/mpeg") == "audio"
        assert extractor._get_category_from_mime("audio/wav") == "audio"

    def test_document_category(self, extractor):
        """Test document MIME types."""
        assert extractor._get_category_from_mime("application/pdf") == "document"
        assert extractor._get_category_from_mime("text/plain") == "document"

    def test_code_category(self, extractor):
        """Test code MIME types."""
        assert extractor._get_category_from_mime("text/javascript") == "code"
        assert extractor._get_category_from_mime("text/css") == "code"

    def test_other_category(self, extractor):
        """Test unknown MIME types."""
        assert extractor._get_category_from_mime("application/octet-stream") == "other"


# ============================================================
# Test Singleton Functions
# ============================================================


@pytest.mark.unit
class TestSingletonFunctions:
    """Test singleton getter/setter functions."""

    def test_get_artifact_extractor(self):
        """Test getting default extractor."""
        ext = get_artifact_extractor()
        assert isinstance(ext, ArtifactExtractor)

    def test_get_returns_same_instance(self):
        """Test that getter returns same instance."""
        ext1 = get_artifact_extractor()
        ext2 = get_artifact_extractor()
        assert ext1 is ext2

    def test_set_artifact_extractor(self):
        """Test setting custom extractor."""
        custom = ArtifactExtractor(debug_logging=True)
        set_artifact_extractor(custom)

        result = get_artifact_extractor()
        assert result is custom

        # Cleanup
        set_artifact_extractor(ArtifactExtractor())


# ============================================================
# Test Edge Cases
# ============================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_set_artifact_service(self, extractor, mock_artifact_service):
        """Test setting artifact service after creation."""
        assert extractor._artifact_service is None
        extractor.set_artifact_service(mock_artifact_service)
        assert extractor._artifact_service is mock_artifact_service

    def test_extract_only_method(self, extractor, sample_image_base64):
        """Test extract_only for preview/testing."""
        result = {
            "content": [{"type": "image", "data": sample_image_base64, "mimeType": "image/png"}]
        }

        extraction = extractor.extract_only(result, "test")

        assert extraction.has_artifacts
        # Content should be extracted but not uploaded
        assert len(extraction.artifacts[0].content) > 0

    def test_invalid_base64_handling(self, extractor):
        """Test handling of invalid base64 data."""
        result = {
            "content": [{"type": "image", "data": "not-valid-base64!!!", "mimeType": "image/png"}]
        }

        extraction = extractor.extract_only(result, "test")

        # Should not crash, just skip the invalid content
        assert not extraction.has_artifacts

    def test_mixed_content_types(self, extractor, sample_image_base64):
        """Test handling mixed content types."""
        result = {
            "content": [
                {"type": "text", "text": "Some text"},
                {"type": "image", "data": sample_image_base64, "mimeType": "image/png"},
                {"type": "text", "text": "More text"},
            ]
        }

        extraction = extractor.extract_only(result, "mixed")

        # Should only extract the image
        assert len(extraction.artifacts) == 1
        assert extraction.artifacts[0].category == "image"

    async def test_service_error_handling(
        self, extractor_with_service, valid_context, sample_image_base64
    ):
        """Test handling of service errors."""
        # Make service throw an error
        extractor_with_service._artifact_service.create_artifact.side_effect = Exception(
            "Storage error"
        )

        result = {
            "content": [{"type": "image", "data": sample_image_base64, "mimeType": "image/png"}]
        }

        events = []
        async for event in extractor_with_service.process(
            tool_name="test", result=result, context=valid_context
        ):
            events.append(event)

        # Should not crash, just log error
        assert len(events) == 0
