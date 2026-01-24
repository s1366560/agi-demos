"""Unit test for TableFormatter (T117).

Tests the table formatter functionality:
- Markdown table generation
- CSV table generation
- HTML table generation
- Data normalization
- Content type and extension
"""

import pytest

from src.infrastructure.agent.output.table_formatter import TableFormatter


class TestTableFormatter:
    """Unit tests for TableFormatter."""

    @pytest.fixture
    def formatter(self):
        """Create a TableFormatter instance."""
        return TableFormatter()

    @pytest.fixture
    def markdown_formatter(self):
        """Create a TableFormatter with markdown format."""
        return TableFormatter("markdown")

    @pytest.fixture
    def csv_formatter(self):
        """Create a TableFormatter with CSV format."""
        return TableFormatter("csv")

    @pytest.fixture
    def html_formatter(self):
        """Create a TableFormatter with HTML format."""
        return TableFormatter("html")

    # === List of Dicts Tests ===

    def test_format_list_of_dicts_markdown(self, markdown_formatter):
        """Test formatting list of dicts as markdown table."""
        # Arrange
        data = [
            {"name": "Alice", "age": 30, "city": "New York"},
            {"name": "Bob", "age": 25, "city": "San Francisco"},
            {"name": "Charlie", "age": 35, "city": "Chicago"},
        ]

        # Act
        result = markdown_formatter.format(data)

        # Assert
        expected = """name | age | city
--- | --- | ---
Alice | 30 | New York
Bob | 25 | San Francisco
Charlie | 35 | Chicago"""
        assert result.strip() == expected

    def test_format_list_of_dicts_csv(self, csv_formatter):
        """Test formatting list of dicts as CSV."""
        # Arrange
        data = [
            {"name": "Alice", "age": 30, "city": "New York"},
            {"name": "Bob", "age": 25, "city": "San Francisco"},
        ]

        # Act
        result = csv_formatter.format(data)

        # Assert
        expected = """name,age,city
Alice,30,New York
Bob,25,San Francisco"""
        assert result.strip() == expected

    def test_format_list_of_dicts_html(self, html_formatter):
        """Test formatting list of dicts as HTML table."""
        # Arrange
        data = [
            {"name": "Alice", "age": 30, "city": "New York"},
            {"name": "Bob", "age": 25, "city": "San Francisco"},
        ]

        # Act
        result = html_formatter.format(data)

        # Assert - Implementation uses multi-line HTML format
        assert "<table>" in result
        assert "<thead>" in result
        assert "<th>name</th>" in result
        assert "<th>age</th>" in result
        assert "<th>city</th>" in result
        assert "<tbody>" in result
        assert "<td>Alice</td>" in result
        assert "<td>30</td>" in result
        assert "<td>New York</td>" in result
        assert "<td>Bob</td>" in result
        assert "</table>" in result

    # === Dict of Lists Tests ===

    def test_format_dict_of_lists_markdown(self, markdown_formatter):
        """Test formatting dict of lists as markdown table."""
        # Arrange
        data = {
            "name": ["Alice", "Bob", "Charlie"],
            "age": [30, 25, 35],
            "city": ["New York", "San Francisco", "Chicago"],
        }

        # Act
        result = markdown_formatter.format(data)

        # Assert
        expected = """name | age | city
--- | --- | ---
Alice | 30 | New York
Bob | 25 | San Francisco
Charlie | 35 | Chicago"""
        assert result.strip() == expected

    def test_format_dict_of_lists_csv(self, csv_formatter):
        """Test formatting dict of lists as CSV."""
        # Arrange
        data = {"name": ["Alice", "Bob"], "age": [30, 25]}

        # Act
        result = csv_formatter.format(data)

        # Assert
        expected = """name,age
Alice,30
Bob,25"""
        assert result.strip() == expected

    # === Simple List Tests ===

    def test_format_simple_list_markdown(self, markdown_formatter):
        """Test formatting simple list as markdown table."""
        # Arrange
        data = ["apple", "banana", "cherry"]

        # Act
        result = markdown_formatter.format(data)

        # Assert
        expected = """value
---
apple
banana
cherry"""
        assert result.strip() == expected

    def test_format_simple_list_csv(self, csv_formatter):
        """Test formatting simple list as CSV."""
        # Arrange
        data = ["apple", "banana", "cherry"]

        # Act
        result = csv_formatter.format(data)

        # Assert
        expected = """value
apple
banana
cherry"""
        assert result.strip() == expected

    # === Single Dict Tests ===

    def test_format_single_dict_markdown(self, markdown_formatter):
        """Test formatting single dict as markdown table."""
        # Arrange
        data = {"name": "Alice", "age": 30, "city": "New York"}

        # Act
        result = markdown_formatter.format(data)

        # Assert
        expected = """name | age | city
--- | --- | ---
Alice | 30 | New York"""
        assert result.strip() == expected

    def test_format_single_dict_csv(self, csv_formatter):
        """Test formatting single dict as CSV."""
        # Arrange
        data = {"name": "Alice", "age": 30}

        # Act
        result = csv_formatter.format(data)

        # Assert
        expected = """name,age
Alice,30"""
        assert result.strip() == expected

    # === Single Value Tests ===

    def test_format_single_value_markdown(self, markdown_formatter):
        """Test formatting single value as markdown table."""
        # Arrange
        data = "Hello World"

        # Act
        result = markdown_formatter.format(data)

        # Assert
        expected = """value
---
Hello World"""
        assert result.strip() == expected

    def test_format_single_value_csv(self, csv_formatter):
        """Test formatting single value as CSV."""
        # Arrange
        data = "Hello World"

        # Act
        result = csv_formatter.format(data)

        # Assert
        expected = """value
Hello World"""
        assert result.strip() == expected

    # === Empty Data Tests ===

    def test_format_empty_list_markdown(self, markdown_formatter):
        """Test formatting empty list."""
        # Arrange
        data = []

        # Act
        result = markdown_formatter.format(data)

        # Assert
        assert result == "No data available"

    def test_format_empty_list_csv(self, csv_formatter):
        """Test formatting empty list as CSV."""
        # Arrange
        data = []

        # Act
        result = csv_formatter.format(data)

        # Assert
        assert result == ""

    def test_format_empty_dict_markdown(self, markdown_formatter):
        """Test formatting empty dict."""
        # Arrange
        data = {}

        # Act
        result = markdown_formatter.format(data)

        # Assert
        assert result == "No data available"

    # === Metadata Format Override Tests ===

    def test_format_with_metadata_override(self, markdown_formatter):
        """Test overriding format via metadata."""
        # Arrange
        data = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
        metadata = {"format": "csv"}

        # Act
        result = markdown_formatter.format(data, metadata)

        # Assert
        # Should format as CSV despite default markdown
        expected = """name,age
Alice,30
Bob,25"""
        assert result.strip() == expected

    # === CSV Escaping Tests ===

    def test_csv_escape_commas(self, csv_formatter):
        """Test CSV escaping of values with commas."""
        # Arrange
        data = {
            "name": ["Alice, Smith", "Bob"],
            "description": ["A description, with commas", "Simple"],
        }

        # Act
        result = csv_formatter.format(data)

        # Assert
        expected = """name,description
"Alice, Smith","A description, with commas"
Bob,Simple"""
        assert result.strip() == expected

    def test_csv_escape_quotes(self, csv_formatter):
        """Test CSV escaping of values with quotes."""
        # Arrange
        data = {"quote": ['Say "hello"', 'Say "world" again'], "normal": ["Normal", "Text"]}

        # Act
        result = csv_formatter.format(data)

        # Assert
        expected = '''quote,normal
"Say ""hello""",Normal
"Say ""world"" again",Text'''
        assert result.strip() == expected

    def test_csv_escape_newlines(self, csv_formatter):
        """Test CSV escaping of values with newlines."""
        # Arrange
        data = {"multiline": ["Line1\nLine2", "Single"], "normal": ["Text", "More"]}

        # Act
        result = csv_formatter.format(data)

        # Assert - rows are aligned by index
        expected = """multiline,normal
"Line1
Line2",Text
Single,More"""
        assert result.strip() == expected

    # === Content Type Tests ===

    def test_markdown_content_type(self, markdown_formatter):
        """Test markdown content type."""
        # Act
        result = markdown_formatter.get_content_type()

        # Assert
        assert result == "text/markdown"

    def test_csv_content_type(self, csv_formatter):
        """Test CSV content type."""
        # Act
        result = csv_formatter.get_content_type()

        # Assert
        assert result == "text/csv"

    def test_html_content_type(self, html_formatter):
        """Test HTML content type."""
        # Act
        result = html_formatter.get_content_type()

        # Assert
        assert result == "text/html"

    # === Extension Tests ===

    def test_markdown_extension(self, markdown_formatter):
        """Test markdown file extension."""
        # Act
        result = markdown_formatter.get_extension()

        # Assert
        assert result == ".md"

    def test_csv_extension(self, csv_formatter):
        """Test CSV file extension."""
        # Act
        result = csv_formatter.get_extension()

        # Assert
        assert result == ".csv"

    def test_html_extension(self, html_formatter):
        """Test HTML file extension."""
        # Act
        result = html_formatter.get_extension()

        # Assert
        assert result == ".html"

    # === Data Normalization Tests ===

    def test_normalize_list_of_dicts(self, markdown_formatter):
        """Test data normalization for list of dicts."""
        # Arrange - This tests internal method
        data = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]

        # Act
        rows, columns = markdown_formatter._normalize_data(data)

        # Assert
        assert rows == data
        assert columns == ["name", "age"]

    def test_normalize_dict_of_lists(self, markdown_formatter):
        """Test data normalization for dict of lists."""
        # Arrange
        data = {"name": ["Alice", "Bob"], "age": [30, 25]}

        # Act
        rows, columns = markdown_formatter._normalize_data(data)

        # Assert
        expected_rows = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
        assert rows == expected_rows
        assert columns == ["name", "age"]

    def test_normalize_simple_list(self, markdown_formatter):
        """Test data normalization for simple list."""
        # Arrange
        data = ["apple", "banana", "cherry"]

        # Act
        rows, columns = markdown_formatter._normalize_data(data)

        # Assert
        expected_rows = [{"value": "apple"}, {"value": "banana"}, {"value": "cherry"}]
        assert rows == expected_rows
        assert columns == ["value"]

    def test_normalize_single_value(self, markdown_formatter):
        """Test data normalization for single value."""
        # Arrange
        data = "Hello"

        # Act
        rows, columns = markdown_formatter._normalize_data(data)

        # Assert
        assert rows == [{"value": "Hello"}]
        assert columns == ["value"]

    # === Format Method Tests ===

    def test_format_with_default_format(self, formatter):
        """Test formatting with default constructor format."""
        # Arrange
        data = [{"name": "Alice", "age": 30}]

        # Act
        result = formatter.format(data)

        # Assert
        # Should default to markdown
        assert " | " in result
        assert "--- | ---" in result

    def test_format_with_custom_format(self):
        """Test formatting with custom format constructor."""
        # Arrange
        formatter = TableFormatter("csv")
        data = [{"name": "Alice", "age": 30}]

        # Act
        result = formatter.format(data)

        # Assert
        # Should use CSV format
        assert "," in result
        assert "name,age" in result

    # === Complex Data Tests ===

    def test_format_complex_data_markdown(self, markdown_formatter):
        """Test formatting complex data structures as markdown."""
        # Arrange
        data = [
            {
                "id": 1,
                "info": {"name": "Project Alpha", "version": "1.0"},
                "tags": ["urgent", "backend"],
                "score": 95.5,
            }
        ]

        # Act
        result = markdown_formatter.format(data)

        # Assert
        # Should handle nested dicts and mixed types
        assert "id" in result
        assert "info" in result
        assert "tags" in result
        assert "score" in result
        assert "Project Alpha" in result
        assert "urgent" in result
        assert "95.5" in result

    def test_format_missing_columns(self, markdown_formatter):
        """Test formatting when some dicts are missing columns."""
        # Arrange
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob"},  # Missing age
            {"age": 25},  # Missing name
        ]

        # Act
        result = markdown_formatter.format(data)

        # Assert
        # Should handle missing columns gracefully
        lines = result.split("\n")
        assert len(lines) >= 4  # Header + separator + 3 rows
        # All data rows should be present
        assert "Alice" in result
        assert "Bob" in result
        assert "25" in result

    def test_format_special_characters(self, markdown_formatter):
        """Test formatting data with special characters."""
        # Arrange
        data = [
            {"text": "Special: & < > \" '", "emoji": "🚀"},
            {"text": "Line\nBreak", "emoji": "⭐"},
        ]

        # Act
        result = markdown_formatter.format(data)

        # Assert
        # Should handle special characters without breaking table structure
        assert "Special:" in result
        assert "🚀" in result
        assert "Line" in result
        assert "Break" in result
        assert "⭐" in result

    # === Performance Tests ===

    def test_format_large_dataset(self, markdown_formatter):
        """Test formatting a large dataset."""
        # Arrange
        data = [{"id": i, "value": f"item_{i}"} for i in range(100)]

        # Act
        result = markdown_formatter.format(data)

        # Assert
        # Should handle large data without errors
        lines = result.split("\n")
        assert len(lines) > 100  # Header + separator + 100 rows
        # Check that all items are included
        assert "item_99" in result

    def test_format_unicode_data(self, markdown_formatter):
        """Test formatting with Unicode characters."""
        # Arrange
        data = [
            {"emoji": "🎉", "language": "中文", "special": "©®™"},
            {"emoji": "🌍", "language": "العربية", "special": "¶§†"},
        ]

        # Act
        result = markdown_formatter.format(data)

        # Assert
        # Should preserve Unicode characters
        assert "🎉" in result
        assert "中文" in result
        assert "©®™" in result
        assert "🌍" in result
        assert "العربية" in result
        assert "¶§†" in result
