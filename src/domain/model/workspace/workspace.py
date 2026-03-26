from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class Workspace(Entity):
    """Business collaboration workspace with optional CyberOffice capabilities."""

    tenant_id: str
    project_id: str
    name: str
    created_by: str
    description: str | None = None
    is_archived: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    office_status: str = "inactive"
    hex_layout_config: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.project_id:
            raise ValueError("project_id cannot be empty")
        if not self.name.strip():
            raise ValueError("name cannot be empty")
        if not self.created_by:
            raise ValueError("created_by cannot be empty")
