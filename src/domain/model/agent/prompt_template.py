"""Domain model for PromptTemplate."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, kw_only=True)
class TemplateVariable:
    """A variable placeholder in a prompt template."""

    name: str
    description: str = ""
    default_value: str = ""
    required: bool = False


@dataclass(kw_only=True)
class PromptTemplate:
    """Reusable prompt template with variable interpolation."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    project_id: str | None = None
    created_by: str

    title: str
    content: str
    category: str = "general"
    variables: list[TemplateVariable] = field(default_factory=list)
    is_system: bool = False
    usage_count: int = 0

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def increment_usage(self) -> None:
        """Record a template usage."""
        self.usage_count += 1
        self.updated_at = datetime.now(UTC)
