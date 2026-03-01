"""Unit tests for DependencyOrchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.plugins.sandbox_deps.models import (
    DepsStateRecord,
    ExecutionContext,
    InstallRequest,
    InstallResult,
    PreparedState,
    RuntimeDependencies,
)
from src.infrastructure.agent.plugins.sandbox_deps.orchestrator import (
    DependencyOrchestrator,
)
from src.infrastructure.agent.plugins.sandbox_deps.security_gate import (
    ValidationResult,
)


def _make_deps(
    pip: tuple[str, ...] = ("pandas",),
) -> RuntimeDependencies:
    """Helper to create RuntimeDependencies with pip packages."""
    return RuntimeDependencies(pip_packages=pip)


def _make_record(
    plugin_id: str = "plug-1",
    project_id: str = "proj-1",
    sandbox_id: str = "sbx-1",
    state: PreparedState | None = None,
) -> DepsStateRecord:
    """Helper to create DepsStateRecord."""
    return DepsStateRecord(
        plugin_id=plugin_id,
        project_id=project_id,
        sandbox_id=sandbox_id,
        state=state,
    )


def _make_prepared(
    plugin_id: str = "plug-1",
    deps_hash: str = "abc123",
) -> PreparedState:
    """Helper to create PreparedState."""
    from datetime import UTC, datetime

    return PreparedState(
        plugin_id=plugin_id,
        deps_hash=deps_hash,
        sandbox_image_digest="sbx-1",
        prepared_at=datetime.now(UTC),
        venv_path="/opt/memstack/envs/plug-1/abc123/",
    )


def _build_orchestrator(
    store: AsyncMock | None = None,
    installer: AsyncMock | None = None,
    gate: MagicMock | None = None,
    max_retries: int = 2,
) -> DependencyOrchestrator:
    """Helper to build orchestrator with default mocks."""
    return DependencyOrchestrator(
        state_store=store or AsyncMock(),
        sandbox_installer=installer or AsyncMock(),
        security_gate=gate,
        max_retries=max_retries,
    )


@pytest.mark.unit
class TestEnsureDependenciesCached:
    """Tests for ensure_dependencies when cached state exists."""

    async def test_cached_state_skips_install(self) -> None:
        """When cached state hash matches, skip installation."""
        deps = _make_deps()
        deps_hash = deps.deps_hash()
        prepared = _make_prepared(deps_hash=deps_hash)
        record = _make_record(state=prepared)

        store = AsyncMock()
        store.load = AsyncMock(return_value=record)
        installer = AsyncMock()

        orch = _build_orchestrator(store=store, installer=installer)

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        assert result.success is True
        assert result.skipped_packages == deps.pip_packages
        installer.install.assert_not_called()
        store.save.assert_not_called()

    async def test_cached_state_with_force_reinstalls(self) -> None:
        """When force=True, bypass cache and reinstall."""
        deps = _make_deps()
        deps_hash = deps.deps_hash()
        prepared = _make_prepared(deps_hash=deps_hash)
        record = _make_record(state=prepared)

        store = AsyncMock()
        store.load = AsyncMock(return_value=record)

        installer = AsyncMock()
        installer.install = AsyncMock(
            return_value=InstallResult(
                success=True,
                plugin_id="plug-1",
                installed_packages=("pandas",),
            )
        )

        gate = MagicMock()
        gate.validate_request = MagicMock(return_value=ValidationResult(valid=True))

        orch = _build_orchestrator(store=store, installer=installer, gate=gate)

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
            force=True,
        )

        assert result.success is True
        installer.install.assert_called_once()


@pytest.mark.unit
class TestEnsureDependenciesSecurityGate:
    """Tests for security gate rejection."""

    async def test_security_rejection_returns_failure(self) -> None:
        """When security gate rejects, return failure without install."""
        deps = _make_deps()

        store = AsyncMock()
        store.load = AsyncMock(return_value=None)

        installer = AsyncMock()

        gate = MagicMock()
        gate.validate_request = MagicMock(
            return_value=ValidationResult(
                valid=False,
                errors=("Package not allowed",),
            )
        )

        orch = _build_orchestrator(store=store, installer=installer, gate=gate)

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        assert result.success is False
        assert "Package not allowed" in result.errors
        installer.install.assert_not_called()


@pytest.mark.unit
class TestEnsureDependenciesFreshInstall:
    """Tests for fresh dependency installation paths."""

    async def test_sandbox_context_delegates_to_sandbox_installer(
        self,
    ) -> None:
        """SANDBOX context routes to sandbox installer."""
        deps = _make_deps()

        store = AsyncMock()
        store.load = AsyncMock(return_value=None)
        store.save = AsyncMock()

        installer = AsyncMock()
        installer.install = AsyncMock(
            return_value=InstallResult(
                success=True,
                plugin_id="plug-1",
                installed_packages=("pandas",),
            )
        )

        gate = MagicMock()
        gate.validate_request = MagicMock(return_value=ValidationResult(valid=True))

        orch = _build_orchestrator(store=store, installer=installer, gate=gate)

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
            execution_context=ExecutionContext.SANDBOX,
        )

        assert result.success is True
        assert "pandas" in result.installed_packages
        installer.install.assert_called_once()
        # State should be saved after success
        assert store.save.call_count >= 1

    @patch("src.infrastructure.agent.plugins.sandbox_deps.orchestrator.asyncio.wait_for")
    async def test_host_context_runs_pip_install(self, mock_wait_for: AsyncMock) -> None:
        """HOST context runs pip install via subprocess."""
        deps = _make_deps()

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stderr = ""
        mock_wait_for.return_value = mock_process

        store = AsyncMock()
        store.load = AsyncMock(return_value=None)
        store.save = AsyncMock()

        installer = AsyncMock()

        gate = MagicMock()
        gate.validate_request = MagicMock(return_value=ValidationResult(valid=True))

        orch = _build_orchestrator(store=store, installer=installer, gate=gate)

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
            execution_context=ExecutionContext.HOST,
        )

        assert result.success is True
        mock_wait_for.assert_called_once()
        # Sandbox installer should NOT be called for HOST
        installer.install.assert_not_called()

    @patch("src.infrastructure.agent.plugins.sandbox_deps.orchestrator.asyncio.wait_for")
    async def test_hybrid_context_installs_both(self, mock_wait_for: AsyncMock) -> None:
        """HYBRID context installs in sandbox first, then host."""
        deps = _make_deps()

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stderr = ""
        mock_wait_for.return_value = mock_process

        store = AsyncMock()
        store.load = AsyncMock(return_value=None)
        store.save = AsyncMock()

        installer = AsyncMock()
        installer.install = AsyncMock(
            return_value=InstallResult(
                success=True,
                plugin_id="plug-1",
                installed_packages=("pandas",),
            )
        )

        gate = MagicMock()
        gate.validate_request = MagicMock(return_value=ValidationResult(valid=True))

        orch = _build_orchestrator(store=store, installer=installer, gate=gate)

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
            execution_context=ExecutionContext.HYBRID,
        )

        assert result.success is True
        # Both sandbox installer and host pip should be called
        installer.install.assert_called_once()
        mock_wait_for.assert_called_once()

    async def test_hybrid_sandbox_failure_skips_host(self) -> None:
        """HYBRID: if sandbox install fails, host is NOT attempted."""
        deps = _make_deps()

        store = AsyncMock()
        store.load = AsyncMock(return_value=None)
        store.save = AsyncMock()

        installer = AsyncMock()
        installer.install = AsyncMock(
            return_value=InstallResult(
                success=False,
                plugin_id="plug-1",
                errors=("sandbox error",),
            )
        )

        gate = MagicMock()
        gate.validate_request = MagicMock(return_value=ValidationResult(valid=True))

        orch = _build_orchestrator(
            store=store,
            installer=installer,
            gate=gate,
            max_retries=0,
        )

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
            execution_context=ExecutionContext.HYBRID,
        )

        assert result.success is False


@pytest.mark.unit
class TestEnsureDependenciesRetry:
    """Tests for the retry mechanism."""

    async def test_retry_on_failure_then_succeed(self) -> None:
        """First attempt fails, second succeeds."""
        deps = _make_deps()

        store = AsyncMock()
        store.load = AsyncMock(return_value=None)
        store.save = AsyncMock()

        fail_result = InstallResult(
            success=False,
            plugin_id="plug-1",
            errors=("transient error",),
        )
        success_result = InstallResult(
            success=True,
            plugin_id="plug-1",
            installed_packages=("pandas",),
        )

        installer = AsyncMock()
        installer.install = AsyncMock(side_effect=[fail_result, success_result])

        gate = MagicMock()
        gate.validate_request = MagicMock(return_value=ValidationResult(valid=True))

        orch = _build_orchestrator(store=store, installer=installer, gate=gate, max_retries=2)

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        assert result.success is True
        assert installer.install.call_count == 2

    async def test_all_retries_fail(self) -> None:
        """All retry attempts fail."""
        deps = _make_deps()

        store = AsyncMock()
        store.load = AsyncMock(return_value=None)
        store.save = AsyncMock()

        fail_result = InstallResult(
            success=False,
            plugin_id="plug-1",
            errors=("persistent error",),
        )

        installer = AsyncMock()
        installer.install = AsyncMock(return_value=fail_result)

        gate = MagicMock()
        gate.validate_request = MagicMock(return_value=ValidationResult(valid=True))

        orch = _build_orchestrator(store=store, installer=installer, gate=gate, max_retries=2)

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        assert result.success is False
        # max_retries=2 means 3 total attempts (0, 1, 2)
        assert installer.install.call_count == 3

    async def test_no_existing_record_creates_new_one(self) -> None:
        """When no existing record, a fresh DepsStateRecord is used."""
        deps = _make_deps()

        store = AsyncMock()
        store.load = AsyncMock(return_value=None)
        store.save = AsyncMock()

        installer = AsyncMock()
        installer.install = AsyncMock(
            return_value=InstallResult(
                success=True,
                plugin_id="plug-1",
                installed_packages=("pandas",),
            )
        )

        gate = MagicMock()
        gate.validate_request = MagicMock(return_value=ValidationResult(valid=True))

        orch = _build_orchestrator(store=store, installer=installer, gate=gate)

        result = await orch.ensure_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        assert result.success is True
        # save is called at least once to persist the prepared state
        assert store.save.call_count >= 1
        saved_record = store.save.call_args[0][0]
        assert saved_record.plugin_id == "plug-1"
        assert saved_record.state is not None


@pytest.mark.unit
class TestCheckDependencies:
    """Tests for check_dependencies method."""

    async def test_no_existing_record_returns_fresh(self) -> None:
        """When no record exists, return a fresh DepsStateRecord."""
        deps = _make_deps()

        store = AsyncMock()
        store.load = AsyncMock(return_value=None)

        orch = _build_orchestrator(store=store)

        record = await orch.check_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        assert record.plugin_id == "plug-1"
        assert record.project_id == "proj-1"
        assert record.sandbox_id == "sbx-1"
        assert record.state is None

    async def test_matching_hash_preserves_state(self) -> None:
        """When deps_hash matches, state is preserved."""
        deps = _make_deps()
        deps_hash = deps.deps_hash()
        prepared = _make_prepared(deps_hash=deps_hash)
        existing = _make_record(state=prepared)

        store = AsyncMock()
        store.load = AsyncMock(return_value=existing)

        orch = _build_orchestrator(store=store)

        record = await orch.check_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        assert record.state is not None
        assert record.state.deps_hash == deps_hash

    async def test_mismatched_hash_clears_state(self) -> None:
        """When deps_hash mismatches, state is set to None."""
        deps = _make_deps()
        # Create a prepared state with a different hash
        prepared = _make_prepared(deps_hash="different_hash")
        existing = _make_record(state=prepared)

        store = AsyncMock()
        store.load = AsyncMock(return_value=existing)

        orch = _build_orchestrator(store=store)

        record = await orch.check_dependencies(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        assert record.state is None


@pytest.mark.unit
class TestInvalidate:
    """Tests for invalidate method."""

    async def test_invalidate_returns_true_when_removed(self) -> None:
        """invalidate returns True when record exists."""
        store = AsyncMock()
        store.remove = AsyncMock(return_value=True)

        orch = _build_orchestrator(store=store)

        removed = await orch.invalidate(
            plugin_id="plug-1",
            sandbox_id="sbx-1",
            project_id="proj-1",
        )

        assert removed is True
        store.remove.assert_called_once_with("plug-1", "sbx-1", "proj-1")

    async def test_invalidate_returns_false_when_not_found(
        self,
    ) -> None:
        """invalidate returns False when no record exists."""
        store = AsyncMock()
        store.remove = AsyncMock(return_value=False)

        orch = _build_orchestrator(store=store)

        removed = await orch.invalidate(
            plugin_id="plug-1",
            sandbox_id="sbx-1",
            project_id="proj-1",
        )

        assert removed is False


@pytest.mark.unit
class TestInvalidateProject:
    """Tests for invalidate_project method."""

    async def test_invalidate_project_removes_all_records(
        self,
    ) -> None:
        """invalidate_project removes all records for a project."""
        records = [
            _make_record(
                plugin_id="plug-1",
                sandbox_id="sbx-1",
            ),
            _make_record(
                plugin_id="plug-2",
                sandbox_id="sbx-2",
            ),
        ]

        store = AsyncMock()
        store.list_by_project = AsyncMock(return_value=records)
        store.remove = AsyncMock(return_value=True)

        orch = _build_orchestrator(store=store)

        count = await orch.invalidate_project(project_id="proj-1")

        assert count == 2
        assert store.remove.call_count == 2

    async def test_invalidate_project_empty(self) -> None:
        """invalidate_project returns 0 when no records exist."""
        store = AsyncMock()
        store.list_by_project = AsyncMock(return_value=[])
        store.remove = AsyncMock()

        orch = _build_orchestrator(store=store)

        count = await orch.invalidate_project(project_id="proj-1")

        assert count == 0
        store.remove.assert_not_called()


@pytest.mark.unit
class TestInstallSandboxDeps:
    """Tests for _install_sandbox_deps private method."""

    async def test_sandbox_installer_exception_returns_failure(
        self,
    ) -> None:
        """If sandbox installer raises, return failure InstallResult."""
        deps = _make_deps()
        request = InstallRequest(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        installer = AsyncMock()
        installer.install = AsyncMock(side_effect=RuntimeError("connection lost"))

        orch = _build_orchestrator(installer=installer)

        result = await orch._install_sandbox_deps(request)

        assert result.success is False
        assert any("connection lost" in e for e in result.errors)


@pytest.mark.unit
class TestInstallHostDeps:
    """Tests for _install_host_deps private method."""

    async def test_no_pip_packages_returns_success(self) -> None:
        """When no pip packages, return success with skipped."""
        deps = RuntimeDependencies(pip_packages=())
        request = InstallRequest(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        orch = _build_orchestrator()

        result = await orch._install_host_deps(request)

        assert result.success is True
        assert result.skipped_packages == ()

    @patch("src.infrastructure.agent.plugins.sandbox_deps.orchestrator.asyncio.wait_for")
    async def test_pip_timeout_returns_failure(self, mock_wait_for: AsyncMock) -> None:
        """TimeoutError from pip install returns failure."""
        deps = _make_deps()
        request = InstallRequest(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        mock_wait_for.side_effect = TimeoutError()

        orch = _build_orchestrator()

        result = await orch._install_host_deps(request)

        assert result.success is False
        assert any("timed out" in e for e in result.errors)

    @patch("src.infrastructure.agent.plugins.sandbox_deps.orchestrator.asyncio.wait_for")
    async def test_pip_nonzero_returncode_fails(self, mock_wait_for: AsyncMock) -> None:
        """pip returning non-zero exit code results in failure."""
        deps = _make_deps()
        request = InstallRequest(
            plugin_id="plug-1",
            project_id="proj-1",
            sandbox_id="sbx-1",
            dependencies=deps,
        )

        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stderr = "No matching distribution"
        mock_wait_for.return_value = mock_process

        orch = _build_orchestrator()

        result = await orch._install_host_deps(request)

        assert result.success is False
        assert any("No matching distribution" in e for e in result.errors)


@pytest.mark.unit
class TestCreatePreparedState:
    """Tests for _create_prepared_state private method."""

    async def test_correct_venv_path(self) -> None:
        """venv_path follows /opt/memstack/envs/{plugin}/{hash[:16]}/."""
        deps = _make_deps()
        deps_hash = deps.deps_hash()

        orch = _build_orchestrator()

        prepared = await orch._create_prepared_state(
            plugin_id="plug-1",
            dependencies=deps,
            sandbox_id="sbx-1",
        )

        expected_path = f"/opt/memstack/envs/plug-1/{deps_hash[:16]}/"
        assert prepared.venv_path == expected_path
        assert prepared.plugin_id == "plug-1"
        assert prepared.deps_hash == deps_hash
        assert prepared.sandbox_image_digest == "sbx-1"
