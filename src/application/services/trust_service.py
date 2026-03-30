"""Application service for Trust System operations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.domain.model.trust.decision_record import DecisionRecord
from src.domain.model.trust.trust_policy import TrustPolicy
from src.domain.ports.repositories.decision_record_repository import (
    DecisionRecordRepository,
)
from src.domain.ports.repositories.trust_policy_repository import (
    TrustPolicyRepository,
)

logger = logging.getLogger(__name__)


class TrustService:
    """Service for managing trust policies and approval decisions."""

    def __init__(
        self,
        policy_repo: TrustPolicyRepository,
        record_repo: DecisionRecordRepository,
    ) -> None:
        self._policy_repo = policy_repo
        self._record_repo = record_repo

    async def list_policies(
        self,
        workspace_id: str,
        *,
        agent_instance_id: str | None = None,
    ) -> list[TrustPolicy]:
        return await self._policy_repo.find_by_workspace(
            workspace_id, agent_instance_id=agent_instance_id
        )

    async def create_policy(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        agent_instance_id: str,
        action_type: str,
        granted_by: str,
        grant_type: str,
    ) -> TrustPolicy:
        policy = TrustPolicy(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_instance_id=agent_instance_id,
            action_type=action_type,
            granted_by=granted_by,
            grant_type=grant_type,
        )
        saved = await self._policy_repo.save(policy)
        logger.info("Created trust policy %s for agent %s", saved.id, agent_instance_id)
        return saved

    async def check_trust(
        self,
        workspace_id: str,
        agent_instance_id: str,
        action_type: str,
    ) -> bool:
        return await self._policy_repo.check_always_trust(
            workspace_id, agent_instance_id, action_type
        )

    async def submit_approval(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        agent_instance_id: str,
        action_type: str,
        proposal: dict[str, object],
        context_summary: str | None = None,
    ) -> DecisionRecord:
        record = DecisionRecord(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_instance_id=agent_instance_id,
            decision_type=action_type,
            proposal=proposal,
            context_summary=context_summary,
            outcome="pending",
        )
        saved = await self._record_repo.save(record)
        logger.info("Submitted approval request %s", saved.id)
        return saved

    async def resolve_approval(
        self,
        record_id: str,
        *,
        reviewer_id: str,
        decision: str,
    ) -> DecisionRecord:
        record = await self._record_repo.find_by_id(record_id)
        if record is None:
            msg = f"Decision record not found: {record_id}"
            raise ValueError(msg)

        now = datetime.now(UTC)

        if decision == "allow_once":
            record.outcome = "success"
            record.review_comment = "Allowed once"
        elif decision == "allow_always":
            record.outcome = "success"
            record.review_comment = "Allowed always — trust policy created"
            await self._policy_repo.save(
                TrustPolicy(
                    tenant_id=record.tenant_id,
                    workspace_id=record.workspace_id,
                    agent_instance_id=record.agent_instance_id,
                    action_type=record.decision_type,
                    granted_by=reviewer_id,
                    grant_type="always",
                )
            )
        elif decision == "deny":
            record.outcome = "rejected"
            record.review_comment = "Denied by reviewer"
        else:
            msg = f"Invalid decision: {decision}"
            raise ValueError(msg)

        record.reviewer_id = reviewer_id
        record.review_type = "human"
        record.resolved_at = now
        record.updated_at = now

        await self._record_repo.update(record)
        logger.info("Resolved approval %s with decision=%s", record_id, decision)
        return record

    async def list_decision_records(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        decision_type: str | None = None,
    ) -> list[DecisionRecord]:
        return await self._record_repo.find_by_workspace(
            workspace_id, agent_id=agent_id, decision_type=decision_type
        )

    async def get_decision_record(
        self,
        record_id: str,
    ) -> DecisionRecord | None:
        return await self._record_repo.find_by_id(record_id)
