"""Transactional legacy admission and exact-identity terminal acknowledgements."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.cron.legacy_admission import (
    LegacyCronAdmissionIdentity,
    LegacyCronExecutionTicket,
)
from src.infrastructure.adapters.secondary.persistence.legacy_cron_admission_model import (
    LegacyCronAdmissionModel,
)
from src.infrastructure.adapters.secondary.persistence.models import CronSchedulerOwnerModel
from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_run_projection import (
    SqlLegacyCronRunProjection,
)


class SqlLegacyCronAdmissionRepository:
    """The caller commits admission before dispatch and terminal only after execution."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def admit(
        self,
        *,
        tenant_id: str,
        project_id: str,
        job_id: str,
        run_id: str,
        message_id: str,
        conversation_id: str,
    ) -> LegacyCronAdmissionIdentity | None:
        _ = await self._session.execute(
            insert(CronSchedulerOwnerModel)
            .values(scope_id="global", owner_kind="python")
            .on_conflict_do_nothing(index_elements=["scope_id"])
        )
        owner = await self._session.scalar(
            select(CronSchedulerOwnerModel)
            .where(CronSchedulerOwnerModel.scope_id == "global")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if owner is None or owner.owner_kind != "python":
            return None
        identity = LegacyCronAdmissionIdentity(
            admission_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            job_id=job_id,
            run_id=run_id,
            message_id=message_id,
            conversation_id=conversation_id,
            owner_epoch=owner.owner_epoch,
            token=secrets.token_urlsafe(32),
        )
        self._session.add(
            LegacyCronAdmissionModel(
                id=identity.admission_id,
                scope_id="global",
                tenant_id=tenant_id,
                project_id=project_id,
                job_id=job_id,
                run_id=run_id,
                message_id=message_id,
                conversation_id=conversation_id,
                owner_epoch=owner.owner_epoch,
                token_hash=identity.token_hash,
                status="active",
                execution_phase="ready",
                admitted_at=datetime.now(UTC),
            )
        )
        await self._session.flush()
        return identity

    async def matches_active(self, identity: LegacyCronAdmissionIdentity) -> bool:
        row = await self._matched_row(identity)
        return row is not None and row.status == "active"

    async def claim_execution(
        self, identity: LegacyCronAdmissionIdentity, *, resume: bool = False
    ) -> LegacyCronExecutionTicket | None:
        row = await self._matched_row(identity, lock=True)
        expected_phase = "waiting" if resume else "ready"
        if row is None or row.status != "active" or row.execution_phase != expected_phase:
            return None
        if not await SqlLegacyCronRunProjection(self._session).progress(
            identity, waiting=False, initial=not resume
        ):
            return None
        nonce = secrets.token_hex(32)
        row.execution_phase = "running"
        row.execution_nonce = nonce
        await self._session.flush()
        return LegacyCronExecutionTicket(admission=identity, nonce=nonce)

    async def park_for_hitl(self, ticket: LegacyCronExecutionTicket) -> bool:
        row = await self._matched_row(ticket.admission, lock=True)
        if (
            row is None
            or row.status != "active"
            or row.execution_phase != "running"
            or row.execution_nonce != ticket.nonce
        ):
            return False
        if not await SqlLegacyCronRunProjection(self._session).progress(
            ticket.admission, waiting=True
        ):
            return False
        row.execution_phase = "waiting"
        row.execution_nonce = None
        await self._session.flush()
        return True

    async def project_hitl(
        self, ticket: LegacyCronExecutionTicket, request_id: str, *, waiting: bool
    ) -> bool:
        """A live Future wait retains its nonce and cannot authorize another execution."""
        if not request_id:
            return False
        row = await self._matched_row(ticket.admission, lock=True)
        if (
            row is None
            or row.status != "active"
            or row.execution_phase != "running"
            or row.execution_nonce != ticket.nonce
        ):
            return False
        if not await SqlLegacyCronRunProjection(self._session).hitl(
            ticket.admission, request_id, waiting=waiting
        ):
            return False
        await self._session.flush()
        return True

    async def complete(self, ticket: LegacyCronExecutionTicket, outcome: str) -> bool:
        if outcome not in {"success", "failed"}:
            return False
        row = await self._matched_row(ticket.admission, lock=True)
        if row is None or row.execution_nonce != ticket.nonce:
            return False
        if row.status != "active":
            return row.status == outcome and row.execution_phase == "terminal"
        if row.execution_phase != "running":
            return False
        terminal_at = await SqlLegacyCronRunProjection(self._session).terminal(
            ticket.admission, outcome
        )
        if terminal_at is None:
            return False
        row.status = outcome
        row.execution_phase = "terminal"
        row.terminal_at = terminal_at
        await self._session.flush()
        return True

    async def _matched_row(
        self, identity: LegacyCronAdmissionIdentity, *, lock: bool = False
    ) -> LegacyCronAdmissionModel | None:
        stmt = (
            select(LegacyCronAdmissionModel)
            .where(
                LegacyCronAdmissionModel.id == identity.admission_id,
                LegacyCronAdmissionModel.scope_id == "global",
                LegacyCronAdmissionModel.tenant_id == identity.tenant_id,
                LegacyCronAdmissionModel.project_id == identity.project_id,
                LegacyCronAdmissionModel.job_id == identity.job_id,
                LegacyCronAdmissionModel.run_id == identity.run_id,
                LegacyCronAdmissionModel.message_id == identity.message_id,
                LegacyCronAdmissionModel.conversation_id == identity.conversation_id,
                LegacyCronAdmissionModel.owner_epoch == identity.owner_epoch,
                LegacyCronAdmissionModel.token_hash == identity.token_hash,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            stmt = stmt.with_for_update()
        row: LegacyCronAdmissionModel | None = await self._session.scalar(stmt)
        return row
