from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class SourceType(str, Enum):
    TEXT = "text"
    JSON = "json"
    DOCUMENT = "document"
    API = "api"
    CONVERSATION = "conversation"


@dataclass(kw_only=True)
class Episode(Entity):
    content: str
    source_type: SourceType
    valid_at: datetime
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    status: str = "PENDING"
