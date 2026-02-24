"""
Context Manager Port - Domain layer interface for context management.

Defines contracts for:
1. MessageBuilder - Converting domain messages to LLM format
2. AttachmentInjector - Adding attachment context to messages
3. ContextManager - Full context window management (facade)

Following hexagonal architecture: domain layer depends only on ports.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from src.domain.model.agent.conversation.context_summary import ContextSummary


class CompressionStrategy(str, Enum):
    """Context compression strategy."""

    NONE = "none"
    TRUNCATE = "truncate"
    SUMMARIZE = "summarize"


@dataclass
class AttachmentMetadata:
    """Metadata for a file attachment."""

    filename: str
    sandbox_path: str
    mime_type: str = "application/octet-stream"
    size_bytes: int = 0

    def format_size(self) -> str:
        """Format size for display."""
        if self.size_bytes < 1024:
            return f"{self.size_bytes} bytes"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        else:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"


@dataclass
class AttachmentContent:
    """Content of an attachment for LLM."""

    type: str  # "image_url", "image", "text"
    content: str | None = None  # Base64 data URL or text content
    filename: str | None = None
    detail: str = "auto"  # For images: "auto", "low", "high"
    image_url: dict[str, Any] | None = None  # OpenAI image_url format


@dataclass
class MessageInput:
    """Input message from conversation history."""

    role: str  # "user", "assistant", "system", "tool"
    content: str
    name: str | None = None  # For tool messages
    tool_call_id: str | None = None  # For tool response messages
    tool_calls: list[dict[str, Any]] | None = None  # For assistant with tool calls


@dataclass
class ContextBuildRequest:
    """Request to build context window."""

    system_prompt: str
    conversation_context: list[dict[str, Any]]  # Raw conversation messages
    user_message: str
    attachment_metadata: list[dict[str, Any]] | None = None
    attachment_content: list[dict[str, Any]] | None = None
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None
    # HITL resume flag: when True, skip adding user_message as it's already in conversation_context
    is_hitl_resume: bool = False
    # Cached context summary from previous turns
    context_summary: ContextSummary | None = None
    # LLM client for compression summarization (Optional[Any] to avoid infrastructure dependency)
    llm_client: Any | None = None


@dataclass
class ContextBuildResult:
    """Result of context window building."""

    messages: list[dict[str, Any]]  # Messages ready for LLM
    was_compressed: bool = False
    compression_strategy: CompressionStrategy = CompressionStrategy.NONE
    original_message_count: int = 0
    final_message_count: int = 0
    estimated_tokens: int = 0
    token_budget: int = 0
    budget_utilization_pct: float = 0.0
    summary: str | None = None
    summarized_message_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_event_data(self) -> dict[str, Any]:
        """Convert to SSE event data."""
        data = {
            "was_compressed": self.was_compressed,
            "compression_strategy": self.compression_strategy.value,
            "original_message_count": self.original_message_count,
            "final_message_count": self.final_message_count,
            "estimated_tokens": self.estimated_tokens,
            "token_budget": self.token_budget,
            "budget_utilization_pct": round(self.budget_utilization_pct, 2),
            "summarized_message_count": self.summarized_message_count,
        }
        if self.metadata.get("compression_history"):
            data["compression_history_summary"] = self.metadata["compression_history"]
        if self.metadata.get("compression_level"):
            data["compression_level"] = self.metadata["compression_level"]
        return data


@runtime_checkable
class MessageBuilderPort(Protocol):
    """
    Port for building LLM-ready messages from conversation context.

    Responsibilities:
    - Convert domain messages to OpenAI format
    - Handle multimodal content (text + images)
    - Maintain message structure consistency
    """

    def convert_to_openai_format(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert conversation messages to OpenAI message format.

        Args:
            messages: Raw conversation messages

        Returns:
            Messages in OpenAI format
        """
        ...

    def build_user_message(
        self,
        text: str,
        attachments: list[AttachmentContent] | None = None,
    ) -> dict[str, Any]:
        """
        Build a user message with optional multimodal content.

        Args:
            text: User message text
            attachments: Optional attachment content (images, text files)

        Returns:
            User message in OpenAI format
        """
        ...

    def build_system_message(self, prompt: str) -> dict[str, Any]:
        """
        Build a system message.

        Args:
            prompt: System prompt text

        Returns:
            System message in OpenAI format
        """
        ...


@runtime_checkable
class AttachmentInjectorPort(Protocol):
    """
    Port for injecting attachment context into messages.

    Responsibilities:
    - Generate attachment context prompts
    - Format file metadata for LLM awareness
    - Handle different attachment types
    """

    def build_attachment_context(self, metadata_list: list[AttachmentMetadata]) -> str:
        """
        Build attachment context prompt from metadata.

        Args:
            metadata_list: List of attachment metadata

        Returns:
            Formatted context prompt for LLM
        """
        ...

    def inject_into_message(
        self,
        message: str,
        metadata_list: list[AttachmentMetadata],
    ) -> str:
        """
        Inject attachment context into user message.

        Args:
            message: Original user message
            metadata_list: Attachment metadata to inject

        Returns:
            Enhanced message with attachment context
        """
        ...

    def prepare_multimodal_content(
        self,
        text: str,
        attachments: list[AttachmentContent],
    ) -> list[dict[str, Any]]:
        """
        Prepare multimodal content array for LLM.

        Args:
            text: Text content
            attachments: Attachment content items

        Returns:
            Content array in OpenAI multimodal format
        """
        ...


@runtime_checkable
class ContextManagerPort(Protocol):
    """
    Port for full context window management (facade).

    Responsibilities:
    - Build complete context window for LLM calls
    - Handle compression when context exceeds limits
    - Coordinate message building and attachment injection
    """

    async def build_context(self, request: ContextBuildRequest) -> ContextBuildResult:
        """
        Build context window from conversation and attachments.

        This is the main entry point for context management.
        Handles message conversion, attachment injection, and compression.

        Args:
            request: Context build request with all inputs

        Returns:
            Context build result with LLM-ready messages
        """
        ...

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        ...

    def estimate_message_tokens(self, message: dict[str, Any]) -> int:
        """
        Estimate token count for a message.

        Args:
            message: Message in OpenAI format

        Returns:
            Estimated token count
        """
        ...


@runtime_checkable
class ContextSummaryPort(Protocol):
    """Port for persisting and retrieving context summaries.

    Summaries are stored as cache alongside original events.
    They can be regenerated if missing or stale.
    """

    async def get_summary(self, conversation_id: str) -> ContextSummary | None:
        """Get cached context summary for a conversation."""
        ...

    async def save_summary(self, conversation_id: str, summary: ContextSummary) -> None:
        """Save context summary to conversation metadata."""
        ...

    async def invalidate_summary(self, conversation_id: str) -> None:
        """Remove cached summary (forces re-generation on next turn)."""
        ...
