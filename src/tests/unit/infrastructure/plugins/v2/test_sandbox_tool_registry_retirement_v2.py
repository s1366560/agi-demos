"""Retirement coverage for the static Sandbox tool-registry composition seam."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]


def test_sandbox_tool_registry_has_no_static_di_authority() -> None:
    router_sources = tuple(
        (_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in (
            "src/infrastructure/adapters/primary/web/routers/sandbox/lifecycle.py",
            "src/infrastructure/adapters/primary/web/routers/sandbox/tools.py",
        )
    )
    sandbox_container_path = _ROOT / "src/configuration/containers/sandbox_container.py"
    di_source = (_ROOT / "src/configuration/di_container.py").read_text(encoding="utf-8")

    assert all("DIContainer" not in source for source in router_sources)
    assert not sandbox_container_path.exists()
    assert "sandbox_tool_registry" not in di_source


def test_sandbox_tool_registry_is_projected_from_the_pinned_generation() -> None:
    source = (_ROOT / "src/infrastructure/adapters/primary/web/routers/sandbox/utils.py").read_text(
        encoding="utf-8"
    )

    assert "def get_sandbox_tool_registry" in source
    assert "current_sandbox_application_services_v2().tool_registry" in source
