from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class MessageSenderType(str, Enum):
    HUMAN = "human"
    AGENT = "agent"


@dataclass(kw_only=True)
class WorkspaceMessage(Entity):
    workspace_id: str
    sender_id: str
    sender_type: MessageSenderType
    content: str
    mentions: list[str] = field(default_factory=list)
    parent_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.sender_id:
            raise ValueError("sender_id cannot be empty")
        if not self.content.strip():
            raise ValueError("content cannot be empty")
