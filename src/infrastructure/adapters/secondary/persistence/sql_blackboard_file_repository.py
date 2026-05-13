"""SQLAlchemy repository for blackboard files."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.blackboard_file import BlackboardFile
from src.domain.ports.repositories.workspace.blackboard_file_repository import (
    BlackboardFileRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import BlackboardFileModel


class SqlBlackboardFileRepository(
    BaseRepository[BlackboardFile, BlackboardFileModel], BlackboardFileRepository
):
    """SQLAlchemy implementation of BlackboardFileRepository."""

    _model_class = BlackboardFileModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_workspace(
        self,
        workspace_id: str,
        parent_path: str = "/",
    ) -> list[BlackboardFile]:
        query = (
            select(BlackboardFileModel)
            .where(
                BlackboardFileModel.workspace_id == workspace_id,
                BlackboardFileModel.parent_path == parent_path,
            )
            .order_by(
                BlackboardFileModel.is_directory.desc(),
                BlackboardFileModel.name.asc(),
            )
        )
        result = await self._session.execute(refresh_select_statement(self._refresh_statement(query)))
        rows = result.scalars().all()
        return [f for row in rows if (f := self._to_domain(row)) is not None]

    async def find_descendants(
        self,
        workspace_id: str,
        path_prefix: str,
    ) -> list[BlackboardFile]:
        """Return every file whose ``parent_path`` starts with ``path_prefix``.

        ``path_prefix`` is expected to end with ``/`` (matches our canonical
        directory representation), so a directory at ``/docs/`` matches descendants
        with ``parent_path`` like ``/docs/`` and ``/docs/sub/``.
        """
        like_pattern = f"{path_prefix}%"
        query = (
            select(BlackboardFileModel)
            .where(
                BlackboardFileModel.workspace_id == workspace_id,
                BlackboardFileModel.parent_path.like(like_pattern),
            )
            .order_by(
                BlackboardFileModel.parent_path.asc(),
                BlackboardFileModel.is_directory.desc(),
                BlackboardFileModel.name.asc(),
            )
        )
        result = await self._session.execute(refresh_select_statement(self._refresh_statement(query)))
        rows = result.scalars().all()
        return [f for row in rows if (f := self._to_domain(row)) is not None]

    async def bulk_update_parent_path(
        self,
        workspace_id: str,
        old_prefix: str,
        new_prefix: str,
    ) -> int:
        """Rewrite ``parent_path`` of every descendant in a single SQL UPDATE.

        Uses string substitution at SQL level: rows where ``parent_path``
        equals ``old_prefix`` or starts with ``old_prefix`` get rewritten to
        the corresponding ``new_prefix`` form.
        """
        # Exact-match rows (parent_path == old_prefix) get the new prefix outright.
        # Deeper rows whose parent_path is like "old_prefix%" need substring
        # replacement of the prefix.
        from sqlalchemy import case, func, literal, or_

        old_len = len(old_prefix)
        stmt = (
            update(BlackboardFileModel)
            .where(
                BlackboardFileModel.workspace_id == workspace_id,
                or_(
                    BlackboardFileModel.parent_path == old_prefix,
                    BlackboardFileModel.parent_path.like(f"{old_prefix}%"),
                ),
            )
            .values(
                parent_path=case(
                    (BlackboardFileModel.parent_path == old_prefix, literal(new_prefix)),
                    else_=func.concat(
                        literal(new_prefix),
                        func.substr(BlackboardFileModel.parent_path, old_len + 1),
                    ),
                )
            )
        )
        result = await self._session.execute(stmt)
        cursor_result = cast(CursorResult[Any], result)
        return int(cursor_result.rowcount or 0)

    async def update_checksum(
        self,
        file_id: str,
        checksum_sha256: str,
    ) -> None:
        """Idempotent set: only writes when checksum is currently NULL."""
        stmt = (
            update(BlackboardFileModel)
            .where(
                BlackboardFileModel.id == file_id,
                BlackboardFileModel.checksum_sha256.is_(None),
            )
            .values(checksum_sha256=checksum_sha256)
        )
        await self._session.execute(stmt)

    def _to_domain(self, db_model: BlackboardFileModel | None) -> BlackboardFile | None:
        if db_model is None:
            return None
        return BlackboardFile(
            id=db_model.id,
            workspace_id=db_model.workspace_id,
            parent_path=db_model.parent_path,
            name=db_model.name,
            is_directory=db_model.is_directory,
            file_size=db_model.file_size,
            content_type=db_model.content_type,
            storage_key=db_model.storage_key,
            uploader_type=db_model.uploader_type,
            uploader_id=db_model.uploader_id,
            uploader_name=db_model.uploader_name,
            checksum_sha256=db_model.checksum_sha256,
            mime_type_detected=db_model.mime_type_detected,
            created_at=db_model.created_at,
        )

    def _to_db(self, domain_entity: BlackboardFile) -> BlackboardFileModel:
        return BlackboardFileModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            parent_path=domain_entity.parent_path,
            name=domain_entity.name,
            is_directory=domain_entity.is_directory,
            file_size=domain_entity.file_size,
            content_type=domain_entity.content_type,
            storage_key=domain_entity.storage_key,
            uploader_type=domain_entity.uploader_type,
            uploader_id=domain_entity.uploader_id,
            uploader_name=domain_entity.uploader_name,
            checksum_sha256=domain_entity.checksum_sha256,
            mime_type_detected=domain_entity.mime_type_detected,
            created_at=domain_entity.created_at,
        )
