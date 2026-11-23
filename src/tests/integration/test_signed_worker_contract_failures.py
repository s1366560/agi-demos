"""An admitted OCI image must meet the signed MCP schema and execution limits."""

import os

import pytest

from src.infrastructure.plugins.v2 import project_package_execution as execution
from src.infrastructure.plugins.v2.oci_mcp_worker import OciWorkerError
from src.infrastructure.plugins.v2.project_plugin_package import admit_package
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
)
from src.tests.integration.test_oci_mcp_worker_docker import (
    DOC,
    signed_worker,
    worker_image as _worker_image,
)

worker_image = _worker_image
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("OCI_WORKER_DOCKER_TESTS") != "1", reason="requires Docker"),
]


async def test_signed_contract_and_runtime_limits_drain_failing_worker(
    worker_image, tmp_path, monkeypatch
):
    image, registry, engine = worker_image
    scope = ScopeBindingV2(tenant_id="qa", project_id="failure-paths")
    monkeypatch.setattr(execution, "allowed_worker_registries", lambda: frozenset({registry}))

    def admit(**options):
        _, _, _, archive, public = signed_worker(tmp_path, image, scope, **options)
        return admit_package(archive, (public,), frozenset({"tools.execute"}), scope)

    def remaining(release):
        return engine.containers.list(
            all=True, filters={"label": "memstack.release=" + release.digest}
        )

    mismatched = admit(
        contribution={
            **DOC,
            "tools": [
                {**DOC["tools"][0], "output_schema": {"type": "object", "required": ["color"]}}
            ],
        }
    )
    with pytest.raises(OciWorkerError, match="schemas differ"):
        await execution.prepare_project_guest(mismatched, scope)
    assert not remaining(mismatched)

    limited = admit(quotas={"max_output_bytes": 8, "max_wall_time_ms": 500})
    with pytest.raises(OptionalBusinessError, match="tool is unavailable"):
        await execution.invoke_project_tool(limited, scope, "undeclared", {})
    with pytest.raises(OciWorkerError, match="schema validation"):
        await execution.invoke_project_tool(limited, scope, "probe", {"wait": "invalid"})
    with pytest.raises(OciWorkerError, match="output quota"):
        await execution.invoke_project_tool(limited, scope, "probe", {})
    with pytest.raises(OciWorkerError, match="deadline"):
        await execution.invoke_project_tool(limited, scope, "probe", {"wait": True})
    assert not remaining(limited)
