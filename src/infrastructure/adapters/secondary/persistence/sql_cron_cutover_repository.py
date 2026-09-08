"""Persist deployment preparation and observations without claiming unverified drain."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.cron.cutover import (
    CronCutoverPhase,
    CronCutoverSnapshot,
    CronDeploymentManifest,
    CronDeploymentObservation,
    CronDeploymentParticipant,
    CronDeploymentParticipantKind,
    CronDeploymentReceipt,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.legacy_cron_admission_model import (
    LegacyCronAdmissionModel,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    AgentSessionSnapshot,
    CronJobModel,
    CronJobRunModel,
    CronSchedulerOwnerModel,
    HITLRequest,
)

_VERIFIER_UNAVAILABLE = "deployment_verifier_unavailable"


class CronCutoverConflictError(ValueError):
    """The requested revision or deployment does not own this barrier."""


class SqlCronCutoverRepository:
    """Caller commits. No verification/activation method exists without a real verifier."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def read(self) -> CronCutoverSnapshot:
        row = await self._session.scalar(
            select(CronSchedulerOwnerModel)
            .where(CronSchedulerOwnerModel.scope_id == "global")
            .execution_options(populate_existing=True)
        )
        if row is None:
            return CronCutoverSnapshot(
                phase=CronCutoverPhase.UNVERIFIED,
                revision=0,
                owner_kind="uninitialized",
                deployment_id=None,
                blockers=(_VERIFIER_UNAVAILABLE,),
            )
        return self._snapshot(row)

    async def lock_registration_boundary(self) -> CronCutoverSnapshot:
        """Hold prepare's initialization/row lock until the caller commits.

        Inserting the default Python row also fences prepare on first startup,
        when SELECT FOR UPDATE alone could not lock an absent row.
        """
        _ = await self._session.execute(
            insert(CronSchedulerOwnerModel)
            .values(scope_id="global", owner_kind="python")
            .on_conflict_do_nothing(index_elements=["scope_id"])
        )
        row = await self._session.scalar(
            select(CronSchedulerOwnerModel)
            .where(CronSchedulerOwnerModel.scope_id == "global")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise CronCutoverConflictError("scheduler owner unavailable")
        return self._snapshot(row)

    async def require_prepared_deployment(
        self,
        *,
        deployment_id: str,
        source_generation: str,
        expected_revision: int,
        producer_id: str,
    ) -> CronDeploymentManifest:
        """Read the exact persisted boundary; never acquire, release or mutate it."""
        if type(expected_revision) is not int or expected_revision < 1:
            raise CronCutoverConflictError("invalid prepared deployment revision")
        row = await self._session.scalar(
            select(CronSchedulerOwnerModel)
            .where(CronSchedulerOwnerModel.scope_id == "global")
            .execution_options(populate_existing=True)
        )
        if row is None or row.cutover_revision != expected_revision:
            raise CronCutoverConflictError("scheduler cutover revision changed")
        _, manifest, _ = self._prepared_evidence(row)
        participant = CronDeploymentParticipant(
            kind=CronDeploymentParticipantKind.PRODUCER,
            participant_id=producer_id,
        )
        if (
            manifest.deployment_id != deployment_id
            or manifest.source_generation != source_generation
            or participant not in manifest.participants
        ):
            raise CronCutoverConflictError("local producer does not belong to prepared deployment")
        return manifest

    async def prepare(
        self, manifest: CronDeploymentManifest, expected_revision: int
    ) -> CronCutoverSnapshot:
        # Validate programmatic callers just as strictly as JSON callers.
        manifest = CronDeploymentManifest.from_wire(manifest.to_wire())
        _ = await self._session.execute(
            insert(CronSchedulerOwnerModel)
            .values(scope_id="global", owner_kind="python")
            .on_conflict_do_nothing(index_elements=["scope_id"])
        )
        row = await self._locked_row(expected_revision)
        if row.owner_kind not in {"python", "off"} or row.lease_token is not None:
            raise CronCutoverConflictError("scheduler owner cannot prepare a legacy cutover")
        if row.cutover_phase != CronCutoverPhase.UNVERIFIED:
            raise CronCutoverConflictError("scheduler cutover is already prepared")
        row.cutover_phase = CronCutoverPhase.PREPARED
        row.cutover_revision += 1
        row.cutover_evidence = {
            "protocol": "cron-cutover-evidence.v1",
            "manifest": manifest.to_wire(),
            "source_owner_kind": row.owner_kind,
            "prepared_at": await self._database_time(),
            "receipts": [],
            "observation": {},
            "blockers": [_VERIFIER_UNAVAILABLE, "participant_receipts_missing"],
        }
        # Existing execution capabilities retain their epoch and may settle or resume.
        row.owner_kind = "draining"
        await self._session.flush()
        return self._snapshot(row)

    async def record_receipt(
        self, receipt: CronDeploymentReceipt, expected_revision: int
    ) -> CronCutoverSnapshot:
        receipt = CronDeploymentReceipt.from_wire(receipt.to_wire())
        row = await self._locked_row(expected_revision)
        evidence, manifest, receipts = self._prepared_evidence(row)
        if (
            receipt.deployment_id != manifest.deployment_id
            or receipt.source_generation != manifest.source_generation
            or receipt.participant not in manifest.participants
        ):
            raise CronCutoverConflictError("receipt does not belong to the prepared deployment")
        existing = next((item for item in receipts if item.receipt_id == receipt.receipt_id), None)
        if existing is not None:
            if existing != receipt:
                raise CronCutoverConflictError("deployment receipt identity was reused")
            return self._snapshot(row)
        if len(receipts) >= 10000:
            raise CronCutoverConflictError("deployment receipt log capacity exceeded")
        receipts.append(receipt)
        evidence["receipts"] = [item.to_wire() for item in receipts]
        evidence["blockers"] = self._blockers(manifest, receipts, self._counts(evidence))
        row.cutover_evidence = evidence
        row.cutover_revision += 1
        await self._session.flush()
        return self._snapshot(row)

    async def observe(self, expected_revision: int) -> CronCutoverSnapshot:
        row = await self._locked_row(expected_revision)
        evidence, manifest, receipts = self._prepared_evidence(row)
        counts = await self._observe_database()
        evidence["observation"] = counts
        evidence["observed_at"] = await self._database_time()
        evidence["blockers"] = self._blockers(manifest, receipts, counts)
        row.cutover_evidence = evidence
        row.cutover_phase = CronCutoverPhase.BLOCKED
        row.cutover_revision += 1
        await self._session.flush()
        return self._snapshot(row)

    async def _locked_row(self, expected_revision: int) -> CronSchedulerOwnerModel:
        if type(expected_revision) is not int or expected_revision < 0:
            raise CronCutoverConflictError("invalid scheduler cutover revision")
        row = await self._session.scalar(
            select(CronSchedulerOwnerModel)
            .where(CronSchedulerOwnerModel.scope_id == "global")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.cutover_revision != expected_revision:
            raise CronCutoverConflictError("scheduler cutover revision changed")
        return row

    @staticmethod
    def _prepared_evidence(
        row: CronSchedulerOwnerModel,
    ) -> tuple[dict[str, object], CronDeploymentManifest, list[CronDeploymentReceipt]]:
        if row.owner_kind != "draining" or row.cutover_phase not in {
            CronCutoverPhase.PREPARED,
            CronCutoverPhase.BLOCKED,
        }:
            raise CronCutoverConflictError("scheduler cutover is not prepared")
        evidence: dict[str, object] = dict(row.cutover_evidence)
        if evidence.get("protocol") != "cron-cutover-evidence.v1":
            raise CronCutoverConflictError("scheduler cutover evidence protocol is unavailable")
        manifest = CronDeploymentManifest.from_wire(evidence.get("manifest"))
        raw = evidence.get("receipts")
        if not isinstance(raw, list):
            raise CronCutoverConflictError("scheduler deployment receipt log is invalid")
        return (
            evidence,
            manifest,
            [CronDeploymentReceipt.from_wire(item) for item in cast(list[object], raw)],
        )

    @staticmethod
    def _counts(evidence: Mapping[str, object]) -> dict[str, int]:
        observation = evidence.get("observation", {})
        if not isinstance(observation, dict):
            raise CronCutoverConflictError("scheduler cutover observation is invalid")
        counts: dict[str, int] = {}
        for name, count in cast(dict[object, object], observation).items():
            if not isinstance(name, str) or type(count) is not int or count < 0:
                raise CronCutoverConflictError("scheduler cutover observation count is invalid")
            counts[name] = count
        return counts

    @staticmethod
    def _blockers(
        manifest: CronDeploymentManifest,
        receipts: list[CronDeploymentReceipt],
        counts: Mapping[str, int],
    ) -> list[str]:
        # Roster membership and protocol facts do not establish roster completeness.
        # That requires the deployment verifier, which is deliberately unavailable here.
        blockers = [_VERIFIER_UNAVAILABLE]
        latest = {receipt.participant: receipt for receipt in receipts}
        if any(participant not in latest for participant in manifest.participants):
            blockers.append("participant_receipts_missing")
        if any(
            item.observation == CronDeploymentObservation.UNRESOLVED for item in latest.values()
        ):
            blockers.append("participant_unresolved")
        blockers.extend(name for name, count in counts.items() if count > 0)
        return blockers

    @classmethod
    def _snapshot(cls, row: CronSchedulerOwnerModel) -> CronCutoverSnapshot:
        evidence: dict[str, object] = dict(row.cutover_evidence or {})
        raw_manifest = evidence.get("manifest")
        deployment_id = None
        if raw_manifest is not None:
            deployment_id = CronDeploymentManifest.from_wire(raw_manifest).deployment_id
        receipts = evidence.get("receipts", [])
        blockers = evidence.get("blockers", [_VERIFIER_UNAVAILABLE])
        observed_at = evidence.get("observed_at")
        if observed_at is not None and not isinstance(observed_at, str):
            raise CronCutoverConflictError("scheduler cutover observation time is invalid")
        if not isinstance(receipts, list) or not isinstance(blockers, list):
            raise CronCutoverConflictError("scheduler cutover evidence is invalid")
        blocker_codes: list[str] = []
        for item in cast(list[object], blockers):
            if not isinstance(item, str):
                raise CronCutoverConflictError("scheduler cutover blocker is invalid")
            blocker_codes.append(item)
        return CronCutoverSnapshot(
            phase=CronCutoverPhase(row.cutover_phase),
            revision=row.cutover_revision,
            owner_kind=row.owner_kind,
            deployment_id=deployment_id,
            blockers=tuple(blocker_codes),
            observed_counts=tuple(cls._counts(evidence).items()),
            receipts_recorded=len(cast(list[object], receipts)),
            observed_at=observed_at,
        )

    async def _observe_database(self) -> dict[str, int]:
        # Scan the complete global deployment scope. An old execution without trusted
        # cron identity must not disappear merely because it cannot be correlated.
        queries = {
            "active_legacy_admissions": select(func.count())
            .select_from(LegacyCronAdmissionModel)
            .where(
                LegacyCronAdmissionModel.scope_id == "global",
                LegacyCronAdmissionModel.status == "active",
            ),
            "unattested_legacy_runs": select(func.count())
            .select_from(CronJobRunModel)
            .join(CronJobModel, CronJobModel.id == CronJobRunModel.job_id)
            .where(
                CronJobRunModel.runtime_execution_id.is_(None),
                ~select(LegacyCronAdmissionModel.id)
                .where(
                    LegacyCronAdmissionModel.run_id == CronJobRunModel.id,
                    LegacyCronAdmissionModel.job_id == CronJobRunModel.job_id,
                    LegacyCronAdmissionModel.project_id == CronJobRunModel.project_id,
                    LegacyCronAdmissionModel.tenant_id == CronJobModel.tenant_id,
                    LegacyCronAdmissionModel.conversation_id == CronJobRunModel.conversation_id,
                )
                .exists(),
            ),
            "unresolved_agent_runs": select(func.count())
            .select_from(AgentRunAuthorityModel)
            .where(AgentRunAuthorityModel.status.not_in(("completed", "failed", "cancelled"))),
            "unresolved_hitl_requests": select(func.count())
            .select_from(HITLRequest)
            .where(HITLRequest.status.in_(("pending", "answered"))),
            "retained_hitl_snapshots": select(func.count())
            .select_from(AgentSessionSnapshot)
            .where(AgentSessionSnapshot.snapshot_type == "hitl"),
        }
        counts: dict[str, int] = {}
        for name, statement in queries.items():
            result = await self._session.execute(refresh_select_statement(statement))
            counts[name] = result.scalar_one()
        return counts

    async def _database_time(self) -> str:
        value: datetime = (
            await self._session.execute(refresh_select_statement(select(func.clock_timestamp())))
        ).scalar_one()
        return value.isoformat()
