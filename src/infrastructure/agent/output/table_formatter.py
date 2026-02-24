"""
TableFormatter for generating table output (T120).

Converts structured data into formatted tables (markdown, CSV, HTML).
"""

from typing import Any, Dict

from src.infrastructure.agent.output import OutputFormatter


class TableFormatter(OutputFormatter):
    """
    Formatter for converting structured data to table format.

    Supports:
    - Markdown tables
    - CSV format
    - HTML tables
    """

    def __init__(self, table_format: str = "markdown"):
        """
        Initialize the table formatter.

        Args:
            table_format: Format for tables ("markdown", "csv", "html")
        """
        self._table_format = table_format

    def format(self, data: Any, metadata: Dict[str, Any] | None = None) -> str:  # noqa: ANN401
        """
        Format data as a table.

        Args:
            data: The data to format. Should be:
                - list of dicts: Each dict is a row
                - dict of lists: Keys are column names
            metadata: Optional formatting options

        Returns:
            Formatted table string
        """
        metadata = metadata or {}
        table_format = metadata.get("format", self._table_format)

        # Normalize data to list of dicts
        rows, columns = self._normalize_data(data)

        if table_format == "csv":
            return self._format_csv(rows, columns)
        elif table_format == "html":
            return self._format_html(rows, columns)
        else:
            return self._format_markdown(rows, columns)

    def _normalize_data(self, data: Any) -> tuple[list[dict], list[str]]:  # noqa: ANN401
        """
        Normalize data to list of dicts and extract columns.

        Args:
            data: Input data

        Returns:
            Tuple of (rows as list of dicts, column names)
        """
        if isinstance(data, list):
            if not data:
                return [], []

            if isinstance(data[0], dict):
                # List of dicts - extract columns
                columns = list(data[0].keys())
                return data, columns
            else:
                # Simple list - convert to single column
                return [{"value": str(item)} for item in data], ["value"]

        elif isinstance(data, dict):
            # Dict of lists
            if all(isinstance(v, list) for v in data.values()):
                columns = list(data.keys())
                rows = [dict(zip(columns, values)) for values in zip(*data.values())]
                return rows, columns
            else:
                # Single dict - convert to single row
                return [data], list(data.keys())

        else:
            # Single value
            return [{"value": str(data)}], ["value"]

    def _format_markdown(self, rows: list[dict], columns: list[str]) -> str:
        """Format as markdown table."""
        if not rows or not columns:
            return "No data available"

        lines = []

        # Header
        header = " | ".join(columns)
        lines.append(header)

        # Separator
        separator = " | ".join(["---"] * len(columns))
        lines.append(separator)

        # Rows
        for row in rows:
            values = [str(row.get(col, "")) for col in columns]
            lines.append(" | ".join(values))

        return "\n".join(lines)

    def _format_csv(self, rows: list[dict], columns: list[str]) -> str:
        """Format as CSV."""
        if not rows or not columns:
            return ""

        lines = []

        # Header
        lines.append(",".join(columns))

        # Rows
        for row in rows:
            values = [self._csv_escape(str(row.get(col, ""))) for col in columns]
            lines.append(",".join(values))

        return "\n".join(lines)

    def _csv_escape(self, value: str) -> str:
        """Escape a value for CSV output."""
        if any(c in value for c in [",", "\n", '"']):
            escaped = value.replace('"', '""')
            return f'"{escaped}"'
        return value

    def _format_html(self, rows: list[dict], columns: list[str]) -> str:
        """Format as HTML table."""
        if not rows or not columns:
            return "<p>No data available</p>"

        lines = ["<table>", "<thead>", "<tr>"]

        # Header
        for col in columns:
            lines.append(f"<th>{col}</th>")
        lines.append("</tr>")
        lines.append("</thead>")

        # Body
        lines.append("<tbody>")
        for row in rows:
            lines.append("<tr>")
            for col in columns:
                value = row.get(col, "")
                lines.append(f"<td>{value}</td>")
            lines.append("</tr>")
        lines.append("</tbody>")

        lines.append("</table>")
        return "\n".join(lines)

    def get_content_type(self) -> str:
        """Get table content type based on format."""
        if self._table_format == "csv":
            return "text/csv"
        elif self._table_format == "html":
            return "text/html"
        else:
            return "text/markdown"

    def get_extension(self) -> str:
        """Get table file extension based on format."""
        if self._table_format == "csv":
            return ".csv"
        elif self._table_format == "html":
            return ".html"
        else:
            return ".md"
