"""Preparing a deployment barrier never fabricates proof of old execution drain."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from src.domain.model.cron.cutover import CronDeploymentManifest, CronDeploymentReceipt
from src.infrastructure.adapters.secondary.persistence.models import CronJobRunModel
from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
    CronCutoverConflictError,
    SqlCronCutoverRepository,
)
from src.tests.unit.domain.model.cron.test_cutover import manifest_wire, receipt_wire

pytestmark = pytest.mark.integration


async def test_prepare_closes_python_admission_and_persists_unverified_boundary(database):
    from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
        SqlLegacyCronAdmissionRepository,
    )

    _, sessions = database
    async with sessions() as session:
        repository = SqlCronCutoverRepository(session)
        before = await repository.read()
        assert before.phase == "unverified"
        prepared = await repository.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
        await session.commit()
        assert prepared.phase == "prepared" and prepared.owner_kind == "draining"
        assert prepared.revision == 1
        assert "deployment_verifier_unavailable" in prepared.blockers
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


async def test_receipts_are_cas_bound_to_prepared_deployment_and_never_verify(database):
    _, sessions = database
    async with sessions() as session:
        repository = SqlCronCutoverRepository(session)
        await repository.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
        receipt = CronDeploymentReceipt.from_wire(receipt_wire())
        recorded = await repository.record_receipt(receipt, 1)
        await session.commit()
        assert recorded.receipts_recorded == 1
        assert recorded.phase == "prepared"
        assert "deployment_verifier_unavailable" in recorded.blockers
        with pytest.raises(CronCutoverConflictError):
            await repository.record_receipt(receipt, 1)
        with pytest.raises(CronCutoverConflictError):
            await repository.record_receipt(
                CronDeploymentReceipt.from_wire(receipt_wire() | {"deployment_id": "other"}),
                recorded.revision,
            )


async def test_old_success_and_expired_snapshot_do_not_prove_drain(database):
    from src.infrastructure.adapters.secondary.persistence.models import AgentSessionSnapshot

    _, sessions = database
    async with sessions() as session:
        session.add(
            CronJobRunModel(
                id="old-fake-success",
                job_id="job",
                project_id="project",
                status="success",
                conversation_id="conversation",
                finished_at=datetime.now(UTC),
            )
        )
        session.add(
            AgentSessionSnapshot(
                id="expired",
                tenant_id="tenant",
                project_id="project",
                agent_mode="default",
                request_id="old-request",
                snapshot_type="hitl",
                snapshot_data={},
                expires_at=datetime.now(UTC) - timedelta(days=2),
            )
        )
        repository = SqlCronCutoverRepository(session)
        await repository.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
        blocked = await repository.observe(1)
        await session.commit()
        assert blocked.phase == "blocked"
        counts = dict(blocked.observed_counts)
        assert counts["unattested_legacy_runs"] == 1
        assert counts["retained_hitl_snapshots"] == 1
        assert "deployment_verifier_unavailable" in blocked.blockers


async def test_zero_active_admissions_and_all_closed_receipts_still_need_real_verifier(database):
    _, sessions = database
    async with sessions() as session:
        repository = SqlCronCutoverRepository(session)
        await repository.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
        recorded = await repository.record_receipt(
            CronDeploymentReceipt.from_wire(receipt_wire()), 1
        )
        blocked = await repository.observe(recorded.revision)
        await session.commit()
        assert blocked.phase == "blocked"
        assert blocked.blockers == ("deployment_verifier_unavailable",)
        assert not any(dict(blocked.observed_counts).values())
        assert blocked.observed_at is not None


async def test_concurrent_prepare_has_one_revision_winner(database):
    _, sessions = database

    async def prepare():
        async with sessions() as session:
            try:
                result = await SqlCronCutoverRepository(session).prepare(
                    CronDeploymentManifest.from_wire(manifest_wire()), 0
                )
                await session.commit()
                return result
            except CronCutoverConflictError:
                await session.rollback()
                return None

    results = await asyncio.gather(prepare(), prepare())
    assert sum(result is not None for result in results) == 1


async def test_prepared_barrier_keeps_existing_legacy_ticket_valid(database):
    from src.infrastructure.adapters.secondary.persistence.sql_legacy_cron_admission_repository import (
        SqlLegacyCronAdmissionRepository,
    )
    from src.tests.integration.scheduler.test_legacy_cron_admission import admit

    _, sessions = database
    async with sessions() as session:
        identity = await admit(session)
        legacy = SqlLegacyCronAdmissionRepository(session)
        ticket = await legacy.claim_execution(identity)
        await session.commit()
        cutover = SqlCronCutoverRepository(session)
        await cutover.prepare(CronDeploymentManifest.from_wire(manifest_wire()), 0)
        blocked = await cutover.observe(1)
        assert dict(blocked.observed_counts)["active_legacy_admissions"] == 1
        assert await legacy.park_for_hitl(ticket)
        resumed = await legacy.claim_execution(identity, resume=True)
        assert resumed is not None
        assert await legacy.complete(resumed, "success")
        await session.commit()
        blocked = await cutover.observe(blocked.revision)
        assert dict(blocked.observed_counts)["active_legacy_admissions"] == 0
        assert blocked.phase == "blocked"


async def test_cli_inspect_is_read_only_and_prepare_observe_are_usable(
    database, monkeypatch, tmp_path
):
    from scripts import cron_cutover_barrier as cli
    from src.infrastructure.adapters.secondary.persistence.models import CronSchedulerOwnerModel

    _, sessions = database
    monkeypatch.setattr(cli, "async_session_factory", sessions)
    inspected = await cli.execute_command(cli.parse_args(["inspect"]))
    assert inspected["phase"] == "unverified"
    async with sessions() as session:
        assert await session.get(CronSchedulerOwnerModel, "global") is None
    manifest = tmp_path / "manifest.json"
    import json

    manifest.write_text(json.dumps(manifest_wire()))
    prepared = await cli.execute_command(
        cli.parse_args(["prepare", "--manifest-file", str(manifest), "--expected-revision", "0"])
    )
    assert prepared["phase"] == "prepared"
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(receipt_wire()))
    recorded = await cli.execute_command(
        cli.parse_args(
            ["record-receipt", "--receipt-file", str(receipt), "--expected-revision", "1"]
        )
    )
    assert recorded["receipts_recorded"] == 1
    observed = await cli.execute_command(cli.parse_args(["observe", "--expected-revision", "2"]))
    assert observed["phase"] == "blocked"
    assert "deployment_verifier_unavailable" in observed["blockers"]
    with pytest.raises(SystemExit):
        cli.parse_args(["finalize", "--verified", "true"])
