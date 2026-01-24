"""Minimal tool base class for CUA MCP server."""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class ToolBase(ABC):
    """Base class for MCP-exposed tools."""

    def __init__(self, name: str, description: str) -> None:
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Execute tool and return string result."""

    async def safe_execute(self, **kwargs: Any) -> str:
        try:
            return await self.execute(**kwargs)
        except Exception as exc:
            logger.error("Tool %s error: %s", self._name, exc, exc_info=True)
            return f"Error: {exc}"
