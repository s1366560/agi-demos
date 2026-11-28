"""A package can resolve only its own capabilities in the pinned deployment generation."""

import pytest

from src.host.operations import deployment_adapters
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    TenantBindingV2,
)
from src.tests.unit.routers.test_signed_tenant_account import account_app as _account_app

account_app = _account_app
pytestmark = pytest.mark.unit


async def test_signed_package_and_scope_select_the_deployed_provider(account_app, monkeypatch):
    runtime = account_app.state.platform_plugin_runtime_v2
    monkeypatch.setattr(
        deployment_adapters, "current_generation_v2", lambda: runtime.manager.current
    )
    project = ScopeBindingV2(tenant_id="t", project_id="p")
    tenant = TenantBindingV2(tenant_id="t")
    resolve = deployment_adapters.resolve_application_operation
    for package, binding, capability in (
        ("automation", project, "app.automation.playbooks.read"),
        ("billing", tenant, "app.billing.account.read"),
        ("environments", tenant, "app.environments.inventory.read"),
        ("knowledge", project, "app.knowledge.memories.write"),
        ("workspace", project, "app.workspace.directory.read"),
    ):
        assert callable(resolve("memstack-" + package, capability, binding))
    for package, binding, name, code in (
        ("memstack-knowledge", tenant, "app.knowledge.memories.write", "forbidden"),
        ("memstack-agent", project, "app.agent.list", "forbidden"),
        ("memstack-agent", project, "app.billing.plan.write", "forbidden"),
        ("unknown-package", tenant, "app.billing.account.read", "runtime_unavailable"),
    ):
        with pytest.raises(OptionalBusinessError) as rejected:
            resolve(package, name, binding)
        assert rejected.value.code == code
