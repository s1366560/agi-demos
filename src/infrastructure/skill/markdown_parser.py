"""
SKILL.md file parser.

Parses SKILL.md files with YAML Frontmatter and Markdown content.
Compatible with Claude Skills and OpenCode skill formats.

Example SKILL.md:
```markdown
---
name: ui-ux-pro-max
description: "UI/UX design intelligence"
trigger_patterns:
  - design
  - UI
tools:
  - web_search
  - memory_create
---

# UI/UX Pro Max

## Instructions
1. Analyze requirements
2. Generate design
```
"""

import re
from dataclasses import dataclass, field
from typing import Any, cast

import yaml


class MarkdownParseError(Exception):
    """Exception raised when SKILL.md parsing fails."""

    def __init__(self, message: str, file_path: str | None = None) -> None:
        self.file_path = file_path
        super().__init__(f"{message}" + (f" in {file_path}" if file_path else ""))


@dataclass(frozen=True)
class SkillMarkdown:
    """
    Parsed SKILL.md file content.

    Attributes:
        frontmatter: YAML Frontmatter as a dictionary
        content: Markdown content (everything after the frontmatter)
        name: Skill name from frontmatter
        description: Skill description from frontmatter
        trigger_patterns: List of trigger patterns (optional, deprecated)
        tools: List of tool names this skill uses (derived from allowed-tools or tools)
        allowed_tools: List of allowed tools (Claude format, optional, deprecated)
        user_invocable: Whether user can directly invoke (optional)
        context: Context mode - shared or fork (optional)
        agent: Agent modes - list of agent modes that can use this skill
               Supports: ["default"], ["plan"], ["default", "plan"], ["*"]
               "*" means all modes (default behavior)

        # AgentSkills.io spec fields
        license: License identifier (e.g., "MIT", "Apache-2.0")
        compatibility: Environment requirements (e.g., "Requires git, docker")
        metadata: Key-value metadata (e.g., author, version)
        allowed_tools_raw: Raw allowed-tools string for fine-grained parsing
    """

    frontmatter: dict[str, Any]
    content: str
    name: str
    description: str
    trigger_patterns: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    user_invocable: bool = True
    context: str = "shared"
    agent: list[str] = field(default_factory=lambda: ["*"])
    # AgentSkills.io spec fields
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    allowed_tools_raw: str | None = None
    # Version tracking
    version: str | None = None

    @property
    def full_content(self) -> str:
        """Return the full markdown content including frontmatter."""
        yaml_str = yaml.dump(self.frontmatter, default_flow_style=False, allow_unicode=True)
        return f"---\n{yaml_str}---\n\n{self.content}"


class MarkdownParser:
    """
    Parser for SKILL.md files.

    Supports the standard format:
    - YAML Frontmatter delimited by ---
    - Markdown content after the frontmatter
    """

    # Regex to match YAML frontmatter: starts with ---, content, ends with ---
    FRONTMATTER_PATTERN = re.compile(
        r"^---\s*\n(.*?)\n---\s*\n?(.*)$",
        re.DOTALL,
    )

    def parse(self, content: str, file_path: str | None = None) -> SkillMarkdown:
        """
        Parse a SKILL.md file content.

        Args:
            content: Raw file content as string
            file_path: Optional file path for error messages

        Returns:
            SkillMarkdown object with parsed frontmatter and content

        Raises:
            MarkdownParseError: If parsing fails
        """
        if not content or not content.strip():
            raise MarkdownParseError("Empty content", file_path)

        frontmatter, markdown_content = self._extract_frontmatter(content, file_path)

        name = frontmatter.get("name")
        if not name:
            raise MarkdownParseError(
                "Missing required field 'name' in frontmatter",
                file_path,
            )

        description = self._extract_description(frontmatter)
        trigger_patterns = self._extract_trigger_patterns(frontmatter)
        tools, allowed_tools_list, allowed_tools_raw = self._extract_tools(frontmatter)
        user_invocable = self._extract_user_invocable(frontmatter)
        context = frontmatter.get("context", "shared")
        agent = self._extract_agent_modes(frontmatter)
        license_field, compatibility, metadata, version_str = self._extract_agentskills_fields(
            frontmatter
        )

        return SkillMarkdown(
            frontmatter=frontmatter,
            content=markdown_content,
            name=str(name),
            description=str(description),
            trigger_patterns=trigger_patterns,
            tools=tools,
            allowed_tools=allowed_tools_list,
            user_invocable=user_invocable,
            context=str(context),
            agent=agent,
            license=str(license_field) if license_field else None,
            compatibility=str(compatibility) if compatibility else None,
            metadata=metadata,
            allowed_tools_raw=allowed_tools_raw if isinstance(allowed_tools_raw, str) else None,
            version=version_str,
        )

    def _extract_frontmatter(
        self, content: str, file_path: str | None
    ) -> tuple[dict[str, Any], str]:
        """Parse and validate YAML frontmatter, returning (frontmatter_dict, markdown_content)."""
        match = self.FRONTMATTER_PATTERN.match(content)
        if not match:
            raise MarkdownParseError(
                "Invalid SKILL.md format: missing or malformed YAML frontmatter. "
                "File must start with '---' followed by YAML and closing '---'",
                file_path,
            )

        frontmatter_yaml = match.group(1)
        markdown_content = match.group(2).strip()

        try:
            frontmatter = yaml.safe_load(frontmatter_yaml)
        except yaml.YAMLError as e:
            raise MarkdownParseError(f"Invalid YAML frontmatter: {e}", file_path) from e

        if not isinstance(frontmatter, dict):
            raise MarkdownParseError(
                "YAML frontmatter must be a dictionary/object",
                file_path,
            )

        return frontmatter, markdown_content

    def _extract_description(self, frontmatter: dict[str, Any]) -> str:
        """Extract description from frontmatter, trying alternative field names."""
        description = frontmatter.get("description", "")
        if not description:
            description = frontmatter.get("desc", "") or frontmatter.get("summary", "")
        return cast(str, description)

    def _extract_trigger_patterns(self, frontmatter: dict[str, Any]) -> list[str]:
        """Extract trigger patterns from frontmatter."""
        trigger_patterns = self._extract_list(frontmatter, "trigger_patterns")
        if not trigger_patterns:
            trigger_patterns = self._extract_list(frontmatter, "triggers")
        return trigger_patterns

    def _extract_tools(self, frontmatter: dict[str, Any]) -> tuple[list[str], list[str], Any]:
        """Extract tools and allowed-tools, returning (tools, allowed_tools_list, raw_value)."""
        allowed_tools_raw = frontmatter.get("allowed-tools")
        tools: list[str] = []
        allowed_tools_list: list[str] = []

        if allowed_tools_raw is not None:
            if isinstance(allowed_tools_raw, str):
                tools, allowed_tools_list = self._parse_allowed_tools_string(allowed_tools_raw)
            else:
                allowed_tools_raw = str(allowed_tools_raw)
        else:
            tools = self._extract_list(frontmatter, "tools")
            allowed_tools_list = self._extract_list(frontmatter, "allowed-tools")
            if not allowed_tools_list:
                allowed_tools_list = self._extract_list(frontmatter, "allowed_tools")

        return tools, allowed_tools_list, allowed_tools_raw

    def _parse_allowed_tools_string(self, raw: str) -> tuple[list[str], list[str]]:
        """Parse AgentSkills.io format space-separated allowed-tools string."""
        tools: list[str] = []
        allowed_tools_list: list[str] = []
        for part in raw.split():
            part = part.strip()
            if part:
                tool_name = re.split(r"[(\[]", part)[0]
                if tool_name:
                    tools.append(tool_name)
                    allowed_tools_list.append(part)
        return tools, allowed_tools_list

    def _extract_user_invocable(self, frontmatter: dict[str, Any]) -> bool:
        """Extract user-invocable flag from frontmatter."""
        user_invocable = frontmatter.get("user-invocable", True)
        if not isinstance(user_invocable, bool):
            user_invocable = str(user_invocable).lower() in ("true", "yes", "1")
        return user_invocable

    def _extract_agentskills_fields(
        self, frontmatter: dict[str, Any]
    ) -> tuple[Any, Any, dict[str, Any], str | None]:
        """Extract AgentSkills.io spec fields (license, compatibility, metadata, version)."""
        license_field = frontmatter.get("license")
        compatibility = frontmatter.get("compatibility")
        metadata = frontmatter.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        version_field = frontmatter.get("version")
        version_str = str(version_field).strip() if version_field is not None else None

        return license_field, compatibility, metadata, version_str

    def parse_file(self, file_path: str) -> SkillMarkdown:
        """
        Parse a SKILL.md file from disk.

        Args:
            file_path: Path to the SKILL.md file

        Returns:
            SkillMarkdown object

        Raises:
            MarkdownParseError: If parsing fails
            FileNotFoundError: If file doesn't exist
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            raise MarkdownParseError(f"File not found: {file_path}", file_path) from None
        except OSError as e:
            raise MarkdownParseError(f"Error reading file: {e}", file_path) from e

        return self.parse(content, file_path)

    def _extract_list(self, data: dict[str, Any], key: str) -> list[str]:
        """
        Extract a list of strings from frontmatter.

        Handles both list and comma-separated string formats.
        """
        value = data.get(key)
        if value is None:
            return []

        if isinstance(value, list):
            return [str(item) for item in value if item]

        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]

        return []

    def _extract_agent_modes(self, frontmatter: dict[str, Any]) -> list[str]:
        """
        Extract agent modes from frontmatter.

        Supports multiple formats:
        - agent: default           -> ["default"]
        - agent: "*"               -> ["*"]
        - agent: [default, plan]   -> ["default", "plan"]
        - agent:                   -> ["*"] (default when omitted)
          - default
          - plan

        Args:
            frontmatter: The parsed YAML frontmatter

        Returns:
            List of agent mode strings
        """
        value = frontmatter.get("agent")

        if value is None:
            return ["*"]  # Default: all agents can access

        if isinstance(value, str):
            return [value]

        if isinstance(value, list):
            return [str(item) for item in value if item]

        return ["*"]
