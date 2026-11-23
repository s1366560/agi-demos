"""Check the approved record callbacks before they can reach a scoped worker's data."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.plugins.v2.oci_mcp_records import (
    WorkerRecords,
    bind_worker_records,
    worker_record_call,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedPackageBytesV2,
    load_contribution_v2,
)

pytestmark = pytest.mark.unit
READ = frozenset({"storage.read"})
WRITE = frozenset({"storage.write"})


def records(session, *, tenant="t", project="p", limit=256, approved=READ | WRITE):
    package = SignedPackageBytesV2(
        plugin_id="example",
        version="1.0",
        digest="sha256:example",
        wasm=b"",
        approved_permissions=approved,
        ui_files={},
        storage_limit=limit,
        contribution=load_contribution_v2(
            {
                "schema": "memstack.plugin.contributions/1",
                "storage": {"schema_version": 1, "permissions": ["storage.read", "storage.write"]},
            }
        ),
    )
    return WorkerRecords(
        db=session,
        scope=ScopeBindingV2(tenant_id=tenant, project_id=project),
        package=package,
        authorize_write=AsyncMock(),
    )


async def test_grants_are_per_tool_and_release(db_session):
    store = records(db_session)
    assert worker_record_call(store.package, store.scope, READ) is None
    with bind_worker_records(store):
        other = records(db_session)
        assert worker_record_call(other.package, store.scope, READ) is None
        assert (
            worker_record_call(
                store.package, ScopeBindingV2(tenant_id="t", project_id="other"), READ
            )
            is None
        )
        read_only = worker_record_call(store.package, store.scope, READ)
        with pytest.raises(OptionalBusinessError, match="not approved"):
            await read_only("memstack/records/create", {"key": "k", "document": {}})
        with pytest.raises(OptionalBusinessError, match="unknown worker record operation"):
            await read_only("memstack/records/get", {"key": "k", "tenant_id": "other"})
    store.authorize_write.assert_not_awaited()
    unapproved = records(db_session, approved=READ)
    with pytest.raises(OptionalBusinessError, match="not approved"):
        await unapproved.call(WRITE, "memstack/records/create", {"key": "k", "document": {}})


async def test_records_are_immutable_and_billed_to_the_scoped_namespace(db_session):
    method = "memstack/records/create"
    row = {"key": "invoice1", "document": {"amount": 20}}
    first = records(db_session)
    assert await first.call(WRITE, method, row) == {"created": True}
    first.authorize_write.assert_awaited_once()
    with pytest.raises(OptionalBusinessError, match="one immutable"):
        await first.call(WRITE, method, {**row, "key": "invoice2"})
    latest = records(db_session)
    assert await latest.call(WRITE, method, {**row, "document": {"amount": 9}}) == {
        "created": False
    }
    assert await latest.call(READ, "memstack/records/get", {"key": "invoice1"}) == {
        "document": {"amount": 20}
    }
    foreign = records(db_session, tenant="other")
    assert await foreign.call(READ, "memstack/records/list", {}) == {
        "keys": [],
        "next_cursor": None,
    }
    cap = records(db_session, limit=16)
    with pytest.raises(OptionalBusinessError, match="quota"):
        await cap.call(WRITE, method, {**row, "key": "invoice2"})
    assert (await latest.call(READ, "memstack/records/list", {}))["keys"] == ["invoice1"]
