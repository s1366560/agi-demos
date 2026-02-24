"""
MarkdownFormatter for generating markdown output (T119).

Converts structured data into formatted markdown documents.
"""

from typing import Any

from src.infrastructure.agent.output import OutputFormatter


class MarkdownFormatter(OutputFormatter):
    """
    Formatter for converting structured data to markdown format.

    Supports:
    - Headers and sections
    - Lists (ordered and unordered)
    - Tables
    - Code blocks
    - Links and images
    """

    def format(self, data: Any, metadata: dict[str, Any] | None = None) -> str:
        """
        Format data as markdown.

        Args:
            data: The data to format. Can be:
                - dict: Converted to sections and tables
                - list: Converted to list items
                - str: Returned as-is with some formatting
            metadata: Optional formatting options

        Returns:
            Formatted markdown string
        """
        metadata = metadata or {}
        title = metadata.get("title", "Report")

        lines = [f"# {title}\n"]

        if isinstance(data, dict):
            # Process dictionary data
            for key, value in data.items():
                lines.append(f"## {self._format_key(key)}\n")

                if isinstance(value, list):
                    lines.extend(self._format_list(value))
                elif isinstance(value, dict):
                    lines.extend(self._format_dict(value))
                else:
                    lines.append(f"{value}\n")

        elif isinstance(data, list):
            # Process list data
            lines.extend(self._format_list(data))

        else:
            # String data
            lines.append(str(data))

        return "\n".join(lines)

    def _format_key(self, key: str) -> str:
        """Format a dictionary key as a heading."""
        return key.replace("_", " ").replace("-", " ").title()

    def _format_list(self, items: list, indent: int = 0) -> list[str]:
        """Format a list as markdown list items."""
        lines = []
        prefix = "  " * indent

        for item in items:
            if isinstance(item, dict):
                # Nested dictionary
                for k, v in item.items():
                    if isinstance(v, list):
                        lines.append(f"{prefix}- **{k}**:")
                        lines.extend(self._format_list(v, indent + 1))
                    else:
                        lines.append(f"{prefix}- **{k}**: {v}")
            elif isinstance(item, list):
                lines.extend(self._format_list(item, indent))
            else:
                lines.append(f"{prefix}- {item}")

        return lines

    def _format_dict(self, data: dict, indent: int = 0) -> list[str]:
        """Format a dictionary as markdown."""
        lines = []
        prefix = "  " * indent

        for key, value in data.items():
            if isinstance(value, list):
                lines.append(f"{prefix}- **{key}**:")
                lines.extend(self._format_list(value, indent + 1))
            elif isinstance(value, dict):
                lines.append(f"{prefix}- **{key}**:")
                lines.extend(self._format_dict(value, indent + 1))
            else:
                lines.append(f"{prefix}- **{key}**: {value}")

        return lines

    def get_content_type(self) -> str:
        """Get markdown content type."""
        return "text/markdown"

    def get_extension(self) -> str:
        """Get markdown file extension."""
        return ".md"
