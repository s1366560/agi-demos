"""Retirement contract for the legacy SQL Workspace Plan composition."""

from __future__ import annotations

import pytest

from src.infrastructure.agent.workspace_plan.factory import (
    LegacyWorkspacePlanRuntimeRetiredError,
    build_sql_orchestrator,
)


@pytest.mark.unit
def test_build_sql_orchestrator_fails_closed_without_using_session() -> None:
    class _ExplodingSession:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"legacy session accessed: {name}")

    with pytest.raises(
        LegacyWorkspacePlanRuntimeRetiredError,
        match="Avernet Workspace Core",
    ):
        build_sql_orchestrator(_ExplodingSession())
