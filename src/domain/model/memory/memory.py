from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class Memory(Entity):
    project_id: str
    title: str
    content: str
    author_id: str
    content_type: str = "text"
    tags: List[str] = field(default_factory=list)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    version: int = 1
    collaborators: List[str] = field(default_factory=list)
    is_public: bool = False
    status: str = "ENABLED"
    processing_status: str = "PENDING"
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    @classmethod
    def create_id(cls) -> str:
        """Alias for generate_id() for backwards compatibility."""
        return cls.generate_id()
