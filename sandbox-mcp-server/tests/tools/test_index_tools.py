"""Tests for code indexing tools using TDD methodology.

TDD Cycle:
1. RED - Write failing test
2. GREEN - Implement minimal code to pass
3. REFACTOR - Improve while keeping tests passing
"""

import asyncio
import pytest

from src.tools.index_tools import (
    code_index_build,
    find_definition,
    find_references,
    get_call_graph,
    get_dependency_graph,
    get_indexer,
)


class TestCodeIndexBuild:
    """Test suite for code_index_build tool."""

    @pytest.mark.asyncio
    async def test_build_index_for_test_fixtures(self):
        """Test building index for the fixtures directory."""
        result = await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        assert "content" in result

        metadata = result["metadata"]
        assert metadata["files_indexed"] >= 1
        assert metadata["total_definitions"] > 0

    @pytest.mark.asyncio
    async def test_build_index_with_exclusions(self):
        """Test building index with directory exclusions."""
        result = await code_index_build(
            project_path="tests/fixtures",
            exclude_dirs=["venv", "__pycache__"],
            _workspace_dir=".",
        )

        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_build_index_force_rebuild(self):
        """Test force rebuilding the index."""
        # Build once
        result1 = await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        # Force rebuild
        result2 = await code_index_build(
            project_path="tests/fixtures",
            force_rebuild=True,
            _workspace_dir=".",
        )

        assert not result2.get("isError")

    @pytest.mark.asyncio
    async def test_build_index_nonexistent_path(self):
        """Test building index for nonexistent path."""
        result = await code_index_build(
            project_path="tests/fixtures/nonexistent",
            _workspace_dir=".",
        )

        assert result.get("isError") is True


class TestFindDefinition:
    """Test suite for find_definition tool."""

    @pytest.mark.asyncio
    async def test_find_class_definition(self):
        """Test finding a class definition."""
        # First build the index
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        # Then find definition
        result = await find_definition(
            symbol_name="UserService",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["found"] is True
        assert metadata["symbol"] == "UserService"

        definitions = metadata["definitions"]
        assert len(definitions) > 0
        assert definitions[0]["type"] == "class"

    @pytest.mark.asyncio
    async def test_find_function_definition(self):
        """Test finding a function definition."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await find_definition(
            symbol_name="calculate_score",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["found"] is True

        definitions = metadata["definitions"]
        assert any(d["type"] == "function" for d in definitions)

    @pytest.mark.asyncio
    async def test_find_definition_by_type(self):
        """Test finding definition filtered by type."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await find_definition(
            symbol_name="UserService",
            symbol_type="class",
            _workspace_dir=".",
        )

        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_find_nonexistent_symbol(self):
        """Test finding a symbol that doesn't exist."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await find_definition(
            symbol_name="NonexistentClass",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert metadata["found"] is False


class TestFindReferences:
    """Test suite for find_references tool."""

    @pytest.mark.asyncio
    async def test_find_symbol_references(self):
        """Test finding references to a symbol."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await find_references(
            symbol_name="UserService",
            group_by_file=True,
            _workspace_dir=".",
        )

        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_find_references_without_grouping(self):
        """Test finding references without file grouping."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await find_references(
            symbol_name="UserService",
            group_by_file=False,
            _workspace_dir=".",
        )

        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_find_references_max_results(self):
        """Test finding references with max results limit."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await find_references(
            symbol_name="User",
            max_results=10,
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        if metadata["found"]:
            assert metadata["total_references"] <= 10


class TestCallGraph:
    """Test suite for call_graph tool."""

    @pytest.mark.asyncio
    async def test_get_call_graph_for_function(self):
        """Test getting call graph for a specific function."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await get_call_graph(
            symbol_name="main",
            _workspace_dir=".",
        )

        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_get_full_call_graph(self):
        """Test getting full project call graph."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await get_call_graph(
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert "total_functions" in metadata

    @pytest.mark.asyncio
    async def test_get_call_graph_with_depth(self):
        """Test getting call graph with depth > 1."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await get_call_graph(
            symbol_name="main",
            max_depth=2,
            _workspace_dir=".",
        )

        assert not result.get("isError")


class TestDependencyGraph:
    """Test suite for dependency_graph tool."""

    @pytest.mark.asyncio
    async def test_get_dependency_graph(self):
        """Test getting dependency graph for a project."""
        await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        result = await get_dependency_graph(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )

        assert not result.get("isError")
        metadata = result["metadata"]
        assert "internal" in metadata or "external" in metadata


class TestCodeIndexer:
    """Test suite for CodeIndexer class."""

    @pytest.mark.asyncio
    async def test_get_indexer_singleton(self):
        """Test that get_indexer returns the same instance."""
        indexer1 = get_indexer(".")
        indexer2 = get_indexer(".")

        assert indexer1 is indexer2

    @pytest.mark.asyncio
    async def test_indexer_build_empty_project(self):
        """Test indexing an empty project."""
        indexer = get_indexer(".")
        result = await indexer.build("tests/fixtures/empty_dir")

        # Should handle gracefully
        assert isinstance(result, dict)


class TestIndexToolsIntegration:
    """Integration tests for index tools."""

    @pytest.mark.asyncio
    async def test_full_index_workflow(self):
        """Test complete workflow: build -> find definition -> find references -> call graph."""
        # Step 1: Build index
        build_result = await code_index_build(
            project_path="tests/fixtures",
            _workspace_dir=".",
        )
        assert not build_result.get("isError")

        # Step 2: Find definition
        def_result = await find_definition(
            symbol_name="UserService",
            _workspace_dir=".",
        )
        assert not def_result.get("isError")
        assert def_result["metadata"]["found"] is True

        # Step 3: Find references
        ref_result = await find_references(
            symbol_name="UserService",
            _workspace_dir=".",
        )
        assert not ref_result.get("isError")

        # Step 4: Get call graph
        call_result = await get_call_graph(
            _workspace_dir=".",
        )
        assert not call_result.get("isError")
