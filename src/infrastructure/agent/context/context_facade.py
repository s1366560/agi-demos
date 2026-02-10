"""
Context Facade - Unified entry point for context management.

Combines:
1. MessageBuilder - Message format conversion
2. AttachmentInjector - Attachment context injection
3. ContextWindowManager - Token budgeting and compression

This facade simplifies context management for ReActAgent by providing
a single, coherent interface for all context-related operations.

Follows Facade pattern to reduce coupling with infrastructure details.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.domain.ports.agent.context_manager_port import (
    CompressionStrategy,
    ContextBuildRequest,
    ContextBuildResult,
    ContextManagerPort,
)
from src.infrastructure.agent.context.builder.attachment_injector import (
    AttachmentInjector,
    AttachmentInjectorConfig,
)
from src.infrastructure.agent.context.builder.message_builder import (
    MessageBuilder,
    MessageBuilderConfig,
)
from src.infrastructure.agent.context.window_manager import (
    ContextWindowConfig,
    ContextWindowManager,
    ContextWindowResult,
)

logger = logging.getLogger(__name__)


@dataclass
class ContextFacadeConfig:
    """Configuration for context facade."""

    # Message builder config
    message_builder: Optional[MessageBuilderConfig] = None

    # Attachment injector config
    attachment_injector: Optional[AttachmentInjectorConfig] = None

    # Context window config
    context_window: Optional[ContextWindowConfig] = None

    # Debug logging
    debug_logging: bool = False


class ContextFacade(ContextManagerPort):
    """
    Unified facade for context management operations.

    Implements ContextManagerPort protocol.

    Coordinates:
    - MessageBuilder for format conversion
    - AttachmentInjector for attachment context
    - ContextWindowManager for token budgeting

    Example:
        facade = ContextFacade()
        result = await facade.build_context(ContextBuildRequest(
            system_prompt="You are helpful.",
            conversation_context=[...],
            user_message="Hello",
            attachment_metadata=[...],
        ))
        # result.messages is ready for LLM
    """

    def __init__(
        self,
        config: Optional[ContextFacadeConfig] = None,
        message_builder: Optional[MessageBuilder] = None,
        attachment_injector: Optional[AttachmentInjector] = None,
        window_manager: Optional[ContextWindowManager] = None,
    ):
        """
        Initialize context facade.

        Args:
            config: Optional configuration
            message_builder: Optional pre-configured builder
            attachment_injector: Optional pre-configured injector
            window_manager: Optional pre-configured window manager
        """
        self.config = config or ContextFacadeConfig()
        self._debug = self.config.debug_logging

        # Initialize components
        self._message_builder = message_builder or MessageBuilder(self.config.message_builder)
        self._attachment_injector = attachment_injector or AttachmentInjector(
            self.config.attachment_injector
        )
        self._window_manager = window_manager or ContextWindowManager(self.config.context_window)

    @property
    def message_builder(self) -> MessageBuilder:
        """Get message builder instance."""
        return self._message_builder

    @property
    def attachment_injector(self) -> AttachmentInjector:
        """Get attachment injector instance."""
        return self._attachment_injector

    @property
    def window_manager(self) -> ContextWindowManager:
        """Get window manager instance."""
        return self._window_manager

    async def build_context(self, request: ContextBuildRequest) -> ContextBuildResult:
        """
        Build complete context window from request.

        Steps:
        1. Convert conversation to OpenAI format
        2. Parse attachment metadata/content
        3. Inject attachment context into user message
        4. Build user message (with multimodal if needed)
        5. Apply context window compression

        Args:
            request: Context build request

        Returns:
            Context build result with LLM-ready messages
        """
        if self._debug:
            logger.debug(
                f"[ContextFacade] Building context: "
                f"{len(request.conversation_context)} history msgs, "
                f"{len(request.attachment_metadata or [])} attachments"
            )

        # Step 1: Convert conversation context to OpenAI format
        context_messages = self._message_builder.convert_to_openai_format(
            request.conversation_context
        )

        # Step 1.5: Inject cached summary as conversation history prefix
        if request.context_summary and request.context_summary.summary_text:
            summary_msg = {
                "role": "system",
                "content": (
                    f"[Previous conversation summary - covers "
                    f"{request.context_summary.messages_covered_count} earlier messages]\n\n"
                    f"{request.context_summary.summary_text}"
                ),
            }
            context_messages.insert(0, summary_msg)
            if self._debug:
                logger.info(
                    f"[ContextFacade] Injected cached summary: "
                    f"{request.context_summary.summary_tokens} tokens, "
                    f"covers {request.context_summary.messages_covered_count} messages"
                )

        # Step 2: Parse attachment metadata and content
        attachment_metadata = self._attachment_injector.parse_metadata_list(
            request.attachment_metadata
        )
        attachment_content = self._attachment_injector.parse_content_list(
            request.attachment_content
        )

        # Step 3: Inject attachment context into user message
        enhanced_message = request.user_message
        if attachment_metadata:
            enhanced_message = self._attachment_injector.inject_into_message(
                request.user_message, attachment_metadata
            )
            if self._debug:
                logger.info(
                    f"[ContextFacade] Injected context for {len(attachment_metadata)} attachments"
                )

        # Step 4: Build user message
        if attachment_content:
            # Multimodal message with attachments
            user_message = self._message_builder.build_user_message(
                text=enhanced_message,
                attachments=attachment_content,
            )
            if self._debug:
                logger.info(
                    f"[ContextFacade] Built multimodal message with "
                    f"{len(attachment_content)} content items"
                )
        else:
            # Simple text message
            user_message = self._message_builder.build_user_message(text=enhanced_message)

        # Add user message to context (skip for HITL resume as it's already in context)
        if not request.is_hitl_resume:
            context_messages.append(user_message)
        elif self._debug:
            logger.debug("[ContextFacade] Skipping user message append for HITL resume")

        # Step 5: Apply context window management
        window_result = await self._window_manager.build_context_window(
            system_prompt=request.system_prompt,
            messages=context_messages,
            llm_client=None,  # TODO: Pass LLM client for summary generation
        )

        # Convert to domain result
        return self._convert_window_result(window_result)

    def _convert_window_result(self, window_result: ContextWindowResult) -> ContextBuildResult:
        """
        Convert ContextWindowResult to ContextBuildResult.

        Args:
            window_result: Result from window manager

        Returns:
            Domain context build result
        """
        # Map compression strategy
        strategy = CompressionStrategy.NONE
        if window_result.compression_strategy.value == "truncate":
            strategy = CompressionStrategy.TRUNCATE
        elif window_result.compression_strategy.value == "summarize":
            strategy = CompressionStrategy.SUMMARIZE

        return ContextBuildResult(
            messages=window_result.messages,
            was_compressed=window_result.was_compressed,
            compression_strategy=strategy,
            original_message_count=window_result.original_message_count,
            final_message_count=window_result.final_message_count,
            estimated_tokens=window_result.estimated_tokens,
            token_budget=window_result.token_budget,
            budget_utilization_pct=window_result.budget_utilization_pct,
            summary=window_result.summary,
            summarized_message_count=window_result.summarized_message_count,
            metadata=window_result.metadata,
        )

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        return self._window_manager.estimate_tokens(text)

    def estimate_message_tokens(self, message: Dict[str, Any]) -> int:
        """
        Estimate token count for a message.

        Args:
            message: Message in OpenAI format

        Returns:
            Estimated token count
        """
        return self._window_manager.estimate_message_tokens(message)

    def estimate_messages_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """
        Estimate total tokens for messages.

        Args:
            messages: Messages in OpenAI format

        Returns:
            Total estimated tokens
        """
        return self._window_manager.estimate_messages_tokens(messages)

    def build_simple_context(
        self,
        system_prompt: str,
        conversation: List[Dict[str, Any]],
        user_message: str,
    ) -> List[Dict[str, Any]]:
        """
        Build context without compression (synchronous).

        Convenience method for simple use cases where
        compression is not needed.

        Args:
            system_prompt: System prompt
            conversation: Conversation history
            user_message: Current user message

        Returns:
            Messages ready for LLM
        """
        # Convert conversation
        messages = self._message_builder.convert_to_openai_format(conversation)

        # Add user message
        messages.append(self._message_builder.build_user_message(user_message))

        # Add system prompt at beginning
        messages.insert(0, self._message_builder.build_system_message(system_prompt))

        return messages

    def update_config(
        self,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> None:
        """
        Update context window configuration.

        Args:
            max_context_tokens: New max context tokens
            max_output_tokens: New max output tokens
        """
        if max_context_tokens is not None:
            self._window_manager.config.max_context_tokens = max_context_tokens
        if max_output_tokens is not None:
            self._window_manager.config.max_output_tokens = max_output_tokens

        if self._debug:
            logger.debug(
                f"[ContextFacade] Updated config: "
                f"max_context={self._window_manager.config.max_context_tokens}, "
                f"max_output={self._window_manager.config.max_output_tokens}"
            )
