"""
Skill source enumeration.

Defines the source of a skill - whether it comes from the file system,
the database, or a plugin.
"""

from enum import Enum
from typing import override


class SkillSource(str, Enum):
    """
    Source of a skill definition.

    Attributes:
        FILESYSTEM: Skill loaded from .memstack/skills/
        DATABASE: Skill stored in PostgreSQL database
        HYBRID: Merged from both sources (file system takes priority)
        PLUGIN: Skill registered by a plugin via the plugin registry
    """

    FILESYSTEM = "filesystem"
    DATABASE = "database"
    HYBRID = "hybrid"
    PLUGIN = "plugin"

    @override
    def __str__(self) -> str:
        return self.value
