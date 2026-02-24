"""
AgentSkills.io specification validator.

Implements validation similar to `skills-ref validate` command,
checking skills against the AgentSkills.io specification.

Reference: https://agentskills.io/specification
"""

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.infrastructure.skill.markdown_parser import MarkdownParseError, MarkdownParser


@dataclass(frozen=True)
class AllowedTool:
    """
    Parsed tool permission from allowed-tools string.

    Represents a single tool with optional argument pattern for
    fine-grained permission control.

    Attributes:
        name: Tool name (e.g., "Bash", "Read")
        args_pattern: Optional argument pattern (e.g., "git:*")

    Example:
        "Bash(git:*)" -> AllowedTool(name="Bash", args_pattern="git:*")
        "Read" -> AllowedTool(name="Read", args_pattern=None)
    """

    name: str
    args_pattern: str | None = None

    # Pattern to parse tool declaration: ToolName or ToolName(args)
    _TOOL_PATTERN = re.compile(r"^(\w+)(?:\(([^)]+)\))?$")

    @classmethod
    def parse(cls, raw: str) -> "AllowedTool":
        """
        Parse a single tool declaration.

        Args:
            raw: Raw tool string like "Bash(git:*)" or "Read"

        Returns:
            AllowedTool instance
        """
        raw = raw.strip()
        match = cls._TOOL_PATTERN.match(raw)
        if match:
            return cls(name=match.group(1), args_pattern=match.group(2))
        # Fallback: treat entire string as tool name
        return cls(name=raw)

    @classmethod
    def parse_many(cls, allowed_tools_raw: str) -> list["AllowedTool"]:
        """
        Parse space-separated allowed-tools string.

        Args:
            allowed_tools_raw: Space-separated tools string
                e.g., "Bash(git:*) Read Write"

        Returns:
            List of AllowedTool instances
        """
        if not allowed_tools_raw or not allowed_tools_raw.strip():
            return []

        tools = []
        for part in allowed_tools_raw.split():
            part = part.strip()
            if part:
                tools.append(cls.parse(part))
        return tools

    def matches(self, tool_name: str, args: dict[str, Any] | None = None) -> bool:
        """
        Check if a tool call matches this permission.

        Args:
            tool_name: Name of the tool being called
            args: Optional arguments passed to the tool

        Returns:
            True if the tool call is permitted
        """
        if self.name != tool_name:
            return False

        if self.args_pattern is None:
            return True  # No argument restrictions

        if args is None:
            return True  # No args to check

        # Use fnmatch for wildcard pattern matching
        args_str = str(args)
        return fnmatch.fnmatch(args_str, f"*{self.args_pattern}*")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "args_pattern": self.args_pattern,
        }


@dataclass
class ValidationError:
    """
    A single validation error or warning.

    Attributes:
        severity: "error" or "warning"
        field: The field that failed validation
        message: Human-readable error message
        suggestion: Optional suggestion for fixing the error
    """

    severity: str  # "error" | "warning"
    field: str
    message: str
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class ValidationResult:
    """
    Result of validating a skill against AgentSkills.io spec.

    Attributes:
        is_valid: Whether the skill passes validation (no errors)
        errors: List of validation errors
        warnings: List of validation warnings
        skill_name: Name of the validated skill (if parsed)
    """

    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    skill_name: str | None = None

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    def format(self) -> str:
        """
        Format validation result as human-readable string.

        Returns:
            Formatted validation result
        """
        lines = []

        if self.skill_name:
            lines.append(f"Validating: {self.skill_name}")

        if self.has_errors:
            lines.append("Errors:")
            for err in self.errors:
                lines.append(f"  [{err.field}] {err.message}")
                if err.suggestion:
                    lines.append(f"    Suggestion: {err.suggestion}")

        if self.has_warnings:
            lines.append("Warnings:")
            for warn in self.warnings:
                lines.append(f"  [{warn.field}] {warn.message}")
                if warn.suggestion:
                    lines.append(f"    Suggestion: {warn.suggestion}")

        if not self.has_errors and not self.has_warnings:
            lines.append("Valid")
        elif self.has_errors:
            lines.append(
                f"Result: Invalid ({len(self.errors)} errors, {len(self.warnings)} warnings)"
            )
        else:
            lines.append(f"Result: Valid with warnings ({len(self.warnings)} warnings)")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "is_valid": self.is_valid,
            "skill_name": self.skill_name,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


class SkillValidationError(Exception):
    """
    Exception raised when skill validation fails in strict mode.

    Attributes:
        skill_id: The ID or name of the skill that failed
        errors: List of validation errors
    """

    def __init__(self, skill_id: str, errors: list[ValidationError]) -> None:
        self.skill_id = skill_id
        self.errors = errors
        error_messages = [f"[{e.field}] {e.message}" for e in errors]
        super().__init__(f"Skill '{skill_id}' failed validation: {'; '.join(error_messages)}")


class AgentSkillsValidator:
    """
    AgentSkills.io specification validator.

    Validates skills against the AgentSkills.io specification:
    - name: 1-64 characters, lowercase, hyphens only
    - description: 1-1024 characters, required
    - license: optional
    - compatibility: optional, ≤500 characters
    - metadata: optional, key-value pairs
    - allowed-tools: optional, space-separated string

    Reference: https://agentskills.io/specification

    Example:
        validator = AgentSkillsValidator()
        result = validator.validate_file(Path("./my-skill"))
        if not result.is_valid:
            print(result.format())
    """

    # Name pattern: lowercase alphanumeric, hyphens allowed but not at start/end
    # and no consecutive hyphens
    NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    # Maximum lengths per spec
    NAME_MAX_LENGTH = 64
    DESCRIPTION_MAX_LENGTH = 1024
    COMPATIBILITY_MAX_LENGTH = 500

    # Fields that are not part of AgentSkills.io spec (custom extensions)
    DEPRECATED_FIELDS = {
        "trigger_patterns": "Use name/description for implicit triggering",
        "triggers": "Use name/description for implicit triggering",
        "tools": "Use 'allowed-tools' with space-separated format",
        "user_invocable": "Not part of AgentSkills.io spec",
        "user-invocable": "Not part of AgentSkills.io spec",
        "context": "Not part of AgentSkills.io spec",
        "agent": "Not part of AgentSkills.io spec",
        "trigger_type": "Not part of AgentSkills.io spec",
    }

    def __init__(self, strict: bool = False) -> None:
        """
        Initialize the validator.

        Args:
            strict: If True, warnings are treated as errors
        """
        self.strict = strict
        self.parser = MarkdownParser()

    def validate_file(self, skill_path: Path) -> ValidationResult:
        """
        Validate a skill directory against AgentSkills.io specification.

        Args:
            skill_path: Path to skill directory (containing SKILL.md)

        Returns:
            ValidationResult with errors and warnings
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationError] = []
        skill_name: str | None = None

        # Check SKILL.md exists
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            errors.append(
                ValidationError(
                    severity="error",
                    field="file",
                    message="SKILL.md not found",
                    suggestion="Create a SKILL.md file in the skill directory",
                )
            )
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # Parse SKILL.md
        try:
            parsed = self.parser.parse_file(str(skill_md))
            skill_name = parsed.name
        except MarkdownParseError as e:
            errors.append(
                ValidationError(
                    severity="error",
                    field="format",
                    message=str(e),
                )
            )
            return ValidationResult(
                is_valid=False, errors=errors, warnings=warnings, skill_name=skill_name
            )

        # Validate name
        self._validate_name(parsed.name, errors)

        # Validate description
        self._validate_description(parsed.description, errors)

        # Validate compatibility if present
        compatibility = parsed.frontmatter.get("compatibility")
        if compatibility:
            self._validate_compatibility(str(compatibility), errors)

        # Validate allowed-tools format if present
        allowed_tools = parsed.frontmatter.get("allowed-tools")
        if allowed_tools is not None:
            self._validate_allowed_tools(allowed_tools, errors)

        # Validate directory structure
        self._validate_directory_structure(skill_path, warnings)

        # Check for deprecated/non-spec fields
        self._check_deprecated_fields(parsed.frontmatter, warnings)

        # In strict mode, warnings become errors
        if self.strict:
            errors.extend(warnings)
            warnings = []

        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            skill_name=skill_name,
        )

    def validate_content(self, content: str, skill_name: str | None = None) -> ValidationResult:
        """
        Validate SKILL.md content directly (without file).

        Args:
            content: Raw SKILL.md content
            skill_name: Optional skill name for error messages

        Returns:
            ValidationResult
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationError] = []

        # Parse content
        try:
            parsed = self.parser.parse(content)
            skill_name = parsed.name
        except MarkdownParseError as e:
            errors.append(
                ValidationError(
                    severity="error",
                    field="format",
                    message=str(e),
                )
            )
            return ValidationResult(
                is_valid=False, errors=errors, warnings=warnings, skill_name=skill_name
            )

        # Validate name
        self._validate_name(parsed.name, errors)

        # Validate description
        self._validate_description(parsed.description, errors)

        # Validate compatibility if present
        compatibility = parsed.frontmatter.get("compatibility")
        if compatibility:
            self._validate_compatibility(str(compatibility), errors)

        # Validate allowed-tools format if present
        allowed_tools = parsed.frontmatter.get("allowed-tools")
        if allowed_tools is not None:
            self._validate_allowed_tools(allowed_tools, errors)

        # Check for deprecated fields
        self._check_deprecated_fields(parsed.frontmatter, warnings)

        # In strict mode, warnings become errors
        if self.strict:
            errors.extend(warnings)
            warnings = []

        is_valid = len(errors) == 0
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            skill_name=skill_name,
        )

    def _validate_name(self, name: str, errors: list[ValidationError]) -> None:
        """Validate the name field."""
        if not name:
            errors.append(
                ValidationError(
                    severity="error",
                    field="name",
                    message="name is required",
                )
            )
            return

        # Length check
        if len(name) > self.NAME_MAX_LENGTH:
            errors.append(
                ValidationError(
                    severity="error",
                    field="name",
                    message=f"name must be 1-{self.NAME_MAX_LENGTH} characters, got {len(name)}",
                    suggestion=f"Shorten the name to max {self.NAME_MAX_LENGTH} characters",
                )
            )

        # Format check
        if not self.NAME_PATTERN.match(name):
            errors.append(
                ValidationError(
                    severity="error",
                    field="name",
                    message=f"name '{name}' must be lowercase with hyphens only, "
                    "no leading/trailing/consecutive hyphens",
                    suggestion="Use format: 'my-skill-name' (lowercase, hyphens, no spaces)",
                )
            )

    def _validate_description(self, description: str, errors: list[ValidationError]) -> None:
        """Validate the description field."""
        if not description or not description.strip():
            errors.append(
                ValidationError(
                    severity="error",
                    field="description",
                    message="description is required and cannot be empty",
                    suggestion="Add a clear description explaining the skill's use case",
                )
            )
            return

        # Length check
        if len(description) > self.DESCRIPTION_MAX_LENGTH:
            errors.append(
                ValidationError(
                    severity="error",
                    field="description",
                    message=f"description must be 1-{self.DESCRIPTION_MAX_LENGTH} characters, "
                    f"got {len(description)}",
                    suggestion=f"Keep description concise (max {self.DESCRIPTION_MAX_LENGTH} characters)",
                )
            )

    def _validate_compatibility(self, compatibility: str, errors: list[ValidationError]) -> None:
        """Validate the compatibility field."""
        if len(compatibility) > self.COMPATIBILITY_MAX_LENGTH:
            errors.append(
                ValidationError(
                    severity="error",
                    field="compatibility",
                    message=f"compatibility must be <={self.COMPATIBILITY_MAX_LENGTH} characters, "
                    f"got {len(compatibility)}",
                    suggestion="Simplify environment requirements description",
                )
            )

    def _validate_allowed_tools(self, allowed_tools: Any, errors: list[ValidationError]) -> None:
        """Validate the allowed-tools field format."""
        if not isinstance(allowed_tools, str):
            errors.append(
                ValidationError(
                    severity="error",
                    field="allowed-tools",
                    message=f"allowed-tools must be a string, got {type(allowed_tools).__name__}",
                    suggestion='Use format: "Bash Read Write" (space-separated)',
                )
            )
            return

        # Try to parse the tools
        try:
            tools = AllowedTool.parse_many(allowed_tools)
            if not tools and allowed_tools.strip():
                errors.append(
                    ValidationError(
                        severity="error",
                        field="allowed-tools",
                        message="allowed-tools contains no valid tool names",
                        suggestion="Specify tools like: Bash Read Write",
                    )
                )
        except Exception as e:
            errors.append(
                ValidationError(
                    severity="error",
                    field="allowed-tools",
                    message=f"Failed to parse allowed-tools: {e}",
                )
            )

    def _validate_directory_structure(
        self, skill_path: Path, warnings: list[ValidationError]
    ) -> None:
        """Validate the skill directory structure."""
        # Check for deprecated directory names
        if (skill_path / "resources").exists():
            warnings.append(
                ValidationError(
                    severity="warning",
                    field="directory",
                    message="'resources/' directory is deprecated",
                    suggestion="Rename to 'references/' or 'assets/' per AgentSkills.io spec",
                )
            )

    def _check_deprecated_fields(
        self, frontmatter: dict[str, Any], warnings: list[ValidationError]
    ) -> None:
        """Check for deprecated/non-spec fields in frontmatter."""
        for field_name, suggestion in self.DEPRECATED_FIELDS.items():
            if field_name in frontmatter:
                warnings.append(
                    ValidationError(
                        severity="warning",
                        field=field_name,
                        message=f"'{field_name}' is not part of AgentSkills.io spec",
                        suggestion=suggestion,
                    )
                )
