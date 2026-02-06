"""
Integration tests for SKILL resource injection with real Sandbox.

These tests require:
1. Docker daemon running
2. sandbox-mcp-server image available
3. Network connectivity

Tests are marked with 'integration' and skipped by default in unit test runs.
"""

import asyncio
import os
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.domain.model.agent.skill import (
    Skill,
    SkillScope,
    SkillStatus,
    TriggerPattern,
    TriggerType,
)
from src.infrastructure.agent.core.skill_executor import SkillExecutor
from src.infrastructure.agent.skill.skill_resource_injector import SkillResourceInjector
from src.infrastructure.agent.skill.skill_resource_loader import SkillResourceLoader
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter


@pytest.fixture
def temp_skill_project():
    """Create a temporary project with a SKILL directory."""
    with TemporaryDirectory() as tmp_dir:
        project_path = Path(tmp_dir)

        # Create .memstack/skills/test-skill directory
        skill_dir = project_path / ".memstack" / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)

        # Create SKILL.md
        (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: A test skill for integration testing
trigger_type: keyword
trigger_patterns:
  - pattern: test
    weight: 1.0
---

# Test Skill

This skill contains scripts for testing.

Usage: Run `bash scripts/test.sh` to execute the test script.
""")

        # Create scripts directory
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()

        # Create a test script
        (scripts_dir / "test.sh").write_text("""#!/bin/bash
# Test script for integration testing
echo "Hello from test-skill!"
echo "SKILL_ROOT is: $SKILL_ROOT"
exit 0
""")

        # Create references directory
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "guide.md").write_text("# Guide\n\nThis is a reference guide.")

        yield project_path


@pytest.fixture
def mock_tool():
    """Create a mock tool that simulates bash execution."""
    from unittest.mock import AsyncMock
    tool = AsyncMock()
    tool.execute.return_value = "Script executed successfully"
    return tool


@pytest.fixture
def sandbox_adapter():
    """Create MCPSandboxAdapter instance."""
    # Use a lightweight configuration for testing
    adapter = MCPSandboxAdapter(
        mcp_image="sandbox-mcp-server:latest",
        default_memory_limit="512m",
        default_cpu_limit="1",
    )
    return adapter


@pytest.fixture
def resource_injector(temp_skill_project):
    """Create SkillResourceInjector with temp project."""
    return SkillResourceInjector(
        SkillResourceLoader(temp_skill_project)
    )


class TestSkillSandboxIntegration:
    """Integration tests for SKILL resource injection with Sandbox."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_full_skill_execution_with_sandbox(
        self,
        temp_skill_project,
        mock_tool,
        sandbox_adapter,
        resource_injector,
    ):
        """Test complete skill execution flow with resource injection."""
        # Skip if Docker is not available or image not found
        pytest.skip("Requires Docker and sandbox-mcp-server image")

        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            project_id="project-1",
            name="test-skill",
            description="Test skill with scripts",
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[TriggerPattern(pattern="test", weight=1.0)],
            tools=["bash"],
            prompt_template="Run scripts/test.sh",
            status=SkillStatus.ACTIVE,
            success_count=0,
            failure_count=0,
            metadata={},
            source="filesystem",
        )

        tools = {"bash": mock_tool}

        # Create executor with resource injection
        executor = SkillExecutor(
            tools=tools,
            resource_injector=resource_injector,
            sandbox_adapter=sandbox_adapter,
        )

        # Create sandbox
        sandbox = await sandbox_adapter.create_sandbox(
            project_path=str(temp_skill_project),
            project_id="project-1",
            tenant_id="tenant-1",
        )

        try:
            # Connect MCP client
            connected = await sandbox_adapter.connect_mcp(sandbox.id)
            assert connected, "Failed to connect MCP client"

            # Execute skill with resource injection
            events = []
            async for event in executor.execute(
                skill,
                "test query",
                sandbox_id=sandbox.id,
            ):
                events.append(event)

            # Verify events were emitted
            assert len(events) > 0, "No events emitted"

            # Verify tool was executed
            mock_tool.execute.assert_called_once()

            # Verify resources were injected into sandbox
            # Check if script file exists in sandbox
            read_result = await sandbox_adapter.call_tool(
                sandbox.id,
                "read",
                {"file_path": ".skills/test-skill/scripts/test.sh"},
            )

            assert not read_result.get("is_error"), "Script not found in sandbox"
            script_content = read_result["content"][0]["text"]
            assert "Hello from test-skill!" in script_content

        finally:
            # Cleanup: terminate sandbox
            await sandbox_adapter.terminate_sandbox(sandbox.id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_resource_injection_multiple_resources(
        self,
        temp_skill_project,
        sandbox_adapter,
        resource_injector,
    ):
        """Test injection of multiple resource types."""
        pytest.skip("Requires Docker and sandbox-mcp-server image")

        # Create sandbox
        sandbox = await sandbox_adapter.create_sandbox(
            project_path=str(temp_skill_project),
        )

        try:
            # Connect MCP client
            await sandbox_adapter.connect_mcp(sandbox.id)

            # Inject resources
            path_mapping = await resource_injector.inject_skill(
                sandbox_adapter,
                sandbox_id=sandbox.id,
                skill_name="test-skill",
            )

            # Verify all resources were injected
            assert len(path_mapping) >= 2, "Not all resources injected"

            # Verify script file
            script_result = await sandbox_adapter.call_tool(
                sandbox.id,
                "read",
                {"file_path": ".skills/test-skill/scripts/test.sh"},
            )
            assert not script_result.get("is_error")

            # Verify reference file
            ref_result = await sandbox_adapter.call_tool(
                sandbox.id,
                "read",
                {"file_path": ".skills/test-skill/references/guide.md"},
            )
            assert not ref_result.get("is_error")
            assert "# Guide" in ref_result["content"][0]["text"]

        finally:
            await sandbox_adapter.terminate_sandbox(sandbox.id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_skill_environment_setup(
        self,
        sandbox_adapter,
        resource_injector,
    ):
        """Test SKILL environment variable setup."""
        pytest.skip("Requires Docker and sandbox-mcp-server image")

        sandbox = await sandbox_adapter.create_sandbox(
            project_path="/tmp",
        )

        try:
            await sandbox_adapter.connect_mcp(sandbox.id)

            # Setup environment
            success = await resource_injector.setup_skill_environment(
                sandbox_adapter,
                sandbox_id=sandbox.id,
                skill_name="test-skill",
            )

            assert success, "Environment setup failed"

            # Verify env.sh was created
            result = await sandbox_adapter.call_tool(
                sandbox.id,
                "read",
                {"file_path": ".skills/test-skill/env.sh"},
            )

            assert not result.get("is_error")
            content = result["content"][0]["text"]
            assert "SKILL_ROOT" in content
            assert "test-skill" in content

        finally:
            await sandbox_adapter.terminate_sandbox(sandbox.id)


class TestSkillSandboxErrorHandling:
    """Integration tests for error handling."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_injection_with_nonexistent_skill(
        self,
        temp_skill_project,
        sandbox_adapter,
        resource_injector,
    ):
        """Test resource injection with non-existent skill."""
        pytest.skip("Requires Docker and sandbox-mcp-server image")

        sandbox = await sandbox_adapter.create_sandbox(
            project_path=str(temp_skill_project),
        )

        try:
            await sandbox_adapter.connect_mcp(sandbox.id)

            # Try to inject non-existent skill
            path_mapping = await resource_injector.inject_skill(
                sandbox_adapter,
                sandbox_id=sandbox.id,
                skill_name="nonexistent-skill",
            )

            # Should return empty mapping
            assert path_mapping == {}

        finally:
            await sandbox_adapter.terminate_sandbox(sandbox.id)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_skill_executor_continues_on_injection_failure(
        self,
        temp_skill_project,
        mock_tool,
        sandbox_adapter,
    ):
        """Test that SkillExecutor continues even if injection fails."""
        pytest.skip("Requires Docker and sandbox-mcp-server image")

        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            name="test-skill",
            description="Test skill",
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[],
            tools=["bash"],
            prompt_template="Run command",
            status=SkillStatus.ACTIVE,
        )

        # Create injector with wrong project path (no skills)
        bad_injector = SkillResourceInjector(
            SkillResourceLoader(Path("/nonexistent"))
        )

        tools = {"bash": mock_tool}
        executor = SkillExecutor(
            tools=tools,
            resource_injector=bad_injector,
            sandbox_adapter=sandbox_adapter,
        )

        sandbox = await sandbox_adapter.create_sandbox(
            project_path=str(temp_skill_project),
        )

        try:
            # Execute should not fail despite injection failure
            events = []
            async for event in executor.execute(
                skill,
                "test query",
                sandbox_id=sandbox.id,
            ):
                events.append(event)

            # Tool should still execute
            mock_tool.execute.assert_called_once()

        finally:
            await sandbox_adapter.terminate_sandbox(sandbox.id)
