"""One durable transaction boundary for canonical Workspace Collaboration mutations."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import shutil
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from fastapi import BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_PostCommitCallback = Callable[[], Awaitable[None] | None]
_FileJournalEntry = Callable[["WorkspaceFileMutationJournal"], None]
_ACTIVE_UNIT_OF_WORK: ContextVar[WorkspaceCollaborationUnitOfWork | None] = ContextVar(
    "workspace_collaboration_unit_of_work",
    default=None,
)
_WORKSPACE_STORAGE_ROOT_FALLBACK = Path("/tmp/agistack-blackboard-files")


@dataclass(frozen=True, kw_only=True)
class _CreatedPath:
    path: Path


@dataclass(frozen=True, kw_only=True)
class _DeletedPath:
    source: Path
    trash: Path


class WorkspaceFileMutationJournal:
    """Compensate filesystem mutations when the enclosing SQL transaction rolls back."""

    def __init__(self, transaction_id: str) -> None:
        self._transaction_id = transaction_id
        self._operations: list[_CreatedPath | _DeletedPath] = []
        self._trash_roots: set[Path] = set()

    def record_created(self, path: Path, *, storage_root: Path) -> None:
        safe_path, _ = self._resolve_scoped_path(path, storage_root=storage_root)
        self._operations.append(_CreatedPath(path=safe_path))

    def stage_delete(self, path: Path, *, storage_root: Path) -> None:
        safe_path, safe_root = self._resolve_scoped_path(path, storage_root=storage_root)
        if not safe_path.exists():
            return
        relative = safe_path.relative_to(safe_root)
        trash_root = safe_root / ".transactions" / self._transaction_id
        trash_path = trash_root / relative
        self._ensure_private_directory(trash_path.parent)
        if trash_path.exists() or trash_path.is_symlink():
            raise ValueError("Workspace file compensation target already exists")
        os.replace(safe_path, trash_path)
        self._trash_roots.add(trash_root)
        self._operations.append(_DeletedPath(source=safe_path, trash=trash_path))

    async def commit(self) -> None:
        for operation in self._operations:
            if isinstance(operation, _DeletedPath):
                self._remove_path(operation.trash)
        self._cleanup_trash_roots()
        self._operations.clear()

    async def rollback(self) -> None:
        for operation in reversed(self._operations):
            try:
                if isinstance(operation, _CreatedPath):
                    self._remove_path(operation.path)
                elif operation.trash.exists():
                    self._ensure_private_directory(operation.source.parent)
                    os.replace(operation.trash, operation.source)
            except Exception:
                logger.exception(
                    "workspace file mutation compensation failed",
                    extra={
                        "workspace_transaction_id": self._transaction_id,
                        "workspace_file_path": str(
                            operation.path
                            if isinstance(operation, _CreatedPath)
                            else operation.source
                        ),
                    },
                )
        self._cleanup_trash_roots()
        self._operations.clear()

    @staticmethod
    def _resolve_scoped_path(path: Path, *, storage_root: Path) -> tuple[Path, Path]:
        safe_root = storage_root.resolve()
        safe_path = path.resolve(strict=False)
        try:
            safe_path.relative_to(safe_root)
        except ValueError as exc:
            raise ValueError("Workspace file mutation escaped its storage root") from exc
        current = safe_path
        while current != safe_root:
            if current.is_symlink():
                raise ValueError("Workspace file mutation path contains a symlink")
            current = current.parent
        return safe_path, safe_root

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        parent = path.parent
        while parent.name and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def _cleanup_trash_roots(self) -> None:
        for trash_root in self._trash_roots:
            if trash_root.exists():
                shutil.rmtree(trash_root, ignore_errors=True)
            transactions_root = trash_root.parent
            if transactions_root.exists() and not any(transactions_root.iterdir()):
                transactions_root.rmdir()
        self._trash_roots.clear()


class _DeferredCommitSession:
    """Expose AsyncSession operations while retaining commit ownership in the outer route."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.inner_commit_count = 0
        self.inner_rollback_count = 0

    async def commit(self) -> None:
        self.inner_commit_count += 1
        await self._session.flush()

    async def rollback(self) -> None:
        self.inner_rollback_count += 1

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(self._session, name)


class _DeferredBackgroundTasks(BackgroundTasks):
    def __init__(self, unit_of_work: WorkspaceCollaborationUnitOfWork) -> None:
        super().__init__()
        self._unit_of_work = unit_of_work

    def add_task(
        self,
        func: Callable[..., Any],
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        self._unit_of_work.defer_background_task(func, *args, **kwargs)


class WorkspaceCollaborationUnitOfWork:
    """Own the real commit, trigger mode, post-commit work, and file compensation."""

    def __init__(
        self,
        session: AsyncSession,
        background_tasks: BackgroundTasks | None,
    ) -> None:
        self._session = session
        self._background_tasks = background_tasks
        self._deferred_session = _DeferredCommitSession(session)
        self._deferred_background_tasks = _DeferredBackgroundTasks(self)
        self._pending_background_tasks: list[
            tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]
        ] = []
        self._post_commit_callbacks: list[_PostCommitCallback] = []
        self._token: Token[WorkspaceCollaborationUnitOfWork | None] | None = None
        self._transaction_id = uuid.uuid4().hex
        self.file_journal = WorkspaceFileMutationJournal(self._transaction_id)
        self.committed = False
        self._deactivated = False

    @property
    def session(self) -> AsyncSession:
        return cast(AsyncSession, self._deferred_session)

    @property
    def background_tasks(self) -> BackgroundTasks:
        return self._deferred_background_tasks

    async def prepare(self) -> None:
        if self._token is not None:
            raise RuntimeError("Workspace Collaboration unit of work is already active")
        self._deactivated = False
        self._token = _ACTIVE_UNIT_OF_WORK.set(self)
        bind = self._session.get_bind()
        if getattr(getattr(bind, "dialect", None), "name", "") == "postgresql":
            await self._session.execute(
                text(
                    "SET LOCAL memstack.workspace_collaboration_authority_mode = "
                    "'canonical'"
                )
            )

    def defer_background_task(
        self,
        func: Callable[..., Any],
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        self._pending_background_tasks.append((func, args, kwargs))

    def defer_post_commit(self, callback: _PostCommitCallback) -> None:
        self._post_commit_callbacks.append(callback)

    def defer_file_journal(self, record: _FileJournalEntry) -> None:
        record(self.file_journal)

    async def commit(self) -> None:
        if self.committed:
            return
        commit_task = asyncio.create_task(self._session.commit())
        cancelled = False
        try:
            await asyncio.shield(commit_task)
        except asyncio.CancelledError:
            cancelled = True
            await asyncio.shield(commit_task)
        except BaseException:
            await self._rollback_database()
            await self._rollback_files()
            self._deactivate(safe_only=True)
            raise

        self.committed = True
        try:
            await asyncio.shield(self._after_commit())
        except asyncio.CancelledError:
            cancelled = True
            await asyncio.shield(self._after_commit())
        except BaseException:
            self._deactivate(safe_only=True)
            raise
        finally:
            self._deactivate(safe_only=True)
        if cancelled:
            raise asyncio.CancelledError

    async def rollback(self) -> None:
        if self.committed:
            self._deactivate(safe_only=True)
            return
        await self._rollback_database()
        await self._rollback_files()
        self._pending_background_tasks.clear()
        self._post_commit_callbacks.clear()
        self._deactivate(safe_only=True)

    async def _after_commit(self) -> None:
        await self.file_journal.commit()
        self._deactivate(safe_only=True)
        if self._background_tasks is not None:
            for func, args, kwargs in self._pending_background_tasks:
                self._background_tasks.add_task(func, *args, **kwargs)
        else:
            for func, args, kwargs in self._pending_background_tasks:
                result = func(*args, **kwargs)
                if inspect.isawaitable(result):
                    await result
        self._pending_background_tasks.clear()
        for callback in self._post_commit_callbacks:
            try:
                result = callback()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "workspace collaboration post-commit callback failed",
                    extra={"workspace_transaction_id": self._transaction_id},
                )
        self._post_commit_callbacks.clear()

    async def _rollback_database(self) -> None:
        rollback_task = asyncio.create_task(self._session.rollback())
        await asyncio.shield(rollback_task)

    async def _rollback_files(self) -> None:
        rollback_task = asyncio.create_task(self.file_journal.rollback())
        await asyncio.shield(rollback_task)

    def _deactivate(self, *, safe_only: bool = True) -> None:
        if self._token is None:
            return
        if safe_only:
            if self._deactivated:
                return
            try:
                _ACTIVE_UNIT_OF_WORK.reset(self._token)
            except ValueError:
                logger.debug(
                    "workspace collaboration unit of work already inactive",
                    extra={"workspace_transaction_id": self._transaction_id},
                )
                self._deactivated = True
                self._token = None
                return
            self._deactivated = True
        else:
            _ACTIVE_UNIT_OF_WORK.reset(self._token)
        self._token = None


def current_workspace_collaboration_unit_of_work() -> WorkspaceCollaborationUnitOfWork | None:
    return _ACTIVE_UNIT_OF_WORK.get()


def defer_workspace_collaboration_post_commit(callback: _PostCommitCallback) -> bool:
    unit_of_work = current_workspace_collaboration_unit_of_work()
    if unit_of_work is None:
        return False
    unit_of_work.defer_post_commit(callback)
    return True


def journal_workspace_file_mutation(record: _FileJournalEntry) -> bool:
    unit_of_work = current_workspace_collaboration_unit_of_work()
    if unit_of_work is None:
        return False
    unit_of_work.defer_file_journal(record)
    return True
