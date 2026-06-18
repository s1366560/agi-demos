"""Tests for code indexing tools using TDD methodology.

TDD Cycle:
1. RED - Write failing test
2. GREEN - Implement minimal code to pass
3. REFACTOR - Improve while keeping tests passing
"""

from pathlib import Path

import pytest

from src.tools.index_tools import (
    code_index_build,
    find_definition,
    find_references,
    get_call_graph,
    get_dependency_graph,
    get_indexer,
    reset_indexer,
)

WORKSPACE_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_indexer_state(monkeypatch: pytest.MonkeyPatch):
    """Reset the shared in-memory index between tests."""
    monkeypatch.chdir(WORKSPACE_DIR)
    reset_indexer(".")
    yield
    reset_indexer(".")


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
        await code_index_build(
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

    @pytest.mark.asyncio
    async def test_build_index_rejects_project_path_escape(self, tmp_path):
        """Project paths should stay inside the workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = await code_index_build(
            project_path="..",
            _workspace_dir=str(workspace),
        )

        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_build_index_respects_pattern(self, tmp_path):
        """Test building index with a narrowed glob pattern."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "included.py").write_text("class Included:\n    pass\n", encoding="utf-8")
        (workspace / "excluded.py").write_text("class Excluded:\n    pass\n", encoding="utf-8")

        result = await code_index_build(
            project_path=".",
            pattern="**/included.py",
            force_rebuild=True,
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        assert result["metadata"]["files_indexed"] == 1

        included = await find_definition(
            symbol_name="Included",
            _workspace_dir=str(workspace),
        )
        excluded = await find_definition(
            symbol_name="Excluded",
            _workspace_dir=str(workspace),
        )

        assert included["metadata"]["found"] is True
        assert excluded["metadata"]["found"] is False

    @pytest.mark.asyncio
    async def test_build_index_rejects_pattern_escape(self, tmp_path):
        """Glob patterns should not escape the workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "included.py").write_text("class Included:\n    pass\n", encoding="utf-8")

        result = await code_index_build(
            project_path=".",
            pattern="../*.py",
            _workspace_dir=str(workspace),
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

    @pytest.mark.asyncio
    async def test_find_definition_auto_builds_when_index_missing(self, tmp_path):
        """Query tools should auto-build when no index exists yet."""
        workspace = tmp_path / "workspace"
        package = workspace / "pkg"
        package.mkdir(parents=True)
        (package / "sample.py").write_text("class AutoBuilt:\n    pass\n", encoding="utf-8")

        reset_indexer(str(workspace))

        result = await find_definition(
            symbol_name="AutoBuilt",
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        assert result["metadata"]["found"] is True

    @pytest.mark.asyncio
    async def test_find_definition_reports_source_module_after_import(self, tmp_path):
        """Imported modules should not replace the source module label."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "sample.py").write_text(
            "import asyncio\n\ndef after_import():\n    return asyncio.sleep\n",
            encoding="utf-8",
        )
        reset_indexer(str(workspace))

        await code_index_build(
            project_path=".",
            force_rebuild=True,
            _workspace_dir=str(workspace),
        )
        result = await find_definition(
            symbol_name="after_import",
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        definitions = result["metadata"]["definitions"]
        assert definitions[0]["module"] == "sample"
        output = result["content"][0]["text"]
        assert "(function in sample)" in output
        assert "(function in asyncio)" not in output


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

    @pytest.mark.asyncio
    async def test_find_references_auto_builds_when_index_missing(self, tmp_path):
        """Reference lookup should auto-build when no index exists yet."""
        workspace = tmp_path / "workspace"
        package = workspace / "pkg"
        package.mkdir(parents=True)
        (package / "sample.py").write_text(
            "class AutoBuilt:\n    pass\n\nitem = AutoBuilt()\n",
            encoding="utf-8",
        )

        reset_indexer(str(workspace))

        result = await find_references(
            symbol_name="AutoBuilt",
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        assert result["metadata"]["found"] is True


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

    @pytest.mark.asyncio
    async def test_get_call_graph_tracks_internal_function_calls(self, tmp_path):
        """Call graph should list calls made inside a file-local function."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "sample.py").write_text(
            "def compute_factorial(n):\n"
            "    if n <= 1:\n"
            "        return 1\n"
            "    return n * compute_factorial(n - 1)\n\n"
            "class Calculator:\n"
            "    def multiply(self, a, b):\n"
            "        return a * b\n\n"
            "def call_internal():\n"
            "    return compute_factorial(3) + Calculator().multiply(2, 3)\n",
            encoding="utf-8",
        )
        reset_indexer(str(workspace))

        await code_index_build(
            project_path=".",
            force_rebuild=True,
            _workspace_dir=str(workspace),
        )
        result = await get_call_graph(
            symbol_name="call_internal",
            _workspace_dir=str(workspace),
        )

        assert not result.get("isError")
        graph = result["metadata"]["graph"]
        assert "compute_factorial" in graph["calls"]
        assert "Calculator.multiply" in graph["calls"]


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
