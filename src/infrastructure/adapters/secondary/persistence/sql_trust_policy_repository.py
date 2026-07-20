"""SQLAlchemy repository for trust policy persistence."""

from __future__ import annotations

from datetime import datetime
from typing import override

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.trust.trust_policy import TrustPolicy
from src.domain.ports.repositories.trust_policy_repository import (
    TrustPolicyRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    TrustPolicyModel,
)


class SqlTrustPolicyRepository(TrustPolicyRepository):
    """Standalone repository -- not extending BaseRepository."""

    def __init__(self, db: AsyncSession) -> None:
        self._session = db

    @override
    async def save(self, policy: TrustPolicy) -> TrustPolicy:
        db_model = self._to_db(policy)
        self._session.add(db_model)
        await self._session.flush()
        return policy

    @override
    async def find_by_workspace(
        self,
        workspace_id: str,
        *,
        agent_instance_id: str | None = None,
    ) -> list[TrustPolicy]:
        stmt = select(TrustPolicyModel).where(
            TrustPolicyModel.workspace_id == workspace_id,
            TrustPolicyModel.deleted_at.is_(None),
        )
        if agent_instance_id is not None:
            stmt = stmt.where(TrustPolicyModel.agent_instance_id == agent_instance_id)
        stmt = stmt.order_by(TrustPolicyModel.created_at.desc())
        result = await self._session.execute(refresh_select_statement(stmt))
        return [self._to_domain(row) for row in result.scalars().all()]

    @override
    async def check_always_trust(
        self,
        workspace_id: str,
        agent_instance_id: str,
        action_type: str,
    ) -> bool:
        stmt = select(TrustPolicyModel).where(
            TrustPolicyModel.workspace_id == workspace_id,
            or_(
                (
                    (TrustPolicyModel.scope == "workspace_tool")
                    & (TrustPolicyModel.canonical_tool_name == action_type)
                ),
                (
                    (TrustPolicyModel.agent_instance_id == agent_instance_id)
                    & (TrustPolicyModel.action_type == action_type)
                ),
            ),
            TrustPolicyModel.grant_type == "always",
            TrustPolicyModel.revoked_at.is_(None),
            TrustPolicyModel.deleted_at.is_(None),
        )
        result = await self._session.execute(refresh_select_statement(stmt))
        return result.scalars().first() is not None

    @override
    async def revoke(
        self,
        policy_id: str,
        *,
        revoked_by: str,
        revoked_at: datetime,
    ) -> TrustPolicy | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(TrustPolicyModel).where(
                    TrustPolicyModel.id == policy_id,
                    TrustPolicyModel.deleted_at.is_(None),
                    TrustPolicyModel.revoked_at.is_(None),
                )
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.revoked_by = revoked_by
        row.revoked_at = revoked_at
        row.deleted_at = revoked_at
        row.revision += 1
        await self._session.flush()
        return self._to_domain(row)

    @staticmethod
    def _to_domain(row: TrustPolicyModel) -> TrustPolicy:
        return TrustPolicy(
            id=row.id,
            tenant_id=row.tenant_id,
            workspace_id=row.workspace_id,
            agent_instance_id=row.agent_instance_id,
            action_type=row.action_type,
            granted_by=row.granted_by,
            grant_type=row.grant_type,
            scope=row.scope,
            canonical_tool_name=row.canonical_tool_name,
            source_hitl_request_id=row.source_hitl_request_id,
            revision=row.revision,
            revoked_by=row.revoked_by,
            revoked_at=row.revoked_at,
            created_at=row.created_at,
            deleted_at=row.deleted_at,
        )

    @staticmethod
    def _to_db(policy: TrustPolicy) -> TrustPolicyModel:
        return TrustPolicyModel(
            id=policy.id,
            tenant_id=policy.tenant_id,
            workspace_id=policy.workspace_id,
            agent_instance_id=policy.agent_instance_id,
            action_type=policy.action_type,
            granted_by=policy.granted_by,
            grant_type=policy.grant_type,
            scope=policy.scope,
            canonical_tool_name=policy.canonical_tool_name,
            source_hitl_request_id=policy.source_hitl_request_id,
            revision=policy.revision,
            revoked_by=policy.revoked_by,
            revoked_at=policy.revoked_at,
            created_at=policy.created_at,
            deleted_at=policy.deleted_at,
        )
