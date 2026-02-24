"""
Base output formatter class (T119-T121).

This module provides the abstract base class and implementations for output formatters.
"""

from abc import ABC, abstractmethod
from typing import Any


class OutputFormatter(ABC):
    """
    Abstract base class for output formatters.

    Formatters convert structured data into various output formats
    like markdown, tables, and code blocks.
    """

    @abstractmethod
    def format(self, data: Any, metadata: dict[str, Any] | None = None) -> str:
        """
        Format the given data into the specific output format.

        Args:
            data: The data to format
            metadata: Optional metadata for formatting

        Returns:
            Formatted string
        """

    @abstractmethod
    def get_content_type(self) -> str:
        """
        Get the content type for this format.

        Returns:
            MIME type string
        """

    @abstractmethod
    def get_extension(self) -> str:
        """
        Get the file extension for this format.

        Returns:
            File extension (with leading dot)
        """


__all__ = [
    "OutputFormatter",
]
