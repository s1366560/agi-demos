"""Unit tests for WorkspaceManager.build_persona() and trim_bootstrap_content.

Tests the workspace file loading, truncation, and persona building system.
"""

import pytest

from src.infrastructure.agent.prompts.persona import (
    AgentPersona,
    PersonaSource,
)
from src.infrastructure.agent.workspace.manager import (
    BOOTSTRAP_HEAD_RATIO,
    BOOTSTRAP_TAIL_RATIO,
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    WorkspaceManager,
    trim_bootstrap_content,
)


@pytest.mark.unit
class TestTrimBootstrapContent:
    """Test the trim_bootstrap_content module-level function."""

    def test_short_content_not_truncated(self):
        """Content under max_chars should pass through unchanged."""
        content = "Short content"
        result = trim_bootstrap_content(content, "TEST.md")
        assert result.content == content
        assert result.truncated is False
        assert result.original_length == len(content)

    def test_exact_limit_not_truncated(self):
        """Content exactly at max_chars should not be truncated."""
        content = "x" * 100
        result = trim_bootstrap_content(content, "TEST.md", max_chars=100)
        assert result.truncated is False
        assert result.content == content

    def test_over_limit_is_truncated(self):
        """Content over max_chars should be truncated."""
        content = "a" * 200
        result = trim_bootstrap_content(content, "TEST.md", max_chars=100)
        assert result.truncated is True
        assert result.original_length == 200

    def test_truncation_preserves_head_and_tail(self):
        """Truncated content should contain head and tail portions."""
        # Build content where each char is its index mod 10
        content = "".join(str(i % 10) for i in range(1000))
        result = trim_bootstrap_content(
            content,
            "FILE.md",
            max_chars=100,
        )
        assert result.truncated is True
        # Head should be first 70 chars (floor(100 * 0.7))
        import math

        head_chars = math.floor(100 * BOOTSTRAP_HEAD_RATIO)
        tail_chars = math.floor(100 * BOOTSTRAP_TAIL_RATIO)
        assert result.content.startswith(content[:head_chars])
        assert result.content.endswith(content[-tail_chars:])

    def test_truncation_marker_present(self):
        """Truncated content should contain a truncation marker."""
        content = "x" * 200
        result = trim_bootstrap_content(
            content,
            "SOUL.md",
            max_chars=100,
        )
        assert "[...truncated, read SOUL.md for full content...]" in result.content

    def test_truncation_marker_includes_stats(self):
        """Truncation marker should include char counts."""
        content = "x" * 500
        result = trim_bootstrap_content(
            content,
            "SOUL.md",
            max_chars=100,
        )
        import math

        head_chars = math.floor(100 * BOOTSTRAP_HEAD_RATIO)
        tail_chars = math.floor(100 * BOOTSTRAP_TAIL_RATIO)
        expected_stats = f"truncated SOUL.md: kept {head_chars}+{tail_chars} chars of 500"
        assert expected_stats in result.content

    def test_trailing_whitespace_stripped(self):
        """Input content should have trailing whitespace stripped."""
        content = "hello   \n\n"
        result = trim_bootstrap_content(content, "TEST.md")
        assert result.content == "hello"
        assert result.original_length == len("hello")

    def test_default_max_chars(self):
        """Default max_chars should be DEFAULT_BOOTSTRAP_MAX_CHARS."""
        content = "x" * (DEFAULT_BOOTSTRAP_MAX_CHARS + 1)
        result = trim_bootstrap_content(content, "TEST.md")
        assert result.truncated is True

    def test_empty_content(self):
        """Empty content should not be truncated."""
        result = trim_bootstrap_content("", "TEST.md")
        assert result.content == ""
        assert result.truncated is False
        assert result.original_length == 0


@pytest.mark.unit
class TestWorkspaceManagerBuildPersona:
    """Test WorkspaceManager.build_persona() method."""

    @pytest.fixture()
    def workspace_dir(self, tmp_path):
        """Create a workspace directory for testing."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        return ws

    @pytest.fixture()
    def templates_dir(self, tmp_path):
        """Create a templates directory for testing."""
        tpl = tmp_path / "templates"
        tpl.mkdir()
        return tpl

    def _make_manager(
        self,
        workspace_dir,
        templates_dir,
        max_chars_per_file=DEFAULT_BOOTSTRAP_MAX_CHARS,
    ):
        """Helper to create a WorkspaceManager."""
        return WorkspaceManager(
            workspace_dir=workspace_dir,
            templates_dir=templates_dir,
            max_chars_per_file=max_chars_per_file,
        )

    async def test_build_persona_with_workspace_files(
        self,
        workspace_dir,
        templates_dir,
    ):
        """build_persona should load workspace files as WORKSPACE source."""
        # Arrange
        (workspace_dir / "SOUL.md").write_text("my soul")
        (workspace_dir / "IDENTITY.md").write_text("my identity")
        (workspace_dir / "USER.md").write_text("my profile")
        manager = self._make_manager(workspace_dir, templates_dir)

        # Act
        persona = await manager.build_persona()

        # Assert
        assert isinstance(persona, AgentPersona)
        assert persona.has_any is True
        assert persona.soul.content == "my soul"
        assert persona.soul.source == PersonaSource.WORKSPACE
        assert persona.soul.is_loaded is True
        assert persona.identity.content == "my identity"
        assert persona.identity.source == PersonaSource.WORKSPACE
        assert persona.user_profile.content == "my profile"
        assert persona.user_profile.source == PersonaSource.WORKSPACE

    async def test_build_persona_with_template_fallback(
        self,
        workspace_dir,
        templates_dir,
    ):
        """build_persona should fall back to templates when workspace
        files are missing."""
        # Arrange - only templates exist, no workspace files
        (templates_dir / "SOUL.md").write_text("template soul")
        manager = self._make_manager(workspace_dir, templates_dir)

        # Act
        persona = await manager.build_persona()

        # Assert
        assert persona.soul.content == "template soul"
        assert persona.soul.source == PersonaSource.TEMPLATE
        assert persona.soul.is_loaded is True

    async def test_build_persona_empty_when_no_files(
        self,
        workspace_dir,
        templates_dir,
    ):
        """build_persona should return empty persona when no files exist."""
        # Arrange - empty directories
        manager = self._make_manager(workspace_dir, templates_dir)

        # Act
        persona = await manager.build_persona()

        # Assert
        assert persona.has_any is False
        assert persona.soul.is_loaded is False
        assert persona.identity.is_loaded is False
        assert persona.user_profile.is_loaded is False

    async def test_build_persona_truncates_large_files(
        self,
        workspace_dir,
        templates_dir,
    ):
        """build_persona should truncate files exceeding max_chars."""
        # Arrange
        large_content = "x" * 500
        (workspace_dir / "SOUL.md").write_text(large_content)
        manager = self._make_manager(
            workspace_dir,
            templates_dir,
            max_chars_per_file=100,
        )

        # Act
        persona = await manager.build_persona()

        # Assert
        assert persona.soul.is_loaded is True
        assert persona.soul.is_truncated is True
        assert "[...truncated, read" in persona.soul.content

    async def test_build_persona_not_truncated_small_files(
        self,
        workspace_dir,
        templates_dir,
    ):
        """build_persona should not truncate files under max_chars."""
        # Arrange
        (workspace_dir / "SOUL.md").write_text("small")
        manager = self._make_manager(workspace_dir, templates_dir)

        # Act
        persona = await manager.build_persona()

        # Assert
        assert persona.soul.is_truncated is False

    async def test_build_persona_disabled(
        self,
        workspace_dir,
        templates_dir,
    ):
        """build_persona should return empty when manager is disabled."""
        # Arrange
        (workspace_dir / "SOUL.md").write_text("soul content")
        manager = WorkspaceManager(
            workspace_dir=workspace_dir,
            templates_dir=templates_dir,
            enabled=False,
        )

        # Act
        persona = await manager.build_persona()

        # Assert
        assert persona.has_any is False

    async def test_build_persona_caching(
        self,
        workspace_dir,
        templates_dir,
    ):
        """build_persona should use cache on second call."""
        # Arrange
        (workspace_dir / "SOUL.md").write_text("original soul")
        manager = self._make_manager(workspace_dir, templates_dir)

        # Act - first call loads files
        persona1 = await manager.build_persona()
        # Modify file after first load
        (workspace_dir / "SOUL.md").write_text("modified soul")
        # Second call should use cache
        persona2 = await manager.build_persona()

        # Assert - both should have original content (cached)
        assert persona1.soul.content == "original soul"
        assert persona2.soul.content == "original soul"

    async def test_build_persona_force_reload(
        self,
        workspace_dir,
        templates_dir,
    ):
        """build_persona(force_reload=True) should bypass cache."""
        # Arrange
        (workspace_dir / "SOUL.md").write_text("original soul")
        manager = self._make_manager(workspace_dir, templates_dir)

        # Act - first call
        await manager.build_persona()
        # Modify file, then force reload
        (workspace_dir / "SOUL.md").write_text("modified soul")
        persona = await manager.build_persona(force_reload=True)

        # Assert
        assert persona.soul.content == "modified soul"

    async def test_build_persona_subagent_mode(
        self,
        workspace_dir,
        templates_dir,
    ):
        """build_persona(subagent_mode=True) should skip HEARTBEAT.md."""
        # Arrange
        (workspace_dir / "SOUL.md").write_text("soul")
        (workspace_dir / "HEARTBEAT.md").write_text("heartbeat")
        manager = self._make_manager(workspace_dir, templates_dir)

        # Act
        persona = await manager.build_persona(subagent_mode=True)

        # Assert - soul loaded, heartbeat not included in persona
        assert persona.soul.is_loaded is True
        # AgentPersona does not have a heartbeat field, so only
        # SOUL, IDENTITY, USER are represented

    async def test_build_persona_injected_chars(
        self,
        workspace_dir,
        templates_dir,
    ):
        """PersonaField.injected_chars should match actual content length."""
        # Arrange
        content = "persona content here"
        (workspace_dir / "SOUL.md").write_text(content)
        manager = self._make_manager(workspace_dir, templates_dir)

        # Act
        persona = await manager.build_persona()

        # Assert
        assert persona.soul.injected_chars == len(content)
        assert persona.soul.raw_chars == len(content)

    async def test_build_persona_filename_set(
        self,
        workspace_dir,
        templates_dir,
    ):
        """PersonaField.filename should be set to the source filename."""
        # Arrange
        (workspace_dir / "SOUL.md").write_text("content")
        (workspace_dir / "IDENTITY.md").write_text("content")
        (workspace_dir / "USER.md").write_text("content")
        manager = self._make_manager(workspace_dir, templates_dir)

        # Act
        persona = await manager.build_persona()

        # Assert
        assert persona.soul.filename == "SOUL.md"
        assert persona.identity.filename == "IDENTITY.md"
        assert persona.user_profile.filename == "USER.md"
