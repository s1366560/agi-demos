"""Integration tests for MCP Sandbox.

Tests the full sandbox workflow:
1. Create sandbox container
2. Connect MCP client
3. Execute file operations
4. Terminate sandbox
"""

import asyncio
import os
import tempfile

import pytest

from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
)


@pytest.fixture
def workspace_dir():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some test files
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        with open(os.path.join(tmpdir, "README.md"), "w") as f:
            f.write("# Test Project\n\nThis is a test project.\n")
        with open(os.path.join(tmpdir, "src", "main.py"), "w") as f:
            f.write('print("Hello, World!")\n')
        yield tmpdir


@pytest.fixture
async def sandbox_adapter():
    """Create sandbox adapter."""
    adapter = MCPSandboxAdapter()
    yield adapter
    # Cleanup all sandboxes after test
    await adapter.cleanup_expired(max_age_seconds=0)


@pytest.mark.integration
@pytest.mark.slow
class TestMCPSandbox:
    """Integration tests for MCP sandbox operations."""

    async def test_create_and_terminate_sandbox(self, sandbox_adapter, workspace_dir):
        """Test creating and terminating a sandbox."""
        # Create sandbox
        instance = await sandbox_adapter.create_sandbox(
            project_path=workspace_dir,
            config=SandboxConfig(timeout_seconds=300),
        )

        assert instance is not None
        assert instance.id.startswith("mcp-sandbox-")
        assert instance.status == SandboxStatus.RUNNING
        assert instance.websocket_url is not None
        assert instance.websocket_url.startswith("ws://")

        # Terminate sandbox
        success = await sandbox_adapter.terminate_sandbox(instance.id)
        assert success is True

    async def test_connect_mcp_and_list_tools(self, sandbox_adapter, workspace_dir):
        """Test connecting MCP client and listing tools."""
        # Create sandbox
        instance = await sandbox_adapter.create_sandbox(
            project_path=workspace_dir,
            config=SandboxConfig(timeout_seconds=300),
        )

        try:
            # Connect MCP client
            connected = await sandbox_adapter.connect_mcp(instance.id, timeout=30.0)
            assert connected is True

            # List tools
            tools = await sandbox_adapter.list_tools(instance.id)
            assert len(tools) > 0

            tool_names = [t["name"] for t in tools]
            assert "read" in tool_names
            assert "write" in tool_names
            assert "edit" in tool_names
            assert "glob" in tool_names
            assert "grep" in tool_names
            assert "bash" in tool_names

        finally:
            await sandbox_adapter.terminate_sandbox(instance.id)

    async def test_read_file(self, sandbox_adapter, workspace_dir):
        """Test reading a file via MCP."""
        instance = await sandbox_adapter.create_sandbox(
            project_path=workspace_dir,
            config=SandboxConfig(timeout_seconds=300),
        )

        try:
            await sandbox_adapter.connect_mcp(instance.id)

            # Read README.md
            result = await sandbox_adapter.call_tool(
                instance.id,
                "read",
                {"file_path": "/workspace/README.md"},
            )

            assert result is not None
            assert result.get("is_error") is False
            content = result.get("content", [])
            assert len(content) > 0
            assert "Test Project" in content[0].get("text", "")

        finally:
            await sandbox_adapter.terminate_sandbox(instance.id)

    async def test_write_and_read_file(self, sandbox_adapter, workspace_dir):
        """Test writing and reading a file via MCP."""
        instance = await sandbox_adapter.create_sandbox(
            project_path=workspace_dir,
            config=SandboxConfig(timeout_seconds=300),
        )

        try:
            await sandbox_adapter.connect_mcp(instance.id)

            # Write a new file
            write_result = await sandbox_adapter.call_tool(
                instance.id,
                "write",
                {
                    "file_path": "/workspace/test_output.txt",
                    "content": "Hello from MCP sandbox!\n",
                },
            )

            assert write_result.get("is_error") is False

            # Read the file back
            read_result = await sandbox_adapter.call_tool(
                instance.id,
                "read",
                {"file_path": "/workspace/test_output.txt"},
            )

            assert read_result.get("is_error") is False
            content = read_result.get("content", [])
            assert "Hello from MCP sandbox" in content[0].get("text", "")

        finally:
            await sandbox_adapter.terminate_sandbox(instance.id)

    async def test_glob_files(self, sandbox_adapter, workspace_dir):
        """Test glob file search via MCP."""
        instance = await sandbox_adapter.create_sandbox(
            project_path=workspace_dir,
            config=SandboxConfig(timeout_seconds=300),
        )

        try:
            await sandbox_adapter.connect_mcp(instance.id)

            # Find all Python files
            result = await sandbox_adapter.call_tool(
                instance.id,
                "glob",
                {"pattern": "**/*.py"},
            )

            assert result.get("is_error") is False
            content = result.get("content", [])
            assert len(content) > 0
            assert "main.py" in content[0].get("text", "")

        finally:
            await sandbox_adapter.terminate_sandbox(instance.id)

    async def test_bash_command(self, sandbox_adapter, workspace_dir):
        """Test bash command execution via MCP."""
        instance = await sandbox_adapter.create_sandbox(
            project_path=workspace_dir,
            config=SandboxConfig(timeout_seconds=300),
        )

        try:
            await sandbox_adapter.connect_mcp(instance.id)

            # Run a simple command
            result = await sandbox_adapter.call_tool(
                instance.id,
                "bash",
                {"command": "echo 'Hello from bash!'"},
            )

            assert result.get("is_error") is False
            content = result.get("content", [])
            assert "Hello from bash" in content[0].get("text", "")

            # Run Python
            result = await sandbox_adapter.call_tool(
                instance.id,
                "bash",
                {"command": "python3 -c 'print(2+2)'"},
            )

            assert result.get("is_error") is False
            content = result.get("content", [])
            assert "4" in content[0].get("text", "")

        finally:
            await sandbox_adapter.terminate_sandbox(instance.id)

    async def test_grep_search(self, sandbox_adapter, workspace_dir):
        """Test grep search via MCP."""
        instance = await sandbox_adapter.create_sandbox(
            project_path=workspace_dir,
            config=SandboxConfig(timeout_seconds=300),
        )

        try:
            await sandbox_adapter.connect_mcp(instance.id)

            # Search for "Hello" in files
            result = await sandbox_adapter.call_tool(
                instance.id,
                "grep",
                {"pattern": "Hello", "path": "/workspace"},
            )

            assert result.get("is_error") is False
            content = result.get("content", [])
            assert len(content) > 0
            # Should find "Hello" in main.py
            assert "main.py" in content[0].get("text", "")

        finally:
            await sandbox_adapter.terminate_sandbox(instance.id)

    async def test_edit_file(self, sandbox_adapter, workspace_dir):
        """Test editing a file via MCP."""
        instance = await sandbox_adapter.create_sandbox(
            project_path=workspace_dir,
            config=SandboxConfig(timeout_seconds=300),
        )

        try:
            await sandbox_adapter.connect_mcp(instance.id)

            # Edit README.md
            edit_result = await sandbox_adapter.call_tool(
                instance.id,
                "edit",
                {
                    "file_path": "/workspace/README.md",
                    "old_string": "This is a test project.",
                    "new_string": "This is an EDITED test project.",
                },
            )

            assert edit_result.get("is_error") is False

            # Verify the edit
            read_result = await sandbox_adapter.call_tool(
                instance.id,
                "read",
                {"file_path": "/workspace/README.md"},
            )

            content = read_result.get("content", [])
            assert "EDITED" in content[0].get("text", "")

        finally:
            await sandbox_adapter.terminate_sandbox(instance.id)


# Quick manual test
async def main():
    """Quick manual test of sandbox functionality."""
    import tempfile

    print("Creating workspace...")
    with tempfile.TemporaryDirectory() as workspace:
        # Create test file
        with open(os.path.join(workspace, "test.txt"), "w") as f:
            f.write("Hello, World!\n")

        print("Creating sandbox adapter...")
        adapter = MCPSandboxAdapter()

        print("Creating sandbox...")
        instance = await adapter.create_sandbox(workspace)
        print(f"Created sandbox: {instance.id}")
        print(f"WebSocket URL: {instance.websocket_url}")

        print("Connecting MCP...")
        await asyncio.sleep(2)  # Wait for server to start
        connected = await adapter.connect_mcp(instance.id)
        print(f"Connected: {connected}")

        if connected:
            print("Listing tools...")
            tools = await adapter.list_tools(instance.id)
            print(f"Tools: {[t['name'] for t in tools]}")

            print("Reading file...")
            result = await adapter.call_tool(
                instance.id, "read", {"file_path": "/workspace/test.txt"}
            )
            print(f"Read result: {result}")

            print("Running bash...")
            result = await adapter.call_tool(instance.id, "bash", {"command": "ls -la /workspace"})
            print(f"Bash result: {result}")

        print("Terminating sandbox...")
        await adapter.terminate_sandbox(instance.id)
        print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
