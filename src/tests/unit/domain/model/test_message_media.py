"""Unit tests for MessageContent media handling."""

import pytest

from src.domain.model.channels.message import MessageContent, MessageType


class TestMessageContentMediaHandling:
    """Test MessageContent media-related methods."""

    def test_is_media_returns_true_for_image(self):
        """Test that is_media() returns True for IMAGE type."""
        content = MessageContent(type=MessageType.IMAGE, image_key="test_key")
        assert content.is_media() is True

    def test_is_media_returns_true_for_file(self):
        """Test that is_media() returns True for FILE type."""
        content = MessageContent(type=MessageType.FILE, file_key="test_key")
        assert content.is_media() is True

    def test_is_media_returns_true_for_audio(self):
        """Test that is_media() returns True for AUDIO type."""
        content = MessageContent(type=MessageType.AUDIO, file_key="test_key")
        assert content.is_media() is True

    def test_is_media_returns_true_for_video(self):
        """Test that is_media() returns True for VIDEO type."""
        content = MessageContent(type=MessageType.VIDEO, file_key="test_key")
        assert content.is_media() is True

    def test_is_media_returns_true_for_sticker(self):
        """Test that is_media() returns True for STICKER type."""
        content = MessageContent(type=MessageType.STICKER, file_key="test_key")
        assert content.is_media() is True

    def test_is_media_returns_false_for_text(self):
        """Test that is_media() returns False for TEXT type."""
        content = MessageContent(type=MessageType.TEXT, text="Hello")
        assert content.is_media() is False

    def test_is_media_returns_false_for_post(self):
        """Test that is_media() returns False for POST type."""
        content = MessageContent(type=MessageType.POST, text="Rich text")
        assert content.is_media() is False

    def test_generate_display_text_returns_text_if_present(self):
        """Test that generate_display_text() returns existing text."""
        content = MessageContent(type=MessageType.TEXT, text="Hello world")
        assert content.generate_display_text() == "Hello world"

    def test_generate_display_text_for_image_with_size(self):
        """Test display text generation for image with size."""
        content = MessageContent(
            type=MessageType.IMAGE,
            image_key="img123",
            size=1024,
        )
        text = content.generate_display_text()
        assert "[图片消息" in text
        assert "1024 bytes" in text

    def test_generate_display_text_for_image_without_size(self):
        """Test display text generation for image without size."""
        content = MessageContent(
            type=MessageType.IMAGE,
            image_key="img123",
        )
        text = content.generate_display_text()
        assert text == "[图片消息]"

    def test_generate_display_text_for_file_with_name_and_size(self):
        """Test display text generation for file with name and size."""
        content = MessageContent(
            type=MessageType.FILE,
            file_key="file123",
            file_name="report.pdf",
            size=2048,
        )
        text = content.generate_display_text()
        assert "[文件: report.pdf" in text
        assert "2048 bytes" in text

    def test_generate_display_text_for_file_without_metadata(self):
        """Test display text generation for file without metadata."""
        content = MessageContent(
            type=MessageType.FILE,
            file_key="file123",
        )
        text = content.generate_display_text()
        assert "[文件: unknown]" in text

    def test_generate_display_text_for_audio_with_duration(self):
        """Test display text generation for audio with duration."""
        content = MessageContent(
            type=MessageType.AUDIO,
            file_key="audio123",
            duration=30,
        )
        text = content.generate_display_text()
        assert "[语音消息: 30秒]" == text

    def test_generate_display_text_for_audio_without_duration(self):
        """Test display text generation for audio without duration."""
        content = MessageContent(
            type=MessageType.AUDIO,
            file_key="audio123",
        )
        text = content.generate_display_text()
        assert "[语音消息: 未知时长]" == text

    def test_generate_display_text_for_video_with_duration(self):
        """Test display text generation for video with duration."""
        content = MessageContent(
            type=MessageType.VIDEO,
            file_key="video123",
            duration=120,
        )
        text = content.generate_display_text()
        assert "[视频消息: 120秒]" == text

    def test_generate_display_text_for_video_without_duration(self):
        """Test display text generation for video without duration."""
        content = MessageContent(
            type=MessageType.VIDEO,
            file_key="video123",
        )
        text = content.generate_display_text()
        assert "[视频消息: 未知时长]" == text

    def test_generate_display_text_for_sticker(self):
        """Test display text generation for sticker."""
        content = MessageContent(
            type=MessageType.STICKER,
            file_key="sticker123",
        )
        text = content.generate_display_text()
        assert text == "[表情消息]"

    def test_message_content_new_fields_exist(self):
        """Test that new media fields can be set."""
        content = MessageContent(
            type=MessageType.VIDEO,
            file_key="video123",
            duration=100,
            size=5000,
            mime_type="video/mp4",
            thumbnail_key="thumb123",
            extra_media_data={"bitrate": 1080},
            sandbox_path="/workspace/input/video.mp4",
            artifact_id="artifact-uuid",
        )

        assert content.duration == 100
        assert content.size == 5000
        assert content.mime_type == "video/mp4"
        assert content.thumbnail_key == "thumb123"
        assert content.extra_media_data == {"bitrate": 1080}
        assert content.sandbox_path == "/workspace/input/video.mp4"
        assert content.artifact_id == "artifact-uuid"

    def test_message_content_frozen(self):
        """Test that MessageContent is immutable (frozen dataclass)."""
        content = MessageContent(type=MessageType.TEXT, text="Hello")

        with pytest.raises(AttributeError):
            content.text = "Modified"  # Should raise because frozen=True
