"""
Skill source enumeration.

Defines the source of a skill - whether it comes from the file system
or the database.
"""

from enum import Enum


class SkillSource(str, Enum):
    """
    Source of a skill definition.

    Attributes:
        FILESYSTEM: Skill loaded from .memstack/skills/
        DATABASE: Skill stored in PostgreSQL database
        HYBRID: Merged from both sources (file system takes priority)
    """

    FILESYSTEM = "filesystem"
    DATABASE = "database"
    HYBRID = "hybrid"

    def __str__(self) -> str:
        return self.value
