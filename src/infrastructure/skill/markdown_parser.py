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
from typing import Any, Dict, List, Optional

import yaml


class MarkdownParseError(Exception):
    """Exception raised when SKILL.md parsing fails."""

    def __init__(self, message: str, file_path: Optional[str] = None):
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

    frontmatter: Dict[str, Any]
    content: str
    name: str
    description: str
    trigger_patterns: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    user_invocable: bool = True
    context: str = "shared"
    agent: List[str] = field(default_factory=lambda: ["*"])
    # AgentSkills.io spec fields
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    allowed_tools_raw: Optional[str] = None
    # Version tracking
    version: Optional[str] = None

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

    def parse(self, content: str, file_path: Optional[str] = None) -> SkillMarkdown:
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
            raise MarkdownParseError(f"Invalid YAML frontmatter: {e}", file_path)

        if not isinstance(frontmatter, dict):
            raise MarkdownParseError(
                "YAML frontmatter must be a dictionary/object",
                file_path,
            )

        # Validate required fields
        name = frontmatter.get("name")
        if not name:
            raise MarkdownParseError(
                "Missing required field 'name' in frontmatter",
                file_path,
            )

        description = frontmatter.get("description", "")
        if not description:
            # Try alternative field names
            description = frontmatter.get("desc", "") or frontmatter.get("summary", "")

        # Extract optional fields
        trigger_patterns = self._extract_list(frontmatter, "trigger_patterns")
        if not trigger_patterns:
            trigger_patterns = self._extract_list(frontmatter, "triggers")

        # Parse allowed-tools (AgentSkills.io spec format: space-separated string)
        # Priority: allowed-tools > tools
        allowed_tools_raw = frontmatter.get("allowed-tools")
        tools: List[str] = []
        allowed_tools_list: List[str] = []

        if allowed_tools_raw is not None:
            if isinstance(allowed_tools_raw, str):
                # AgentSkills.io format: space-separated string like "Bash(git:*) Read Write"
                # Extract tool names (without arguments)
                for part in allowed_tools_raw.split():
                    part = part.strip()
                    if part:
                        # Extract tool name before any parentheses
                        tool_name = re.split(r"[(\[]", part)[0]
                        if tool_name:
                            tools.append(tool_name)
                            allowed_tools_list.append(part)
            else:
                # Invalid format - will be caught by validator
                allowed_tools_raw = str(allowed_tools_raw)
        else:
            # Fallback to tools array format (deprecated but supported)
            tools = self._extract_list(frontmatter, "tools")
            allowed_tools_list = self._extract_list(frontmatter, "allowed-tools")
            if not allowed_tools_list:
                allowed_tools_list = self._extract_list(frontmatter, "allowed_tools")

        user_invocable = frontmatter.get("user-invocable", True)
        if not isinstance(user_invocable, bool):
            user_invocable = str(user_invocable).lower() in ("true", "yes", "1")

        context = frontmatter.get("context", "shared")
        agent = self._extract_agent_modes(frontmatter)

        # Extract AgentSkills.io spec fields
        license_field = frontmatter.get("license")
        compatibility = frontmatter.get("compatibility")
        metadata = frontmatter.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        # Extract version field
        version_field = frontmatter.get("version")
        version_str = str(version_field).strip() if version_field is not None else None

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
            # AgentSkills.io spec fields
            license=str(license_field) if license_field else None,
            compatibility=str(compatibility) if compatibility else None,
            metadata=metadata,
            allowed_tools_raw=allowed_tools_raw if isinstance(allowed_tools_raw, str) else None,
            version=version_str,
        )

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
            raise MarkdownParseError(f"File not found: {file_path}", file_path)
        except OSError as e:
            raise MarkdownParseError(f"Error reading file: {e}", file_path)

        return self.parse(content, file_path)

    def _extract_list(self, data: Dict[str, Any], key: str) -> List[str]:
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
            # Handle comma-separated string
            return [item.strip() for item in value.split(",") if item.strip()]

        return []

    def _extract_agent_modes(self, frontmatter: Dict[str, Any]) -> List[str]:
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
