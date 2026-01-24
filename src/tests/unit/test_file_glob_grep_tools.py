"""
Unit tests for FileGlobTool and FileGrepTool.

Tests the file search and content search tools.
"""

import tempfile
from pathlib import Path

import pytest

from src.infrastructure.agent.tools.file_glob import FileGlobTool, glob_recursive
from src.infrastructure.agent.tools.file_grep import FileGrepTool, grep_search


@pytest.mark.unit
class TestGlobRecursive:
    """Test cases for glob_recursive helper function."""

    def test_glob_recursive_python_files(self):
        """Test finding Python files recursively."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create test files
            (root / "test1.py").write_text("# test")
            (root / "test2.txt").write_text("text")
            (root / "subdir").mkdir()
            (root / "subdir" / "test3.py").write_text("# sub")

            results = glob_recursive(root, "*.py")

            assert len(results) == 2
            assert any("test1.py" in r for r in results)
            assert any("test3.py" in r for r in results)
            assert not any("test2.txt" in r for r in results)

    def test_glob_recursive_with_pattern(self):
        """Test finding files with double-star pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("# main")
            (root / "src" / "utils.py").write_text("# utils")
            (root / "test.py").write_text("# test")

            results = glob_recursive(root, "src/**/*.py")

            assert len(results) == 2
            assert all("src/" in r for r in results)

    def test_glob_recursive_with_exclude(self):
        """Test excluding patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            (root / "test.py").write_text("# test")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "lib.js").write_text("// js")

            results = glob_recursive(root, "*.py", exclude_patterns=["node_modules"])

            assert len(results) == 1
            assert "test.py" in results[0]

    def test_glob_recursive_max_results(self):
        """Test max_results limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            for i in range(10):
                (root / f"test{i}.py").write_text(f"# {i}")

            results = glob_recursive(root, "*.py", max_results=5)

            assert len(results) == 5


@pytest.mark.unit
class TestFileGlobTool:
    """Test cases for FileGlobTool."""

    @pytest.fixture
    def file_glob_tool(self):
        """Create a FileGlobTool."""
        # Allow any path for tests
        return FileGlobTool(allowed_paths=None)

    def test_tool_name_and_description(self, file_glob_tool):
        """Test tool metadata."""
        assert file_glob_tool.name == "file_glob"
        assert "glob" in file_glob_tool.description.lower()
        assert "pattern" in file_glob_tool.description.lower()

    async def test_glob_search_files(self, file_glob_tool):
        """Test searching for files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            root = Path(tmpdir)
            (root / "test1.py").write_text("# test")
            (root / "test2.py").write_text("# test")
            (root / "readme.md").write_text("docs")

            result = await file_glob_tool.execute(
                pattern="*.py",
                root=tmpdir,
            )

            assert "Found 2 file(s)" in result
            assert "test1.py" in result
            assert "test2.py" in result
            assert "readme.md" not in result

    async def test_glob_search_recursive(self, file_glob_tool):
        """Test recursive search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("# main")
            (root / "test.py").write_text("# test")

            result = await file_glob_tool.execute(
                pattern="**/*.py",
                root=tmpdir,
            )

            assert "Found 2 file(s)" in result
            assert "main.py" in result
            assert "test.py" in result

    async def test_glob_no_matches(self, file_glob_tool):
        """Test when no files match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await file_glob_tool.execute(
                pattern="*.nonexistent",
                root=tmpdir,
            )

            assert "No files found" in result

    async def test_glob_with_exclude(self, file_glob_tool):
        """Test excluding patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "test.py").write_text("# test")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "lib.js").write_text("// js")

            result = await file_glob_tool.execute(
                pattern="**/*",
                root=tmpdir,
                exclude=["node_modules"],
            )

            assert "test.py" in result
            assert "node_modules" not in result

    async def test_validate_args_missing_pattern(self, file_glob_tool):
        """Test validation fails without pattern."""
        assert file_glob_tool.validate_args() is False
        assert file_glob_tool.validate_args(root="/tmp") is False

    async def test_validate_args_valid(self, file_glob_tool):
        """Test validation with valid args."""
        assert file_glob_tool.validate_args(pattern="*.py") is True

    async def test_parameters_schema(self, file_glob_tool):
        """Test parameters schema."""
        schema = file_glob_tool.get_parameters_schema()

        assert schema["type"] == "object"
        assert "pattern" in schema["properties"]
        assert "root" in schema["properties"]
        assert "exclude" in schema["properties"]
        assert "max_results" in schema["properties"]
        assert "pattern" in schema["required"]


@pytest.mark.unit
class TestGrepSearch:
    """Test cases for grep_search helper function."""

    def test_grep_search_simple_pattern(self):
        """Test searching for simple text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "test.py").write_text("def hello():\n    pass")

            results = grep_search(root, "hello")

            assert len(results) == 1
            file_path, matches = results[0]
            assert "test.py" in file_path
            assert len(matches) > 0

    def test_grep_search_regex_pattern(self):
        """Test searching with regex."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "test.py").write_text("def hello():\ndef world():")

            results = grep_search(root, r"def \w+\(\):")

            assert len(results) == 1
            assert len(results[0][1]) == 2  # Two matches

    def test_grep_search_with_file_pattern(self):
        """Test filtering by file pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "test.py").write_text("hello")
            (root / "test.txt").write_text("hello")

            results = grep_search(root, "hello", file_pattern="*.py")

            assert len(results) == 1
            assert "test.py" in results[0][0]

    def test_grep_search_case_insensitive(self):
        """Test case-insensitive search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "test.py").write_text("HELLO world")

            results = grep_search(root, "hello", case_insensitive=True)

            assert len(results) == 1

    def test_grep_search_with_context(self):
        """Test search with context lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            content = "line1\nline2\nMATCH\nline4\nline5"
            (root / "test.py").write_text(content)

            results = grep_search(root, "MATCH", context_lines=1)

            assert len(results) == 1
            matches = results[0][1]
            assert len(matches) == 1
            line_num, line, context = matches[0]
            assert len(context) == 2  # One line before, one after


@pytest.mark.unit
class TestFileGrepTool:
    """Test cases for FileGrepTool."""

    @pytest.fixture
    def file_grep_tool(self):
        """Create a FileGrepTool."""
        # Allow any path for tests
        return FileGrepTool(allowed_paths=None)

    def test_tool_name_and_description(self, file_grep_tool):
        """Test tool metadata."""
        assert file_grep_tool.name == "file_grep"
        assert "grep" in file_grep_tool.description.lower()
        assert "search" in file_grep_tool.description.lower()

    async def test_grep_search_pattern(self, file_grep_tool):
        """Test searching for pattern in files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "test.py").write_text("def hello():\n    pass")

            result = await file_grep_tool.execute(
                pattern="hello",
                root=tmpdir,
            )

            assert "Found matches" in result
            assert "test.py" in result

    async def test_grep_with_file_pattern(self, file_grep_tool):
        """Test filtering by file type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "test.py").write_text("hello")
            (root / "test.txt").write_text("hello")

            result = await file_grep_tool.execute(
                pattern="hello",
                root=tmpdir,
                file_pattern="*.py",
            )

            assert "test.py" in result
            assert "test.txt" not in result

    async def test_grep_no_matches(self, file_grep_tool):
        """Test when no matches found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await file_grep_tool.execute(
                pattern="nonexistent",
                root=tmpdir,
            )

            assert "No matches found" in result

    async def test_grep_case_insensitive(self, file_grep_tool):
        """Test case-insensitive search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "test.py").write_text("HELLO world")

            result = await file_grep_tool.execute(
                pattern="hello",
                root=tmpdir,
                case_insensitive=True,
            )

            assert "Found matches" in result

    async def test_grep_with_context(self, file_grep_tool):
        """Test search with context lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            content = "line1\nline2\nMATCH HERE\nline4\nline5"
            (root / "test.py").write_text(content)

            result = await file_grep_tool.execute(
                pattern="MATCH",
                root=tmpdir,
                context_lines=1,
            )

            assert "Context:" in result
            assert "line2" in result
            assert "line4" in result

    async def test_validate_args_missing_pattern(self, file_grep_tool):
        """Test validation fails without pattern."""
        assert file_grep_tool.validate_args() is False
        assert file_grep_tool.validate_args(root="/tmp") is False

    async def test_validate_args_valid(self, file_grep_tool):
        """Test validation with valid args."""
        assert file_grep_tool.validate_args(pattern="test") is True

    async def test_parameters_schema(self, file_grep_tool):
        """Test parameters schema."""
        schema = file_grep_tool.get_parameters_schema()

        assert schema["type"] == "object"
        assert "pattern" in schema["properties"]
        assert "root" in schema["properties"]
        assert "file_pattern" in schema["properties"]
        assert "exclude" in schema["properties"]
        assert "context_lines" in schema["properties"]
        assert "case_insensitive" in schema["properties"]
        assert "pattern" in schema["required"]
