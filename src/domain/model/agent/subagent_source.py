"""
SubAgent source enumeration.

Defines the source of a SubAgent - whether it comes from the file system
or the database.
"""

from enum import Enum


class SubAgentSource(str, Enum):
    """
    Source of a SubAgent definition.

    Attributes:
        FILESYSTEM: SubAgent loaded from .memstack/agents/
        DATABASE: SubAgent stored in PostgreSQL database
    """

    FILESYSTEM = "filesystem"
    DATABASE = "database"

    def __str__(self) -> str:
        return self.value
