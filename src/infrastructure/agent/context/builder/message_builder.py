"""
Message Builder - Convert domain messages to LLM-ready format.

Responsibilities:
1. Convert conversation messages to OpenAI format
2. Build multimodal user messages (text + images)
3. Handle different message roles and structures
4. Maintain message structure consistency

Extracted from react_agent.py to follow Single Responsibility Principle.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.domain.ports.agent.context_manager_port import (
    AttachmentContent,
    MessageBuilderPort,
)

logger = logging.getLogger(__name__)


@dataclass
class MessageBuilderConfig:
    """Configuration for message builder."""

    # Default role when not specified
    default_role: str = "user"

    # Content key names in messages
    content_key: str = "content"
    role_key: str = "role"

    # Maximum text length before truncation warning
    max_text_length: int = 100_000

    # Debug logging
    debug_logging: bool = False


class MessageBuilder(MessageBuilderPort):
    """
    Builds LLM-ready messages from conversation context.

    Implements MessageBuilderPort protocol.

    Features:
    - OpenAI message format conversion
    - Multimodal content (text + images)
    - Role normalization
    - Content validation

    Example:
        builder = MessageBuilder()
        messages = builder.convert_to_openai_format(conversation_context)
        user_msg = builder.build_user_message("Hello", attachments=[...])
    """

    def __init__(self, config: Optional[MessageBuilderConfig] = None):
        """
        Initialize message builder.

        Args:
            config: Optional configuration. Uses defaults if None.
        """
        self.config = config or MessageBuilderConfig()
        self._debug = self.config.debug_logging

    def convert_to_openai_format(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert conversation messages to OpenAI message format.

        Handles:
        - Role normalization (user, assistant, system, tool)
        - Content extraction
        - Missing field defaults

        Args:
            messages: Raw conversation messages

        Returns:
            Messages in OpenAI format
        """
        if not messages:
            return []

        result = []
        for msg in messages:
            converted = self._convert_single_message(msg)
            if converted:
                result.append(converted)

        if self._debug:
            logger.debug(f"[MessageBuilder] Converted {len(messages)} -> {len(result)} messages")

        return result

    def _convert_single_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert a single message to OpenAI format.

        Args:
            msg: Raw message dict

        Returns:
            Converted message or None if invalid
        """
        if not msg:
            return None

        role = msg.get(self.config.role_key, self.config.default_role)
        content = msg.get(self.config.content_key, "")

        # Normalize role
        role = self._normalize_role(role)

        # Handle empty content
        if content is None:
            content = ""

        # Build base message
        converted = {"role": role, "content": content}

        # Copy additional fields for tool messages
        if role == "tool":
            if "tool_call_id" in msg:
                converted["tool_call_id"] = msg["tool_call_id"]
            if "name" in msg:
                converted["name"] = msg["name"]

        # Copy tool_calls for assistant messages
        if role == "assistant" and "tool_calls" in msg:
            converted["tool_calls"] = msg["tool_calls"]

        return converted

    def _normalize_role(self, role: str) -> str:
        """
        Normalize message role to valid OpenAI role.

        Args:
            role: Raw role string

        Returns:
            Normalized role (user, assistant, system, tool)
        """
        role = str(role).lower().strip()

        # Map common variations
        role_mapping = {
            "human": "user",
            "ai": "assistant",
            "bot": "assistant",
            "model": "assistant",
            "function": "tool",
        }

        return role_mapping.get(role, role)

    def build_user_message(
        self,
        text: str,
        attachments: Optional[List[AttachmentContent]] = None,
    ) -> Dict[str, Any]:
        """
        Build a user message with optional multimodal content.

        Handles:
        - Text-only messages
        - Multimodal messages (text + images)
        - Different attachment types (image_url, image, text)

        Args:
            text: User message text
            attachments: Optional attachment content

        Returns:
            User message in OpenAI format
        """
        if not attachments:
            return {"role": "user", "content": text}

        # Build multimodal content array
        content = self._build_multimodal_content(text, attachments)

        if self._debug:
            logger.debug(f"[MessageBuilder] Built multimodal message with {len(attachments)} attachments")

        return {"role": "user", "content": content}

    def _build_multimodal_content(
        self,
        text: str,
        attachments: List[AttachmentContent],
    ) -> List[Dict[str, Any]]:
        """
        Build multimodal content array for LLM.

        Args:
            text: Text content
            attachments: Attachment content items

        Returns:
            Content array in OpenAI multimodal format
        """
        content: List[Dict[str, Any]] = []

        # Add text part first
        if text:
            content.append({"type": "text", "text": text})

        # Add attachments
        for attachment in attachments:
            part = self._convert_attachment_to_content_part(attachment)
            if part:
                content.append(part)

        return content

    def _convert_attachment_to_content_part(
        self, attachment: AttachmentContent
    ) -> Optional[Dict[str, Any]]:
        """
        Convert attachment to OpenAI content part.

        Handles:
        - image_url: Direct OpenAI image_url format
        - image: Legacy format with base64 data URL
        - text: Text file content

        Args:
            attachment: Attachment content

        Returns:
            Content part dict or None if invalid
        """
        att_type = attachment.type

        if att_type == "image_url":
            # Modern format from attachment_service.prepare_for_llm
            if attachment.image_url:
                return {
                    "type": "image_url",
                    "image_url": attachment.image_url,
                }

        elif att_type == "image":
            # Legacy format: base64 data URL
            if attachment.content:
                return {
                    "type": "image_url",
                    "image_url": {
                        "url": attachment.content,
                        "detail": attachment.detail,
                    },
                }

        elif att_type == "text":
            # Text file content
            text_content = attachment.content
            if text_content:
                filename = attachment.filename or "attachment"
                return {
                    "type": "text",
                    "text": f"\n\n--- Attached file: {filename} ---\n{text_content}\n--- End of file ---",
                }

        return None

    def build_system_message(self, prompt: str) -> Dict[str, Any]:
        """
        Build a system message.

        Args:
            prompt: System prompt text

        Returns:
            System message in OpenAI format
        """
        return {"role": "system", "content": prompt}

    def build_assistant_message(
        self,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Build an assistant message with optional tool calls.

        Args:
            content: Assistant response text
            tool_calls: Optional tool calls made by assistant

        Returns:
            Assistant message in OpenAI format
        """
        message: Dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    def build_tool_message(
        self,
        tool_call_id: str,
        name: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Build a tool response message.

        Args:
            tool_call_id: ID of the tool call being responded to
            name: Name of the tool
            content: Tool execution result

        Returns:
            Tool message in OpenAI format
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content,
        }

    def validate_messages(self, messages: List[Dict[str, Any]]) -> List[str]:
        """
        Validate messages for common issues.

        Args:
            messages: Messages to validate

        Returns:
            List of validation warning messages
        """
        warnings = []

        for i, msg in enumerate(messages):
            # Check for missing role
            if "role" not in msg:
                warnings.append(f"Message {i}: missing 'role' field")

            # Check for missing content
            if "content" not in msg:
                warnings.append(f"Message {i}: missing 'content' field")

            # Check for invalid role
            role = msg.get("role", "")
            if role not in ("user", "assistant", "system", "tool"):
                warnings.append(f"Message {i}: invalid role '{role}'")

            # Check for overly long content
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > self.config.max_text_length:
                warnings.append(
                    f"Message {i}: content exceeds {self.config.max_text_length} chars"
                )

        return warnings

    def count_messages_by_role(
        self, messages: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Count messages by role.

        Args:
            messages: Messages to count

        Returns:
            Dict mapping role to count
        """
        counts: Dict[str, int] = {}
        for msg in messages:
            role = msg.get("role", "unknown")
            counts[role] = counts.get(role, 0) + 1
        return counts
