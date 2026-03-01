"""Unit tests for sandbox dependency management data models."""

import pytest

from src.infrastructure.agent.plugins.sandbox_deps.models import (
    DepsStateRecord,
    ExecutionContext,
    InstallRequest,
    InstallResult,
    MCPServerDependency,
    PreparedState,
    RuntimeDependencies,
)


@pytest.mark.unit
class TestExecutionContext:
    """Tests for ExecutionContext enum."""

    def test_host_value(self) -> None:
        """HOST enum member should have string value 'host'."""
        assert ExecutionContext.HOST.value == "host"

    def test_sandbox_value(self) -> None:
        """SANDBOX enum member should have string value 'sandbox'."""
        assert ExecutionContext.SANDBOX.value == "sandbox"

    def test_hybrid_value(self) -> None:
        """HYBRID enum member should have string value 'hybrid'."""
        assert ExecutionContext.HYBRID.value == "hybrid"

    def test_enum_has_exactly_three_members(self) -> None:
        """ExecutionContext should contain exactly three members."""
        assert len(ExecutionContext) == 3


@pytest.mark.unit
class TestMCPServerDependency:
    """Tests for MCPServerDependency frozen dataclass."""

    def test_creation_with_all_fields(self) -> None:
        """MCPServerDependency should store all provided fields."""
        dep = MCPServerDependency(
            name="filesystem-server",
            transport_type="stdio",
            command="node",
            args=("--port", "3000"),
            env={"NODE_ENV": "production"},
        )
        assert dep.name == "filesystem-server"
        assert dep.transport_type == "stdio"
        assert dep.command == "node"
        assert dep.args == ("--port", "3000")
        assert dep.env == {"NODE_ENV": "production"}

    def test_default_empty_args_and_env(self) -> None:
        """args should default to empty tuple, env to empty dict."""
        dep = MCPServerDependency(
            name="test-server",
            transport_type="sse",
            command="python",
        )
        assert dep.args == ()
        assert dep.env == {}


@pytest.mark.unit
class TestRuntimeDependencies:
    """Tests for RuntimeDependencies frozen dataclass and deps_hash."""

    def test_creation_with_defaults(self) -> None:
        """All collection fields should default to empty."""
        deps = RuntimeDependencies()
        assert deps.pip_packages == ()
        assert deps.system_packages == ()
        assert deps.mcp_servers == ()
        assert deps.env_vars == {}
        assert deps.python_version is None

    def test_creation_with_all_fields(self) -> None:
        """RuntimeDependencies should accept all fields."""
        mcp = MCPServerDependency(name="srv", transport_type="stdio", command="cmd")
        deps = RuntimeDependencies(
            pip_packages=("pandas>=2.0", "numpy"),
            system_packages=("ffmpeg",),
            mcp_servers=(mcp,),
            env_vars={"KEY": "val"},
            python_version="3.11",
        )
        assert deps.pip_packages == ("pandas>=2.0", "numpy")
        assert deps.system_packages == ("ffmpeg",)
        assert len(deps.mcp_servers) == 1
        assert deps.env_vars == {"KEY": "val"}
        assert deps.python_version == "3.11"

    def test_deps_hash_returns_hex_string(self) -> None:
        """deps_hash() should return a 64-char hex SHA256 digest."""
        deps = RuntimeDependencies(pip_packages=("numpy",))
        h = deps.deps_hash()
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deps_hash_is_deterministic(self) -> None:
        """Same inputs must produce the same hash every time."""
        deps = RuntimeDependencies(
            pip_packages=("pandas", "numpy"),
            system_packages=("ffmpeg",),
        )
        assert deps.deps_hash() == deps.deps_hash()

    def test_deps_hash_changes_when_pip_packages_differ(self) -> None:
        """Different pip_packages should produce a different hash."""
        a = RuntimeDependencies(pip_packages=("numpy",))
        b = RuntimeDependencies(pip_packages=("pandas",))
        assert a.deps_hash() != b.deps_hash()

    def test_deps_hash_changes_when_system_packages_differ(self) -> None:
        """Different system_packages should produce a different hash."""
        a = RuntimeDependencies(system_packages=("ffmpeg",))
        b = RuntimeDependencies(system_packages=("git",))
        assert a.deps_hash() != b.deps_hash()

    def test_deps_hash_changes_when_env_vars_differ(self) -> None:
        """Different env_vars should produce a different hash."""
        a = RuntimeDependencies(env_vars={"A": "1"})
        b = RuntimeDependencies(env_vars={"B": "2"})
        assert a.deps_hash() != b.deps_hash()

    def test_deps_hash_changes_when_mcp_servers_differ(self) -> None:
        """Different mcp_servers should produce a different hash."""
        srv_a = MCPServerDependency(name="a", transport_type="stdio", command="cmd")
        srv_b = MCPServerDependency(name="b", transport_type="sse", command="cmd2")
        a = RuntimeDependencies(mcp_servers=(srv_a,))
        b = RuntimeDependencies(mcp_servers=(srv_b,))
        assert a.deps_hash() != b.deps_hash()

    def test_deps_hash_is_order_independent(self) -> None:
        """Hash should be the same regardless of input ordering."""
        a = RuntimeDependencies(
            pip_packages=("numpy", "pandas"),
            env_vars={"B": "2", "A": "1"},
        )
        b = RuntimeDependencies(
            pip_packages=("pandas", "numpy"),
            env_vars={"A": "1", "B": "2"},
        )
        assert a.deps_hash() == b.deps_hash()

    def test_frozen_cannot_modify_after_creation(self) -> None:
        """RuntimeDependencies is frozen; attribute assignment must raise."""
        deps = RuntimeDependencies()
        with pytest.raises(AttributeError):
            deps.pip_packages = ("evil",)  # type: ignore[misc]


@pytest.mark.unit
class TestPreparedState:
    """Tests for PreparedState frozen dataclass."""

    def test_creation_with_all_fields(self) -> None:
        """PreparedState should store all provided fields."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        state = PreparedState(
            plugin_id="plugin-1",
            deps_hash="abc123",
            sandbox_image_digest="sha256:deadbeef",
            prepared_at=now,
            venv_path="/opt/memstack/envs/plugin-1/abc123/",
        )
        assert state.plugin_id == "plugin-1"
        assert state.deps_hash == "abc123"
        assert state.sandbox_image_digest == "sha256:deadbeef"
        assert state.prepared_at == now
        assert state.venv_path == "/opt/memstack/envs/plugin-1/abc123/"

    def test_frozen_cannot_modify_after_creation(self) -> None:
        """PreparedState is frozen; attribute assignment must raise."""
        from datetime import UTC, datetime

        state = PreparedState(
            plugin_id="p",
            deps_hash="h",
            sandbox_image_digest="d",
            prepared_at=datetime.now(UTC),
            venv_path="/v",
        )
        with pytest.raises(AttributeError):
            state.plugin_id = "other"  # type: ignore[misc]


@pytest.mark.unit
class TestDepsStateRecord:
    """Tests for DepsStateRecord mutable dataclass."""

    def test_creation_with_defaults(self) -> None:
        """Default state should be None, 0 attempts, no error."""
        record = DepsStateRecord(
            plugin_id="p1",
            project_id="proj1",
            sandbox_id="sb1",
        )
        assert record.plugin_id == "p1"
        assert record.state is None
        assert record.install_attempts == 0
        assert record.last_error is None

    def test_is_prepared_returns_false_when_state_is_none(self) -> None:
        """is_prepared() should be False when no PreparedState is set."""
        record = DepsStateRecord(plugin_id="p", project_id="proj", sandbox_id="sb")
        assert record.is_prepared() is False

    def test_is_prepared_returns_true_when_state_is_set(self) -> None:
        """is_prepared() should be True when a PreparedState exists."""
        from datetime import UTC, datetime

        state = PreparedState(
            plugin_id="p",
            deps_hash="h",
            sandbox_image_digest="d",
            prepared_at=datetime.now(UTC),
            venv_path="/v",
        )
        record = DepsStateRecord(
            plugin_id="p",
            project_id="proj",
            sandbox_id="sb",
            state=state,
        )
        assert record.is_prepared() is True

    def test_mutable_can_update_fields(self) -> None:
        """DepsStateRecord is NOT frozen; fields can be updated."""
        record = DepsStateRecord(plugin_id="p", project_id="proj", sandbox_id="sb")
        record.install_attempts = 3
        record.last_error = "timeout"
        assert record.install_attempts == 3
        assert record.last_error == "timeout"


@pytest.mark.unit
class TestInstallRequest:
    """Tests for InstallRequest frozen dataclass."""

    def test_creation_with_all_fields(self) -> None:
        """InstallRequest should store all provided fields."""
        deps = RuntimeDependencies(pip_packages=("numpy",))
        req = InstallRequest(
            plugin_id="p1",
            project_id="proj1",
            sandbox_id="sb1",
            dependencies=deps,
            force=True,
        )
        assert req.plugin_id == "p1"
        assert req.project_id == "proj1"
        assert req.sandbox_id == "sb1"
        assert req.dependencies is deps
        assert req.force is True

    def test_default_force_is_false(self) -> None:
        """force field should default to False."""
        deps = RuntimeDependencies()
        req = InstallRequest(
            plugin_id="p",
            project_id="proj",
            sandbox_id="sb",
            dependencies=deps,
        )
        assert req.force is False

    def test_frozen_cannot_modify_after_creation(self) -> None:
        """InstallRequest is frozen; attribute assignment must raise."""
        deps = RuntimeDependencies()
        req = InstallRequest(
            plugin_id="p",
            project_id="proj",
            sandbox_id="sb",
            dependencies=deps,
        )
        with pytest.raises(AttributeError):
            req.force = True  # type: ignore[misc]


@pytest.mark.unit
class TestInstallResult:
    """Tests for InstallResult frozen dataclass."""

    def test_creation_with_all_fields(self) -> None:
        """InstallResult should store all provided fields."""
        result = InstallResult(
            success=True,
            plugin_id="p1",
            installed_packages=("numpy", "pandas"),
            skipped_packages=("scipy",),
            errors=(),
            duration_ms=1234,
        )
        assert result.success is True
        assert result.plugin_id == "p1"
        assert result.installed_packages == ("numpy", "pandas")
        assert result.skipped_packages == ("scipy",)
        assert result.errors == ()
        assert result.duration_ms == 1234

    def test_defaults_empty_tuples_and_zero_duration(self) -> None:
        """Optional fields should default to empty tuples and 0."""
        result = InstallResult(success=False, plugin_id="p")
        assert result.installed_packages == ()
        assert result.skipped_packages == ()
        assert result.errors == ()
        assert result.duration_ms == 0

    def test_frozen_cannot_modify_after_creation(self) -> None:
        """InstallResult is frozen; attribute assignment must raise."""
        result = InstallResult(success=True, plugin_id="p")
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]
