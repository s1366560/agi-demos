"""Unit tests for the canonical Workspace Collaboration transaction boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks

from src.infrastructure.adapters.primary.web.routers.workspace_collaboration_transaction import (
    WorkspaceCollaborationUnitOfWork,
)


class _FakeSession:
    def __init__(self, *, dialect_name: str = "sqlite") -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.flush = AsyncMock()
        self.execute = AsyncMock(return_value="executed")
        self.refresh = AsyncMock()
        self.get_bind = lambda: SimpleNamespace(
            dialect=SimpleNamespace(name=dialect_name)
        )


@pytest.mark.unit
async def test_inner_session_never_commits_or_rolls_back_real_transaction() -> None:
    real = _FakeSession()
    background = BackgroundTasks()
    unit = WorkspaceCollaborationUnitOfWork(real, background)

    await unit.prepare()
    await unit.session.execute("statement")
    await unit.session.refresh("entity")
    await unit.session.commit()
    await unit.session.rollback()

    real.execute.assert_awaited_once_with("statement")
    real.refresh.assert_awaited_once_with("entity")
    real.flush.assert_awaited_once()
    real.commit.assert_not_awaited()
    real.rollback.assert_not_awaited()

    await unit.commit()

    real.commit.assert_awaited_once()


@pytest.mark.unit
async def test_background_tasks_are_released_only_after_real_commit() -> None:
    real = _FakeSession()
    background = BackgroundTasks()
    unit = WorkspaceCollaborationUnitOfWork(real, background)

    unit.background_tasks.add_task(lambda: None)
    assert background.tasks == []

    await unit.commit()

    assert len(background.tasks) == 1


@pytest.mark.unit
async def test_postgresql_prepare_sets_transaction_local_trigger_mode() -> None:
    real = _FakeSession(dialect_name="postgresql")
    unit = WorkspaceCollaborationUnitOfWork(real, BackgroundTasks())

    await unit.prepare()

    statement = str(real.execute.await_args.args[0])
    assert "SET LOCAL" in statement
    assert "memstack.workspace_collaboration_authority_mode" in statement
    assert "canonical" in statement


@pytest.mark.unit
async def test_file_delete_and_copy_compensate_on_rollback(tmp_path: Path) -> None:
    real = _FakeSession()
    unit = WorkspaceCollaborationUnitOfWork(real, BackgroundTasks())
    deleted = tmp_path / "workspace-1" / "file-1" / "report.txt"
    deleted.parent.mkdir(parents=True)
    deleted.write_text("original")
    created = tmp_path / "workspace-1" / "file-2" / "copy.txt"
    created.parent.mkdir(parents=True)
    created.write_text("copy")

    unit.file_journal.stage_delete(deleted, storage_root=tmp_path)
    unit.file_journal.record_created(created, storage_root=tmp_path)
    assert deleted.exists() is False

    await unit.rollback()

    assert deleted.read_text() == "original"
    assert created.exists() is False
    real.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_file_delete_finalizes_only_after_commit(tmp_path: Path) -> None:
    real = _FakeSession()
    unit = WorkspaceCollaborationUnitOfWork(real, BackgroundTasks())
    deleted = tmp_path / "workspace-1" / "file-1" / "report.txt"
    deleted.parent.mkdir(parents=True)
    deleted.write_text("original")

    unit.file_journal.stage_delete(deleted, storage_root=tmp_path)
    trash_paths = list((tmp_path / ".transactions").rglob("report.txt"))
    assert len(trash_paths) == 1

    await unit.commit()

    assert deleted.exists() is False
    assert trash_paths[0].exists() is False


@pytest.mark.unit
async def test_commit_wins_cancellation_and_keeps_created_file(tmp_path: Path) -> None:
    commit_started = asyncio.Event()
    finish_commit = asyncio.Event()
    real = _FakeSession()

    async def commit() -> None:
        commit_started.set()
        await finish_commit.wait()

    real.commit.side_effect = commit
    unit = WorkspaceCollaborationUnitOfWork(real, BackgroundTasks())
    created = tmp_path / "workspace-1" / "file-1" / "report.txt"
    created.parent.mkdir(parents=True)
    created.write_text("committed")
    unit.file_journal.record_created(created, storage_root=tmp_path)

    task = asyncio.create_task(unit.commit())
    await commit_started.wait()
    task.cancel()
    finish_commit.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert unit.committed is True
    assert created.read_text() == "committed"
    real.rollback.assert_not_awaited()
