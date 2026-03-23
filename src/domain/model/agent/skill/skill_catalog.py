"""
Skill catalog entry for the Skills Marketplace.

A frozen value object representing a skill's marketplace metadata.
Wraps existing Skill entities with marketplace-specific fields
(rating, download count, install source, category, tags).

This is a read-only projection -- catalog entries are derived from
the existing skill infrastructure, not stored separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class SkillCatalogEntry:
    """
    Immutable value object representing a skill in the marketplace catalog.

    Attributes:
        id: Unique identifier (same as the underlying Skill ID).
        name: Human-readable skill name.
        version: Semantic version string (e.g. "1.0.0").
        description: What this skill does.
        author: Author or publisher of the skill.
        category: Functional category (e.g. "search", "code", "data", "communication").
        tags: Discovery tags for search/filtering.
        trigger_keywords: Keywords that activate this skill.
        install_source: Origin of the skill ("builtin", "marketplace", "custom").
        download_count: Number of times this skill has been installed.
        rating: Average user rating (0.0 - 5.0).
        created_at: When the catalog entry was created (UTC).
        updated_at: When the catalog entry was last modified (UTC).
    """

    id: str
    name: str
    version: str
    description: str
    author: str
    category: str
    tags: tuple[str, ...]
    trigger_keywords: tuple[str, ...]
    install_source: str
    download_count: int = 0
    rating: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the catalog entry."""
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")
        if not self.version:
            raise ValueError("version cannot be empty")
        if not self.description:
            raise ValueError("description cannot be empty")
        if not self.author:
            raise ValueError("author cannot be empty")
        if not self.category:
            raise ValueError("category cannot be empty")
        if not 0.0 <= self.rating <= 5.0:
            raise ValueError("rating must be between 0.0 and 5.0")
        if self.download_count < 0:
            raise ValueError("download_count must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "tags": list(self.tags),
            "trigger_keywords": list(self.trigger_keywords),
            "install_source": self.install_source,
            "download_count": self.download_count,
            "rating": self.rating,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillCatalogEntry:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data["description"],
            author=data.get("author", "system"),
            category=data.get("category", "general"),
            tags=tuple(data.get("tags", ())),
            trigger_keywords=tuple(data.get("trigger_keywords", ())),
            install_source=data.get("install_source", "builtin"),
            download_count=data.get("download_count", 0),
            rating=data.get("rating", 0.0),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(UTC),
        )
