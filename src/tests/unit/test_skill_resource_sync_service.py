"""Unit tests for SkillResourceSyncService.

Tests the unified sync-on-load mechanism for synchronizing skill resources
to sandbox containers from SkillLoaderTool and ReActAgent INJECT mode.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.skill_resource_sync_service import (
    CONTAINER_SKILL_BASE,
    SkillResourceSyncService,
)
from src.domain.ports.services.skill_resource_port import (
    ResourceEnvironment,
    ResourceSyncResult,
    SkillResource,
    SkillResourceContext,
)


@pytest.fixture
def mock_resource_port():
    """Create a mock SkillResourcePort for sandbox environment."""
    port = MagicMock()
    port.environment = ResourceEnvironment.SANDBOX
    port.sync_resources = AsyncMock()
    port.setup_environment = AsyncMock(return_value=True)
    port.list_resources = AsyncMock(return_value=[])
    port.parse_virtual_path = MagicMock(
        side_effect=lambda vp: vp.replace("skill://", "").split("/", 1)
    )
    return port


@pytest.fixture
def mock_local_port():
    """Create a mock SkillResourcePort for local environment."""
    port = MagicMock()
    port.environment = ResourceEnvironment.SYSTEM
    return port


@pytest.fixture
def sync_service(mock_resource_port):
    """Create a SkillResourceSyncService with a sandbox resource port."""
    return SkillResourceSyncService(
        skill_resource_port=mock_resource_port,
        tenant_id="test-tenant",
        project_id="test-project",
        project_path=Path("/workspace"),
    )


@pytest.fixture
def sample_resources():
    """Create sample SkillResource objects."""
    return [
        SkillResource(
            virtual_path="skill://analyze-data/scripts/analyze.py",
            name="analyze.py",
            content="print('hello')",
            local_path=Path("/workspace/.memstack/skills/analyze-data/scripts/analyze.py"),
            container_path="/workspace/.memstack/skills/analyze-data/scripts/analyze.py",
            size_bytes=100,
        ),
        SkillResource(
            virtual_path="skill://analyze-data/references/guide.md",
            name="guide.md",
            content="# Guide",
            local_path=Path("/workspace/.memstack/skills/analyze-data/references/guide.md"),
            container_path="/workspace/.memstack/skills/analyze-data/references/guide.md",
            size_bytes=50,
        ),
    ]


@pytest.mark.unit
class TestSkillResourceSyncService:
    """Tests for SkillResourceSyncService."""

    async def test_sync_for_skill_success(self, sync_service, mock_resource_port, sample_resources):
        """Test successful resource sync to sandbox."""
        mock_resource_port.sync_resources.return_value = ResourceSyncResult(
            success=True,
            synced_resources=sample_resources,
        )

        status = await sync_service.sync_for_skill(
            skill_name="analyze-data",
            sandbox_id="sandbox-123",
        )

        assert status.synced is True
        assert len(status.resource_paths) == 2
        assert not status.errors
        mock_resource_port.sync_resources.assert_called_once()
        mock_resource_port.setup_environment.assert_called_once()

    async def test_sync_for_skill_no_sandbox_id(self, sync_service, mock_resource_port):
        """Test sync is skipped when no sandbox_id provided."""
        status = await sync_service.sync_for_skill(
            skill_name="analyze-data",
            sandbox_id=None,
        )

        assert status.synced is False
        assert not status.resource_paths
        mock_resource_port.sync_resources.assert_not_called()

    async def test_sync_for_skill_local_environment(self, mock_local_port):
        """Test sync is skipped for local (SYSTEM) environment."""
        service = SkillResourceSyncService(
            skill_resource_port=mock_local_port,
            tenant_id="test-tenant",
        )

        status = await service.sync_for_skill(
            skill_name="analyze-data",
            sandbox_id="sandbox-123",
        )

        assert status.synced is False

    async def test_sync_for_skill_failure(self, sync_service, mock_resource_port):
        """Test sync failure is captured in status."""
        mock_resource_port.sync_resources.return_value = ResourceSyncResult(
            success=False,
            errors=["MCP write failed for skill://analyze-data/scripts/analyze.py"],
            failed_resources=["skill://analyze-data/scripts/analyze.py"],
        )

        status = await sync_service.sync_for_skill(
            skill_name="analyze-data",
            sandbox_id="sandbox-123",
        )

        assert status.synced is False
        assert len(status.errors) == 1

    async def test_sync_for_skill_exception(self, sync_service, mock_resource_port):
        """Test sync exception is handled gracefully."""
        mock_resource_port.sync_resources.side_effect = RuntimeError("Connection refused")

        status = await sync_service.sync_for_skill(
            skill_name="analyze-data",
            sandbox_id="sandbox-123",
        )

        assert status.synced is False
        assert "Connection refused" in status.errors[0]

    async def test_sync_idempotent(self, sync_service, mock_resource_port, sample_resources):
        """Test that sync is idempotent (second call uses adapter cache)."""
        mock_resource_port.sync_resources.return_value = ResourceSyncResult(
            success=True,
            synced_resources=sample_resources,
        )

        # First sync
        await sync_service.sync_for_skill(
            skill_name="analyze-data",
            sandbox_id="sandbox-123",
        )

        # Second sync - still calls port (idempotency is in the adapter's version cache)
        await sync_service.sync_for_skill(
            skill_name="analyze-data",
            sandbox_id="sandbox-123",
        )

        # Port is called twice but adapter internally skips redundant syncs
        assert mock_resource_port.sync_resources.call_count == 2

    async def test_is_synced_tracking(self, sync_service, mock_resource_port, sample_resources):
        """Test is_synced tracks which skills have been synced."""
        mock_resource_port.sync_resources.return_value = ResourceSyncResult(
            success=True,
            synced_resources=sample_resources,
        )

        assert sync_service.is_synced("analyze-data", "sandbox-123") is False

        await sync_service.sync_for_skill(
            skill_name="analyze-data",
            sandbox_id="sandbox-123",
        )

        assert sync_service.is_synced("analyze-data", "sandbox-123") is True
        assert sync_service.is_synced("other-skill", "sandbox-123") is False

    async def test_sync_passes_context_correctly(
        self, sync_service, mock_resource_port, sample_resources
    ):
        """Test that sync creates proper SkillResourceContext."""
        mock_resource_port.sync_resources.return_value = ResourceSyncResult(
            success=True,
            synced_resources=sample_resources,
        )

        await sync_service.sync_for_skill(
            skill_name="analyze-data",
            sandbox_id="sandbox-123",
            skill_content="# SKILL.md content",
        )

        call_args = mock_resource_port.sync_resources.call_args
        context = call_args[0][0]
        assert isinstance(context, SkillResourceContext)
        assert context.skill_name == "analyze-data"
        assert context.sandbox_id == "sandbox-123"
        assert context.tenant_id == "test-tenant"
        assert context.project_id == "test-project"
        assert context.skill_content == "# SKILL.md content"


@pytest.mark.unit
class TestBuildResourcePathsHint:
    """Tests for path hint generation."""

    def test_hint_with_resources(self):
        """Test path hint includes all resource paths."""
        service = SkillResourceSyncService(
            skill_resource_port=MagicMock(),
        )

        hint = service.build_resource_paths_hint(
            skill_name="analyze-data",
            resource_paths=[
                "/workspace/.memstack/skills/analyze-data/scripts/analyze.py",
                "/workspace/.memstack/skills/analyze-data/references/guide.md",
            ],
        )

        assert "SKILL_ROOT" in hint
        assert f"{CONTAINER_SKILL_BASE}/analyze-data" in hint
        assert "/workspace/.memstack/skills/analyze-data/scripts/analyze.py" in hint
        assert "/workspace/.memstack/skills/analyze-data/references/guide.md" in hint
        assert "$SKILL_ROOT" in hint

    def test_hint_empty_resources(self):
        """Test path hint is empty when no resources."""
        service = SkillResourceSyncService(
            skill_resource_port=MagicMock(),
        )

        hint = service.build_resource_paths_hint(
            skill_name="analyze-data",
            resource_paths=[],
        )

        assert hint == ""

    def test_hint_sorted_paths(self):
        """Test resource paths are sorted in hint."""
        service = SkillResourceSyncService(
            skill_resource_port=MagicMock(),
        )

        hint = service.build_resource_paths_hint(
            skill_name="test",
            resource_paths=[
                "/workspace/.memstack/skills/test/scripts/z.py",
                "/workspace/.memstack/skills/test/scripts/a.py",
            ],
        )

        a_idx = hint.index("a.py")
        z_idx = hint.index("z.py")
        assert a_idx < z_idx
