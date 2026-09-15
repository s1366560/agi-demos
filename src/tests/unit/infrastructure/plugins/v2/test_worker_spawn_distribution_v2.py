"""An admitted worker forwards only its exact verified distribution to nested spawns."""

from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import (
    DataPlaneGenerationAdmissionV2,
    PlatformPluginRuntimeHostV2,
)

_ROOT = Path(__file__).resolve().parents[6]


@pytest.mark.unit
async def test_admitted_worker_can_forward_exact_distribution_to_spawned_child():
    from src.application.services.agent.runtime_bootstrapper import _current_plugin_distribution_v2
    from src.infrastructure.plugins.v2.boundary import OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2

    source = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    admission = DataPlaneGenerationAdmissionV2(builtin_runtime_definitions_v2())
    try:
        publication = await source.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=701,
            version=701,
            nonce="nested-spawn-distribution",
        )
        assert publication.accepted
        payload = source.current_distribution.to_payload()
        for distribution in (payload, None):
            async with admission.admit(
                descriptor_payload=payload["descriptor"],
                distribution_payload=distribution,
                operation_id="nested-spawn",
                scope=ScopeV2(
                    kind=ScopeKindV2.SESSION,
                    tenant_id="tenant",
                    project_id="project",
                    session_id="parent",
                ),
            ) as operation:
                descriptor, forwarded = _current_plugin_distribution_v2()
                assert descriptor == payload["descriptor"]
                assert forwarded == payload
                assert operation.require(OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2) == payload
        with pytest.raises(RuntimeV2Error, match="distribution"):
            async with admission.admit(
                descriptor_payload=payload["descriptor"],
                distribution_payload=None,
                operation_id="forged-spawn",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
                services={
                    OPERATION_PLUGIN_DISTRIBUTION_SERVICE_V2: {
                        "descriptor": payload["descriptor"],
                        "snapshot": {},
                    }
                },
            ):
                pytest.fail("caller replaced the verified distribution")
    finally:
        await admission.close()
        await source.close()
