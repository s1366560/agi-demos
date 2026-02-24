"""
SubAgent markdown file parser.

Parses .memstack/agents/*.md files with YAML frontmatter and markdown body.
Compatible with Claude Code custom agent format.

Example agent.md:
```markdown
---
name: architect
description: Software architecture specialist...
tools: ["Read", "Grep", "Glob"]
model: opus
---

You are a senior software architect...
```
"""

import re
from dataclasses import dataclass, field
from typing import Any

import yaml


class SubAgentParseError(Exception):
    """Exception raised when agent .md parsing fails."""

    def __init__(self, message: str, file_path: str | None = None) -> None:
        self.file_path = file_path
        super().__init__(f"{message}" + (f" in {file_path}" if file_path else ""))


@dataclass(frozen=True)
class SubAgentMarkdown:
    """
    Parsed agent .md file content.

    Attributes:
        frontmatter: YAML frontmatter as a dictionary
        content: Markdown content (system prompt body)
        name: Agent name from frontmatter
        description: Agent description from frontmatter
        tools: List of allowed tool names
        model_raw: Raw model string (e.g., "opus", "sonnet", "gpt-4")
        display_name: Optional human-readable name
        keywords: Optional trigger keywords
        examples: Optional trigger examples
        max_iterations: Optional max ReAct iterations
        temperature: Optional LLM temperature
        color: Optional UI color
        enabled: Whether the agent is enabled
    """

    frontmatter: dict[str, Any]
    content: str
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    model_raw: str = "inherit"
    display_name: str | None = None
    keywords: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    max_iterations: int | None = None
    temperature: float | None = None
    color: str | None = None
    enabled: bool = True


# Regex to match YAML frontmatter: starts with ---, content, ends with ---
_FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n?(.*)$",
    re.DOTALL,
)


class SubAgentMarkdownParser:
    """
    Parser for .memstack/agents/*.md files.

    Supports the standard format:
    - YAML frontmatter delimited by ---
    - Markdown content after the frontmatter (used as system_prompt)
    """

    def parse(self, content: str, file_path: str | None = None) -> SubAgentMarkdown:
        """
        Parse an agent .md file content.

        Args:
            content: Raw file content as string
            file_path: Optional file path for error messages

        Returns:
            SubAgentMarkdown object with parsed frontmatter and content

        Raises:
            SubAgentParseError: If parsing fails
        """
        if not content or not content.strip():
            raise SubAgentParseError("Empty content", file_path)

        match = _FRONTMATTER_PATTERN.match(content)
        if not match:
            raise SubAgentParseError(
                "Invalid format: missing or malformed YAML frontmatter. "
                "File must start with '---' followed by YAML and closing '---'",
                file_path,
            )

        frontmatter_yaml = match.group(1)
        markdown_content = match.group(2).strip()

        try:
            frontmatter = yaml.safe_load(frontmatter_yaml)
        except yaml.YAMLError as e:
            raise SubAgentParseError(f"Invalid YAML frontmatter: {e}", file_path) from e

        if not isinstance(frontmatter, dict):
            raise SubAgentParseError(
                "YAML frontmatter must be a dictionary/object",
                file_path,
            )

        # Validate required fields
        name = frontmatter.get("name")
        if not name:
            raise SubAgentParseError(
                "Missing required field 'name' in frontmatter",
                file_path,
            )

        description = frontmatter.get("description", "")
        if not description:
            description = frontmatter.get("desc", "") or frontmatter.get("summary", "")

        # Extract tools (list or comma-separated string)
        tools = self._extract_list(frontmatter, "tools")

        # Extract model
        model_raw = str(frontmatter.get("model", "inherit")).strip()

        # Extract optional extended fields
        display_name = frontmatter.get("display_name")
        keywords = self._extract_list(frontmatter, "keywords")
        examples = self._extract_list(frontmatter, "examples")

        max_iterations = frontmatter.get("max_iterations")
        if max_iterations is not None:
            try:
                max_iterations = int(max_iterations)
            except (ValueError, TypeError):
                max_iterations = None

        temperature = frontmatter.get("temperature")
        if temperature is not None:
            try:
                temperature = float(temperature)
            except (ValueError, TypeError):
                temperature = None

        color = frontmatter.get("color")
        enabled = frontmatter.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = str(enabled).lower() in ("true", "yes", "1")

        return SubAgentMarkdown(
            frontmatter=frontmatter,
            content=markdown_content,
            name=str(name),
            description=str(description),
            tools=tools,
            model_raw=model_raw,
            display_name=str(display_name) if display_name else None,
            keywords=keywords,
            examples=examples,
            max_iterations=max_iterations,
            temperature=temperature,
            color=str(color) if color else None,
            enabled=enabled,
        )

    def parse_file(self, file_path: str) -> SubAgentMarkdown:
        """
        Parse an agent .md file from disk.

        Args:
            file_path: Path to the .md file

        Returns:
            SubAgentMarkdown object

        Raises:
            SubAgentParseError: If parsing fails
            FileNotFoundError: If file doesn't exist
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            raise SubAgentParseError(f"File not found: {file_path}", file_path) from None
        except OSError as e:
            raise SubAgentParseError(f"Error reading file: {e}", file_path) from e

        return self.parse(content, file_path)

    def _extract_list(self, data: dict[str, Any], key: str) -> list[str]:
        """Extract a list of strings from frontmatter."""
        value = data.get(key)
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return []
