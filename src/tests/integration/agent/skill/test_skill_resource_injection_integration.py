"""
Integration tests for SKILL resource injection components.

These tests verify the interaction between SkillResourceLoader,
SkillResourceInjector, and SkillExecutor without requiring Docker.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.skill import (
    Skill,
    SkillStatus,
    TriggerPattern,
    TriggerType,
)
from src.infrastructure.agent.core.skill_executor import SkillExecutor
from src.infrastructure.agent.skill.skill_resource_injector import SkillResourceInjector
from src.infrastructure.agent.skill.skill_resource_loader import SkillResourceLoader


@pytest.fixture
def skill_project():
    """Create a temporary project with SKILL directories."""
    with TemporaryDirectory() as tmp_dir:
        project_path = Path(tmp_dir)

        # Create test-skill with multiple resource types
        test_skill = project_path / ".memstack" / "skills" / "test-skill"
        test_skill.mkdir(parents=True)

        (test_skill / "SKILL.md").write_text("""---
name: test-skill
description: Test skill with scripts and references
---
Run `bash scripts/analyze.sh` to analyze.
See `references/guide.md` for more info.
""")

        # Scripts
        scripts_dir = test_skill / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "analyze.sh").write_text("#!/bin/bash\necho 'Analyze'")
        (scripts_dir / "process.py").write_text("print('Process')")

        # References
        refs_dir = test_skill / "references"
        refs_dir.mkdir()
        (refs_dir / "guide.md").write_text("# Guide\n\nInstructions here.")
        (refs_dir / "api.md").write_text("# API\n\nAPI docs.")

        # Assets
        assets_dir = test_skill / "assets"
        assets_dir.mkdir()
        (assets_dir / "config.json").write_text('{"key": "value"}')

        yield project_path


@pytest.fixture
def mock_sandbox_adapter():
    """Create a mock sandbox adapter that tracks injected resources."""
    from unittest.mock import MagicMock

    # Track written files
    written_files = {}

    async def mock_call_tool(sandbox_id, tool_name, arguments):
        """Mock implementation of call_tool."""
        if tool_name == "write":
            file_path = arguments.get("file_path")
            content = arguments.get("content")
            written_files[file_path] = content
        return {
            "content": [{"type": "text", "text": "Success"}],
            "isError": False,
        }

    # Create adapter with tracked files
    adapter = MagicMock()
    adapter.call_tool = mock_call_tool
    adapter._written_files = written_files  # Store reference

    return adapter


@pytest.fixture
def mock_tool():
    """Create a mock tool for skill execution."""
    tool = AsyncMock()
    tool.execute.return_value = "Tool executed successfully"
    return tool


class TestSkillResourceInjectionIntegration:
    """Integration tests for the complete resource injection flow."""

    @pytest.mark.asyncio
    async def test_loader_finds_all_resource_types(self, skill_project):
        """Test that SkillResourceLoader finds all resource types."""
        loader = SkillResourceLoader(skill_project)

        resources = await loader.get_skill_resources("test-skill")

        # Should find 5 resources: analyze.sh, process.py, guide.md, api.md, config.json
        assert len(resources) == 5

        resource_names = {r.name for r in resources}
        assert "analyze.sh" in resource_names
        assert "process.py" in resource_names
        assert "guide.md" in resource_names
        assert "api.md" in resource_names
        assert "config.json" in resource_names

    @pytest.mark.asyncio
    async def test_loader_detects_referred_resources(self, skill_project):
        """Test content-based resource detection."""
        loader = SkillResourceLoader(skill_project)

        skill_content = "Run scripts/analyze.sh and check references/guide.md"
        detected = await loader.detect_referred_resources("test-skill", skill_content)

        # Should detect the referenced files
        assert len(detected) > 0

    @pytest.mark.asyncio
    async def test_injector_writes_all_resources(
        self,
        skill_project,
        mock_sandbox_adapter,
    ):
        """Test that injector writes all resources to sandbox."""
        injector = SkillResourceInjector(SkillResourceLoader(skill_project))

        path_mapping = await injector.inject_skill(
            mock_sandbox_adapter,
            sandbox_id="test-sandbox",
            skill_name="test-skill",
        )

        # All 5 resources should be injected
        assert len(path_mapping) == 5

        # Check written files via the adapter's tracked dict
        written_files = mock_sandbox_adapter._written_files
        assert any("analyze.sh" in f for f in written_files)
        assert any("process.py" in f for f in written_files)
        assert any("guide.md" in f for f in written_files)
        assert any("api.md" in f for f in written_files)
        assert any("config.json" in f for f in written_files)

    @pytest.mark.asyncio
    async def test_injector_sets_up_environment(
        self,
        skill_project,
        mock_sandbox_adapter,
    ):
        """Test environment variable setup."""
        injector = SkillResourceInjector(SkillResourceLoader(skill_project))

        success = await injector.setup_skill_environment(
            mock_sandbox_adapter,
            sandbox_id="test-sandbox",
            skill_name="test-skill",
        )

        assert success is True

        # Verify env.sh was written
        written_files = mock_sandbox_adapter._written_files
        assert ".memstack/skills/test-skill/env.sh" in written_files

        env_content = written_files.get(".memstack/skills/test-skill/env.sh", "")
        assert "SKILL_ROOT" in env_content
        assert "test-skill" in env_content
        assert "PATH" in env_content

    @pytest.mark.asyncio
    async def test_skill_executor_end_to_end_flow(
        self,
        skill_project,
        mock_sandbox_adapter,
        mock_tool,
    ):
        """Test complete end-to-end flow from SkillExecutor to resource injection."""
        skill = Skill(
            id="skill-1",
            tenant_id="tenant-1",
            project_id="project-1",
            name="test-skill",
            description="Test skill with scripts",
            trigger_type=TriggerType.KEYWORD,
            trigger_patterns=[TriggerPattern(pattern="test", weight=1.0)],
            tools=["bash"],
            prompt_template="Run scripts/analyze.sh",
            status=SkillStatus.ACTIVE,
            success_count=0,
            failure_count=0,
            metadata={},
            source="filesystem",
        )

        injector = SkillResourceInjector(SkillResourceLoader(skill_project))

        tools = {"bash": mock_tool}
        executor = SkillExecutor(
            tools=tools,
            resource_injector=injector,
            sandbox_adapter=mock_sandbox_adapter,
        )

        # Execute skill with resource injection
        events = []
        async for event in executor.execute(
            skill,
            "test query",
            sandbox_id="test-sandbox",
        ):
            events.append(event)

        # Verify resource injection occurred
        written_files = mock_sandbox_adapter._written_files

        # Should have written resources and env script
        assert any("analyze.sh" in f for f in written_files)
        assert any("env.sh" in f for f in written_files)

        # Verify tool was executed
        mock_tool.execute.assert_called_once()

        # Verify events were emitted
        assert len(events) > 0


class TestSkillResourceInjectionEdgeCases:
    """Integration tests for edge cases."""

    @pytest.mark.asyncio
    async def test_injector_handles_missing_skill(self, mock_sandbox_adapter):
        """Test injector with non-existent skill."""
        with TemporaryDirectory() as tmp_dir:
            injector = SkillResourceInjector(SkillResourceLoader(Path(tmp_dir)))

            path_mapping = await injector.inject_skill(
                mock_sandbox_adapter,
                sandbox_id="test-sandbox",
                skill_name="nonexistent",
            )

            # Should return empty mapping
            assert path_mapping == {}

    @pytest.mark.asyncio
    async def test_injector_handles_write_errors(
        self,
        skill_project,
    ):
        """Test injector handles sandbox write errors gracefully."""
        # Create adapter that returns errors
        error_adapter = MagicMock()
        error_adapter.call_tool = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": "Error"}],
                "isError": True,
            }
        )

        injector = SkillResourceInjector(SkillResourceLoader(skill_project))

        # Should not raise exception
        path_mapping = await injector.inject_skill(
            error_adapter,
            sandbox_id="test-sandbox",
            skill_name="test-skill",
        )

        # Should return empty mapping on error
        assert path_mapping == {}

    @pytest.mark.asyncio
    async def test_skill_executor_with_injection_error(
        self,
        skill_project,
        mock_sandbox_adapter,
        mock_tool,
    ):
        """Test SkillExecutor continues when injection fails."""
        # Create adapter that returns errors for write
        error_adapter = MagicMock()
        error_adapter.call_tool = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": "Error"}],
                "isError": True,
            }
        )

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

        injector = SkillResourceInjector(SkillResourceLoader(skill_project))

        tools = {"bash": mock_tool}
        executor = SkillExecutor(
            tools=tools,
            resource_injector=injector,
            sandbox_adapter=error_adapter,
        )

        # Execute should not raise exception
        events = []
        async for event in executor.execute(
            skill,
            "test query",
            sandbox_id="test-sandbox",
        ):
            events.append(event)

        # Tool should still execute
        mock_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_skill_injections(
        self,
        skill_project,
        mock_sandbox_adapter,
    ):
        """Test injecting multiple skills to same sandbox."""
        # Create another skill
        another_skill = skill_project / ".memstack" / "skills" / "another-skill"
        another_skill.mkdir(parents=True)
        (another_skill / "SKILL.md").write_text("---\nname: another-skill\n---")
        (another_skill / "scripts").mkdir()
        (another_skill / "scripts" / "run.sh").write_text("#!/bin/bash\necho 'Run'")

        injector = SkillResourceInjector(SkillResourceLoader(skill_project))

        # Inject first skill
        mapping1 = await injector.inject_skill(
            mock_sandbox_adapter,
            sandbox_id="test-sandbox",
            skill_name="test-skill",
        )

        # Inject second skill
        mapping2 = await injector.inject_skill(
            mock_sandbox_adapter,
            sandbox_id="test-sandbox",
            skill_name="another-skill",
        )

        # Both should succeed
        assert len(mapping1) > 0
        assert len(mapping2) > 0

        # Files should be in different directories
        written_files = mock_sandbox_adapter._written_files
        assert any("test-skill" in f for f in written_files)
        assert any("another-skill" in f for f in written_files)


class TestSkillResourcePathResolution:
    """Integration tests for path resolution."""

    @pytest.mark.asyncio
    async def test_container_path_generation(self, skill_project):
        """Test correct container path generation."""
        loader = SkillResourceLoader(skill_project)

        resources = await loader.get_skill_resources("test-skill")
        analyze_script = next(r for r in resources if r.name == "analyze.sh")

        container_path = loader.get_resource_container_path(
            "test-skill",
            analyze_script,
            skill_project / ".memstack" / "skills" / "test-skill",
        )

        # Should be in /workspace/.memstack/skills/test-skill/scripts/
        assert container_path.startswith("/workspace/.memstack/skills/test-skill/")
        assert "analyze.sh" in container_path

    @pytest.mark.asyncio
    async def test_fallback_path_without_skill_dir(self, skill_project):
        """Test path generation when skill dir cannot be determined."""
        loader = SkillResourceLoader(skill_project)

        resources = await loader.get_skill_resources("test-skill")
        analyze_script = next(r for r in resources if r.name == "analyze.sh")

        # Use None for skill_dir (fallback case)
        container_path = loader.get_resource_container_path(
            "test-skill",
            analyze_script,
            None,
        )

        # Should still generate a valid path
        assert container_path.startswith("/workspace/.memstack/skills/test-skill/")
        assert "analyze.sh" in container_path
