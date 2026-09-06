"""Real admin rollback, route leases and restart on independently migrated PostgreSQL."""

import pytest
import pytest_asyncio

from src.tests.integration import test_root_startup_postgres as root_support
from src.tests.unit.application.services import test_root_admin_republish_v2 as support

pytestmark = pytest.mark.integration
root_sessions = root_support.root_sessions


@pytest_asyncio.fixture(loop_scope="function")
async def rollback_sessions(root_sessions):
    return root_sessions


async def test_postgres_admin_rollback_after_nack_restores_exact_generation(
    rollback_sessions, monkeypatch
):
    await support.test_bound_rollback_after_nack_restores_routes_and_survives_restart(
        rollback_sessions, monkeypatch
    )


async def test_postgres_admin_rollback_preserves_old_generation_lease(rollback_sessions):
    await support.test_rollback_creates_new_generation_while_old_a_lease_remains(rollback_sessions)
