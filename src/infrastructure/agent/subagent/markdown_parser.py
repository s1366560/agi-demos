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
        max_tokens: Optional maximum tokens for responses
        max_retries: Optional maximum retry count
        fallback_models: List of fallback model names
        allowed_skills: List of allowed skill IDs
        allowed_mcp_servers: List of allowed MCP server names
        mode: Agent mode ("subagent" | "primary" | "all")
        allow_spawn: Whether this agent can spawn sub-agents
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
    max_tokens: int | None = None
    max_retries: int | None = None
    fallback_models: list[str] = field(default_factory=list)
    allowed_skills: list[str] = field(default_factory=list)
    allowed_mcp_servers: list[str] = field(default_factory=list)
    mode: str = "subagent"
    allow_spawn: bool = False


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
        frontmatter, markdown_content = self._split_frontmatter(content, file_path)

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

        return SubAgentMarkdown(
            frontmatter=frontmatter,
            content=markdown_content,
            name=str(name),
            description=str(description),
            tools=self._extract_list(frontmatter, "tools"),
            model_raw=str(frontmatter.get("model", "inherit")).strip(),
            display_name=self._extract_optional_str(frontmatter, "display_name"),
            keywords=self._extract_list(frontmatter, "keywords"),
            examples=self._extract_list(frontmatter, "examples"),
            max_iterations=self._extract_optional_int(frontmatter, "max_iterations"),
            temperature=self._extract_optional_float(frontmatter, "temperature"),
            color=self._extract_optional_str(frontmatter, "color"),
            enabled=self._extract_bool(frontmatter, "enabled", default=True),
            max_tokens=self._extract_optional_int(frontmatter, "max_tokens"),
            max_retries=self._extract_optional_int(frontmatter, "max_retries"),
            fallback_models=self._extract_list(frontmatter, "fallback_models"),
            allowed_skills=self._extract_list(frontmatter, "allowed_skills"),
            allowed_mcp_servers=self._extract_list(frontmatter, "allowed_mcp_servers"),
            mode=self._extract_constrained_str(
                frontmatter, "mode", ("subagent", "primary", "all"), default="subagent"
            ),
            allow_spawn=self._extract_bool(frontmatter, "allow_spawn", default=False),
        )

    def _split_frontmatter(self, content: str, file_path: str | None) -> tuple[dict[str, Any], str]:
        """Split raw content into frontmatter dict and markdown body."""
        if not content or not content.strip():
            raise SubAgentParseError("Empty content", file_path)

        match = _FRONTMATTER_PATTERN.match(content)
        if not match:
            raise SubAgentParseError(
                "Invalid format: missing or malformed YAML frontmatter. "
                "File must start with '---' followed by YAML and closing '---'",
                file_path,
            )

        try:
            frontmatter = yaml.safe_load(match.group(1))
        except yaml.YAMLError as e:
            raise SubAgentParseError(f"Invalid YAML frontmatter: {e}", file_path) from e

        if not isinstance(frontmatter, dict):
            raise SubAgentParseError(
                "YAML frontmatter must be a dictionary/object",
                file_path,
            )

        return frontmatter, match.group(2).strip()

    @staticmethod
    def _extract_optional_int(data: dict[str, Any], key: str) -> int | None:
        """Extract an optional integer from frontmatter, returning None on failure."""
        value = data.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_optional_float(data: dict[str, Any], key: str) -> float | None:
        """Extract an optional float from frontmatter, returning None on failure."""
        value = data.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_optional_str(data: dict[str, Any], key: str) -> str | None:
        """Extract an optional string from frontmatter."""
        value = data.get(key)
        return str(value) if value is not None else None

    @staticmethod
    def _extract_bool(data: dict[str, Any], key: str, *, default: bool) -> bool:
        """Extract a boolean from frontmatter with flexible truthy parsing."""
        value = data.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "yes", "1")

    @staticmethod
    def _extract_constrained_str(
        data: dict[str, Any], key: str, allowed: tuple[str, ...], *, default: str
    ) -> str:
        """Extract a string constrained to allowed values."""
        value = str(data.get(key, default)).strip()
        return value if value in allowed else default

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
