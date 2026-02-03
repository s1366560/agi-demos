"""
Attachment Injector - Add attachment context to messages.

Responsibilities:
1. Generate attachment context prompts for LLM awareness
2. Format file metadata (filename, path, size, type)
3. Inject context into user messages
4. Prepare multimodal content arrays

Extracted from react_agent.py to follow Single Responsibility Principle.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.domain.ports.agent.context_manager_port import (
    AttachmentContent,
    AttachmentInjectorPort,
    AttachmentMetadata,
)

logger = logging.getLogger(__name__)


# Default attachment context template
DEFAULT_CONTEXT_TEMPLATE = """╔══════════════════════════════════════════════════════════════╗
║  📎 用户本次消息上传的文件 (CURRENT MESSAGE ATTACHMENTS)    ║
╚══════════════════════════════════════════════════════════════╝

{file_list}

⚠️ 重要提示:
1. 以上是用户在【本条消息】中上传的文件，不是历史文件
2. 文件已同步到沙箱，请直接使用【沙箱路径】访问
3. 如需读取文件内容，请使用 bash 工具执行: cat <沙箱路径>
4. 请勿猜测或修改路径，直接使用上面列出的沙箱路径

════════════════════════════════════════════════════════════════

"""

# Default file item template
DEFAULT_FILE_TEMPLATE = """  📄 文件名: {filename}
     沙箱路径: {sandbox_path}
     类型: {mime_type}
     大小: {size}"""


@dataclass
class AttachmentInjectorConfig:
    """Configuration for attachment injector."""

    # Context template with {file_list} placeholder
    context_template: str = DEFAULT_CONTEXT_TEMPLATE

    # File item template with placeholders
    file_template: str = DEFAULT_FILE_TEMPLATE

    # Separator between file items
    file_separator: str = "\n\n"

    # Default sandbox workspace path
    default_workspace: str = "/workspace"

    # Debug logging
    debug_logging: bool = False


class AttachmentInjector(AttachmentInjectorPort):
    """
    Injects attachment context into user messages.

    Implements AttachmentInjectorPort protocol.

    Features:
    - Generates structured context prompts
    - Formats file metadata for LLM
    - Handles multimodal content preparation
    - Customizable templates

    Example:
        injector = AttachmentInjector()
        context = injector.build_attachment_context(attachments)
        enhanced = injector.inject_into_message("Hello", attachments)
    """

    def __init__(self, config: Optional[AttachmentInjectorConfig] = None):
        """
        Initialize attachment injector.

        Args:
            config: Optional configuration. Uses defaults if None.
        """
        self.config = config or AttachmentInjectorConfig()
        self._debug = self.config.debug_logging

    def build_attachment_context(
        self, metadata_list: List[AttachmentMetadata]
    ) -> str:
        """
        Build attachment context prompt from metadata.

        Creates a structured prompt that informs the LLM about
        files uploaded in the current message.

        Args:
            metadata_list: List of attachment metadata

        Returns:
            Formatted context prompt, empty string if no attachments
        """
        if not metadata_list:
            return ""

        # Format each file
        file_lines = []
        for meta in metadata_list:
            file_line = self._format_file_metadata(meta)
            file_lines.append(file_line)

        # Build full context
        file_list = self.config.file_separator.join(file_lines)
        context = self.config.context_template.format(file_list=file_list)

        if self._debug:
            logger.debug(
                f"[AttachmentInjector] Built context for {len(metadata_list)} files"
            )

        return context

    def _format_file_metadata(self, meta: AttachmentMetadata) -> str:
        """
        Format a single file's metadata.

        Args:
            meta: Attachment metadata

        Returns:
            Formatted file description
        """
        return self.config.file_template.format(
            filename=meta.filename,
            sandbox_path=meta.sandbox_path,
            mime_type=meta.mime_type,
            size=meta.format_size(),
        )

    def inject_into_message(
        self,
        message: str,
        metadata_list: List[AttachmentMetadata],
    ) -> str:
        """
        Inject attachment context into user message.

        Prepends the attachment context to the message.

        Args:
            message: Original user message
            metadata_list: Attachment metadata to inject

        Returns:
            Enhanced message with attachment context prepended
        """
        context = self.build_attachment_context(metadata_list)
        if not context:
            return message

        if self._debug:
            filenames = [m.filename for m in metadata_list]
            logger.info(
                f"[AttachmentInjector] Injecting context for {len(metadata_list)} files: {filenames}"
            )

        return context + message

    def prepare_multimodal_content(
        self,
        text: str,
        attachments: List[AttachmentContent],
    ) -> List[Dict[str, Any]]:
        """
        Prepare multimodal content array for LLM.

        Converts text and attachments into OpenAI multimodal format.

        Args:
            text: Text content
            attachments: Attachment content items

        Returns:
            Content array in OpenAI multimodal format
        """
        content: List[Dict[str, Any]] = []

        # Add text first
        if text:
            content.append({"type": "text", "text": text})

        # Add each attachment
        for attachment in attachments:
            part = self._convert_attachment(attachment)
            if part:
                content.append(part)

        if self._debug:
            logger.debug(
                f"[AttachmentInjector] Prepared {len(content)} content parts "
                f"({1 if text else 0} text, {len(attachments)} attachments)"
            )

        return content

    def _convert_attachment(
        self, attachment: AttachmentContent
    ) -> Optional[Dict[str, Any]]:
        """
        Convert an attachment to content part.

        Args:
            attachment: Attachment content

        Returns:
            Content part dict or None
        """
        att_type = attachment.type

        if att_type == "image_url":
            if attachment.image_url:
                return {
                    "type": "image_url",
                    "image_url": attachment.image_url,
                }

        elif att_type == "image":
            if attachment.content:
                return {
                    "type": "image_url",
                    "image_url": {
                        "url": attachment.content,
                        "detail": attachment.detail,
                    },
                }

        elif att_type == "text":
            if attachment.content:
                filename = attachment.filename or "attachment"
                return {
                    "type": "text",
                    "text": (
                        f"\n\n--- Attached file: {filename} ---\n"
                        f"{attachment.content}\n"
                        f"--- End of file ---"
                    ),
                }

        return None

    def parse_metadata_from_dict(
        self, data: Dict[str, Any]
    ) -> AttachmentMetadata:
        """
        Parse attachment metadata from raw dict.

        Args:
            data: Raw metadata dict

        Returns:
            AttachmentMetadata instance
        """
        filename = data.get("filename", "unknown")
        sandbox_path = data.get(
            "sandbox_path", f"{self.config.default_workspace}/{filename}"
        )
        mime_type = data.get("mime_type", "application/octet-stream")
        size_bytes = data.get("size_bytes", 0)

        return AttachmentMetadata(
            filename=filename,
            sandbox_path=sandbox_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
        )

    def parse_metadata_list(
        self, data_list: Optional[List[Dict[str, Any]]]
    ) -> List[AttachmentMetadata]:
        """
        Parse multiple attachment metadata from raw dicts.

        Args:
            data_list: List of raw metadata dicts

        Returns:
            List of AttachmentMetadata instances
        """
        if not data_list:
            return []
        return [self.parse_metadata_from_dict(d) for d in data_list]

    def parse_content_from_dict(self, data: Dict[str, Any]) -> AttachmentContent:
        """
        Parse attachment content from raw dict.

        Args:
            data: Raw content dict

        Returns:
            AttachmentContent instance
        """
        return AttachmentContent(
            type=data.get("type", ""),
            content=data.get("content") or data.get("text"),
            filename=data.get("filename"),
            detail=data.get("detail", "auto"),
            image_url=data.get("image_url"),
        )

    def parse_content_list(
        self, data_list: Optional[List[Dict[str, Any]]]
    ) -> List[AttachmentContent]:
        """
        Parse multiple attachment contents from raw dicts.

        Args:
            data_list: List of raw content dicts

        Returns:
            List of AttachmentContent instances
        """
        if not data_list:
            return []
        return [self.parse_content_from_dict(d) for d in data_list]
