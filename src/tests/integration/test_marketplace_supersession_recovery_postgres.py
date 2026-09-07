"""Exercise complete pending replacement recovery on independently migrated PostgreSQL."""

import pytest
import pytest_asyncio

from src.tests.integration import test_root_startup_postgres as root_support
from src.tests.unit.application.services import (
    test_marketplace_supersession_recovery_v2 as recovery_support,
)

pytestmark = pytest.mark.integration
root_sessions = root_support.root_sessions
supersession_case = recovery_support.supersession_case


@pytest_asyncio.fixture(loop_scope="function")
async def supersession_sessions(root_sessions):
    return root_sessions


async def test_postgres_pending_ack_replacement_preserves_real_history(supersession_case):
    await recovery_support.test_pending_ack_replaced_without_fabricating_its_receipt(
        supersession_case
    )


@pytest.mark.parametrize("after_commit", [False, True])
async def test_postgres_audit_commit_failure_is_recoverable(supersession_case, after_commit):
    await recovery_support.test_audit_commit_failure_preserves_pending_and_retry_is_idempotent(
        supersession_case, after_commit
    )


@pytest.mark.parametrize("old_ack_durable", [False, True])
async def test_postgres_nack_requires_higher_ack(supersession_case, monkeypatch, old_ack_durable):
    await recovery_support.test_replacement_nack_stays_blocked_until_a_higher_ack(
        supersession_case, monkeypatch, old_ack_durable
    )


async def test_postgres_unbound_request_preserves_pending(supersession_case):
    await recovery_support.test_unbound_replacement_does_not_discard_actual_pending(
        supersession_case
    )


async def test_postgres_newer_request_during_stage_preserves_outcomes(supersession_case):
    await recovery_support.test_newer_bound_request_during_stage_preserves_both_actual_outcomes(
        supersession_case
    )
