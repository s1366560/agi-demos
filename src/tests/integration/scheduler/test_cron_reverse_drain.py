"""Reverse drain (Rust to Python) never leaves two execution authorities.

The synthetic verifier stand-in below is permitted only inside the private
`qa_` test schemas; it exists because the real trusted verification writer is
deliberately not part of this repository batch.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from src.domain.model.cron.cutover import CronDeploymentManifest, CronDeploymentReceipt
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentSessionSnapshot,
    CronJobRunModel,
    CronOperationModel,
    CronSchedulerOwnerModel,
    HITLRequest,
)
from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
    CronCutoverConflictError,
    SqlCronCutoverRepository,
)
from src.tests.unit.domain.model.cron.test_cutover import manifest_wire, receipt_wire

pytestmark = pytest.mark.integration


async def simulate_trusted_verifier(session) -> int:
    """Private-schema stand-in for the future trusted verification writer."""
    schema = await session.scalar(text("SELECT current_schema()"))
    if not isinstance(schema, str) or not schema.startswith("qa_"):
        raise AssertionError("synthetic verification is forbidden in a migrated shared schema")
    row = await session.scalar(
        select(CronSchedulerOwnerModel)
        .where(CronSchedulerOwnerModel.scope_id == "global")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    evidence = dict(row.cutover_evidence)
    evidence["verification"] = {
        "protocol": "cron-deployment-verification.v1",
        "deployment_id": "deployment-1",
        "cutover_revision": row.cutover_revision,
        "receipt_id": "fixture-only-receipt",
        "verifier_id": "fixture-only-verifier",
        "inventory_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
    }
    row.cutover_evidence = evidence
    row.owner_kind = "rust"
    row.cutover_phase = "verified"
    row.owner_id = None
    row.lease_token = None
    row.lease_expires_at = None
    await session.flush()
    return row.cutover_revision


async def verified_rust_owner(session) -> tuple[SqlCronCutoverRepository, int]:
    repository = SqlCronCutoverRepository(session)
    await repository.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
    revision = await simulate_trusted_verifier(session)
    await session.commit()
    return repository, revision


def run_row(run_id, status, **overrides):
    values = {
        "id": run_id,
        "job_id": "job",
        "project_id": "project",
        "status": status,
        "conversation_id": "conversation",
    } | overrides
    return CronJobRunModel(**values)


def operation_row(operation_id, status, **overrides):
    values = {
        "id": operation_id,
        "tenant_id": "tenant",
        "project_id": "project",
        "job_id": "job",
        "job_revision": 1,
        "operation_kind": "execute_run",
        "status": status,
        "attempt_count": 0,
        "max_attempts": 5,
        "input_json": {},
        "result_json": {},
    } | overrides
    return CronOperationModel(**values)


async def seed_midflight_work(session):
    live = datetime.now(UTC) + timedelta(minutes=5)
    owner = await session.get(CronSchedulerOwnerModel, "global", populate_existing=True)
    owner.owner_id = "rust-worker-1"
    owner.lease_token = "global:9:99"
    owner.lease_expires_at = live
    session.add(run_row("queued-run", "queued"))
    session.add(
        run_row(
            "live-run",
            "running",
            runtime_lease_owner="rust-worker-1",
            runtime_lease_token="live-token",
            runtime_lease_expires_at=live,
        )
    )
    session.add(run_row("waiting-run", "waiting_human"))
    session.add(operation_row("pending-operation", "pending"))
    session.add(
        operation_row(
            "live-operation",
            "processing",
            lease_owner="rust-worker-1",
            lease_token="operation-token",
            lease_expires_at=live,
        )
    )
    session.add(operation_row("waiting-operation", "waiting_runtime"))
    session.add(
        HITLRequest(
            id="pending-hitl",
            request_type="clarification",
            conversation_id="conversation",
            tenant_id="tenant",
            project_id="project",
            question="Confirm?",
            status="pending",
            expires_at=live,
        )
    )
    session.add(
        AgentSessionSnapshot(
            id="hitl-snapshot",
            tenant_id="tenant",
            project_id="project",
            agent_mode="default",
            request_id="request",
            snapshot_type="hitl",
            snapshot_data={},
            expires_at=live,
        )
    )
    await session.flush()


async def settle_midflight_work(session):
    finished = await session.scalar(select(func.clock_timestamp()))
    owner = await session.get(CronSchedulerOwnerModel, "global", populate_existing=True)
    owner.owner_id = None
    owner.lease_token = None
    owner.lease_expires_at = None
    live_run = await session.get(CronJobRunModel, "live-run", populate_existing=True)
    live_run.status = "success"
    live_run.finished_at = finished
    live_run.runtime_lease_owner = None
    live_run.runtime_lease_token = None
    live_run.runtime_lease_expires_at = None
    live_operation = await session.get(CronOperationModel, "live-operation", populate_existing=True)
    live_operation.status = "completed"
    live_operation.lease_owner = None
    live_operation.lease_token = None
    live_operation.lease_expires_at = None
    await session.flush()


async def test_prepare_reverse_closes_rust_admission_and_keeps_python_closed(database):
    from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
        SqlLegacyCronAdmissionRepository,
    )

    _, sessions = database
    async with sessions() as session:
        repository, revision = await verified_rust_owner(session)
        active = await repository.read()
        assert active.phase == "verified" and active.owner_kind == "rust"
        assert active.drain_direction is None
        prepared = await repository.prepare_reverse(revision)
        await session.commit()
        assert prepared.phase == "prepared" and prepared.owner_kind == "rust"
        assert prepared.drain_direction == "reverse"
        assert prepared.revision == revision + 1
        assert prepared.blockers == ("reverse_drain_unobserved",)
        assert (
            await SqlLegacyCronAdmissionRepository(session).admit(
                tenant_id="tenant",
                project_id="project",
                job_id="job",
                run_id="run",
                message_id="message",
                conversation_id="conversation",
            )
            is None
        )
        with pytest.raises(CronCutoverConflictError):
            await repository.prepare_reverse(prepared.revision)
        with pytest.raises(CronCutoverConflictError):
            await repository.observe(prepared.revision)
        with pytest.raises(CronCutoverConflictError):
            await repository.record_receipt(
                CronDeploymentReceipt.from_wire(receipt_wire()), prepared.revision
            )


async def test_reverse_commands_reject_non_verified_or_python_owners(database):
    _, sessions = database
    async with sessions() as session:
        repository = SqlCronCutoverRepository(session)
        with pytest.raises(CronCutoverConflictError):
            await repository.prepare_reverse(0)
        prepared = await repository.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
        with pytest.raises(CronCutoverConflictError):
            await repository.prepare_reverse(prepared.revision)
        with pytest.raises(CronCutoverConflictError):
            await repository.observe_reverse(prepared.revision)
        with pytest.raises(CronCutoverConflictError):
            await repository.complete_reverse(prepared.revision)


async def test_observe_reverse_records_open_counts_and_what_drained(database):
    _, sessions = database
    async with sessions() as session:
        repository, revision = await verified_rust_owner(session)
        prepared = await repository.prepare_reverse(revision)
        await seed_midflight_work(session)
        old = datetime.now(UTC) - timedelta(days=1)
        session.add(run_row("old-terminal", "success", finished_at=old))
        await session.flush()
        observed = await repository.observe_reverse(prepared.revision)
        await session.commit()
        assert observed.phase == "blocked" and observed.drain_direction == "reverse"
        counts = dict(observed.observed_counts)
        assert counts["active_rust_owner_lease"] == 1
        assert counts["live_running_runs"] == 1
        assert counts["live_processing_operations"] == 1
        assert counts["queued_runs"] == 1
        assert counts["waiting_human_runs"] == 1
        assert counts["retryable_operations"] == 1
        assert counts["waiting_runtime_operations"] == 1
        assert counts["unresolved_hitl_requests"] == 1
        assert counts["retained_hitl_snapshots"] == 1
        assert dict(observed.terminal_outcomes) == {}
        assert observed.last_run_ids == ()
        assert set(observed.blockers) == {
            "active_rust_owner_lease",
            "live_processing_operations",
            "live_running_runs",
        }
        assert observed.observed_at is not None
        await settle_midflight_work(session)
        drained = await repository.observe_reverse(observed.revision)
        await session.commit()
        assert drained.blockers == ()
        assert dict(drained.terminal_outcomes) == {"success": 1}
        assert drained.last_run_ids == ("live-run",)


async def test_complete_reverse_requires_observation_and_a_settled_drain(database):
    _, sessions = database
    async with sessions() as session:
        repository, revision = await verified_rust_owner(session)
        prepared = await repository.prepare_reverse(revision)
        with pytest.raises(CronCutoverConflictError):
            await repository.complete_reverse(prepared.revision)
        await seed_midflight_work(session)
        observed = await repository.observe_reverse(prepared.revision)
        await session.commit()
        with pytest.raises(CronCutoverConflictError):
            await repository.complete_reverse(observed.revision)


async def test_complete_reverse_readmits_python_and_preserves_all_evidence(database):
    from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
        SqlLegacyCronAdmissionRepository,
    )

    _, sessions = database
    async with sessions() as session:
        repository = SqlCronCutoverRepository(session)
        await repository.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
        recorded = await repository.record_receipt(
            CronDeploymentReceipt.from_wire(receipt_wire()), 1
        )
        revision = await simulate_trusted_verifier(session)
        prepared = await repository.prepare_reverse(revision)
        await seed_midflight_work(session)
        observed = await repository.observe_reverse(prepared.revision)
        await settle_midflight_work(session)
        completed = await repository.complete_reverse(observed.revision)
        await session.commit()
        assert completed.phase == "unverified" and completed.owner_kind == "python"
        assert completed.revision == observed.revision + 1
        assert completed.drain_direction is None
        assert completed.blockers == ()
        identity = await SqlLegacyCronAdmissionRepository(session).admit(
            tenant_id="tenant",
            project_id="project",
            job_id="job",
            run_id="run-after-rollback",
            message_id="message",
            conversation_id="conversation",
        )
        assert identity is not None
        row = await session.get(CronSchedulerOwnerModel, "global", populate_existing=True)
        evidence = dict(row.cutover_evidence)
        assert evidence["manifest"]["deployment_id"] == "deployment-1"
        assert len(evidence["receipts"]) == 1
        assert evidence["verification"]["protocol"] == "cron-deployment-verification.v1"
        reverse = evidence["reverse"]
        assert reverse["protocol"] == "cron-reverse-drain.v1"
        assert reverse["completion"]["protocol"] == "cron-reverse-drain-completion.v1"
        final = reverse["completion"]["final_observation"]
        assert final["terminal_outcomes"] == {"success": 1}
        assert final["last_run_ids"] == ["live-run"]
        assert final["counts"]["queued_runs"] == 1
        assert row.cutover_revision > recorded.revision
        # A stale Rust worker waking after rollback has no admission path left:
        # the row no longer satisfies owner_kind='rust' AND cutover_phase='verified'.
        assert not (row.owner_kind == "rust" and row.cutover_phase == "verified")


async def test_concurrent_prepare_reverse_has_one_revision_winner(database):
    _, sessions = database
    async with sessions() as session:
        _, revision = await verified_rust_owner(session)

    async def prepare_reverse():
        async with sessions() as session:
            try:
                result = await SqlCronCutoverRepository(session).prepare_reverse(revision)
                await session.commit()
                return result
            except CronCutoverConflictError:
                await session.rollback()
                return None

    results = await asyncio.gather(prepare_reverse(), prepare_reverse())
    assert sum(result is not None for result in results) == 1


async def test_cli_reverse_commands_mirror_forward_json_discipline(database, monkeypatch):
    from scripts import cron_cutover_barrier as cli

    _, sessions = database
    monkeypatch.setattr(cli, "async_session_factory", sessions)
    async with sessions() as session:
        _, revision = await verified_rust_owner(session)
    prepared = await cli.execute_command(
        cli.parse_args(["prepare-reverse", "--expected-revision", str(revision)])
    )
    assert prepared["phase"] == "prepared"
    assert prepared["drain_direction"] == "reverse"
    observed = await cli.execute_command(
        cli.parse_args(["observe-reverse", "--expected-revision", str(prepared["revision"])])
    )
    assert observed["phase"] == "blocked"
    assert observed["blockers"] == []
    assert "active_rust_owner_lease" in observed["observed_counts"]
    completed = await cli.execute_command(
        cli.parse_args(["complete-reverse", "--expected-revision", str(observed["revision"])])
    )
    assert completed["phase"] == "unverified"
    assert completed["owner_kind"] == "python"
    with pytest.raises(SystemExit):
        cli.parse_args(["complete-reverse"])
    with pytest.raises(SystemExit):
        cli.parse_args(["activate-python", "--force"])
