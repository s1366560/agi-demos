from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class Memory(Entity):
    project_id: str
    title: str
    content: str
    author_id: str
    content_type: str = "text"
    tags: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1
    collaborators: list[str] = field(default_factory=list)
    is_public: bool = False
    status: str = "ENABLED"
    processing_status: str = "PENDING"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    @classmethod
    def create_id(cls) -> str:
        """Alias for generate_id() for backwards compatibility."""
        return cls.generate_id()
