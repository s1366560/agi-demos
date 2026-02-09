"""
SkillVersion entity for skill version history.

Stores a complete snapshot of a skill at a specific point in time,
including SKILL.md content and all resource files.

Each skill_sync call creates a new SkillVersion entry.
Rollbacks create a new version entry with created_by="rollback".
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(kw_only=True)
class SkillVersion:
    """
    A versioned snapshot of a skill.

    Attributes:
        id: Unique identifier for this version
        skill_id: Reference to the parent skill
        version_number: Auto-incremented integer for ordering (1, 2, 3...)
        version_label: Display version from SKILL.md frontmatter (e.g., "1.2.0")
        skill_md_content: Full SKILL.md content at this version
        resource_files: Map of relative_path -> content (text or base64 for binary)
        change_summary: Description of what changed from the previous version
        created_by: Who created this version ("agent", "api", "rollback")
        created_at: When this version was created
    """

    id: str
    skill_id: str
    version_number: int
    version_label: Optional[str] = None
    skill_md_content: str = ""
    resource_files: Dict[str, str] = field(default_factory=dict)
    change_summary: Optional[str] = None
    created_by: str = "agent"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.skill_id:
            raise ValueError("skill_id cannot be empty")
        if self.version_number < 1:
            raise ValueError("version_number must be >= 1")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "skill_id": self.skill_id,
            "version_number": self.version_number,
            "version_label": self.version_label,
            "skill_md_content": self.skill_md_content,
            "resource_files": dict(self.resource_files),
            "change_summary": self.change_summary,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillVersion":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            skill_id=data["skill_id"],
            version_number=data["version_number"],
            version_label=data.get("version_label"),
            skill_md_content=data.get("skill_md_content", ""),
            resource_files=data.get("resource_files", {}),
            change_summary=data.get("change_summary"),
            created_by=data.get("created_by", "agent"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(timezone.utc),
        )
