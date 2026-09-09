"""Persist deployment preparation and observations without claiming unverified drain."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.cron.cutover import (
    CRON_RUN_TERMINAL_OUTCOMES,
    CronCutoverDrainDirection,
    CronCutoverPhase,
    CronCutoverSnapshot,
    CronDeploymentManifest,
    CronDeploymentObservation,
    CronDeploymentParticipant,
    CronDeploymentParticipantKind,
    CronDeploymentReceipt,
    CronReverseDrainCompletion,
    CronReverseDrainObservation,
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
    CronOperationModel,
    CronSchedulerOwnerModel,
    HITLRequest,
)

_VERIFIER_UNAVAILABLE = "deployment_verifier_unavailable"
_REVERSE_PROTOCOL = "cron-reverse-drain.v1"
_REVERSE_UNOBSERVED = "reverse_drain_unobserved"
# Mid-flight execution facts that must settle before Python may re-admit. Queued,
# interrupted, waiting and retryable work is durable and resumable; it is recorded
# in the drain observation but never blocks rollback completion.
_REVERSE_BLOCKING_COUNTS = (
    "active_rust_owner_lease",
    "live_processing_operations",
    "live_running_runs",
)


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

    async def prepare_reverse(self, expected_revision: int) -> CronCutoverSnapshot:
        """Close Rust admission for a verified delegate and open the reverse drain.

        The phase leaves `verified`, so every Rust admission/renewal/acquisition
        predicate fails closed in the same transaction. The exact lease release CAS
        does not check the phase, so the fenced owner can still release its lease.
        Python admission stays closed because `owner_kind` remains `rust`.
        """
        row = await self._locked_row(expected_revision)
        evidence, manifest = self._verified_rust_evidence(row)
        evidence["reverse"] = {
            "protocol": _REVERSE_PROTOCOL,
            "deployment_id": manifest.deployment_id,
            "source_owner_kind": "rust",
            "target_owner_kind": "python",
            "prepared_at": await self._database_time(),
            "observations_recorded": 0,
            "observation": None,
            "blockers": [_REVERSE_UNOBSERVED],
        }
        row.cutover_evidence = evidence
        row.cutover_phase = CronCutoverPhase.PREPARED
        row.cutover_revision += 1
        await self._session.flush()
        return self._snapshot(row)

    async def observe_reverse(self, expected_revision: int) -> CronCutoverSnapshot:
        """Record a durable reverse-drain observation; never completes the drain."""
        row = await self._locked_row(expected_revision)
        evidence, reverse = self._reverse_evidence(row)
        observation = await self._observe_reverse_database(reverse["prepared_at"])
        reverse["observation"] = observation.to_wire()
        reverse["observations_recorded"] = cast(int, reverse["observations_recorded"]) + 1
        reverse["blockers"] = self._reverse_blockers(observation)
        evidence["reverse"] = reverse
        row.cutover_evidence = evidence
        row.cutover_phase = CronCutoverPhase.BLOCKED
        row.cutover_revision += 1
        await self._session.flush()
        return self._snapshot(row)

    async def complete_reverse(self, expected_revision: int) -> CronCutoverSnapshot:
        """Re-admit Python only after a recorded, still-settled reverse drain.

        Re-checks the live blocking counts inside the completion transaction, so a
        stale recorded observation cannot authorize rollback. History, receipts and
        the verification evidence are preserved; the revision keeps increasing, so
        the migration downgrade guard still refuses to drop the barrier afterwards.
        """
        row = await self._locked_row(expected_revision)
        evidence, reverse = self._reverse_evidence(row)
        if cast(int, reverse["observations_recorded"]) < 1:
            raise CronCutoverConflictError("reverse drain was never observed")
        current = await self._observe_reverse_database(reverse["prepared_at"])
        if self._reverse_blockers(current):
            raise CronCutoverConflictError("reverse drain has not settled")
        reverse["completion"] = CronReverseDrainCompletion(
            completed_at=await self._database_time(),
            final_observation=current,
        ).to_wire()
        reverse["blockers"] = []
        evidence["reverse"] = reverse
        # Transient forward-direction diagnostics no longer apply to the rolled-back
        # posture; the durable manifest, receipts, verification and reverse record stay.
        evidence["blockers"] = []
        row.cutover_evidence = evidence
        row.owner_kind = "python"
        row.cutover_phase = CronCutoverPhase.UNVERIFIED
        row.cutover_revision += 1
        await self._session.flush()
        return self._snapshot(row)

    @staticmethod
    def _reverse_blockers(observation: CronReverseDrainObservation) -> list[str]:
        counts = dict(observation.counts)
        return [name for name in _REVERSE_BLOCKING_COUNTS if counts.get(name, 0) > 0]

    @staticmethod
    def _verified_rust_evidence(
        row: CronSchedulerOwnerModel,
    ) -> tuple[dict[str, object], CronDeploymentManifest]:
        """Structurally mirror the unified verified-cutover admission predicate."""
        if (
            row.owner_kind != "rust"
            or row.cutover_phase != CronCutoverPhase.VERIFIED
            or row.cutover_revision < 1
        ):
            raise CronCutoverConflictError("scheduler owner is not a verified Rust delegate")
        evidence: dict[str, object] = dict(row.cutover_evidence)
        if evidence.get("protocol") != "cron-cutover-evidence.v1":
            raise CronCutoverConflictError("scheduler cutover evidence protocol is unavailable")
        manifest = CronDeploymentManifest.from_wire(evidence.get("manifest"))
        verification = evidence.get("verification")
        if not isinstance(verification, Mapping):
            raise CronCutoverConflictError("scheduler deployment verification is unavailable")
        record = cast(Mapping[object, object], verification)
        if record.get("protocol") != "cron-deployment-verification.v1":
            raise CronCutoverConflictError("scheduler deployment verification is unavailable")
        revision = record.get("cutover_revision")
        receipt_id = record.get("receipt_id")
        verifier_id = record.get("verifier_id")
        digests = (record.get("inventory_sha256"), record.get("evidence_sha256"))
        if (
            type(revision) is not int
            or revision != row.cutover_revision
            or record.get("deployment_id") != manifest.deployment_id
            or not isinstance(receipt_id, str)
            or not receipt_id
            or not isinstance(verifier_id, str)
            or not verifier_id
            or any(
                not isinstance(digest, str)
                or len(digest) != 64
                or not set(digest).issubset("0123456789abcdef")
                for digest in digests
            )
        ):
            raise CronCutoverConflictError("scheduler deployment verification is unavailable")
        return evidence, manifest

    @staticmethod
    def _reverse_evidence(
        row: CronSchedulerOwnerModel,
    ) -> tuple[dict[str, object], dict[str, object]]:
        if row.owner_kind != "rust" or row.cutover_phase not in {
            CronCutoverPhase.PREPARED,
            CronCutoverPhase.BLOCKED,
        }:
            raise CronCutoverConflictError("scheduler cutover is not reverse-draining")
        evidence: dict[str, object] = dict(row.cutover_evidence)
        raw = evidence.get("reverse")
        if not isinstance(raw, Mapping):
            raise CronCutoverConflictError("scheduler reverse drain evidence is unavailable")
        reverse: dict[str, object] = dict(cast(Mapping[str, object], raw))
        prepared_at = reverse.get("prepared_at")
        recorded = reverse.get("observations_recorded")
        if (
            reverse.get("protocol") != _REVERSE_PROTOCOL
            or not isinstance(prepared_at, str)
            or type(recorded) is not int
            or recorded < 0
            or "completion" in reverse
        ):
            raise CronCutoverConflictError("scheduler reverse drain evidence is unavailable")
        observation = reverse.get("observation")
        if observation is not None:
            _ = CronReverseDrainObservation.from_wire(observation)
        return evidence, reverse

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
        raw_reverse = evidence.get("reverse")
        if (
            row.owner_kind == "rust"
            and CronCutoverPhase(row.cutover_phase)
            in {CronCutoverPhase.PREPARED, CronCutoverPhase.BLOCKED}
            and isinstance(raw_reverse, Mapping)
            and cast(Mapping[object, object], raw_reverse).get("protocol") == _REVERSE_PROTOCOL
        ):
            return cls._reverse_snapshot(row, evidence, cast(Mapping[str, object], raw_reverse))
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
        phase = CronCutoverPhase(row.cutover_phase)
        direction = None
        if row.owner_kind == "draining" and phase in {
            CronCutoverPhase.PREPARED,
            CronCutoverPhase.BLOCKED,
        }:
            direction = CronCutoverDrainDirection.FORWARD
        return CronCutoverSnapshot(
            phase=phase,
            revision=row.cutover_revision,
            owner_kind=row.owner_kind,
            deployment_id=deployment_id,
            blockers=tuple(blocker_codes),
            observed_counts=tuple(cls._counts(evidence).items()),
            receipts_recorded=len(cast(list[object], receipts)),
            observed_at=observed_at,
            drain_direction=direction,
        )

    @classmethod
    def _reverse_snapshot(
        cls,
        row: CronSchedulerOwnerModel,
        evidence: Mapping[str, object],
        reverse: Mapping[str, object],
    ) -> CronCutoverSnapshot:
        raw_manifest = evidence.get("manifest")
        deployment_id = None
        if raw_manifest is not None:
            deployment_id = CronDeploymentManifest.from_wire(raw_manifest).deployment_id
        receipts = evidence.get("receipts", [])
        if not isinstance(receipts, list):
            raise CronCutoverConflictError("scheduler cutover evidence is invalid")
        raw_blockers = reverse.get("blockers", [_REVERSE_UNOBSERVED])
        if not isinstance(raw_blockers, list):
            raise CronCutoverConflictError("scheduler reverse drain blockers are invalid")
        blockers: list[str] = []
        for item in cast(list[object], raw_blockers):
            if not isinstance(item, str):
                raise CronCutoverConflictError("scheduler reverse drain blocker is invalid")
            blockers.append(item)
        counts: tuple[tuple[str, int], ...] = ()
        outcomes: tuple[tuple[str, int], ...] = ()
        last_run_ids: tuple[str, ...] = ()
        observed_at: str | None = None
        raw_observation = reverse.get("observation")
        if raw_observation is not None:
            observation = CronReverseDrainObservation.from_wire(raw_observation)
            counts = observation.counts
            outcomes = observation.terminal_outcomes
            last_run_ids = observation.last_run_ids
            observed_at = observation.observed_at
        return CronCutoverSnapshot(
            phase=CronCutoverPhase(row.cutover_phase),
            revision=row.cutover_revision,
            owner_kind=row.owner_kind,
            deployment_id=deployment_id,
            blockers=tuple(blockers),
            observed_counts=counts,
            receipts_recorded=len(cast(list[object], receipts)),
            observed_at=observed_at,
            drain_direction=CronCutoverDrainDirection.REVERSE,
            terminal_outcomes=outcomes,
            last_run_ids=last_run_ids,
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

    async def _observe_reverse_database(self, prepared_at: object) -> CronReverseDrainObservation:
        """Scan the global scope for Rust-side work, conservatively.

        Open-state scans cover every cron run and operation regardless of origin:
        work that cannot be safely correlated must not disappear from the drain
        record. `live_*` counts are mid-flight execution with an unexpired lease;
        everything else durable is resumable remainder, recorded for the operator.
        Terminal outcomes and last run ids cover runs settled since reverse
        preparation began — that is what actually drained.
        """
        if not isinstance(prepared_at, str):
            raise CronCutoverConflictError("scheduler reverse drain preparation time is invalid")
        try:
            since = datetime.fromisoformat(prepared_at)
        except ValueError:
            raise CronCutoverConflictError(
                "scheduler reverse drain preparation time is invalid"
            ) from None
        now = func.clock_timestamp()
        queries = {
            "active_rust_owner_lease": select(func.count())
            .select_from(CronSchedulerOwnerModel)
            .where(
                CronSchedulerOwnerModel.scope_id == "global",
                CronSchedulerOwnerModel.owner_kind == "rust",
                CronSchedulerOwnerModel.lease_token.is_not(None),
                CronSchedulerOwnerModel.lease_expires_at > now,
            ),
            "live_running_runs": select(func.count())
            .select_from(CronJobRunModel)
            .where(
                CronJobRunModel.status == "running",
                CronJobRunModel.runtime_lease_expires_at > now,
            ),
            "live_processing_operations": select(func.count())
            .select_from(CronOperationModel)
            .where(
                CronOperationModel.status == "processing",
                CronOperationModel.lease_expires_at > now,
            ),
            "queued_runs": select(func.count())
            .select_from(CronJobRunModel)
            .where(CronJobRunModel.status == "queued"),
            "interrupted_runs": select(func.count())
            .select_from(CronJobRunModel)
            .where(
                CronJobRunModel.status == "running",
                (CronJobRunModel.runtime_lease_expires_at.is_(None))
                | (CronJobRunModel.runtime_lease_expires_at <= now),
            ),
            "waiting_human_runs": select(func.count())
            .select_from(CronJobRunModel)
            .where(CronJobRunModel.status == "waiting_human"),
            "retryable_operations": select(func.count())
            .select_from(CronOperationModel)
            .where(
                (CronOperationModel.status.in_(("pending", "failed")))
                | (
                    (CronOperationModel.status == "processing")
                    & (
                        (CronOperationModel.lease_expires_at.is_(None))
                        | (CronOperationModel.lease_expires_at <= now)
                    )
                )
            ),
            "waiting_runtime_operations": select(func.count())
            .select_from(CronOperationModel)
            .where(CronOperationModel.status == "waiting_runtime"),
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
        drained = (
            select(CronJobRunModel.status, func.count())
            .where(
                CronJobRunModel.finished_at.is_not(None),
                CronJobRunModel.finished_at >= since,
                CronJobRunModel.status.in_(sorted(CRON_RUN_TERMINAL_OUTCOMES)),
            )
            .group_by(CronJobRunModel.status)
        )
        outcomes = {
            status: count
            for status, count in (await self._session.execute(refresh_select_statement(drained)))
        }
        last = await self._session.execute(
            refresh_select_statement(
                select(CronJobRunModel.id)
                .where(
                    CronJobRunModel.finished_at.is_not(None),
                    CronJobRunModel.finished_at >= since,
                    CronJobRunModel.status.in_(sorted(CRON_RUN_TERMINAL_OUTCOMES)),
                )
                .order_by(CronJobRunModel.finished_at.desc(), CronJobRunModel.id.desc())
                .limit(50)
            )
        )
        return CronReverseDrainObservation.from_wire(
            {
                "protocol": "cron-reverse-drain-observation.v1",
                "counts": counts,
                "terminal_outcomes": outcomes,
                "last_run_ids": list(last.scalars()),
                "observed_at": await self._database_time(),
            }
        )

    async def _database_time(self) -> str:
        value: datetime = (
            await self._session.execute(refresh_select_statement(select(func.clock_timestamp())))
        ).scalar_one()
        return value.isoformat()
