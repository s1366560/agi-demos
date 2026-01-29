"""Session aggregates."""

from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass, field

from .entities import Session, SessionMessage, MessageRole


@dataclass(slots=True)
class SessionAggregate:
    """Session aggregate root managing session and its messages."""

    session: Session
    messages: List[SessionMessage] = field(default_factory=list)

    def add_message(
        self,
        message_id: str,
        role: MessageRole,
        content: str,
        metadata: Optional[dict] = None,
    ) -> SessionMessage:
        """Add a message to the session."""
        message = SessionMessage(
            id=message_id,
            session_id=self.session.id,
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self.messages.append(message)
        self.session.update_last_active()
        return message

    def get_messages(
        self,
        limit: Optional[int] = None,
        include_tools: bool = False,
    ) -> List[SessionMessage]:
        """Get messages from the session."""
        messages = self.messages

        if not include_tools:
            messages = [m for m in messages if m.role != MessageRole.TOOL]

        if limit:
            messages = messages[-limit:]

        return messages

    def get_last_user_message(self) -> Optional[SessionMessage]:
        """Get the last user message."""
        for message in reversed(self.messages):
            if message.role == MessageRole.USER:
                return message
        return None

    def get_message_history(self, limit: int = 50) -> List[dict[str, any]]:
        """Get message history in format suitable for LLM context."""
        messages = self.get_messages(limit=limit, include_tools=False)

        history = []
        for message in messages:
            history.append({
                "role": message.role.value,
                "content": message.content,
            })

        return history

    def terminate(self) -> None:
        """Terminate the session."""
        self.session.terminate()

    def is_empty(self) -> bool:
        """Check if session has any messages."""
        return len(self.messages) == 0

    def message_count(self) -> int:
        """Get total message count."""
        return len(self.messages)
