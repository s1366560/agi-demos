"""Tests for edit tools using TDD methodology.

TDD Cycle:
1. RED - Write failing test
2. GREEN - Implement minimal code to pass
3. REFACTOR - Improve while keeping tests passing
"""

import asyncio
import pytest

from src.tools.edit_tools import (
    batch_edit,
    edit_by_ast,
    preview_edit,
)


class TestEditByAST:
    """Test suite for edit_by_ast tool."""

    @pytest.mark.asyncio
    async def test_edit_class_name(self):
        """Test renaming a class using AST."""
        # First, create a test file
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_sample.py"
            test_file.write_text('''
class OldName:
    """Old class."""

    def method(self):
        return "old"
''')

            result = await edit_by_ast(
                file_path=str(test_file),
                target_type="class",
                target_name="OldName",
                operation="rename",
                new_value="NewName",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")

            # Verify the change
            content = test_file.read_text()
            assert "class NewName:" in content
            assert "class OldName:" not in content

    @pytest.mark.asyncio
    async def test_edit_function_name(self):
        """Test renaming a function."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_sample.py"
            test_file.write_text('''
def old_function():
    """Old function."""
    return "result"
''')

            result = await edit_by_ast(
                file_path=str(test_file),
                target_type="function",
                target_name="old_function",
                operation="rename",
                new_value="new_function",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")

            content = test_file.read_text()
            assert "def new_function():" in content
            assert "def old_function():" not in content

    @pytest.mark.asyncio
    async def test_edit_nonexistent_file(self):
        """Test editing a file that doesn't exist."""
        result = await edit_by_ast(
            file_path="nonexistent.py",
            target_type="class",
            target_name="SomeClass",
            operation="rename",
            new_value="NewName",
            _workspace_dir=".",
        )

        assert result.get("isError") is True

    @pytest.mark.asyncio
    async def test_edit_invalid_operation(self):
        """Test with invalid operation."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_sample.py"
            test_file.write_text('class MyClass:\n    pass\n')

            result = await edit_by_ast(
                file_path=str(test_file),
                target_type="class",
                target_name="MyClass",
                operation="invalid_op",
                new_value="Something",
                _workspace_dir=tmpdir,
            )

            assert result.get("isError") is True


class TestBatchEdit:
    """Test suite for batch_edit tool."""

    @pytest.mark.asyncio
    async def test_batch_edit_multiple_files(self):
        """Test editing multiple files at once."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            file1 = Path(tmpdir) / "file1.py"
            file2 = Path(tmpdir) / "file2.py"
            file1.write_text("OLD_VALUE = 1\n")
            file2.write_text("OLD_VALUE = 2\n")

            edits = [
                {"file_path": "file1.py", "old_string": "OLD_VALUE", "new_string": "NEW_VALUE"},
                {"file_path": "file2.py", "old_string": "OLD_VALUE", "new_string": "NEW_VALUE"},
            ]

            result = await batch_edit(
                edits=edits,
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")

            # Verify changes
            assert "NEW_VALUE = 1" in file1.read_text()
            assert "NEW_VALUE = 2" in file2.read_text()

    @pytest.mark.asyncio
    async def test_batch_edit_with_dry_run(self):
        """Test batch edit with dry_run mode."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("OLD = 1\n")

            edits = [
                {"file_path": "test.py", "old_string": "OLD", "new_string": "NEW"},
            ]

            result = await batch_edit(
                edits=edits,
                dry_run=True,
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")

            # File should not be modified in dry run mode
            content = test_file.read_text()
            assert "OLD = 1" in content
            assert "NEW = 1" not in content

    @pytest.mark.asyncio
    async def test_batch_edit_stop_on_error(self):
        """Test batch edit with stop_on_error enabled."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "file1.py"
            file2 = Path(tmpdir) / "file2.py"
            file1.write_text("VALUE1\n")
            file2.write_text("VALUE2\n")

            edits = [
                {"file_path": "file1.py", "old_string": "VALUE1", "new_string": "NEW1"},
                {"file_path": "file2.py", "old_string": "NONEXISTENT", "new_string": "NEW2"},
            ]

            result = await batch_edit(
                edits=edits,
                stop_on_error=True,
                _workspace_dir=tmpdir,
            )

            # First edit should succeed, second should fail
            metadata = result.get("metadata", {})
            assert metadata.get("successful") >= 1
            assert metadata.get("failed") >= 1


class TestPreviewEdit:
    """Test suite for preview_edit tool."""

    @pytest.mark.asyncio
    async def test_preview_single_edit(self):
        """Test previewing a single edit."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text('''
def function_one():
    return 1

def function_two():
    return 2
''')

            result = await preview_edit(
                file_path=str(test_file),
                old_string="function_one",
                new_string="function_renamed",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            assert "preview" in result.get("metadata", {})

    @pytest.mark.asyncio
    async def test_preview_with_context_lines(self):
        """Test preview with context lines."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("line1\nline2\nline3\n")

            result = await preview_edit(
                file_path=str(test_file),
                old_string="line2",
                new_string="line2_modified",
                context_lines=2,
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            # Should show context around the change

    @pytest.mark.asyncio
    async def test_preview_no_changes(self):
        """Test preview when no changes would be made."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.py"
            original_content = "content\n"
            test_file.write_text(original_content)

            result = await preview_edit(
                file_path=str(test_file),
                old_string="nonexistent",
                new_string="replacement",
                _workspace_dir=tmpdir,
            )

            assert not result.get("isError")
            metadata = result.get("metadata", {})
            assert metadata.get("changes_found") == 0


class TestEditToolsIntegration:
    """Integration tests for edit tools."""

    @pytest.mark.asyncio
    async def test_full_edit_workflow(self):
        """Test complete workflow: preview -> edit -> verify."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "workflow_test.py"
            test_file.write_text('''
class OriginalClass:
    """Original class."""

    def original_method(self):
        return "original"
''')

            # Step 1: Preview the edit
            preview = await preview_edit(
                file_path=str(test_file),
                old_string="OriginalClass",
                new_string="UpdatedClass",
                _workspace_dir=tmpdir,
            )
            assert not preview.get("isError")

            # Step 2: Apply the edit via batch_edit
            edits = [{
                "file_path": "workflow_test.py",
                "old_string": "OriginalClass",
                "new_string": "UpdatedClass",
            }]

            result = await batch_edit(
                edits=edits,
                _workspace_dir=tmpdir,
            )
            assert not result.get("isError")

            # Step 3: Verify
            content = test_file.read_text()
            assert "class UpdatedClass:" in content
            assert "class OriginalClass:" not in content
