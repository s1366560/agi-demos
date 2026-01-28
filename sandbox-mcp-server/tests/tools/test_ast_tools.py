"""Tests for AST parsing tools using TDD methodology.

TDD Cycle:
1. RED - Write failing test
2. GREEN - Implement minimal code to pass
3. REFACTOR - Improve while keeping tests passing
"""

import asyncio
import pytest

from src.tools.ast_tools import (
    ast_extract_function,
    ast_find_symbols,
    ast_get_imports,
    ast_parse,
)


class TestASTParse:
    """Test suite for ast_parse tool."""

    @pytest.mark.asyncio
    async def test_parse_valid_python_file(self):
        """Test parsing a valid Python file."""
        result = await ast_parse(
            file_path="tests/fixtures/sample.py",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        assert "content" in result
        assert "metadata" in result

        metadata = result["metadata"]
        assert metadata["file_path"] == "tests/fixtures/sample.py"
        assert metadata["total_symbols"] > 0

        symbols = metadata["symbols"]
        assert len(symbols["classes"]) >= 2  # BaseService, UserService
        assert len(symbols["functions"]) >= 3  # calculate_score, fetch_data, main
        assert len(symbols["imports"]) > 0

    @pytest.mark.asyncio
    async def test_parse_nonexistent_file(self):
        """Test parsing a file that doesn't exist."""
        result = await ast_parse(
            file_path="tests/fixtures/nonexistent.py",
            _workspace_dir=".",
        )

        assert result.get("isError") is True
        assert "not found" in result["content"][0]["text"].lower()

    @pytest.mark.asyncio
    async def test_parse_includes_docstrings(self):
        """Test that docstrings are included by default."""
        result = await ast_parse(
            file_path="tests/fixtures/sample.py",
            include_docstrings=True,
            _workspace_dir=".",
        )

        symbols = result["metadata"]["symbols"]

        # Check that classes have docstrings
        user_service = next((c for c in symbols["classes"] if c["name"] == "UserService"), None)
        assert user_service is not None
        assert user_service.get("docstring") is not None

        # Check that functions have docstrings
        calc_score = next((f for f in symbols["functions"] if f["name"] == "calculate_score"), None)
        assert calc_score is not None
        assert calc_score.get("docstring") is not None

    @pytest.mark.asyncio
    async def test_parse_without_docstrings(self):
        """Test parsing without docstrings."""
        result = await ast_parse(
            file_path="tests/fixtures/sample.py",
            include_docstrings=False,
            _workspace_dir=".",
        )

        assert not result.get("isError")


class TestASTFindSymbols:
    """Test suite for ast_find_symbols tool."""

    @pytest.mark.asyncio
    async def test_find_classes(self):
        """Test finding classes."""
        result = await ast_find_symbols(
            file_path="tests/fixtures/sample.py",
            symbol_type="class",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["count"] >= 2

        matches = metadata["matches"]
        class_names = [m["name"] for m in matches]
        assert "BaseService" in class_names
        assert "UserService" in class_names

    @pytest.mark.asyncio
    async def test_find_functions(self):
        """Test finding functions."""
        result = await ast_find_symbols(
            file_path="tests/fixtures/sample.py",
            symbol_type="function",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["count"] >= 2

        matches = metadata["matches"]
        function_names = [m["name"] for m in matches]
        assert "calculate_score" in function_names
        assert "main" in function_names

    @pytest.mark.asyncio
    async def test_find_imports(self):
        """Test finding imports."""
        result = await ast_find_symbols(
            file_path="tests/fixtures/sample.py",
            symbol_type="import",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["count"] > 0

    @pytest.mark.asyncio
    async def test_find_with_pattern_filter(self):
        """Test finding symbols with regex pattern."""
        result = await ast_find_symbols(
            file_path="tests/fixtures/sample.py",
            symbol_type="class",
            pattern="Service",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["count"] >= 1

        # Should only match classes containing "Service"
        matches = metadata["matches"]
        for m in matches:
            assert "Service" in m["name"]

    @pytest.mark.asyncio
    async def test_find_invalid_symbol_type(self):
        """Test with invalid symbol type."""
        result = await ast_find_symbols(
            file_path="tests/fixtures/sample.py",
            symbol_type="invalid_type",
            _workspace_dir=".",
        )

        assert result.get("isError") is True
        assert "Invalid symbol_type" in result["content"][0]["text"]


class TestASTExtractFunction:
    """Test suite for ast_extract_function tool."""

    @pytest.mark.asyncio
    async def test_extract_function(self):
        """Test extracting a function."""
        result = await ast_extract_function(
            file_path="tests/fixtures/sample.py",
            function_name="calculate_score",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["found"] is True
        assert metadata["name"] == "calculate_score"
        assert metadata["lineno"] > 0

        content = result["content"][0]["text"]
        assert "def calculate_score" in content

    @pytest.mark.asyncio
    async def test_extract_method(self):
        """Test extracting a class method."""
        result = await ast_extract_function(
            file_path="tests/fixtures/sample.py",
            function_name="get_user",
            class_name="UserService",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["found"] is True
        assert metadata["name"] == "get_user"
        assert metadata["class"] == "UserService"

    @pytest.mark.asyncio
    async def test_extract_nonexistent_function(self):
        """Test extracting a function that doesn't exist."""
        result = await ast_extract_function(
            file_path="tests/fixtures/sample.py",
            function_name="nonexistent_function",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["found"] is False

    @pytest.mark.asyncio
    async def test_extract_function_from_nonexistent_file(self):
        """Test extracting from a file that doesn't exist."""
        result = await ast_extract_function(
            file_path="tests/fixtures/nonexistent.py",
            function_name="calculate_score",
            _workspace_dir=".",
        )

        assert result.get("isError") is True


class TestASTGetImports:
    """Test suite for ast_get_imports tool."""

    @pytest.mark.asyncio
    async def test_get_imports_flat(self):
        """Test getting imports as a flat list."""
        result = await ast_get_imports(
            file_path="tests/fixtures/sample.py",
            group_by_module=False,
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["count"] > 0
        assert "imports" in metadata

    @pytest.mark.asyncio
    async def test_get_imports_grouped(self):
        """Test getting imports grouped by module."""
        result = await ast_get_imports(
            file_path="tests/fixtures/sample.py",
            group_by_module=True,
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert "grouped" in metadata

        # Check that imports are grouped
        grouped = metadata["grouped"]
        # Should have at least some standard library imports
        assert any("os" in key or "sys" in key or "typing" in key for key in grouped.keys())

    @pytest.mark.asyncio
    async def test_get_imports_from_nonexistent_file(self):
        """Test getting imports from a file that doesn't exist."""
        result = await ast_get_imports(
            file_path="tests/fixtures/nonexistent.py",
            _workspace_dir=".",
        )

        assert result.get("isError") is True


class TestASTToolsIntegration:
    """Integration tests for AST tools."""

    @pytest.mark.asyncio
    async def test_full_ast_workflow(self):
        """Test a complete workflow: parse -> find -> extract."""
        # Step 1: Parse the file
        parse_result = await ast_parse(
            file_path="tests/fixtures/sample.py",
            _workspace_dir=".",
        )
        assert not parse_result.get("isError")

        # Step 2: Find UserService class
        find_result = await ast_find_symbols(
            file_path="tests/fixtures/sample.py",
            symbol_type="class",
            pattern="UserService",
            _workspace_dir=".",
        )
        assert not find_result.get("isError")
        assert find_result["metadata"]["count"] >= 1

        # Step 3: Extract a method from UserService
        extract_result = await ast_extract_function(
            file_path="tests/fixtures/sample.py",
            function_name="get_user",
            class_name="UserService",
            _workspace_dir=".",
        )
        assert not extract_result.get("isError")
        assert extract_result["metadata"]["found"] is True
