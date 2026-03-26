from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from src.domain.shared_kernel import Entity


class CyberGeneCategory(str, Enum):
    SKILL = "skill"
    KNOWLEDGE = "knowledge"
    TOOL = "tool"
    WORKFLOW = "workflow"


@dataclass(kw_only=True)
class CyberGene(Entity):
    """A gene/skill package that can be assigned to workspace agents."""

    workspace_id: str
    name: str
    category: CyberGeneCategory = CyberGeneCategory.SKILL
    description: str | None = None
    config_json: str | None = None
    version: str = "1.0.0"
    is_active: bool = True
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.name.strip():
            raise ValueError("name cannot be empty")
