"""Retirement tests for the legacy Python Workspace Plan outbox handlers."""

from __future__ import annotations

import pytest

from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    LegacyWorkspacePlanRuntimeRetiredError,
    make_attempt_retry_handler,
    make_handoff_resume_handler,
    make_pipeline_run_requested_handler,
    make_supervisor_tick_handler,
    make_worker_launch_handler,
)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory",
    [
        make_supervisor_tick_handler,
        make_worker_launch_handler,
        make_handoff_resume_handler,
        make_attempt_retry_handler,
        make_pipeline_run_requested_handler,
    ],
)
async def test_retired_handler_fails_closed_without_touching_persistence(factory: object) -> None:
    class _ExplodingBoundary:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"legacy boundary accessed: {name}")

    handler = factory()  # type: ignore[operator]
    with pytest.raises(
        LegacyWorkspacePlanRuntimeRetiredError,
        match="Avernet Workspace Core",
    ):
        await handler(_ExplodingBoundary(), _ExplodingBoundary())
