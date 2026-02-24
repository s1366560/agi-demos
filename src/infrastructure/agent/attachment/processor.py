"""
Attachment Processor - Unified attachment handling for ReActAgent.

This module provides centralized attachment processing logic, extracted from
ReActAgent to support the Single Responsibility Principle.

Handles:
- Building attachment context prompts for LLM awareness
- Processing multimodal content (images, text files)
- Formatting file metadata for user messages
- Constructing LLM-compatible message content

Reference: Extracted from react_agent.py::stream() attachment handling (lines 780-882)
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProcessedAttachment:
    """
    Represents a processed attachment ready for LLM consumption.

    Attributes:
        type: Attachment type ('image_url', 'text', etc.)
        content: Content data (base64 URL, text content, etc.)
        filename: Original filename
        metadata: Additional metadata
    """

    type: str
    content: Any
    filename: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_llm_content(self) -> dict[str, Any]:
        """Convert to LLM-compatible content format."""
        if self.type == "image_url":
            return {
                "type": "image_url",
                "image_url": self.content,
            }
        elif self.type == "text":
            return {
                "type": "text",
                "text": f"\n\n--- Attached file: {self.filename} ---\n{self.content}\n--- End of file ---",
            }
        else:
            # Fallback for unknown types
            return {
                "type": "text",
                "text": f"\n\n--- Attached file: {self.filename} (type: {self.type}) ---\n{self.content!s}\n--- End of file ---",
            }


@dataclass
class AttachmentContext:
    """
    Represents the full context of attachments for a message.

    Attributes:
        context_prompt: Human-readable context prompt about attachments
        processed_attachments: List of processed attachments for LLM
        file_count: Number of files attached
        total_size_bytes: Total size of all attachments
    """

    context_prompt: str = ""
    processed_attachments: list[ProcessedAttachment] = field(default_factory=list)
    file_count: int = 0
    total_size_bytes: int = 0

    @property
    def has_attachments(self) -> bool:
        """Check if there are any attachments."""
        return self.file_count > 0 or len(self.processed_attachments) > 0


class AttachmentProcessor:
    """
    Unified attachment processor for ReActAgent.

    Handles all attachment-related processing including:
    - Building context prompts that inform the LLM about uploaded files
    - Processing different attachment types (images, text)
    - Formatting messages with multimodal content

    Usage:
        processor = AttachmentProcessor()

        # Process attachments and build context
        context = processor.build_context(
            attachment_metadata=[{"filename": "doc.pdf", "sandbox_path": "/workspace/doc.pdf"}],
            attachment_content=[{"type": "text", "text": "...", "filename": "doc.pdf"}]
        )

        # Build final user message
        message = processor.build_user_message(
            user_message="Please analyze this file",
            context=context
        )
    """

    # Template for attachment context prompt
    CONTEXT_TEMPLATE = (
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  📎 用户本次消息上传的文件 (CURRENT MESSAGE ATTACHMENTS)    ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n\n"
        "{file_lines}\n\n"
        "⚠️ 重要提示:\n"
        "1. 以上是用户在【本条消息】中上传的文件，不是历史文件\n"
        "2. 文件已同步到沙箱，请直接使用【沙箱路径】访问\n"
        "3. 如需读取文件内容，请使用 bash 工具执行: cat <沙箱路径>\n"
        "4. 请勿猜测或修改路径，直接使用上面列出的沙箱路径\n\n"
        "════════════════════════════════════════════════════════════════\n\n"
    )

    def __init__(self, debug_logging: bool = False) -> None:
        """
        Initialize the attachment processor.

        Args:
            debug_logging: Whether to enable debug logging
        """
        self._debug_logging = debug_logging

    def build_context(
        self,
        attachment_metadata: list[dict[str, Any]] | None = None,
        attachment_content: list[dict[str, Any]] | None = None,
    ) -> AttachmentContext:
        """
        Build attachment context from metadata and content.

        Args:
            attachment_metadata: List of attachment metadata dicts containing
                                 filename, sandbox_path, mime_type, size_bytes
            attachment_content: List of attachment content dicts for LLM
                               (image_url, text, etc.)

        Returns:
            AttachmentContext with processed information
        """
        context = AttachmentContext()

        # Process metadata into context prompt
        if attachment_metadata:
            context.context_prompt = self._build_context_prompt(attachment_metadata)
            context.file_count = len(attachment_metadata)
            context.total_size_bytes = sum(
                m.get("size_bytes", 0) for m in attachment_metadata
            )

        # Process content into LLM-compatible format
        if attachment_content:
            context.processed_attachments = self._process_content(attachment_content)

        if self._debug_logging and context.has_attachments:
            logger.info(
                f"[AttachmentProcessor] Built context: {context.file_count} files, "
                f"{len(context.processed_attachments)} processed attachments"
            )

        return context

    def _build_context_prompt(
        self, attachment_metadata: list[dict[str, Any]]
    ) -> str:
        """
        Build human-readable context prompt from metadata.

        Args:
            attachment_metadata: List of attachment metadata

        Returns:
            Formatted context prompt string
        """
        file_lines = []

        for meta in attachment_metadata:
            filename = meta.get("filename", "unknown")
            sandbox_path = meta.get("sandbox_path", f"/workspace/{filename}")
            mime_type = meta.get("mime_type", "unknown")
            size_bytes = meta.get("size_bytes", 0)

            # Format file size for readability
            size_str = self._format_size(size_bytes)

            file_lines.append(
                f"  📄 文件名: {filename}\n"
                f"     沙箱路径: {sandbox_path}\n"
                f"     类型: {mime_type}\n"
                f"     大小: {size_str}"
            )

        if not file_lines:
            return ""

        logger.info(
            f"[AttachmentProcessor] Building context for {len(file_lines)} files: "
            f"{[m.get('filename') for m in attachment_metadata]}"
        )

        return self.CONTEXT_TEMPLATE.format(file_lines="\n\n".join(file_lines))

    def _format_size(self, size_bytes: int) -> str:
        """Format file size for human readability."""
        if size_bytes < 1024:
            return f"{size_bytes} bytes"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

    def _process_content(
        self, attachment_content: list[dict[str, Any]]
    ) -> list[ProcessedAttachment]:
        """
        Process attachment content into LLM-compatible format.

        Args:
            attachment_content: Raw attachment content list

        Returns:
            List of ProcessedAttachment objects
        """
        processed = []

        for attachment in attachment_content:
            att_type = attachment.get("type", "")

            if att_type == "image_url":
                # Image attachment from attachment_service.prepare_for_llm
                image_url_data = attachment.get("image_url", {})
                if image_url_data:
                    processed.append(
                        ProcessedAttachment(
                            type="image_url",
                            content=image_url_data,
                            filename=attachment.get("filename", "image"),
                            metadata={"source": "image_url"},
                        )
                    )

            elif att_type == "image":
                # Legacy format: image attachment with base64 data URL
                image_url = attachment.get("content", "")
                if image_url:
                    processed.append(
                        ProcessedAttachment(
                            type="image_url",
                            content={
                                "url": image_url,
                                "detail": attachment.get("detail", "auto"),
                            },
                            filename=attachment.get("filename", "image"),
                            metadata={"source": "legacy_image"},
                        )
                    )

            elif att_type == "text":
                # Text attachment: append as text content
                text_content = attachment.get("text", "") or attachment.get("content", "")
                if text_content:
                    processed.append(
                        ProcessedAttachment(
                            type="text",
                            content=text_content,
                            filename=attachment.get("filename", "attachment"),
                            metadata={"source": "text_file"},
                        )
                    )

        return processed

    def build_user_message(
        self,
        user_message: str,
        context: AttachmentContext,
    ) -> dict[str, Any]:
        """
        Build the final user message with attachment context.

        Args:
            user_message: Original user message text
            context: AttachmentContext from build_context()

        Returns:
            Dict with 'role' and 'content' ready for LLM
        """
        # Prepend attachment context to user message
        enhanced_message = context.context_prompt + user_message

        if context.processed_attachments:
            # Build multimodal content array
            user_content: list[dict[str, Any]] = [
                {"type": "text", "text": enhanced_message}
            ]

            for attachment in context.processed_attachments:
                user_content.append(attachment.to_llm_content())

            logger.info(
                f"[AttachmentProcessor] Added {len(context.processed_attachments)} "
                f"attachments to user message"
            )

            return {
                "role": "user",
                "content": user_content,
            }
        else:
            return {
                "role": "user",
                "content": enhanced_message,
            }

    def enhance_message_with_context(
        self,
        user_message: str,
        attachment_metadata: list[dict[str, Any]] | None = None,
        attachment_content: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Convenience method: build context and user message in one call.

        Args:
            user_message: Original user message
            attachment_metadata: Optional attachment metadata
            attachment_content: Optional attachment content

        Returns:
            Dict with 'role' and 'content' ready for LLM
        """
        context = self.build_context(attachment_metadata, attachment_content)
        return self.build_user_message(user_message, context)


# Module-level singleton for convenience
_default_processor: AttachmentProcessor | None = None


def get_attachment_processor() -> AttachmentProcessor:
    """Get the default attachment processor singleton."""
    global _default_processor
    if _default_processor is None:
        _default_processor = AttachmentProcessor()
    return _default_processor


def set_attachment_processor(processor: AttachmentProcessor) -> None:
    """Set the default attachment processor singleton."""
    global _default_processor
    _default_processor = processor
