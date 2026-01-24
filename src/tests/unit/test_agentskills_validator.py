"""
Unit tests for AgentSkills.io specification validator.

Tests the validator against the AgentSkills.io specification:
- Name validation (1-64 chars, lowercase, hyphens only)
- Description validation (1-1024 chars)
- Compatibility validation (≤500 chars)
- allowed-tools format validation
- Directory structure validation
- Deprecated fields warning
"""

import pytest

from src.infrastructure.skill.validator import (
    AgentSkillsValidator,
    AllowedTool,
    SkillValidationError,
    ValidationError,
    ValidationResult,
)


class TestAllowedTool:
    """Tests for AllowedTool parsing."""

    def test_parse_simple_tool(self):
        """Test parsing simple tool name."""
        tool = AllowedTool.parse("Bash")
        assert tool.name == "Bash"
        assert tool.args_pattern is None

    def test_parse_tool_with_args(self):
        """Test parsing tool with argument pattern."""
        tool = AllowedTool.parse("Bash(git:*)")
        assert tool.name == "Bash"
        assert tool.args_pattern == "git:*"

    def test_parse_tool_with_complex_args(self):
        """Test parsing tool with complex argument pattern."""
        tool = AllowedTool.parse("Read(*.py)")
        assert tool.name == "Read"
        assert tool.args_pattern == "*.py"

    def test_parse_many(self):
        """Test parsing multiple tools from string."""
        tools = AllowedTool.parse_many("Bash(git:*) Read Write")
        assert len(tools) == 3
        assert tools[0].name == "Bash"
        assert tools[0].args_pattern == "git:*"
        assert tools[1].name == "Read"
        assert tools[2].name == "Write"

    def test_parse_many_empty(self):
        """Test parsing empty string."""
        tools = AllowedTool.parse_many("")
        assert tools == []

    def test_matches_tool_name(self):
        """Test matching tool by name."""
        tool = AllowedTool(name="Bash", args_pattern=None)
        assert tool.matches("Bash") is True
        assert tool.matches("Read") is False

    def test_matches_with_pattern(self):
        """Test matching tool with pattern."""
        tool = AllowedTool(name="Bash", args_pattern="git:*")
        # Pattern matching uses fnmatch on string representation
        assert tool.matches("Bash", {"command": "git:clone"}) is True
        assert tool.matches("Read") is False


class TestAgentSkillsValidator:
    """Tests for AgentSkillsValidator."""

    @pytest.fixture
    def validator(self):
        """Create a validator instance."""
        return AgentSkillsValidator(strict=False)

    @pytest.fixture
    def strict_validator(self):
        """Create a strict validator instance."""
        return AgentSkillsValidator(strict=True)

    def test_valid_skill(self, tmp_path, validator):
        """Test validating a fully compliant skill."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: my-skill
description: A valid skill that does something useful.
license: MIT
allowed-tools: Bash Read
---
# Instructions
Do something useful.
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_valid_skill_with_metadata(self, tmp_path, validator):
        """Test validating skill with metadata."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: Test skill with metadata.
license: Apache-2.0
compatibility: Requires Python 3.12+
metadata:
  author: test-author
  version: "1.0"
allowed-tools: memory_search graph_query
---
# Test Skill
Instructions here.
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is True

    def test_missing_skill_md(self, tmp_path, validator):
        """Test error when SKILL.md is missing."""
        skill_dir = tmp_path / "empty-skill"
        skill_dir.mkdir()

        result = validator.validate_file(skill_dir)
        assert result.is_valid is False
        assert any(e.field == "file" for e in result.errors)

    def test_invalid_name_uppercase(self, tmp_path, validator):
        """Test error when name contains uppercase."""
        skill_dir = tmp_path / "BadSkill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: BadSkill
description: Test skill.
---
# Test
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is False
        assert any("lowercase" in e.message for e in result.errors)

    def test_invalid_name_spaces(self, tmp_path, validator):
        """Test error when name contains spaces."""
        skill_dir = tmp_path / "bad skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: bad skill
description: Test skill.
---
# Test
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is False
        assert any("name" in e.field for e in result.errors)

    def test_invalid_name_too_long(self, tmp_path, validator):
        """Test error when name exceeds 64 characters."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        long_name = "a" * 65
        (skill_dir / "SKILL.md").write_text(f"""---
name: {long_name}
description: Test skill.
---
# Test
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is False
        assert any("64" in e.message for e in result.errors)

    def test_invalid_name_consecutive_hyphens(self, tmp_path, validator):
        """Test error when name has consecutive hyphens."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: bad--skill
description: Test skill.
---
# Test
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is False
        assert any("name" in e.field for e in result.errors)

    def test_invalid_description_empty(self, tmp_path, validator):
        """Test error when description is empty."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: ""
---
# Test
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is False
        assert any("description" in e.field for e in result.errors)

    def test_invalid_description_too_long(self, tmp_path, validator):
        """Test error when description exceeds 1024 characters."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        long_desc = "a" * 1025
        (skill_dir / "SKILL.md").write_text(f"""---
name: test-skill
description: {long_desc}
---
# Test
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is False
        assert any("1024" in e.message for e in result.errors)

    def test_invalid_compatibility_too_long(self, tmp_path, validator):
        """Test error when compatibility exceeds 500 characters."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        long_compat = "a" * 501
        (skill_dir / "SKILL.md").write_text(f"""---
name: test-skill
description: Test skill.
compatibility: {long_compat}
---
# Test
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is False
        assert any("500" in e.message for e in result.errors)

    def test_invalid_allowed_tools_format(self, tmp_path, validator):
        """Test error when allowed-tools is not a string."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: Test skill.
allowed-tools:
  - Bash
  - Read
---
# Test
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is False
        assert any("allowed-tools" in e.field for e in result.errors)

    def test_deprecated_fields_warning(self, tmp_path, validator):
        """Test warnings for deprecated fields."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: Test skill with deprecated fields.
trigger_patterns:
  - test
tools:
  - Bash
user_invocable: true
---
# Test
""")

        result = validator.validate_file(skill_dir)
        # Should be valid but with warnings
        assert result.is_valid is True
        assert len(result.warnings) >= 2
        warning_fields = [w.field for w in result.warnings]
        assert "trigger_patterns" in warning_fields
        assert "tools" in warning_fields

    def test_deprecated_resources_directory_warning(self, tmp_path, validator):
        """Test warning for deprecated resources directory."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "resources").mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: Test skill.
---
# Test
""")

        result = validator.validate_file(skill_dir)
        assert result.is_valid is True
        assert any("resources" in w.message for w in result.warnings)

    def test_strict_mode_warnings_as_errors(self, tmp_path, strict_validator):
        """Test that strict mode treats warnings as errors."""
        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: Test skill with deprecated fields.
trigger_patterns:
  - test
---
# Test
""")

        result = strict_validator.validate_file(skill_dir)
        # In strict mode, warnings become errors
        assert result.is_valid is False
        assert len(result.errors) >= 1

    def test_validate_content(self, validator):
        """Test validating SKILL.md content directly."""
        content = """---
name: inline-skill
description: An inline skill for testing.
allowed-tools: Bash Read
---
# Instructions
Do something.
"""

        result = validator.validate_content(content)
        assert result.is_valid is True
        assert result.skill_name == "inline-skill"


class TestValidationResult:
    """Tests for ValidationResult."""

    def test_format_valid(self):
        """Test formatting valid result."""
        result = ValidationResult(is_valid=True, skill_name="test-skill")
        formatted = result.format()
        assert "Valid" in formatted

    def test_format_with_errors(self):
        """Test formatting result with errors."""
        result = ValidationResult(
            is_valid=False,
            skill_name="bad-skill",
            errors=[
                ValidationError(
                    severity="error",
                    field="name",
                    message="name is invalid",
                )
            ],
        )
        formatted = result.format()
        assert "Error" in formatted or "error" in formatted.lower()
        assert "name" in formatted

    def test_to_dict(self):
        """Test converting to dictionary."""
        result = ValidationResult(
            is_valid=True,
            skill_name="test-skill",
            warnings=[
                ValidationError(
                    severity="warning",
                    field="tools",
                    message="deprecated",
                )
            ],
        )
        data = result.to_dict()
        assert data["is_valid"] is True
        assert data["skill_name"] == "test-skill"
        assert data["warning_count"] == 1


class TestSkillValidationError:
    """Tests for SkillValidationError exception."""

    def test_exception_message(self):
        """Test exception message formatting."""
        errors = [
            ValidationError(severity="error", field="name", message="invalid name"),
            ValidationError(severity="error", field="description", message="too long"),
        ]
        exc = SkillValidationError("test-skill", errors)

        assert "test-skill" in str(exc)
        assert "invalid name" in str(exc)
        assert exc.skill_id == "test-skill"
        assert len(exc.errors) == 2
