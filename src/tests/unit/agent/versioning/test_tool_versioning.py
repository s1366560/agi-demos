"""
Tests for tool versioning module.
"""

import pytest

from src.domain.ports.tool_port import BaseTool, ToolResult
from src.infrastructure.agent.versioning import (
    SemanticVersion,
    ToolVersionRequest,
    VersionConstraint,
    VersionMigration,
    VersionMigrator,
    create_versioned_registry,
    create_versioned_tool,
)


class DummyTool(BaseTool):
    """Simple tool for testing."""

    async def execute(self, **kwargs):
        return ToolResult.ok("ok")


def make_tool(name: str, version: str) -> DummyTool:
    """Create a tool instance for tests."""
    return DummyTool(name=name, description=f"{name} tool", version=version)


@pytest.mark.unit
class TestSemanticVersion:
    """Tests for SemanticVersion."""

    def test_parse_basic(self):
        """Should parse basic versions and normalize."""
        assert str(SemanticVersion.parse("1")) == "1.0.0"
        assert str(SemanticVersion.parse("1.2")) == "1.2.0"

    def test_parse_prerelease_and_build(self):
        """Should parse prerelease and build metadata."""
        version = SemanticVersion.parse("1.2.3-alpha+001")
        assert version.prerelease == "alpha"
        assert version.build == "001"
        assert str(version) == "1.2.3-alpha+001"

    def test_compare_prerelease(self):
        """Prerelease should be lower than release."""
        prerelease = SemanticVersion.parse("1.0.0-alpha")
        release = SemanticVersion.parse("1.0.0")
        assert prerelease < release

    def test_compatibility(self):
        """Should follow semver compatibility rules."""
        assert SemanticVersion.parse("1.2.0").is_compatible_with(
            SemanticVersion.parse("1.9.9")
        )
        assert not SemanticVersion.parse("1.2.0").is_compatible_with(
            SemanticVersion.parse("2.0.0")
        )
        assert SemanticVersion.parse("0.2.1").is_compatible_with(
            SemanticVersion.parse("0.2.9")
        )
        assert not SemanticVersion.parse("0.2.1").is_compatible_with(
            SemanticVersion.parse("0.3.0")
        )
        assert SemanticVersion.parse("0.0.3").is_compatible_with(
            SemanticVersion.parse("0.0.3")
        )
        assert not SemanticVersion.parse("0.0.3").is_compatible_with(
            SemanticVersion.parse("0.0.4")
        )

    def test_invalid_version(self):
        """Should reject invalid versions."""
        with pytest.raises(ValueError, match="Invalid semantic version"):
            SemanticVersion.parse("bad-version")


@pytest.mark.unit
class TestVersionConstraint:
    """Tests for VersionConstraint."""

    def test_wildcard(self):
        """Wildcard should match any version."""
        constraint = VersionConstraint.parse("*")
        assert constraint.matches(SemanticVersion.parse("1.2.3"))

    def test_exact_and_range(self):
        """Exact and range operators should match correctly."""
        exact = VersionConstraint.parse("=1.2.3")
        assert exact.matches(SemanticVersion.parse("1.2.3"))
        assert not exact.matches(SemanticVersion.parse("1.2.4"))

        gte = VersionConstraint.parse(">=1.2.3")
        assert gte.matches(SemanticVersion.parse("1.2.3"))
        assert gte.matches(SemanticVersion.parse("1.3.0"))
        assert not gte.matches(SemanticVersion.parse("1.2.2"))

        lt = VersionConstraint.parse("<1.2.3")
        assert lt.matches(SemanticVersion.parse("1.2.2"))
        assert not lt.matches(SemanticVersion.parse("1.2.3"))

    def test_caret(self):
        """Caret range should respect semver rules."""
        constraint = VersionConstraint.parse("^1.2.3")
        assert constraint.matches(SemanticVersion.parse("1.2.3"))
        assert constraint.matches(SemanticVersion.parse("1.9.9"))
        assert not constraint.matches(SemanticVersion.parse("2.0.0"))

        minor_constraint = VersionConstraint.parse("^0.2.3")
        assert minor_constraint.matches(SemanticVersion.parse("0.2.9"))
        assert not minor_constraint.matches(SemanticVersion.parse("0.3.0"))

        patch_constraint = VersionConstraint.parse("^0.0.3")
        assert patch_constraint.matches(SemanticVersion.parse("0.0.3"))
        assert not patch_constraint.matches(SemanticVersion.parse("0.0.4"))

    def test_tilde(self):
        """Tilde range should lock minor version."""
        constraint = VersionConstraint.parse("~1.2.3")
        assert constraint.matches(SemanticVersion.parse("1.2.9"))
        assert not constraint.matches(SemanticVersion.parse("1.3.0"))


@pytest.mark.unit
class TestVersionedToolRegistry:
    """Tests for VersionedToolRegistry."""

    @pytest.fixture
    def registry(self):
        """Create registry with sample tools."""
        registry = create_versioned_registry()
        registry.register(create_versioned_tool(make_tool("search", "1.0.0")))
        registry.register(create_versioned_tool(make_tool("search", "1.1.0")))
        registry.register(create_versioned_tool(make_tool("search", "2.0.0-alpha")))
        return registry

    def test_get_prefers_stable(self, registry):
        """Should prefer stable versions when available."""
        tool = registry.get("search")
        assert tool.version == SemanticVersion.parse("1.1.0")

    def test_get_prerelease_fallback(self, registry):
        """Should fall back to prerelease when no stable matches."""
        constraint = VersionConstraint.parse("^2.0.0")
        tool = registry.get("search", constraint=constraint)
        assert tool.version == SemanticVersion.parse("2.0.0-alpha")

    def test_deprecated_filter(self):
        """Should filter deprecated versions when requested."""
        registry = create_versioned_registry()
        registry.register(
            create_versioned_tool(make_tool("search", "1.0.0"), deprecated=True),
            deprecated=True,
            deprecation_message="use 2.0",
        )

        assert registry.get("search", allow_deprecated=False) is None
        assert registry.is_deprecated("search", SemanticVersion.parse("1.0.0"))

    def test_list_versions_sorted(self, registry):
        """Should list versions in descending order."""
        versions = registry.list_versions("search")
        assert versions[0] == SemanticVersion.parse("2.0.0-alpha")
        assert versions[-1] == SemanticVersion.parse("1.0.0")

    def test_latest_compatible(self, registry):
        """Should return latest compatible version."""
        tool = registry.get_latest_compatible("search", SemanticVersion.parse("1.0.0"))
        assert tool.version == SemanticVersion.parse("1.1.0")

    def test_suggest_upgrade(self):
        """Should suggest latest compatible non-deprecated upgrade."""
        registry = create_versioned_registry()
        registry.register(create_versioned_tool(make_tool("search", "1.0.0")))
        registry.register(create_versioned_tool(make_tool("search", "1.1.0")))
        registry.register(
            create_versioned_tool(make_tool("search", "1.2.0"), deprecated=True),
            deprecated=True,
        )

        upgrade = registry.suggest_upgrade("search", SemanticVersion.parse("1.0.0"))
        assert upgrade == SemanticVersion.parse("1.1.0")

    def test_resolve_request(self, registry):
        """Should resolve using ToolVersionRequest settings."""
        request = ToolVersionRequest(
            name="search",
            constraint=VersionConstraint.parse("^1.0.0"),
            allow_deprecated=True,
            prefer_stable=True,
        )
        tool = registry.resolve(request)
        assert tool.version == SemanticVersion.parse("1.1.0")


@pytest.mark.unit
class TestVersionedToolAdapter:
    """Tests for VersionedToolAdapter."""

    def test_create_versioned_tool(self):
        """Should wrap ToolPort as versioned tool."""
        tool = make_tool("search", "1.0.0")
        adapter = create_versioned_tool(tool)

        assert adapter.name == "search"
        assert adapter.version == SemanticVersion.parse("1.0.0")
        assert adapter.parameters["type"] == "object"


@pytest.mark.unit
class TestVersionMigrator:
    """Tests for VersionMigrator."""

    def test_migration_path_and_args(self):
        """Should migrate args across multiple versions."""
        migrator = VersionMigrator()
        v1 = SemanticVersion.parse("1.0.0")
        v2 = SemanticVersion.parse("1.1.0")
        v3 = SemanticVersion.parse("1.2.0")

        def add_step1(args):
            result = args.copy()
            result["step1"] = True
            return result

        def add_step2(args):
            result = args.copy()
            result["step2"] = True
            return result

        migrator.register(
            VersionMigration(
                tool_name="search",
                from_version=v1,
                to_version=v2,
                migrate_args=add_step1,
            )
        )
        migrator.register(
            VersionMigration(
                tool_name="search",
                from_version=v2,
                to_version=v3,
                migrate_args=add_step2,
            )
        )

        assert migrator.can_migrate("search", v1, v3)
        migrated = migrator.migrate_args("search", v1, v3, {"query": "test"})
        assert migrated["step1"] is True
        assert migrated["step2"] is True

    def test_migration_result(self):
        """Should migrate results back along the path."""
        migrator = VersionMigrator()
        v1 = SemanticVersion.parse("1.0.0")
        v2 = SemanticVersion.parse("1.1.0")

        def add_back(result):
            updated = result.copy()
            updated["back"] = True
            return updated

        migrator.register(
            VersionMigration(
                tool_name="search",
                from_version=v1,
                to_version=v2,
                migrate_result=add_back,
            )
        )

        migrated = migrator.migrate_result("search", v1, v2, {"ok": True})
        assert migrated["back"] is True

    def test_missing_path(self):
        """Should return false when migration path missing."""
        migrator = VersionMigrator()
        v1 = SemanticVersion.parse("1.0.0")
        v2 = SemanticVersion.parse("1.1.0")
        assert not migrator.can_migrate("search", v1, v2)
