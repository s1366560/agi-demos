"""SQL persistence for Workspace Collaboration revision and idempotency authority."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.dml import Insert

from src.application.services.workspace_collaboration_authority import (
    WorkspaceCollaborationActor,
    WorkspaceCollaborationAuthorityCorruptError,
    WorkspaceCollaborationIdempotencyConflictError,
    WorkspaceCollaborationMutationCommand,
    WorkspaceCollaborationMutationReceipt,
    WorkspaceCollaborationRevisionConflictError,
    WorkspaceCollaborationTargetNotFoundError,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspaceCollaborationAuthorityModel,
    WorkspaceCollaborationMutationReceiptModel,
    WorkspaceModel,
)


class SqlWorkspaceCollaborationAuthorityRepository:
    """Serialize commands on the workspace row in the caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def current_revision(self, *, actor: WorkspaceCollaborationActor) -> int:
        await self._require_workspace(actor=actor, lock=False)
        authority = await self._find_authority(actor=actor, lock=False)
        return 0 if authority is None else int(authority.revision)

    async def reserve(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
        request_hash: str,
    ) -> WorkspaceCollaborationMutationReceipt:
        await self._require_workspace(actor=actor, lock=True)
        existing = await self._find_receipt(actor=actor, command=command, lock=True)
        if existing is not None:
            self._validate_replay(
                existing,
                actor=actor,
                command=command,
                request_hash=request_hash,
            )
            return self._to_receipt(existing, duplicate=True, dispatch_required=False)

        authority = await self._ensure_authority(actor=actor)
        current_revision = int(authority.revision)
        if current_revision != command.expected_revision:
            raise WorkspaceCollaborationRevisionConflictError(
                expected_revision=command.expected_revision,
                current_revision=current_revision,
            )

        receipt = WorkspaceCollaborationMutationReceiptModel(
            id=str(uuid.uuid4()),
            tenant_id=actor.tenant_id,
            project_id=actor.project_id,
            workspace_id=actor.workspace_id,
            actor_user_id=actor.user_id,
            contract_version=command.contract_version,
            surface=command.surface,
            action=command.action,
            idempotency_key=command.idempotency_key,
            request_hash=request_hash,
            expected_revision=command.expected_revision,
            committed_revision=None,
            created_at=datetime.now(UTC),
            committed_at=None,
        )
        self._session.add(receipt)
        await self._session.flush()
        return self._to_receipt(receipt, duplicate=False, dispatch_required=True)

    async def finalize(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
        request_hash: str,
        duplicate: bool,
    ) -> WorkspaceCollaborationMutationReceipt:
        await self._require_workspace(actor=actor, lock=True)
        receipt = await self._find_receipt(actor=actor, command=command, lock=True)
        if receipt is None:
            raise WorkspaceCollaborationAuthorityCorruptError(
                "Workspace Collaboration receipt disappeared before finalization"
            )
        self._validate_replay(
            receipt,
            actor=actor,
            command=command,
            request_hash=request_hash,
        )
        authority = await self._ensure_authority(actor=actor)

        current_revision = int(authority.revision)
        if current_revision < command.expected_revision:
            raise WorkspaceCollaborationAuthorityCorruptError(
                "Workspace Collaboration authority regressed below the reserved revision"
            )
        if receipt.committed_revision is None:
            if current_revision == command.expected_revision:
                current_revision += 1
                authority.revision = current_revision
            receipt.committed_revision = current_revision
            receipt.committed_at = datetime.now(UTC)
        elif int(receipt.committed_revision) > current_revision:
            raise WorkspaceCollaborationAuthorityCorruptError(
                "Workspace Collaboration receipt is newer than its authority"
            )
        await self._session.flush()
        return self._to_receipt(receipt, duplicate=duplicate, dispatch_required=False)

    async def _require_workspace(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        lock: bool,
    ) -> None:
        bind = self._session.get_bind()
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
        statement = self._workspace_select_statement(
            actor=actor,
            lock=lock,
            dialect_name=dialect_name,
        )
        workspace_id = (
            await self._session.execute(refresh_select_statement(statement))
        ).scalar_one_or_none()
        if workspace_id is None:
            raise WorkspaceCollaborationTargetNotFoundError(
                "Workspace does not exist in the mutation scope"
            )

    @staticmethod
    def _workspace_select_statement(
        *,
        actor: WorkspaceCollaborationActor,
        lock: bool,
        dialect_name: str,
    ) -> Select[tuple[str]]:
        statement = select(WorkspaceModel.id).where(
            WorkspaceModel.id == actor.workspace_id,
            WorkspaceModel.tenant_id == actor.tenant_id,
            WorkspaceModel.project_id == actor.project_id,
        )
        if lock:
            if dialect_name == "postgresql":
                return statement.with_for_update(key_share=True)
            return statement.with_for_update()
        return statement

    async def _find_authority(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        lock: bool,
    ) -> WorkspaceCollaborationAuthorityModel | None:
        statement = select(WorkspaceCollaborationAuthorityModel).where(
            WorkspaceCollaborationAuthorityModel.workspace_id == actor.workspace_id,
            WorkspaceCollaborationAuthorityModel.tenant_id == actor.tenant_id,
            WorkspaceCollaborationAuthorityModel.project_id == actor.project_id,
        )
        if lock:
            statement = statement.with_for_update()
        result = await self._session.execute(refresh_select_statement(statement))
        return result.scalar_one_or_none()

    async def _ensure_authority(
        self,
        *,
        actor: WorkspaceCollaborationActor,
    ) -> WorkspaceCollaborationAuthorityModel:
        bind = self._session.get_bind()
        dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
        await self._session.execute(
            self._authority_insert_statement(
                actor=actor,
                dialect_name=dialect_name,
            )
        )
        authority = await self._find_authority(actor=actor, lock=True)
        if authority is None:
            raise WorkspaceCollaborationAuthorityCorruptError(
                "Workspace Collaboration authority scope is inconsistent"
            )
        return authority

    @staticmethod
    def _authority_insert_statement(
        *,
        actor: WorkspaceCollaborationActor,
        dialect_name: str,
    ) -> Insert:
        values = {
            "workspace_id": actor.workspace_id,
            "tenant_id": actor.tenant_id,
            "project_id": actor.project_id,
            "revision": 0,
        }
        if dialect_name == "postgresql":
            return (
                postgresql_insert(WorkspaceCollaborationAuthorityModel)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["workspace_id"])
            )
        if dialect_name == "sqlite":
            return (
                sqlite_insert(WorkspaceCollaborationAuthorityModel)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["workspace_id"])
            )
        return insert(WorkspaceCollaborationAuthorityModel).values(**values)

    async def _find_receipt(
        self,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
        lock: bool,
    ) -> WorkspaceCollaborationMutationReceiptModel | None:
        statement = select(WorkspaceCollaborationMutationReceiptModel).where(
            WorkspaceCollaborationMutationReceiptModel.tenant_id == actor.tenant_id,
            WorkspaceCollaborationMutationReceiptModel.project_id == actor.project_id,
            WorkspaceCollaborationMutationReceiptModel.workspace_id == actor.workspace_id,
            WorkspaceCollaborationMutationReceiptModel.actor_user_id == actor.user_id,
            WorkspaceCollaborationMutationReceiptModel.idempotency_key == command.idempotency_key,
        )
        if lock:
            statement = statement.with_for_update()
        result = await self._session.execute(refresh_select_statement(statement))
        return result.scalar_one_or_none()

    @staticmethod
    def _validate_replay(
        receipt: WorkspaceCollaborationMutationReceiptModel,
        *,
        actor: WorkspaceCollaborationActor,
        command: WorkspaceCollaborationMutationCommand,
        request_hash: str,
    ) -> None:
        if (
            receipt.request_hash != request_hash
            or receipt.tenant_id != actor.tenant_id
            or receipt.project_id != actor.project_id
            or receipt.workspace_id != actor.workspace_id
            or receipt.actor_user_id != actor.user_id
            or receipt.contract_version != command.contract_version
            or receipt.surface != command.surface
            or receipt.action != command.action
            or int(receipt.expected_revision) != command.expected_revision
        ):
            raise WorkspaceCollaborationIdempotencyConflictError(
                "Idempotency key already belongs to a different Workspace mutation"
            )

    @staticmethod
    def _to_receipt(
        receipt: WorkspaceCollaborationMutationReceiptModel,
        *,
        duplicate: bool,
        dispatch_required: bool,
    ) -> WorkspaceCollaborationMutationReceipt:
        revision = None if receipt.committed_revision is None else int(receipt.committed_revision)
        return WorkspaceCollaborationMutationReceipt(
            receipt_id=receipt.id,
            workspace_id=receipt.workspace_id,
            surface=receipt.surface,
            action=receipt.action,
            expected_revision=int(receipt.expected_revision),
            revision=revision,
            duplicate=duplicate,
            dispatch_required=dispatch_required,
        )
