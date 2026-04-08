"""
Agent source enumeration.

Defines the source of an Agent - whether it comes from the file system
or the database.
"""

from enum import Enum


class AgentSource(str, Enum):
    """
    Source of an Agent definition.

    Attributes:
        FILESYSTEM: Agent loaded from .memstack/agents/
        DATABASE: Agent stored in PostgreSQL database
        BUILTIN: Agent provided by the runtime
    """

    FILESYSTEM = "filesystem"
    DATABASE = "database"
    BUILTIN = "builtin"

    def __str__(self) -> str:
        return self.value
