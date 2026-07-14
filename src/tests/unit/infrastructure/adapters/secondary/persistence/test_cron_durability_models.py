from __future__ import annotations

import pytest

from src.infrastructure.adapters.secondary.persistence.models import (
    CronJobModel,
    CronJobRunModel,
    CronOperationModel,
    CronRequestReceiptModel,
    CronSchedulerOwnerModel,
    CronScheduleStateModel,
)

pytestmark = pytest.mark.unit


def test_cron_jobs_expose_monotonic_definition_revisions() -> None:
    columns = CronJobModel.__table__.columns

    assert columns["revision"].nullable is False
    assert columns["schedule_revision"].nullable is False
    assert str(columns["revision"].server_default.arg) == "1"
    assert str(columns["schedule_revision"].server_default.arg) == "1"


def test_cron_operation_queue_has_fenced_lease_and_deduplication_indexes() -> None:
    table = CronOperationModel.__table__
    index_names = {index.name for index in table.indexes}

    assert table.name == "agistack_cron_operations"
    assert not table.columns["job_id"].foreign_keys
    assert table.columns["next_attempt_at"].nullable is True
    assert {
        "lease_owner",
        "lease_token",
        "lease_expires_at",
        "next_attempt_at",
        "request_receipt_id",
    }.issubset(table.columns.keys())
    assert {
        "uq_agistack_cron_operations_run",
        "uq_agistack_cron_operations_reconcile",
        "uq_agistack_cron_operations_scheduled_fire",
        "ix_agistack_cron_operations_claim",
        "ix_agistack_cron_operations_lease",
    }.issubset(index_names)


def test_cron_runs_keep_command_receipt_and_runtime_correlation_fields() -> None:
    table = CronJobRunModel.__table__
    index_names = {index.name for index in table.indexes}

    assert {
        "accepted_at",
        "job_revision",
        "schedule_revision",
        "runtime_execution_id",
        "idempotency_key",
        "request_receipt_id",
        "scheduled_for",
        "runtime_revision",
        "runtime_lease_owner",
        "runtime_lease_token",
        "runtime_lease_expires_at",
        "deadline_at",
        "last_heartbeat_at",
    }.issubset(table.columns.keys())
    assert {
        "uq_cron_job_runs_runtime_execution",
        "ix_cron_job_runs_runtime_dispatch",
        "ix_cron_job_runs_runtime_deadline",
    }.issubset(index_names)
    assert table.columns["runtime_revision"].nullable is False
    assert str(table.columns["runtime_revision"].server_default.arg) == "0"


def test_cron_schedule_receipt_and_owner_state_are_explicit() -> None:
    schedule_columns = CronScheduleStateModel.__table__.columns
    receipt_indexes = {index.name for index in CronRequestReceiptModel.__table__.indexes}
    owner_columns = CronSchedulerOwnerModel.__table__.columns

    assert {"schedule_revision", "schedule_fingerprint", "next_fire_at"}.issubset(
        schedule_columns.keys()
    )
    assert "uq_agistack_cron_request_receipts_intent" in receipt_indexes
    assert {"owner_kind", "owner_epoch", "lease_token", "lease_expires_at"}.issubset(
        owner_columns.keys()
    )
