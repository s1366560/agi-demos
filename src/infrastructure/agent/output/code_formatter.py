"""
CodeFormatter for generating code output (T121).

Converts structured data into formatted code blocks in various languages.
"""

from typing import Any, Dict

from src.infrastructure.agent.output import OutputFormatter


class CodeFormatter(OutputFormatter):
    """
    Formatter for converting structured data to code blocks.

    Supports multiple programming languages and automatic formatting.
    """

    def __init__(self, language: str = "python", indent: int = 4):
        """
        Initialize the code formatter.

        Args:
            language: Programming language (python, javascript, json, yaml, etc.)
            indent: Number of spaces for indentation
        """
        self._language = language
        self._indent = indent

    def format(self, data: Any, metadata: Dict[str, Any] | None = None) -> str:
        """
        Format data as a code block.

        Args:
            data: The data to format
            metadata: Optional formatting options

        Returns:
            Formatted code string
        """
        metadata = metadata or {}
        language = metadata.get("language", self._language)

        if language == "json":
            return self._format_json(data)
        elif language == "yaml":
            return self._format_yaml(data)
        elif language == "python":
            return self._format_python(data)
        elif language == "javascript":
            return self._format_javascript(data)
        else:
            # Default: just wrap in code block
            return f"```{language}\n{str(data)}\n```"

    def _format_json(self, data: Any) -> str:
        """Format as JSON."""
        import json

        json_str = json.dumps(data, indent=self._indent, ensure_ascii=False)
        return f"```json\n{json_str}\n```"

    def _format_yaml(self, data: Any) -> str:
        """Format as YAML."""
        # Simple YAML formatter (basic implementation)
        lines = ["```yaml"]
        lines.extend(self._yaml_format_value(data, 0))
        lines.append("```")
        return "\n".join(lines)

    def _yaml_format_value(self, value: Any, indent: int) -> list[str]:
        """Recursively format a value as YAML."""
        lines = []
        prefix = " " * indent

        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"{prefix}{k}:")
                    lines.extend(self._yaml_format_value(v, indent + self._indent))
                else:
                    lines.append(f"{prefix}{k}: {v}")
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    lines.append(f"{prefix}-")
                    lines.extend(self._yaml_format_value(item, indent + self._indent + 2))
                else:
                    lines.append(f"{prefix}- {item}")
        else:
            lines.append(f"{prefix}{value}")

        return lines

    def _format_python(self, data: Any) -> str:
        """Format as Python code."""
        lines = ["```python"]

        if isinstance(data, dict):
            lines.append("# Data as Python dictionary")
            lines.append("data = {")
            for k, v in data.items():
                lines.append(f'    "{k}": {repr(v)},')
            lines.append("}")
        elif isinstance(data, list):
            lines.append("# Data as Python list")
            lines.append("data = [")
            for item in data:
                lines.append(f"    {repr(item)},")
            lines.append("]")
        else:
            lines.append("# Data")
            lines.append(f"data = {repr(data)}")

        lines.append("```")
        return "\n".join(lines)

    def _format_javascript(self, data: Any) -> str:
        """Format as JavaScript code."""
        import json

        json_str = json.dumps(data, indent=self._indent, ensure_ascii=False)
        return f"```javascript\n// Data as JavaScript object\nconst data = {json_str};\n```"

    def get_content_type(self) -> str:
        """Get code content type."""
        return "text/plain"

    def get_extension(self) -> str:
        """Get code file extension based on language."""
        extensions = {
            "python": ".py",
            "javascript": ".js",
            "json": ".json",
            "yaml": ".yaml",
            "typescript": ".ts",
        }
        return extensions.get(self._language, ".txt")
