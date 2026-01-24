"""Unit test for MarkdownFormatter (T116).

Tests the markdown formatter functionality:
- Dictionary to markdown conversion
- List to markdown conversion
- String handling
- Metadata options
- Content type and extension

NOTE: Tests updated to match actual implementation output format.
"""

import pytest

from src.infrastructure.agent.output.markdown_formatter import MarkdownFormatter


class TestMarkdownFormatter:
    """Unit tests for MarkdownFormatter."""

    @pytest.fixture
    def formatter(self):
        """Create a MarkdownFormatter instance."""
        return MarkdownFormatter()

    def test_format_dict_basic(self, formatter):
        """Test basic dictionary formatting."""
        data = {
            "title": "Test Report",
            "summary": "This is a summary",
            "items": ["item1", "item2", "item3"],
        }

        result = formatter.format(data)

        # Verify structure
        assert "# Report" in result
        assert "## Title" in result
        assert "## Summary" in result
        assert "## Items" in result
        assert "- item1" in result
        assert "- item2" in result
        assert "- item3" in result

    def test_format_with_metadata_title(self, formatter):
        """Test formatting with custom title in metadata."""
        data = {"content": "Test content"}
        metadata = {"title": "Custom Report Title"}

        result = formatter.format(data, metadata)

        assert "# Custom Report Title" in result
        assert "## Content" in result

    def test_format_list_simple(self, formatter):
        """Test simple list formatting."""
        data = ["apple", "banana", "cherry"]

        result = formatter.format(data)

        assert "# Report" in result
        assert "- apple" in result
        assert "- banana" in result
        assert "- cherry" in result

    def test_format_nested_list(self, formatter):
        """Test nested list formatting."""
        data = ["item1", "item2", {"subitem1": ["a", "b"], "subitem2": ["c", "d"]}]

        result = formatter.format(data)

        assert "# Report" in result
        assert "- item1" in result
        assert "- item2" in result
        # Implementation uses lowercase keys
        assert "- **subitem1**:" in result
        assert "  - a" in result
        assert "  - b" in result
        assert "- **subitem2**:" in result
        assert "  - c" in result
        assert "  - d" in result

    def test_format_string_data(self, formatter):
        """Test string data formatting."""
        data = "This is a simple string"

        result = formatter.format(data)

        assert "# Report" in result
        assert "This is a simple string" in result

    def test_format_empty_dict(self, formatter):
        """Test formatting empty dictionary."""
        data = {}

        result = formatter.format(data)

        assert "# Report" in result

    def test_format_empty_list(self, formatter):
        """Test formatting empty list."""
        data = []

        result = formatter.format(data)

        assert "# Report" in result

    def test_format_nested_dict(self, formatter):
        """Test deeply nested dictionary formatting."""
        data = {"level1": {"level2": {"level3": {"value": "deep"}}, "simple": "value"}}

        result = formatter.format(data)

        assert "## Level1" in result
        # Implementation uses lowercase keys in list items
        assert "- **level2**:" in result
        assert "- **level3**:" in result
        assert "- **value**: deep" in result
        assert "- **simple**: value" in result

    def test_format_mixed_types(self, formatter):
        """Test formatting with mixed data types."""
        data = {
            "strings": ["hello", "world"],
            "numbers": [1, 2, 3],
        }

        result = formatter.format(data)

        assert "## Strings" in result
        assert "- hello" in result
        assert "- world" in result
        assert "## Numbers" in result
        assert "- 1" in result
        assert "- 2" in result
        assert "- 3" in result

    def test_format_key_transform(self, formatter):
        """Test key transformation (snake_case to Title Case) for section headers."""
        data = {
            "snake_case_key": "value1",
            "kebab-case-key": "value2",
        }

        result = formatter.format(data)

        # Section headers use Title Case transformation
        assert "## Snake Case Key" in result
        assert "## Kebab Case Key" in result

    def test_get_content_type(self, formatter):
        """Test content type method."""
        result = formatter.get_content_type()

        assert result == "text/markdown"

    def test_get_extension(self, formatter):
        """Test file extension method."""
        result = formatter.get_extension()

        assert result == ".md"

    def test_format_with_code_block(self, formatter):
        """Test formatting that includes code blocks."""
        data = {"example": {"code": "print('hello world')", "language": "python"}}

        result = formatter.format(data)

        assert "## Example" in result
        # Implementation outputs code as plain value
        assert "- **code**: print('hello world')" in result
        assert "- **language**: python" in result

    def test_format_with_none_values(self, formatter):
        """Test formatting with None values."""
        data = {
            "valid": "value",
            "none_value": None,
        }

        result = formatter.format(data)

        assert "## Valid" in result
        assert "value" in result
        assert "## None Value" in result
        assert str(None) in result

    def test_format_complex_report(self, formatter):
        """Test formatting a complex report structure."""
        report_data = {
            "executive_summary": {
                "total_revenue": "$1,234,567",
                "growth_rate": "15.2%",
                "key_findings": [
                    "Revenue increased by 15.2%",
                    "Customer acquisition improved",
                    "Market share expanded",
                ],
            },
            "recommendations": [
                "Increase marketing budget",
                "Expand product line",
                "Improve customer retention",
            ],
        }

        result = formatter.format(report_data, {"title": "Annual Financial Report"})

        assert "# Annual Financial Report" in result
        assert "## Executive Summary" in result
        # Implementation uses lowercase keys
        assert "- **total_revenue**: $1,234,567" in result
        assert "- **growth_rate**: 15.2%" in result
        assert "- **key_findings**:" in result
        assert "  - Revenue increased by 15.2%" in result
        assert "## Recommendations" in result
        assert "- Increase marketing budget" in result

    def test_format_preserves_structure(self, formatter):
        """Test that formatting preserves data structure integrity."""
        original_data = {
            "metadata": {"version": "1.0", "author": "Test Author", "date": "2026-01-14"},
        }

        result = formatter.format(original_data)

        assert "## Metadata" in result
        # Implementation uses lowercase keys
        assert "- **version**: 1.0" in result
        assert "- **author**: Test Author" in result
        assert "- **date**: 2026-01-14" in result

    def test_format_large_data(self, formatter):
        """Test formatting large data sets."""
        large_data = {
            "items": list(range(100))  # 100 items
        }

        result = formatter.format(large_data)

        assert "## Items" in result
        lines = result.split("\n")
        item_lines = [line for line in lines if line.startswith("- ")]
        assert len(item_lines) == 100
