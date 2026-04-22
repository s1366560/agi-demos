"""Conversation bounded context - conversations, messages, and attachments."""

from src.domain.model.agent.conversation.attachment import (
    Attachment,
    AttachmentMetadata,
    AttachmentPurpose,
    AttachmentStatus,
)
from src.domain.model.agent.conversation.conversation import Conversation, ConversationStatus
from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.domain.model.agent.conversation.errors import (
    ConversationDomainError,
    CoordinatorRequiredError,
    MentionsInvalidError,
    ParticipantAlreadyPresentError,
    ParticipantLimitError,
    ParticipantNotPresentError,
    SenderNotInRosterError,
)
from src.domain.model.agent.conversation.message import (
    Message,
    MessageRole,
    MessageType,
    ToolCall,
    ToolResult,
)

__all__ = [
    "Attachment",
    "AttachmentMetadata",
    "AttachmentPurpose",
    "AttachmentStatus",
    "Conversation",
    "ConversationDomainError",
    "ConversationMode",
    "ConversationStatus",
    "CoordinatorRequiredError",
    "MentionsInvalidError",
    "Message",
    "MessageRole",
    "MessageType",
    "ParticipantAlreadyPresentError",
    "ParticipantLimitError",
    "ParticipantNotPresentError",
    "SenderNotInRosterError",
    "ToolCall",
    "ToolResult",
]
