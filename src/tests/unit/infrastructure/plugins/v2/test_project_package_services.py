"""Validate immutable service identities and per-tool call budgets at the guest boundary."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from memstack_plugin_sdk.contract import ContractError, ToolContribution, parse_contribution
from memstack_plugin_sdk.package_services import project_services

from src.infrastructure.plugins.v2.oci_mcp_services import (
    WorkerServices,
    bind_worker_services,
    worker_host_callback,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
)
from src.tests.unit.infrastructure.plugins.v2.test_signed_optional_business_v2 import _package

pytestmark = pytest.mark.unit
SERVICE = "service:package:plans:quote"
OFFER = {"service": SERVICE, "version": "1.0.0"}
USE = {**OFFER, "alias": "quote"}
CONSUMER = ToolContribution(
    name="preview",
    abi="mcp.stdio",
    input_schema={},
    output_schema={},
    permissions=frozenset({"tools.execute", "services.call"}),
    service_aliases=frozenset({"quote"}),
)
PROVIDER = replace(
    CONSUMER,
    name="quote",
    abi="invoke",
    service_aliases=frozenset(),
    permissions=frozenset({"tools.execute", "services.provide"}),
)


@pytest.mark.parametrize(
    ("declarations", "plugin", "worker", "tool"),
    [
        ({"requires": [USE]}, "plans", True, CONSUMER),
        ({"requires": [USE]}, "invoice", False, CONSUMER),
        ({"provides": [OFFER]}, "plans", True, PROVIDER),
        ({"provides": [OFFER]}, "other", False, PROVIDER),
        (
            {"provides": [OFFER]},
            "plans",
            False,
            replace(PROVIDER, permissions=PROVIDER.permissions | {"storage.read"}),
        ),
        ({"requires": [{**USE, "version": ">=1"}]}, "invoice", True, CONSUMER),
        ({"requires": [{**USE, "alias": "catalog"}]}, "invoice", True, CONSUMER),
        ({"requires": [{**USE, "service": "service:tenant-auth"}]}, "invoice", True, CONSUMER),
        ({"requires": [USE, USE]}, "invoice", True, CONSUMER),
        ({"requires": [USE]}, "invoice", True, replace(CONSUMER, service_aliases=frozenset())),
    ],
)
def test_unsupported_or_cyclic_service_graph_is_rejected(declarations, plugin, worker, tool):
    with pytest.raises(ValueError):
        project_services(declarations, plugin=plugin, worker=worker, target="python", tools=(tool,))


@pytest.mark.parametrize(
    ("aliases", "permission"), [([], True), (["read"], False), (["a", "a"], True)]
)
def test_service_access_requires_its_own_aliases_and_permission(aliases, permission):
    permissions = ["tools.execute", "services.call"] if permission else ["tools.execute"]
    with pytest.raises(ContractError):
        parse_contribution(
            {
                "schema": "memstack.plugin.contributions/1",
                "tools": [
                    {
                        "name": "t",
                        "abi": "mcp.stdio",
                        "input_schema": {},
                        "output_schema": {},
                        "permissions": permissions,
                        "service_aliases": aliases,
                    }
                ],
            }
        )


async def test_worker_callbacks_cannot_select_scope_tool_or_provider_and_stop_at_quota():
    scope = ScopeBindingV2(project_id="p", tenant_id="t")
    package = replace(_package(), approved_permissions=CONSUMER.permissions)
    invoke = AsyncMock(return_value={"n": 1})
    bound = WorkerServices(scope=scope, package=package, invoke=invoke)
    with bind_worker_services(bound):
        callback = worker_host_callback(package, scope, CONSUMER)
        assert callback is not None
        assert worker_host_callback(package, replace(scope, project_id="q"), CONSUMER) is None
        assert worker_host_callback(replace(package, digest="changed"), scope, CONSUMER) is None
        for injected in ("project_id", "tenant_id", "tool", "version", "digest", "plugin_id"):
            with pytest.raises(OptionalBusinessError):
                await callback(
                    "memstack/services/call", {"alias": "quote", "input": {}, injected: "changed"}
                )
        denied = worker_host_callback(
            package, scope, replace(CONSUMER, service_aliases=frozenset())
        )
        with pytest.raises(OptionalBusinessError):
            await denied("memstack/services/call", {"alias": "quote", "input": {}})
        with pytest.raises(OptionalBusinessError):
            await callback("memstack/services/call", {"alias": "other", "input": {}})
        for _ in range(4):
            assert await callback("memstack/services/call", {"alias": "quote", "input": {}}) == {
                "n": 1
            }
        with pytest.raises(OptionalBusinessError, match="count"):
            await callback("memstack/services/call", {"alias": "quote", "input": {}})
        assert invoke.await_count == 4
    with pytest.raises(OptionalBusinessError, match="64 KiB"):
        await WorkerServices(scope=scope, package=package, invoke=invoke).call(
            CONSUMER, {"alias": "quote", "input": {"oversized": "x" * 65536}}
        )
    assert invoke.await_count == 4
