from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

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
    name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    status: str = "PENDING"
